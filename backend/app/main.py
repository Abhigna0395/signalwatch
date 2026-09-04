"""FastAPI application entry point."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.config import settings
from app.database import init_db
from app.providers.base import ProviderError
from app.timeutil import to_iso, utcnow

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("signalwatch")

_stop_refresh = threading.Event()


def _background_refresh() -> None:
    """Keep quotes warm for every tracked stock.

    A user opening the dashboard should read from cache, not wait on the
    provider. This is the cheap version of the scheduled worker described in
    the README: one thread, one pass per interval, entirely skippable.
    """
    from app.database import session_scope
    from app.models import Stock
    from app.providers.registry import get_market_data_service
    from sqlalchemy import select

    while not _stop_refresh.is_set():
        # Wait first, so startup is never blocked by a provider round trip.
        if _stop_refresh.wait(settings.background_refresh_seconds):
            return
        try:
            with session_scope() as db:
                symbols = [s.symbol for s in db.scalars(select(Stock))]
            if symbols:
                get_market_data_service().get_quotes(symbols, use_cache=False)
                logger.debug("background refresh warmed %d symbols", len(symbols))
        except Exception as exc:  # noqa: BLE001 - a worker must never die quietly
            logger.warning("background refresh failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    # Prime the replay-world cache now, while no request is in flight. After
    # this, get_world_step() is a pure in-memory read (see services/world.py).
    from app.services.world import load_world_step

    load_world_step()

    logger.info(
        "SignalWatch starting — demo_mode=%s provider=%s db=%s",
        settings.demo_mode,
        settings.market_provider if not settings.demo_mode else "demo",
        settings.database_url.split("://")[0],
    )

    thread: threading.Thread | None = None
    if settings.enable_background_refresh:
        thread = threading.Thread(target=_background_refresh, daemon=True, name="refresh")
        thread.start()

    yield

    _stop_refresh.set()
    if thread is not None:
        thread.join(timeout=2)


app = FastAPI(
    title="SignalWatch API",
    version="1.0.0",
    summary="Don't just watch the market. Know what changed.",
    description=(
        "SignalWatch tracks what a user has already seen and surfaces only what has "
        "**meaningfully changed** since then.\n\n"
        "The scoring is deliberately transparent: every attention score is a sum of six "
        "bounded, individually-explained components. See `/api/config` for the live weights "
        "and `/api/stocks/{symbol}/signals` for a full breakdown.\n\n"
        "SignalWatch surfaces market changes for informational purposes. "
        "It does not provide investment advice."
    ),
    lifespan=lifespan,
)

_cors_origins = settings.cors_origin_list
# The app authenticates via an X-User-Email header, never cookies or TLS
# certs — so it carries no CORS "credentials" in the browser's sense, and a
# wildcard origin is safe. That matters for deployment: set CORS_ORIGINS=*
# to stand the API up before the frontend's final domain is known, then
# narrow it once it is. allow_credentials must be False whenever origins
# includes "*" — combining them is rejected by every browser outright.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials="*" not in _cors_origins,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def timing_header(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Response-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Structured error handling
#
# The frontend renders `error` verbatim, so these must stay human-readable.
# Internal details go to the log, never to the client.
# ─────────────────────────────────────────────────────────────────────────────


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": str(exc.detail),
            "code": f"HTTP_{exc.status_code}",
            "path": request.url.path,
            "time": to_iso(utcnow()),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    raw = exc.errors()
    first = raw[0] if raw else {}
    field = " → ".join(str(p) for p in first.get("loc", []) if p != "body")
    # Pydantic v2 stows the original exception object under ctx["error"], which
    # is not JSON-serialisable. Strip ctx down to plain strings before echoing
    # the details back to the client.
    detail = [
        {
            "loc": [str(p) for p in item.get("loc", [])],
            "msg": item.get("msg", ""),
            "type": item.get("type", ""),
        }
        for item in raw
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": f"{field}: {first.get('msg', 'invalid input')}"
            if field
            else first.get("msg", "Invalid request"),
            "code": "VALIDATION_ERROR",
            "detail": detail,
            "path": request.url.path,
        },
    )


@app.exception_handler(ProviderError)
async def provider_error(request: Request, exc: ProviderError):
    logger.warning("provider error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={
            "error": "Market data is temporarily unavailable. Please retry shortly.",
            "code": "PROVIDER_UNAVAILABLE",
            "detail": str(exc),
        },
    )


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    logger.exception("unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Something went wrong on our side.",
            "code": "INTERNAL_ERROR",
            "path": request.url.path,
        },
    )


app.include_router(router)


@app.get("/", tags=["system"], include_in_schema=False)
def root() -> dict:
    return {
        "name": "SignalWatch",
        "tagline": "Don't just watch the market. Know what changed.",
        "docs": "/docs",
        "health": "/api/health",
        "disclaimer": (
            "SignalWatch surfaces market changes for informational purposes. "
            "It does not provide investment advice."
        ),
    }
