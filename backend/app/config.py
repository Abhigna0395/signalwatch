"""Centralised configuration.

Every tunable in SignalWatch lives here — most importantly the attention-score
weights, which are deliberately configuration rather than magic numbers buried
in the scoring code.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AttentionWeights(BaseSettings):
    """Maximum points each signal family can contribute to the 0–100 score."""

    price_move: float = 25.0
    volume_anomaly: float = 20.0
    technical: float = 15.0
    news: float = 15.0
    volatility: float = 15.0
    recency: float = 10.0

    @property
    def total(self) -> float:
        return (
            self.price_move
            + self.volume_anomaly
            + self.technical
            + self.news
            + self.volatility
            + self.recency
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "price_move": self.price_move,
            "volume_anomaly": self.volume_anomaly,
            "technical": self.technical,
            "news": self.news,
            "volatility": self.volatility,
            "recency": self.recency,
        }


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # ── Core ────────────────────────────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ── Database ────────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./signalwatch.db"

    # ── Provider ────────────────────────────────────────────────────────────
    demo_mode: bool = True
    market_provider: str = "finnhub"
    finnhub_api_key: str = ""
    provider_timeout_seconds: float = 6.0
    provider_max_retries: int = 2

    enable_cross_source_check: bool = True
    discrepancy_tolerance_percent: float = 0.75

    # ── Freshness (seconds) ─────────────────────────────────────────────────
    freshness_fresh_seconds: int = 90
    freshness_recent_seconds: int = 900
    freshness_stale_seconds: int = 21600

    # ── Cache / background ──────────────────────────────────────────────────
    quote_cache_ttl_seconds: int = 45
    history_cache_ttl_seconds: int = 1800
    news_cache_ttl_seconds: int = 600
    redis_url: str = ""
    enable_background_refresh: bool = True
    background_refresh_seconds: int = 60

    # ── Attention scoring ───────────────────────────────────────────────────
    weight_price_move: float = 25.0
    weight_volume_anomaly: float = 20.0
    weight_technical: float = 15.0
    weight_news: float = 15.0
    weight_volatility: float = 15.0
    weight_recency: float = 10.0

    threshold_high_attention: float = 75.0
    threshold_watch: float = 45.0

    # ── Detection thresholds (surfaced so they can be tuned without a deploy)─
    price_move_notable_percent: float = 2.0
    volume_spike_ratio: float = 1.8
    volatility_spike_ratio: float = 1.6
    breakout_lookback_days: int = 60
    since_visit_notable_percent: float = 2.0
    news_spike_count: int = 3

    # ── Sentiment ───────────────────────────────────────────────────────────
    sentiment_provider: str = "keyword"
    anthropic_api_key: str = ""

    # ── Auth ────────────────────────────────────────────────────────────────
    demo_user_email: str = "demo@signalwatch.app"

    @field_validator("market_provider", "sentiment_provider", mode="before")
    @classmethod
    def _lower(cls, v: str) -> str:
        return str(v).strip().lower()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def weights(self) -> AttentionWeights:
        return AttentionWeights(
            price_move=self.weight_price_move,
            volume_anomaly=self.weight_volume_anomaly,
            technical=self.weight_technical,
            news=self.weight_news,
            volatility=self.weight_volatility,
            recency=self.weight_recency,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
