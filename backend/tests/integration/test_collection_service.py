"""Integration tests for SC-COLL-001/002: CollectionService + DB."""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.data_pipeline.card_resolver import CardResolver
from app.data_pipeline.collection_normalizer import CollectionNormalizer
from app.data_pipeline.csv_importer import CSVImporter
from app.repositories.collection_repo import CollectionRepository
from app.services.collection_service import CollectionService
from tests.fixtures.sample_csv_collections import VALID_COLLECTION_CSV


@pytest.fixture
def service(db_session: Session, sample_card_resolver: CardResolver) -> CollectionService:
    importer = CSVImporter()
    normalizer = CollectionNormalizer(sample_card_resolver)
    repo = CollectionRepository(db_session)
    return CollectionService(importer, normalizer, repo)


@pytest.fixture
def repo(db_session: Session) -> CollectionRepository:
    return CollectionRepository(db_session)


# ---------------------------------------------------------------------------
# Basic persistence
# ---------------------------------------------------------------------------


def test_collection_is_saved(service: CollectionService) -> None:
    """Importing a CSV creates a Collection record in the DB."""
    response = service.import_collection(
        "session-001", VALID_COLLECTION_CSV.encode(), "test.csv"
    )
    assert response.success
    assert response.collection_id != ""
    assert response.session_id == "session-001"


def test_collection_is_loaded(
    service: CollectionService, repo: CollectionRepository
) -> None:
    """A saved collection can be retrieved with its items."""
    response = service.import_collection(
        "session-002", VALID_COLLECTION_CSV.encode(), "test.csv"
    )
    collection = repo.get_collection(response.collection_id)
    assert collection is not None
    assert collection.session_id == "session-002"
    items = repo.get_items(collection.id)
    assert len(items) == 3


def test_owned_quantity_preserved(
    service: CollectionService, repo: CollectionRepository
) -> None:
    """Quantity values are stored accurately."""
    response = service.import_collection(
        "session-003", VALID_COLLECTION_CSV.encode(), "test.csv"
    )
    items = repo.get_items(response.collection_id)
    qty_map = {i.canonical_name: i.quantity for i in items}
    assert qty_map["Swords to Plowshares"] == 2
    assert qty_map["Sol Ring"] == 1


# ---------------------------------------------------------------------------
# Session scoping
# ---------------------------------------------------------------------------


def test_collection_is_user_scoped(service: CollectionService) -> None:
    """Different session IDs produce separate collections."""
    resp_a = service.import_collection(
        "session-A", VALID_COLLECTION_CSV.encode(), "a.csv"
    )
    resp_b = service.import_collection(
        "session-B", VALID_COLLECTION_CSV.encode(), "b.csv"
    )
    assert resp_a.collection_id != resp_b.collection_id
    assert resp_a.session_id == "session-A"
    assert resp_b.session_id == "session-B"


# ---------------------------------------------------------------------------
# Reimport
# ---------------------------------------------------------------------------


def test_reimport_updates_existing_quantity(
    service: CollectionService, repo: CollectionRepository
) -> None:
    """Reimporting replaces item quantities."""
    service.import_collection(
        "session-R1", VALID_COLLECTION_CSV.encode(), "test.csv"
    )
    updated_csv = "name,quantity\nSol Ring,4\n"
    resp2 = service.reimport_collection(
        "session-R1", updated_csv.encode(), "test.csv"
    )
    items = repo.get_items(resp2.collection_id)
    assert len(items) == 1
    assert items[0].canonical_name == "Sol Ring"
    assert items[0].quantity == 4


