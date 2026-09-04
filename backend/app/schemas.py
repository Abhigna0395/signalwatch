"""Pydantic request/response models.

Response bodies for the analytical endpoints are assembled as dicts by the
service layer (they are deep, heterogeneous and shaped for one specific screen),
so the schemas here concentrate on **request validation** — the surface where
untrusted input actually arrives.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# Requests
# ─────────────────────────────────────────────────────────────────────────────


class WatchlistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be blank")
        return v


class WatchlistUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be blank")
        return v


class WatchlistReorder(BaseModel):
    ordered_ids: list[int] = Field(min_length=1)


class StockAdd(BaseModel):
    symbol: str = Field(min_length=1, max_length=24)
    threshold_percent: float | None = Field(default=None, gt=0, le=100)

    @field_validator("symbol")
    @classmethod
    def _normalise(cls, v: str) -> str:
        v = v.strip().upper()
        if not v.replace(".", "").replace("-", "").isalnum():
            raise ValueError("Symbol contains invalid characters")
        return v


class ItemsReorder(BaseModel):
    ordered_symbols: list[str] = Field(min_length=1)

    @field_validator("ordered_symbols")
    @classmethod
    def _upper(cls, v: list[str]) -> list[str]:
        return [s.strip().upper() for s in v if s.strip()]


class ThresholdUpdate(BaseModel):
    threshold_percent: float | None = Field(default=None, gt=0, le=100)


class MarkReviewedRequest(BaseModel):
    """Omitting `symbols` reviews everything currently tracked."""

    symbols: list[str] | None = None

    @field_validator("symbols")
    @classmethod
    def _upper(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return [s.strip().upper() for s in v if s.strip()]


class ReplayStepRequest(BaseModel):
    step: int | None = Field(default=None, ge=0, le=32)


# ─────────────────────────────────────────────────────────────────────────────
# Responses
# ─────────────────────────────────────────────────────────────────────────────


class StockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    name: str
    exchange: str
    sector: str
    currency: str


class WatchlistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    threshold_percent: float | None
    stock: StockOut


class WatchlistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    position: int
    created_at: datetime
    items: list[WatchlistItemOut] = []


class SymbolMatchOut(BaseModel):
    symbol: str
    name: str
    exchange: str = ""
    currency: str = "USD"


class MessageOut(BaseModel):
    message: str
    detail: str | None = None


class ErrorOut(BaseModel):
    error: str
    detail: str | None = None
    code: str | None = None
