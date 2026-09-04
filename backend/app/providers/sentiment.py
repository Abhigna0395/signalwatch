"""Sentiment scoring, behind a swappable interface.

Design constraint from the brief: do **not** require an LLM call per request.
The default implementation is a deterministic lexicon scorer that runs offline,
costs nothing, and returns the same answer every time — which also makes the
demo reproducible. An LLM implementation is provided for when quality matters
more than determinism, and it degrades to the lexicon on any failure.
"""

from __future__ import annotations

import abc
import re
from dataclasses import dataclass

from app.config import settings


@dataclass
class SentimentResult:
    label: str          # positive | neutral | negative
    confidence: float   # 0.0 – 1.0
    provider: str
    rationale: str = ""


class SentimentProvider(abc.ABC):
    name: str = "abstract"

    @abc.abstractmethod
    def score(self, text: str) -> SentimentResult: ...

    def score_many(self, texts: list[str]) -> list[SentimentResult]:
        return [self.score(t) for t in texts]


# ─────────────────────────────────────────────────────────────────────────────
# Lexicon scorer
# ─────────────────────────────────────────────────────────────────────────────

_POSITIVE = {
    "beat": 2.0, "beats": 2.0, "record": 2.0, "surge": 2.5, "surges": 2.5,
    "soar": 2.5, "soars": 2.5, "rally": 2.0, "rallies": 2.0, "jump": 1.8,
    "jumps": 1.8, "gain": 1.4, "gains": 1.4, "growth": 1.5, "grows": 1.4,
    "upgrade": 2.2, "upgrades": 2.2, "raise": 1.6, "raises": 1.6,
    "raised": 1.6, "lifted": 1.5, "outperform": 2.0, "strong": 1.6,
    "stronger": 1.6, "robust": 1.5, "expansion": 1.3, "expands": 1.3,
    "wins": 1.8, "won": 1.5, "awarded": 1.6, "landed": 1.5, "lands": 1.5,
    "approval": 1.8, "approved": 1.8, "breakthrough": 2.2, "demand": 1.2,
    "profit": 1.4, "profitable": 1.7, "dividend": 1.0, "buyback": 1.6,
    "ahead": 1.2, "exceeds": 2.0, "exceeded": 2.0, "accelerating": 1.6,
    "improved": 1.4, "improving": 1.4, "optimistic": 1.6, "bullish": 2.0,
    "high": 0.8, "highs": 1.2, "momentum": 1.2, "agreement": 1.0,
}

_NEGATIVE = {
    "miss": 2.0, "misses": 2.0, "missed": 2.0, "plunge": 2.5, "plunges": 2.5,
    "slump": 2.2, "slumps": 2.2, "fall": 1.5, "falls": 1.5, "drop": 1.6,
    "drops": 1.6, "decline": 1.6, "declines": 1.6, "declining": 1.6,
    "downgrade": 2.2, "downgrades": 2.2, "cut": 1.6, "cuts": 1.6,
    "trimmed": 1.5, "lowered": 1.6, "underperform": 2.0, "weak": 1.7,
    "weaker": 1.7, "weakness": 1.7, "soft": 1.3, "softer": 1.3,
    "loss": 1.8, "losses": 1.8, "lawsuit": 2.0, "probe": 1.8,
    "investigation": 2.0, "regulatory": 1.0, "recall": 2.2, "halt": 1.8,
    "halted": 1.8, "delay": 1.5, "delayed": 1.5, "warning": 1.9,
    "warns": 1.9, "concern": 1.4, "concerns": 1.4, "risk": 1.2,
    "risks": 1.2, "pressure": 1.3, "headwind": 1.6, "headwinds": 1.6,
    "layoff": 1.9, "layoffs": 1.9, "bearish": 2.0, "slowdown": 1.8,
    "shortfall": 2.0, "low": 0.8, "lows": 1.2, "resign": 1.6,
    "resigns": 1.6, "fraud": 2.6, "bankruptcy": 3.0, "default": 2.4,
}

