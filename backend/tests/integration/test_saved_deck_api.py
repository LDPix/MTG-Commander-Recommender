"""Integration tests for saved/generated deck persistence and retrieval.

Covers FR-14, FR-15, FR-16, FR-17, FR-18, NFR-12, NFR-13 per the
CR-002 Test Update Package (TC-FR-014-01 through TC-NFR-013-01).
"""
from __future__ import annotations

import io

from fastapi.testclient import TestClient

from tests.conftest import DECK_TEST_SESSION, MEREN_ORACLE_ID
from tests.fixtures.sample_csv_collections import DECK_TEST_COLLECTION_CSV

GENERATE_ENDPOINT = "/api/v1/decks/generate"
SAVED_LIST_ENDPOINT = "/api/v1/decks/saved"
EXPORT_ENDPOINT = "/api/v1/decks/export/plaintext"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import(client: TestClient, session_id: str) -> None:
    """Import the standard deck test collection for a session."""
    resp = client.post(
        "/api/v1/collections/import",
        files={
            "file": ("collection.csv", io.BytesIO(DECK_TEST_COLLECTION_CSV.encode()), "text/csv")
        },
        headers={"X-Session-Id": session_id},
    )
    assert resp.status_code == 200, f"Import failed: {resp.text}"


def _generate(client: TestClient, session_id: str, commander_id: str = MEREN_ORACLE_ID):
    """POST to the generate endpoint."""
    return client.post(
        GENERATE_ENDPOINT,
        json={"session_id": session_id, "commander_oracle_id": commander_id},
    )


def _list_saved(client: TestClient, session_id: str):
    return client.get(SAVED_LIST_ENDPOINT, params={"session_id": session_id})


def _get_saved(client: TestClient, deck_id: str, session_id: str):
    return client.get(f"{SAVED_LIST_ENDPOINT}/{deck_id}", params={"session_id": session_id})


# ---------------------------------------------------------------------------
# TC-FR-014-01 / AT-FR-014-INT-01
# Successful generation persists saved deck artifact
# ---------------------------------------------------------------------------


def test_successful_generation_persists_saved_deck(
    api_client: TestClient, seeded_collection: str
) -> None:
    """TC-FR-014-01: Successful deck generation creates a retrievable saved artifact."""
    gen_resp = _generate(api_client, seeded_collection)
    assert gen_resp.status_code == 200
    deck_id = gen_resp.json()["deck_id"]

    list_resp = _list_saved(api_client, seeded_collection)
    assert list_resp.status_code == 200
    saved_ids = [d["deck_id"] for d in list_resp.json()["decks"]]
    assert deck_id in saved_ids


def test_saved_deck_has_required_metadata(
    api_client: TestClient, seeded_collection: str
) -> None:
    """TC-FR-014-01: Saved deck record includes deck_id, session_id, and commander metadata."""
    gen_resp = _generate(api_client, seeded_collection)
    assert gen_resp.status_code == 200
    deck_id = gen_resp.json()["deck_id"]

    list_resp = _list_saved(api_client, seeded_collection)
    summary = next(d for d in list_resp.json()["decks"] if d["deck_id"] == deck_id)
    assert summary["session_id"] == seeded_collection
    assert summary["commander_oracle_id"] == MEREN_ORACLE_ID
    assert summary["commander_name"]
    assert summary["created_at"]


# ---------------------------------------------------------------------------
# TC-FR-014-02 / AT-FR-014-INT-02
# Saved deck detail matches generated deck response
# ---------------------------------------------------------------------------


def test_saved_deck_detail_matches_generated_response(
    api_client: TestClient, seeded_collection: str
) -> None:
    """TC-FR-014-02: Saved deck detail preserves commander identity and card list fidelity."""
    gen_resp = _generate(api_client, seeded_collection)
    assert gen_resp.status_code == 200
    generated = gen_resp.json()
    deck_id = generated["deck_id"]

    detail_resp = _get_saved(api_client, deck_id, seeded_collection)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()

    assert detail["deck"]["commander"]["oracle_id"] == generated["commander"]["oracle_id"]
    assert detail["deck"]["commander"]["name"] == generated["commander"]["name"]
    saved_ids = {c["oracle_id"] for c in detail["deck"]["main_deck"]}
    generated_ids = {c["oracle_id"] for c in generated["main_deck"]}
    assert saved_ids == generated_ids


