"""Integration tests for SC-API-001: Collection import API endpoints."""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from tests.fixtures.sample_csv_collections import (
    MALFORMED_COLLECTION_CSV,
    VALID_COLLECTION_CSV,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _upload(client: TestClient, csv_content: str, session_id: str = "test-session"):
    """POST a CSV file to the import endpoint."""
    return client.post(
        "/api/v1/collections/import",
        files={"file": ("collection.csv", io.BytesIO(csv_content.encode()), "text/csv")},
        headers={"X-Session-Id": session_id},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_import_api_accepts_valid_csv(api_client: TestClient) -> None:
    """POST /import returns 200 for a valid CSV."""
    resp = _upload(api_client, VALID_COLLECTION_CSV)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


def test_import_api_returns_summary(api_client: TestClient) -> None:
    """Response body contains imported_count and collection_id."""
    resp = _upload(api_client, VALID_COLLECTION_CSV)
    data = resp.json()
    assert "collection_id" in data
    assert data["collection_id"] != ""
    assert data["imported_count"] == 3


def test_import_api_returns_unknown_cards(api_client: TestClient) -> None:
    """Unknown card names appear in the unknown_cards list."""
    csv = "name,quantity\nSol Ring,1\nFake Card ZZZZ,1\n"
    resp = _upload(api_client, csv)
    data = resp.json()
    assert data["success"] is True
    assert "Fake Card ZZZZ" in data["unknown_cards"]


def test_import_api_rejects_invalid_file(api_client: TestClient) -> None:
    """Empty file content returns success=False."""
    resp = api_client.post(
        "/api/v1/collections/import",
        files={"file": ("empty.csv", io.BytesIO(b""), "text/csv")},
        headers={"X-Session-Id": "test-session"},
    )
    data = resp.json()
    assert data["success"] is False
    assert data["error"] is not None


def test_import_api_is_user_scoped(api_client: TestClient) -> None:
    """Different session IDs receive separate collections."""
    resp_a = _upload(api_client, VALID_COLLECTION_CSV, session_id="user-alpha")
    resp_b = _upload(api_client, VALID_COLLECTION_CSV, session_id="user-beta")
    assert resp_a.json()["collection_id"] != resp_b.json()["collection_id"]
    assert resp_a.json()["session_id"] == "user-alpha"
    assert resp_b.json()["session_id"] == "user-beta"


def test_get_collection_returns_items(api_client: TestClient) -> None:
    """GET /collections/{session_id} returns stored items."""
    session_id = "get-test-session"
    _upload(api_client, VALID_COLLECTION_CSV, session_id=session_id)
    resp = api_client.get(f"/api/v1/collections/{session_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == session_id
    assert data["total_items"] == 3
    assert len(data["items"]) == 3


def test_get_collection_returns_404_for_unknown_session(api_client: TestClient) -> None:
    """GET /collections/{session_id} returns 404 for a non-existent session."""
    resp = api_client.get("/api/v1/collections/no-such-session-xyz")
    assert resp.status_code == 404


def test_reimport_via_api_updates_collection(api_client: TestClient) -> None:
    """A second POST for the same session replaces the collection."""
    session_id = "reimport-session"
    _upload(api_client, VALID_COLLECTION_CSV, session_id=session_id)
    small_csv = "name,quantity\nSol Ring,5\n"
    resp = _upload(api_client, small_csv, session_id=session_id)
    data = resp.json()
    assert data["success"] is True
    assert data["imported_count"] == 1


def test_reimport_change_summary_returned(api_client: TestClient) -> None:
    """Second import for a session returns structured visible change data."""
    session_id = "reimport-summary-session"
    _upload(api_client, VALID_COLLECTION_CSV, session_id=session_id)
    updated_csv = "name,quantity\nSol Ring,5\nCommand Tower,1\nCultivate,1\n"

    resp = _upload(api_client, updated_csv, session_id=session_id)

    assert resp.status_code == 200
    summary = resp.json()["change_summary"]
    assert summary == {
        "added_count": 1,
        "removed_count": 1,
        "quantity_changed_count": 1,
        "unchanged_count": 1,
        "added_cards": ["Cultivate"],
        "removed_cards": ["Swords to Plowshares"],
        "quantity_changed_cards": ["Sol Ring"],
    }