# Words that flip the polarity of the term that follows them.
_NEGATORS = {"no", "not", "never", "without", "denies", "denied", "avoids", "avoided"}

_TOKEN_RE = re.compile(r"[a-z']+")


class KeywordSentimentProvider(SentimentProvider):
    """Deterministic financial-lexicon scorer.

    Handles simple negation ("does *not* beat estimates") because financial
    headlines lean on it constantly and ignoring it inverts the answer on
    exactly the headlines that matter most.
    """

    name = "keyword"

    def score(self, text: str) -> SentimentResult:
        tokens = _TOKEN_RE.findall((text or "").lower())
        if not tokens:
            return SentimentResult("neutral", 0.3, self.name, "No scoreable text")

        score = 0.0
        matched: list[str] = []
        for i, token in enumerate(tokens):
            weight = _POSITIVE.get(token, 0.0) - _NEGATIVE.get(token, 0.0)
            if weight == 0.0:
                continue
            # Look back two tokens for a negator.
            if any(t in _NEGATORS for t in tokens[max(0, i - 2): i]):
                weight = -weight
            score += weight
            matched.append(token)

        if not matched:
            return SentimentResult("neutral", 0.35, self.name, "No sentiment-bearing terms")

        # Normalise by a saturating curve: a headline with six negative words is
        # not six times more negative than one with a single strong word.
        magnitude = min(1.0, abs(score) / 5.0)
        if score > 0.75:
            label = "positive"
        elif score < -0.75:
            label = "negative"
        else:
            label = "neutral"

        confidence = 0.4 + 0.55 * magnitude if label != "neutral" else 0.4
        rationale = "Matched: " + ", ".join(matched[:5])
        return SentimentResult(label, round(min(confidence, 0.97), 2), self.name, rationale)


# ─────────────────────────────────────────────────────────────────────────────
# Optional LLM scorer
# ─────────────────────────────────────────────────────────────────────────────


class LLMSentimentProvider(SentimentProvider):
    """Anthropic-backed scorer. Falls back to the lexicon on any failure.

    Batches every headline into a single call rather than one call per article,
    because per-article calls are what make LLM sentiment too slow and too
    expensive to sit in a dashboard request path.
    """

    name = "llm"

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._fallback = KeywordSentimentProvider()

    def score(self, text: str) -> SentimentResult:
        return self.score_many([text])[0]

    def score_many(self, texts: list[str]) -> list[SentimentResult]:
        if not texts:
            return []
        if not self._api_key:
            return self._fallback.score_many(texts)
        try:
            return self._call(texts)
        except Exception:  # noqa: BLE001 - never let sentiment break a render
            return self._fallback.score_many(texts)

    def _call(self, texts: list[str]) -> list[SentimentResult]:
        import json

        import httpx

        numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
        prompt = (
            "Classify the market sentiment of each financial headline for the "
            "company it concerns. Reply with JSON only: a list of objects with "
            '"label" (positive|neutral|negative) and "confidence" (0-1), one '
            "per headline, in order.\n\n" + numbered
        )
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-5",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=settings.provider_timeout_seconds * 2,
        )
        response.raise_for_status()
        body = response.json()["content"][0]["text"].strip()
        body = re.sub(r"^```(?:json)?|```$", "", body, flags=re.MULTILINE).strip()
        parsed = json.loads(body)

        results: list[SentimentResult] = []
        for i, _ in enumerate(texts):
            if i < len(parsed) and isinstance(parsed[i], dict):
                label = str(parsed[i].get("label", "neutral")).lower()
                if label not in ("positive", "neutral", "negative"):
                    label = "neutral"
                conf = float(parsed[i].get("confidence", 0.5))
                results.append(SentimentResult(label, round(min(max(conf, 0.0), 1.0), 2), self.name))
            else:
                results.append(self._fallback.score(texts[i]))
        return results


def get_sentiment_provider() -> SentimentProvider:
    if settings.sentiment_provider == "llm" and settings.anthropic_api_key:
        return LLMSentimentProvider(settings.anthropic_api_key)
    return KeywordSentimentProvider()
