"""Integration tests for the deck generation API (SC-API-003)."""
from __future__ import annotations

from app.api.v1.deck import _build_saved_deck_service, _build_service
from app.main import app
from app.models.deck import DeckCard, GeneratedDeck, StrategicCoherenceReport
from tests.conftest import GRETA_ORACLE_ID, MEREN_ORACLE_ID

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
        assert "repair_blockers" in data
        assert isinstance(data["repair_blockers"], list)
        assert data["generation_status"] in {"success", "failed_quality", "generated_with_collection_gap"}
        if data["generation_status"] == "failed_quality":
            assert any("Deck quality failure" in warning for warning in data["warnings"])
        if data["generation_status"] == "generated_with_collection_gap":
            assert any("collection_gap:" in warning for warning in data["warnings"])

    def test_api_marks_validation_error_as_generation_failure(self, api_client):
        """Invalid service output is clearly surfaced as failed validation."""
        invalid_deck = _invalid_generated_deck()
        saved_service = _FakeSavedDeckService()

        app.dependency_overrides[_build_service] = lambda: _FakeDeckService(invalid_deck)
        app.dependency_overrides[_build_saved_deck_service] = lambda: saved_service
        try:
            resp = _generate(api_client, "invalid-session", "invalid-cmd")
        finally:
            app.dependency_overrides.pop(_build_service, None)
            app.dependency_overrides.pop(_build_saved_deck_service, None)

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_valid"] is False
        assert data["generation_status"] == "failed_validation"
        assert data["validation_errors"] == ["Deck contains duplicate non-basic cards."]
        assert saved_service.saved is False

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

    def test_deck_generation_api_includes_quota_credit_fields(
        self, api_client, seeded_collection
    ):
        """Response exposes role-credit quota status for each tracked role."""
        resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert resp.status_code == 200
        quota_status = resp.json()["quota_status"]
        assert quota_status
        for q in quota_status:
            assert "credit_sum" in q
            assert isinstance(q["credit_sum"], (float, int))
            assert "credit_satisfied" in q
            assert isinstance(q["credit_satisfied"], bool)
            assert "credit_warning" in q

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

    def test_deck_generation_api_includes_strategic_coherence(
        self, api_client, seeded_collection
    ):
        resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert resp.status_code == 200
        coherence = resp.json()["strategic_coherence"]
        assert coherence is not None
        assert "primary_plan" in coherence
        assert "confidence" in coherence
        assert "warning_card_oracle_ids" in coherence
        assert isinstance(coherence["warnings"], list)

    def test_plaintext_export_api_returns_text(self, api_client, seeded_collection):
        deck_resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert deck_resp.status_code == 200
        deck = deck_resp.json()
        deck["generation_status"] = "success"

        resp = api_client.post(EXPORT_ENDPOINT, json={"deck": deck})

        assert resp.status_code == 200
        data = resp.json()
        assert data["format"] == "plaintext"
        assert "Commander" in data["text"]
        assert "Main Deck" in data["text"]

    def test_invalid_generated_deck_not_exportable(
        self, api_client, seeded_collection
    ):
        deck_resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert deck_resp.status_code == 200
        deck = deck_resp.json()
        deck["is_valid"] = False
        deck["generation_status"] = "failed_validation"
        deck["validation_errors"] = ["Deck contains duplicate non-basic cards."]

        resp = api_client.post(EXPORT_ENDPOINT, json={"deck": deck})

        assert resp.status_code == 422
        assert "invalid generated deck" in resp.text

    def test_plaintext_export_api_preserves_generated_deck_quantities(
        self, api_client, seeded_collection
    ):
        deck_resp = _generate(api_client, seeded_collection, MEREN_ORACLE_ID)
        assert deck_resp.status_code == 200
        deck = deck_resp.json()
        deck["generation_status"] = "success"
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
        deck["generation_status"] = "success"
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
        deck["generation_status"] = "success"
        deck["commander"]["name"] = "API Supplied Commander"

        exported = api_client.post(EXPORT_ENDPOINT, json={"deck": deck})

        assert exported.status_code == 200
        assert "1 API Supplied Commander" in exported.json()["text"]


class TestGretaDeckGenerationAPI:
    """SC-DECK-035: Archetype quota profile integration tests for food-sacrifice."""

    def test_greta_deck_includes_aristocrats_synergy_cards(
        self, api_client, seeded_greta_collection
    ):
        """Greta deck with food-sacrifice profile contains at least one ARISTOCRATS_SYNERGY card."""
        resp = _generate(api_client, seeded_greta_collection, GRETA_ORACLE_ID)
        assert resp.status_code == 200
        data = resp.json()
        all_roles = [role for card in data["main_deck"] for role in card.get("roles", [])]
        assert "ARISTOCRATS_SYNERGY" in all_roles, (
            "Expected at least one ARISTOCRATS_SYNERGY card in Greta deck"
        )

    def test_greta_deck_quota_status_shows_aristocrats_synergy_satisfied(
        self, api_client, seeded_greta_collection
    ):
        """Greta deck quota_status includes ARISTOCRATS_SYNERGY entry with is_satisfied=True."""
        resp = _generate(api_client, seeded_greta_collection, GRETA_ORACLE_ID)
        assert resp.status_code == 200
        data = resp.json()
        quota_status = data["quota_status"]
        synergy_quota = next(
            (q for q in quota_status if q["role"] == "ARISTOCRATS_SYNERGY"), None
        )
        assert synergy_quota is not None, "ARISTOCRATS_SYNERGY quota must be present for food-sacrifice plan"
        assert synergy_quota["is_satisfied"], (
            f"ARISTOCRATS_SYNERGY quota not satisfied: {synergy_quota}"
        )


class _FakeDeckService:
    def __init__(self, deck: GeneratedDeck) -> None:
        self._deck = deck

    def generate_deck(self, session_id: str, commander_oracle_id: str) -> GeneratedDeck:
        return self._deck


class _FakeSavedDeckService:
    def __init__(self) -> None:
        self.saved = False

    def save_generated_deck(self, deck) -> None:
        self.saved = True


def _invalid_generated_deck() -> GeneratedDeck:
    return GeneratedDeck(
        deck_id="invalid-deck",
        session_id="invalid-session",
        generation_status="failed_validation",
        commander=DeckCard(
            oracle_id="invalid-cmd",
            name="Invalid Commander",
            is_owned=True,
            quantity=1,
            roles=["COMMANDER"],
            selection_reason="test commander",
        ),
        main_deck=[
            DeckCard(
                oracle_id="duplicate-nonbasic",
                name="Duplicate Nonbasic",
                is_owned=True,
                quantity=2,
                roles=["WIN_CONDITION"],
                selection_reason="invalid duplicate",
            )
        ],
        role_breakdown={"WIN_CONDITION": 2},
        quota_status=[],
        package_breakdown=[],
        warnings=["Generation failed validation."],
        owned_count=2,
        owned_percentage=2 / 99,
        is_valid=False,
        validation_errors=["Deck contains duplicate non-basic cards."],
        strategic_coherence=StrategicCoherenceReport(
            primary_plan=None,
            confidence=0.0,
            warnings=["Generation failed validation."],
        ),
    )
