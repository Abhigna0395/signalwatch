"""News ingestion, sentiment and topic clustering.

Two product decisions drive this module:

1. **Sentiment is scored once, at ingest, and persisted.** Re-scoring on every
   dashboard render would be wasteful with the lexicon provider and outright
   expensive with the LLM one. Articles are keyed by `external_id`, so a repeat
   fetch updates nothing and costs nothing.

2. **Headlines are grouped, not listed.** Five separate cards saying roughly the
   same thing is the information overload the product exists to remove. Related
   headlines collapse into one cluster with a topic, a count and a net tone.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NewsItem, Stock
from app.providers.base import NewsArticle
from app.providers.sentiment import SentimentProvider, get_sentiment_provider
from app.services.signal_engine import ScoredNews
from app.timeutil import age_seconds, humanize_age, to_iso, utcnow

# ─────────────────────────────────────────────────────────────────────────────
# Topic inference
# ─────────────────────────────────────────────────────────────────────────────

# Ordered: the first matching topic wins, so more specific themes are listed
# before generic ones.
_TOPIC_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Earnings", ("earnings", "quarterly results", "eps", "revenue beat", "guidance",
                  "quarterly profit", "results season")),
    ("AI Demand", ("ai ", "artificial intelligence", "accelerator", "gpu", "data-centre",
                   "data center", "inference", "training cluster")),
    ("Analyst Actions", ("price target", "upgrade", "downgrade", "initiated coverage",
                         "rating", "analyst", "brokerage", "research desk")),
    ("Regulatory", ("regulator", "regulatory", "antitrust", "probe", "investigation",
                    "lawsuit", "settlement", "compliance", "recall")),
    ("Supply Chain", ("supply chain", "shipment", "shipments", "inventory", "supplier",
                      "production", "factory", "capacity")),
    ("Deliveries", ("delivery", "deliveries", "order intake", "units sold")),
    ("Leadership", ("ceo", "cfo", "resign", "appointed", "steps down", "board")),
    ("Capital Returns", ("dividend", "buyback", "share repurchase", "split")),
    ("Product Launch", ("launch", "unveil", "announces", "introduces", "new model")),
    ("Partnerships", ("partnership", "agreement", "contract", "deal", "collaboration")),
    ("Retail Expansion", ("store", "retail", "expansion", "outlet")),
    ("Services Growth", ("services revenue", "subscription", "subscribers", "recurring")),
]


def infer_topic(headline: str, summary: str = "") -> str:
    text = f"{headline} {summary}".lower()
    for topic, keywords in _TOPIC_RULES:
        if any(k in text for k in keywords):
            return topic
    return "General"


# ─────────────────────────────────────────────────────────────────────────────
# Ingest
# ─────────────────────────────────────────────────────────────────────────────


def ingest_news(
    db: Session,
    stock: Stock,
    articles: list[NewsArticle],
    *,
    sentiment: SentimentProvider | None = None,
) -> list[NewsItem]:
    """Upsert articles for a stock, scoring sentiment only for genuinely new ones."""
    if not articles:
        return _recent_news_rows(db, stock.id)

    provider = sentiment or get_sentiment_provider()

    existing = {
        row.external_id: row
        for row in db.scalars(
            select(NewsItem).where(
                NewsItem.stock_id == stock.id,
                NewsItem.external_id.in_([a.external_id for a in articles if a.external_id]),
            )
        )
    }

    fresh = [a for a in articles if a.external_id and a.external_id not in existing]
    scores = provider.score_many([f"{a.headline}. {a.summary}".strip() for a in fresh]) if fresh else []

    for article, score in zip(fresh, scores):
        db.add(
            NewsItem(
                stock_id=stock.id,
                headline=article.headline[:400],
                summary=(article.summary or "")[:2000],
                source=(article.source or "")[:80],
                url=(article.url or "")[:600],
                topic=infer_topic(article.headline, article.summary),
                sentiment=score.label,
                sentiment_confidence=score.confidence,
                sentiment_provider=score.provider,
                published_at=article.published_at or utcnow(),
                external_id=article.external_id[:120],
            )
        )

    if fresh:
        db.flush()
    return _recent_news_rows(db, stock.id)


def _recent_news_rows(db: Session, stock_id: int, limit: int = 30) -> list[NewsItem]:
    return list(
        db.scalars(
            select(NewsItem)
            .where(NewsItem.stock_id == stock_id)
            .order_by(NewsItem.published_at.desc())
            .limit(limit)
        )
    )


def to_scored_news(rows: list[NewsItem]) -> list[ScoredNews]:
    """Adapt persisted rows into the engine's input type."""
    return [
        ScoredNews(
            headline=row.headline,
            sentiment=row.sentiment,
            sentiment_confidence=row.sentiment_confidence,
            topic=row.topic,
            published_at=row.published_at,
            source=row.source,
            url=row.url,
        )
        for row in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Clustering
# ─────────────────────────────────────────────────────────────────────────────

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "for", "of", "to", "in", "on", "at", "by",
    "with", "from", "as", "is", "are", "was", "were", "be", "been", "its", "it",
    "that", "this", "than", "then", "after", "over", "into", "amid", "says", "said",
    "new", "more", "most", "up", "down", "inc", "corp", "ltd", "plc", "company",
}
_WORD_RE = re.compile(r"[a-z][a-z'-]+")


