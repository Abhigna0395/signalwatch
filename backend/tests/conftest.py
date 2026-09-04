"""Shared test fixtures.

Every test runs against a fresh in-memory SQLite database, so the suite is
order-independent and leaves nothing behind.
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("ENABLE_BACKGROUND_REFRESH", "false")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import database as db_module
from app.models import Base


@pytest.fixture()
def engine():
    # StaticPool keeps a single shared connection alive, which is what makes an
    # in-memory SQLite database visible across sessions within one test.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture()
def db(engine):
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(engine, monkeypatch):
    """A TestClient wired to the throwaway engine, with caches reset."""
    from app.cache import InMemoryCache
    import app.cache as cache_module
    import app.providers.registry as registry_module
    from app.services import world as world_module

    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", TestingSession)
    monkeypatch.setattr(cache_module, "_cache", InMemoryCache())
    registry_module._service = None
    world_module.reset_cache()

    from app.main import app

    def _get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[db_module.get_db] = _get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    registry_module._service = None
