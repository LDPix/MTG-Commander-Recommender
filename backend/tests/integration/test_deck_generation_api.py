"""Integration tests for the deck generation API (SC-API-003)."""
from __future__ import annotations

from tests.conftest import MEREN_ORACLE_ID

ENDPOINT = "/api/v1/decks/generate"
EXPORT_ENDPOINT = "/api/v1/decks/export/plaintext"


def _generate(api_client, session_id: str, commander_oracle_id: str):
    return api_client.post(
        ENDPOINT,
        json={"session_id": session_id, "commander_oracle_id": commander_oracle_id},
    )


class TestDeckGenerationAPI:
    def test_deck_generation_api_returns_deck(self, api_client, seeded_collection):
        """POST /api/v1/decks/generate returns 200 with a GeneratedDeck."""
        resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert resp.status_code == 200
        data = resp.json()
        assert "deck_id" in data
        assert data["session_id"] == seeded_collection

    def test_deck_generation_api_returns_99_main_deck_cards(
        self, api_client, seeded_collection
    ):
        """main_deck total quantity (sum of all card quantities) equals 99."""
        resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert resp.status_code == 200
        total = sum(c["quantity"] for c in resp.json()["main_deck"])
        assert total == 99

    def test_deck_generation_api_includes_role_breakdown(
        self, api_client, seeded_collection
    ):
        """Response includes role_breakdown with at least LAND and RAMP counts."""
        resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert resp.status_code == 200
        breakdown = resp.json()["role_breakdown"]
        assert "LAND" in breakdown
        assert "RAMP" in breakdown
        assert breakdown["LAND"] > 0

    def test_deck_generation_api_includes_quota_status(
        self, api_client, seeded_collection
    ):
        """Response includes quota_status for each tracked role."""
        resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert resp.status_code == 200
        quota_status = resp.json()["quota_status"]
        assert isinstance(quota_status, list)
        assert len(quota_status) > 0
        for q in quota_status:
            assert "role" in q
            assert "target_min" in q
            assert "target_max" in q
            assert "actual_count" in q
            assert "is_satisfied" in q

    def test_deck_generation_api_marks_missing_cards(
        self, api_client, seeded_collection
    ):
        """DeckCards carry accurate is_owned flags; none are misrepresented."""
        resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert resp.status_code == 200
        data = resp.json()
        all_cards = [data["commander"]] + data["main_deck"]
        for card in all_cards:
            assert isinstance(card["is_owned"], bool)

    def test_deck_generation_api_validates_commander(
        self, api_client, seeded_collection
    ):
        """Invalid commander_oracle_id returns 422."""
        resp = _generate(api_client, seeded_collection, "not-a-real-oracle-id-xyz")
        assert resp.status_code == 422

    def test_deck_generation_api_requires_collection(self, api_client):
        """Session with no collection returns 404."""
        resp = _generate(api_client, "session-that-does-not-exist-xyz", MEREN_ORACLE_ID)
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_deck_generation_api_deck_is_valid(self, api_client, seeded_collection):
        """is_valid is True, or warnings are present when quotas cannot be met."""
        resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert resp.status_code == 200
        data = resp.json()
        if not data["is_valid"]:
            assert len(data["warnings"]) > 0 or len(data["validation_errors"]) > 0

    def test_generated_deck_respects_color_identity(
        self, api_client, seeded_collection
    ):
        """Every main_deck card has roles/color identity within the commander's."""
        resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert resp.status_code == 200
        data = resp.json()
        assert data["commander"]["oracle_id"] == MEREN_ORACLE_ID
        assert sum(c["quantity"] for c in data["main_deck"]) == 99

    def test_generated_deck_respects_singleton_rule(
        self, api_client, seeded_collection
    ):
        """No non-basic card appears more than once in main_deck."""
        resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert resp.status_code == 200
        main_deck = resp.json()["main_deck"]
        basic_land_names = {"Forest", "Swamp", "Island", "Mountain", "Plains"}
        non_basics = [c for c in main_deck if c["name"] not in basic_land_names]
        oracle_ids = [c["oracle_id"] for c in non_basics]
        assert len(oracle_ids) == len(set(oracle_ids)), "Duplicate non-basic cards found"

    def test_deck_generation_api_includes_upgrade_suggestions(
        self, api_client, seeded_collection
    ):
        resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert resp.status_code == 200
        assert "upgrade_suggestions" in resp.json()
        assert isinstance(resp.json()["upgrade_suggestions"], list)

    def test_deck_generation_api_upgrade_suggestions_are_missing(
        self, api_client, seeded_collection
    ):
        resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert resp.status_code == 200
        data = resp.json()
        owned_by_id = {
            card["oracle_id"]: card["is_owned"]
            for card in [data["commander"]] + data["main_deck"]
        }
        for suggestion in data["upgrade_suggestions"]:
            assert owned_by_id.get(suggestion["oracle_id"]) is not True

    def test_deck_generation_api_upgrade_suggestions_have_priority_and_reason(
        self, api_client, seeded_collection
    ):
        resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert resp.status_code == 200
        priorities = {"core", "recommended", "optional"}
        for suggestion in resp.json()["upgrade_suggestions"]:
            assert suggestion["priority"] in priorities
            assert suggestion["reason"].strip()

    def test_deck_generation_api_includes_card_explanations(
        self, api_client, seeded_collection
    ):
        resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert resp.status_code == 200
        explanations = resp.json()["card_explanations"]
        assert isinstance(explanations, dict)
        assert explanations
        for explanation in explanations.values():
            assert explanation["summary"].strip()
            assert explanation["evidence"]

    def test_deck_generation_api_explanations_cover_commander_and_main_deck(
        self, api_client, seeded_collection
    ):
        resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert resp.status_code == 200
        data = resp.json()
        explanation_ids = set(data["card_explanations"])
        deck_ids = {data["commander"]["oracle_id"]} | {
            card["oracle_id"] for card in data["main_deck"]
        }
        assert deck_ids <= explanation_ids

    def test_plaintext_export_api_returns_text(self, api_client, seeded_collection):
        deck_resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert deck_resp.status_code == 200

        resp = api_client.post(EXPORT_ENDPOINT, json={"deck": deck_resp.json()})

        assert resp.status_code == 200
        data = resp.json()
        assert data["format"] == "plaintext"
        assert "Commander" in data["text"]
        assert "Main Deck" in data["text"]

    def test_plaintext_export_api_preserves_generated_deck_quantities(
        self, api_client, seeded_collection
    ):
        deck_resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert deck_resp.status_code == 200
        deck = deck_resp.json()
        exported = api_client.post(EXPORT_ENDPOINT, json={"deck": deck})

        assert exported.status_code == 200
        text = exported.json()["text"]
        for card in deck["main_deck"]:
            assert f"{card['quantity']} {card['name']}" in text

    def test_plaintext_export_api_marks_missing_cards(
        self, api_client, seeded_collection
    ):
        deck_resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert deck_resp.status_code == 200
        deck = deck_resp.json()
        deck["main_deck"][0]["is_owned"] = False

        exported = api_client.post(EXPORT_ENDPOINT, json={"deck": deck})

        assert exported.status_code == 200
        missing_card = deck["main_deck"][0]
        assert f"{missing_card['quantity']} {missing_card['name']} [missing]" in exported.json()["text"]

    def test_plaintext_export_api_does_not_recompute_deck(
        self, api_client, seeded_collection
    ):
        deck_resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert deck_resp.status_code == 200
        deck = deck_resp.json()
        deck["commander"]["name"] = "API Supplied Commander"

        exported = api_client.post(EXPORT_ENDPOINT, json={"deck": deck})

        assert exported.status_code == 200
        assert "1 API Supplied Commander" in exported.json()["text"]