# ---------------------------------------------------------------------------
# TC-FR-015-01 / AT-FR-015-INT-01 and TC-NFR-013-01 / AT-NFR-013-SEC-01
# Session isolation — each session only sees its own saved decks
# ---------------------------------------------------------------------------


def test_saved_decks_are_session_scoped(api_client: TestClient) -> None:
    """TC-FR-015-01, TC-NFR-013-01: Each session's saved decks are isolated."""
    session_a = "saved-deck-session-A"
    session_b = "saved-deck-session-B"
    _import(api_client, session_a)
    _import(api_client, session_b)

    gen_a = _generate(api_client, session_a)
    gen_b = _generate(api_client, session_b)
    assert gen_a.status_code == 200
    assert gen_b.status_code == 200

    deck_id_a = gen_a.json()["deck_id"]
    deck_id_b = gen_b.json()["deck_id"]

    list_a = _list_saved(api_client, session_a)
    list_b = _list_saved(api_client, session_b)
    ids_a = {d["deck_id"] for d in list_a.json()["decks"]}
    ids_b = {d["deck_id"] for d in list_b.json()["decks"]}

    assert deck_id_a in ids_a
    assert deck_id_b not in ids_a
    assert deck_id_b in ids_b
    assert deck_id_a not in ids_b


def test_saved_deck_detail_cannot_be_retrieved_across_sessions(
    api_client: TestClient,
) -> None:
    """TC-NFR-013-01: Session B cannot retrieve Session A's saved deck by id."""
    session_a = "cross-session-A"
    session_b = "cross-session-B"
    _import(api_client, session_a)

    gen_a = _generate(api_client, session_a)
    assert gen_a.status_code == 200
    deck_id_a = gen_a.json()["deck_id"]

    # Session B tries to retrieve Session A's deck — must return 404
    cross_resp = _get_saved(api_client, deck_id_a, session_b)
    assert cross_resp.status_code == 404


# ---------------------------------------------------------------------------
# TC-FR-016-01 / AT-FR-016-INT-01
# List saved deck summaries for a session
# ---------------------------------------------------------------------------


def test_list_saved_decks_returns_summaries(
    api_client: TestClient, seeded_collection: str
) -> None:
    """TC-FR-016-01: List endpoint returns saved deck summaries."""
    _generate(api_client, seeded_collection)

    list_resp = _list_saved(api_client, seeded_collection)
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert "decks" in body
    assert isinstance(body["decks"], list)
    assert len(body["decks"]) >= 1
    for summary in body["decks"]:
        assert "deck_id" in summary
        assert "session_id" in summary
        assert "commander_oracle_id" in summary
        assert "commander_name" in summary
        assert "created_at" in summary


# ---------------------------------------------------------------------------
# TC-FR-016-02 / AT-FR-016-INT-02
# Empty saved deck list for session with no saved decks
# ---------------------------------------------------------------------------


def test_list_saved_decks_empty_for_unknown_session(api_client: TestClient) -> None:
    """TC-FR-016-02: Session with no saved decks returns an empty list, not an error."""
    resp = _list_saved(api_client, "session-with-no-saved-decks-xyz")
    assert resp.status_code == 200
    assert resp.json()["decks"] == []


# ---------------------------------------------------------------------------
# TC-FR-017-01 / AT-FR-017-INT-01
# Retrieve saved deck detail by id
# ---------------------------------------------------------------------------


def test_get_saved_deck_detail_by_id(
    api_client: TestClient, seeded_collection: str
) -> None:
    """TC-FR-017-01: GET /saved/{deck_id} returns full deck detail."""
    gen_resp = _generate(api_client, seeded_collection)
    assert gen_resp.status_code == 200
    deck_id = gen_resp.json()["deck_id"]

    detail_resp = _get_saved(api_client, deck_id, seeded_collection)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["deck_id"] == deck_id
    assert detail["session_id"] == seeded_collection
    assert "deck" in detail
    assert "commander" in detail["deck"]
    assert "main_deck" in detail["deck"]


# ---------------------------------------------------------------------------
# TC-FR-017-02 / AT-FR-017-INT-02
# Unknown saved deck id returns 404
# ---------------------------------------------------------------------------


