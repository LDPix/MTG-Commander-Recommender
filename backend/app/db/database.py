"""Database setup.

Provides both async (PostgreSQL/production) and sync (SQLite/test) engine
configurations, a shared DeclarativeBase, and FastAPI dependency helpers.
"""
from __future__ import annotations

import os
from collections.abc import Generator
from typing import TYPE_CHECKING

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Async setup (PostgreSQL, production) — lazy to avoid import-time errors
# when asyncpg is not installed (e.g. during unit tests).
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/mtg_recommender",
)


def _get_async_engine():
    """Create the async engine lazily."""
    from sqlalchemy.ext.asyncio import create_async_engine
    return create_async_engine(DATABASE_URL, echo=False)


def _get_async_session_local():
    """Create the async session factory lazily."""
    from sqlalchemy.ext.asyncio import async_sessionmaker
    return async_sessionmaker(_get_async_engine(), expire_on_commit=False)


async def get_db() -> "AsyncSession":  # type: ignore[misc]
    """FastAPI dependency that yields an async database session."""
    session_local = _get_async_session_local()
    async with session_local() as session:
        yield session


# ---------------------------------------------------------------------------
# ORM Base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

    pass


# ---------------------------------------------------------------------------
# Sync setup (SQLite, tests / simple scripts)
# ---------------------------------------------------------------------------

SYNC_DATABASE_URL = os.environ.get(
    "SYNC_DATABASE_URL",
    "sqlite:///./mtg_recommender.db",
)

_sync_engine: Engine | None = None


def get_sync_engine(url: str = SYNC_DATABASE_URL) -> Engine:
    """Return (or create) the sync SQLAlchemy engine."""
    global _sync_engine
    if _sync_engine is None or str(_sync_engine.url) != url:
        connect_args = {}
        if "sqlite" in url:
            connect_args["check_same_thread"] = False
        _sync_engine = create_engine(url, connect_args=connect_args)
    return _sync_engine


def get_sync_session_factory(engine: Engine) -> sessionmaker:
    """Return a sync session factory bound to *engine*."""
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_tables(engine: Engine) -> None:
    """Create all tables defined in Base.metadata against *engine*.

    Primarily used in tests with an in-memory SQLite DB.
    """
    Base.metadata.create_all(bind=engine)


def get_sync_db(engine: Engine | None = None) -> Generator[Session, None, None]:
    """FastAPI / test dependency that yields a sync database session."""
    _engine = engine or get_sync_engine()
    factory = get_sync_session_factory(_engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()