def _keywords(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS and len(w) > 3}


@dataclass
class NewsCluster:
    topic: str
    headlines: list[dict] = field(default_factory=list)
    sentiment: str = "neutral"
    sentiment_confidence: float = 0.5
    latest_published_at: datetime | None = None

    @property
    def count(self) -> int:
        return len(self.headlines)

    def to_dict(self) -> dict:
        age = age_seconds(self.latest_published_at)
        return {
            "topic": self.topic,
            "count": self.count,
            "sentiment": self.sentiment,
            "sentiment_confidence": round(self.sentiment_confidence, 2),
            "latest_published_at": to_iso(self.latest_published_at),
            "latest_label": humanize_age(age),
            "headlines": self.headlines,
        }


def cluster_news(rows: list[NewsItem], *, max_age_hours: float = 72.0) -> list[NewsCluster]:
    """Group related headlines into topic clusters.

    Grouping is primarily by inferred topic. Within the `General` bucket — where
    the rule-based topic gave us nothing — we fall back to keyword overlap, so
    three differently-worded stories about the same event still collapse into
    one card instead of three.
    """
    now = utcnow()
    recent = [
        r for r in rows
        if r.published_at and (age_seconds(r.published_at, now=now) or 0) <= max_age_hours * 3600
    ]
    if not recent:
        return []

    buckets: dict[str, list[NewsItem]] = {}
    generic: list[NewsItem] = []
    for row in recent:
        if row.topic and row.topic != "General":
            buckets.setdefault(row.topic, []).append(row)
        else:
            generic.append(row)

    # Keyword-overlap clustering for the untagged remainder.
    for row in generic:
        words = _keywords(f"{row.headline} {row.summary}")
        placed = False
        for key, members in buckets.items():
            if not key.startswith("~"):
                continue
            member_words = _keywords(members[0].headline + " " + members[0].summary)
            overlap = len(words & member_words)
            if overlap >= 3:
                members.append(row)
                placed = True
                break
        if not placed:
            buckets[f"~{row.id}"] = [row]

    clusters: list[NewsCluster] = []
    for key, members in buckets.items():
        members.sort(key=lambda r: r.published_at or now, reverse=True)

        # Net tone across the cluster, weighted by each item's own confidence.
        polarity = sum(
            {"positive": 1, "negative": -1}.get(m.sentiment, 0) * m.sentiment_confidence
            for m in members
        ) / len(members)
        if polarity > 0.25:
            label = "positive"
        elif polarity < -0.25:
            label = "negative"
        else:
            label = "neutral"

        if key.startswith("~"):
            # Untagged cluster: name it after its most distinctive shared words.
            common = Counter()
            for m in members:
                common.update(_keywords(m.headline))
            top = [w for w, _ in common.most_common(2)]
            topic = " ".join(w.title() for w in top) if top else "Market Coverage"
        else:
            topic = key

        clusters.append(
            NewsCluster(
                topic=topic,
                headlines=[
                    {
                        "id": m.id,
                        "headline": m.headline,
                        "summary": m.summary,
                        "source": m.source,
                        "url": m.url,
                        "sentiment": m.sentiment,
                        "sentiment_confidence": round(m.sentiment_confidence, 2),
                        "sentiment_provider": m.sentiment_provider,
                        "published_at": to_iso(m.published_at),
                        "published_label": humanize_age(age_seconds(m.published_at, now=now)),
                    }
                    for m in members
                ],
                sentiment=label,
                sentiment_confidence=min(0.97, 0.4 + 0.5 * abs(polarity)),
                latest_published_at=members[0].published_at,
            )
        )

    clusters.sort(key=lambda c: (-c.count, -(c.latest_published_at or now).timestamp()))
    return clusters