def test_reimport_adds_new_cards(
    service: CollectionService, repo: CollectionRepository
) -> None:
    """Reimporting a larger collection adds previously absent cards."""
    initial_csv = "name,quantity\nSol Ring,1\n"
    service.import_collection("session-R2", initial_csv.encode(), "test.csv")

    extended_csv = "name,quantity\nSol Ring,1\nCommand Tower,1\n"
    resp2 = service.reimport_collection(
        "session-R2", extended_csv.encode(), "test.csv"
    )
    items = repo.get_items(resp2.collection_id)
    names = {i.canonical_name for i in items}
    assert "Sol Ring" in names
    assert "Command Tower" in names


def test_reimport_does_not_duplicate_cards(
    service: CollectionService, repo: CollectionRepository
) -> None:
    """Reimporting the same CSV twice does not create duplicate items."""
    service.import_collection(
        "session-R3", VALID_COLLECTION_CSV.encode(), "test.csv"
    )
    resp2 = service.reimport_collection(
        "session-R3", VALID_COLLECTION_CSV.encode(), "test.csv"
    )
    items = repo.get_items(resp2.collection_id)
    oracle_ids = [i.oracle_id for i in items]
    assert len(oracle_ids) == len(set(oracle_ids)), "Duplicate oracle_ids found."


def test_reimport_change_summary_added_cards(service: CollectionService) -> None:
    initial_csv = "name,quantity\nSol Ring,1\n"
    updated_csv = "name,quantity\nSol Ring,1\nCommand Tower,1\n"
    service.import_collection("session-R4", initial_csv.encode(), "test.csv")

    response = service.import_collection("session-R4", updated_csv.encode(), "test.csv")

    assert response.change_summary is not None
    assert response.change_summary.added_count == 1
    assert response.change_summary.added_cards == ["Command Tower"]


def test_reimport_change_summary_removed_cards(service: CollectionService) -> None:
    initial_csv = "name,quantity\nSol Ring,1\nCommand Tower,1\n"
    updated_csv = "name,quantity\nSol Ring,1\n"
    service.import_collection("session-R5", initial_csv.encode(), "test.csv")

    response = service.import_collection("session-R5", updated_csv.encode(), "test.csv")

    assert response.change_summary is not None
    assert response.change_summary.removed_count == 1
    assert response.change_summary.removed_cards == ["Command Tower"]


def test_reimport_change_summary_quantity_changes(service: CollectionService) -> None:
    initial_csv = "name,quantity\nSol Ring,1\nCommand Tower,1\n"
    updated_csv = "name,quantity\nSol Ring,4\nCommand Tower,1\n"
    service.import_collection("session-R6", initial_csv.encode(), "test.csv")

    response = service.import_collection("session-R6", updated_csv.encode(), "test.csv")

    assert response.change_summary is not None
    assert response.change_summary.quantity_changed_count == 1
    assert response.change_summary.quantity_changed_cards == ["Sol Ring"]


def test_reimport_change_summary_unchanged_count(service: CollectionService) -> None:
    initial_csv = "name,quantity\nSol Ring,1\nCommand Tower,1\n"
    updated_csv = "name,quantity\nSol Ring,4\nCommand Tower,1\n"
    service.import_collection("session-R7", initial_csv.encode(), "test.csv")

    response = service.import_collection("session-R7", updated_csv.encode(), "test.csv")

    assert response.change_summary is not None
    assert response.change_summary.unchanged_count == 1


def test_reimport_change_summary_is_deterministic(service: CollectionService) -> None:
    initial_csv = "name,quantity\nSol Ring,1\nSwords to Plowshares,2\n"
    updated_csv = (
        "name,quantity\n"
        "Sol Ring,3\n"
        "Command Tower,1\n"
        "Cultivate,1\n"
    )
    service.import_collection("session-R8", initial_csv.encode(), "test.csv")

    response = service.import_collection("session-R8", updated_csv.encode(), "test.csv")

    assert response.change_summary is not None
    assert response.change_summary.added_cards == ["Command Tower", "Cultivate"]
    assert response.change_summary.removed_cards == ["Swords to Plowshares"]
    assert response.change_summary.quantity_changed_cards == ["Sol Ring"]
