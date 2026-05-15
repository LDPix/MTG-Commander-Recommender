"""Shared pytest fixtures for the MTG Commander Recommender test suite."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.data_pipeline.card_resolver import CardResolver
from app.data_pipeline.scryfall_ingest import load_scryfall_bulk_data
from app.db.database import Base, create_tables
from app.models.card import CardData

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Existing fixtures (keep as-is to not break 39 existing tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def sample_cards_path() -> Path:
    """Return path to the sample Scryfall cards fixture file."""
    return FIXTURES_DIR / "sample_scryfall_cards.json"


@pytest.fixture(scope="session")
def manual_overrides_path() -> Path:
    """Return path to the manual tag overrides fixture file."""
    return FIXTURES_DIR / "manual_tag_overrides.json"


@pytest.fixture(scope="session")
def sample_cards(sample_cards_path: Path) -> list[CardData]:
    """Load and return all cards from the sample fixture."""
    return load_scryfall_bulk_data(sample_cards_path)


@pytest.fixture(scope="session")
def cards_by_name(sample_cards: list[CardData]) -> dict[str, CardData]:
    """Return a dict mapping card name to CardData."""
    return {card.name: card for card in sample_cards}


# ---------------------------------------------------------------------------
# New fixtures for collection import layer
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def sample_card_resolver(sample_cards: list[CardData]) -> CardResolver:
    """CardResolver loaded from the sample Scryfall fixture."""
    return CardResolver(sample_cards)


def _make_sqlite_engine():
    """Create a shared in-memory SQLite engine using StaticPool.

    StaticPool ensures all sessions share the same connection, which is
    required for SQLite in-memory databases (each connection would
    otherwise get its own isolated DB).
    """
    import app.models.collection  # noqa: F401 — register models with Base
    import app.models.saved_deck  # noqa: F401 — register SavedDeck model with Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    create_tables(engine)
    return engine


@pytest.fixture
def db_session():
    """Synchronous SQLite in-memory session for integration tests."""
    engine = _make_sqlite_engine()
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def api_client(sample_card_resolver: CardResolver):
    """FastAPI TestClient with an in-memory SQLite DB and the sample resolver."""
    from app.api.v1.collection import (
        _get_db_session,
        get_card_resolver,
        set_card_resolver,
    )
    from app.main import app

    engine = _make_sqlite_engine()
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db_session():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    def override_get_card_resolver():
        return sample_card_resolver

    app.dependency_overrides[_get_db_session] = override_get_db_session
    app.dependency_overrides[get_card_resolver] = override_get_card_resolver
    set_card_resolver(sample_card_resolver)

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    engine.dispose()


# ---------------------------------------------------------------------------
# Fixture: seeded_collection for deck generation tests
# ---------------------------------------------------------------------------

MEREN_ORACLE_ID = "4b2521bc-8f94-1a0b-c3d4-5e6f7a8b9c0d"
DECK_TEST_SESSION = "deck-test-session-001"


@pytest.fixture
def seeded_collection(api_client):
    """Import a B/G collection that supports Meren as commander.

    Returns the session_id so deck generation tests can reference it.
    """
    import io

    from tests.fixtures.sample_csv_collections import DECK_TEST_COLLECTION_CSV

    file = io.BytesIO(DECK_TEST_COLLECTION_CSV.encode())
    resp = api_client.post(
        "/api/v1/collections/import",
        files={"file": ("collection.csv", file, "text/csv")},
        headers={"X-Session-Id": DECK_TEST_SESSION},
    )
    assert resp.status_code == 200, f"Collection import failed: {resp.text}"
    return DECK_TEST_SESSION