def test_get_saved_deck_unknown_id_returns_404(api_client: TestClient) -> None:
    """TC-FR-017-02: Unknown saved deck id returns 404."""
    resp = _get_saved(api_client, "nonexistent-deck-id-xyz", "any-session")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TC-FR-017-03 / AT-FR-017-INT-03
# Retrieved saved deck contains sufficient data for inspection/export
# ---------------------------------------------------------------------------


def test_saved_deck_detail_supports_export_data_needs(
    api_client: TestClient, seeded_collection: str
) -> None:
    """TC-FR-017-03: Saved deck detail includes all fields needed for inspection/export."""
    gen_resp = _generate(api_client, seeded_collection)
    assert gen_resp.status_code == 200
    deck_id = gen_resp.json()["deck_id"]

    detail_resp = _get_saved(api_client, deck_id, seeded_collection)
    assert detail_resp.status_code == 200
    deck = detail_resp.json()["deck"]

    # Fields needed by deck inspection / plaintext export
    assert deck["commander"]["oracle_id"]
    assert deck["commander"]["name"]
    assert len(deck["main_deck"]) > 0
    total = sum(c["quantity"] for c in deck["main_deck"])
    assert total == 99


# ---------------------------------------------------------------------------
# TC-FR-014-03 / AT-FR-014-INT-03
# Missing collection failure does not save a deck
# ---------------------------------------------------------------------------


def test_missing_collection_does_not_save_deck(api_client: TestClient) -> None:
    """TC-FR-014-03: 404 from missing collection leaves no saved deck artifact."""
    session_id = "no-collection-save-test"
    gen_resp = _generate(api_client, session_id)
    assert gen_resp.status_code == 404

    list_resp = _list_saved(api_client, session_id)
    assert list_resp.status_code == 200
    assert list_resp.json()["decks"] == []


# ---------------------------------------------------------------------------
# TC-FR-014-04 / AT-FR-014-INT-04
# Invalid commander failure does not save a deck
# ---------------------------------------------------------------------------


def test_invalid_commander_does_not_save_deck(
    api_client: TestClient, seeded_collection: str
) -> None:
    """TC-FR-014-04: 422 from invalid commander leaves no saved deck for that attempt."""
    before = _list_saved(api_client, seeded_collection).json()["decks"]
    before_ids = {d["deck_id"] for d in before}

    gen_resp = _generate(api_client, seeded_collection, "not-a-real-oracle-id-xyz")
    assert gen_resp.status_code == 422

    after = _list_saved(api_client, seeded_collection).json()["decks"]
    after_ids = {d["deck_id"] for d in after}
    assert after_ids == before_ids


# ---------------------------------------------------------------------------
# TC-NFR-012-01 / AT-NFR-012-CONTRACT-01
# Generate response remains backward-compatible (NFR-12)
# ---------------------------------------------------------------------------


def test_generate_response_is_backward_compatible(
    api_client: TestClient, seeded_collection: str
) -> None:
    """TC-NFR-012-01: POST /generate response retains all existing fields unchanged."""
    gen_resp = _generate(api_client, seeded_collection)
    assert gen_resp.status_code == 200
    data = gen_resp.json()

    # All fields that existed before CR-002 must still be present
    required_fields = {
        "deck_id", "session_id", "commander", "main_deck",
        "role_breakdown", "quota_status", "package_breakdown",
        "warnings", "owned_count", "owned_percentage",
        "is_valid", "validation_errors", "upgrade_suggestions",
        "card_explanations",
    }
    for field in required_fields:
        assert field in data, f"Missing backward-compatible field: {field}"


# ---------------------------------------------------------------------------
# TC-FR-018-01 / AT-FR-018-INT-01
# Plaintext export remains payload-based and persistence-independent (FR-18)
# ---------------------------------------------------------------------------


def test_export_does_not_require_saved_deck(
    api_client: TestClient, seeded_collection: str
) -> None:
    """TC-FR-018-01: Plaintext export works from generated payload without deck_id lookup."""
    gen_resp = _generate(api_client, seeded_collection)
    assert gen_resp.status_code == 200

    # Submit the raw generated payload — no deck_id reference needed for export
    export_resp = api_client.post(EXPORT_ENDPOINT, json={"deck": gen_resp.json()})
    assert export_resp.status_code == 200
    assert export_resp.json()["format"] == "plaintext"
    assert "Commander" in export_resp.json()["text"]
    assert "Main Deck" in export_resp.json()["text"]
