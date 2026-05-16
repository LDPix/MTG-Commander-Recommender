"""Unit tests for deck generation request/response schemas (SC-API-003)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.deck_schema import (
    CardExplanationSchema,
    DeckCardSchema,
    DeckExportRequest,
    DeckExportResponse,
    DeckGenerateRequest,
    GeneratedDeckResponse,
    PackageSchema,
    QuotaStatusSchema,
    UpgradeSuggestionSchema,
)


class TestDeckGenerateRequest:
    def test_deck_generate_request_requires_session_id(self):
        with pytest.raises(ValidationError):
            DeckGenerateRequest(session_id="", commander_oracle_id="some-oracle-id")

    def test_deck_generate_request_requires_commander_oracle_id(self):
        with pytest.raises(ValidationError):
            DeckGenerateRequest(session_id="some-session", commander_oracle_id="")

    def test_deck_generate_request_requires_both_fields(self):
        with pytest.raises(ValidationError):
            DeckGenerateRequest(session_id="s")  # type: ignore[call-arg]

    def test_deck_generate_request_valid(self):
        req = DeckGenerateRequest(
            session_id="session-123",
            commander_oracle_id="oracle-abc",
        )
        assert req.session_id == "session-123"
        assert req.commander_oracle_id == "oracle-abc"

    def test_deck_generate_request_rejects_whitespace_only_session(self):
        with pytest.raises(ValidationError):
            DeckGenerateRequest(session_id="   ", commander_oracle_id="oracle-abc")


class TestGeneratedDeckResponse:
    def _make_card(self, oracle_id: str = "oid-1", name: str = "Card") -> dict:
        return {
            "oracle_id": oracle_id,
            "name": name,
            "is_owned": True,
            "quantity": 1,
            "roles": ["RAMP"],
            "package_ids": [],
            "selection_reason": "test",
            "synergy_score": 0.5,
        }

    def test_generated_deck_response_serializes_correctly(self):
        main_deck = [self._make_card(f"oid-{i}", f"Card {i}") for i in range(99)]
        response = GeneratedDeckResponse(
            deck_id="deck-001",
            session_id="session-001",
            commander=DeckCardSchema(**self._make_card("cmd-1", "Commander")),
            main_deck=[DeckCardSchema(**c) for c in main_deck],
            role_breakdown={"LAND": 37, "RAMP": 10},
            quota_status=[
                QuotaStatusSchema(
                    role="LAND",
                    target_min=36,
                    target_max=38,
                    actual_count=37,
                    is_satisfied=True,
                    warning=None,
                )
            ],
            package_breakdown=[
                PackageSchema(
                    package_id="pkg-1",
                    label="sacrifice",
                    confidence=0.9,
                    card_oracle_ids=["oid-1"],
                    top_roles=["SACRIFICE_OUTLET"],
                )
            ],
            warnings=[],
            owned_count=50,
            owned_percentage=0.5,
            is_valid=True,
            validation_errors=[],
            upgrade_suggestions=[],
            card_explanations={},
        )
        assert response.deck_id == "deck-001"
        assert len(response.main_deck) == 99
        assert response.is_valid is True
        assert response.role_breakdown["LAND"] == 37

    def test_generated_deck_response_allows_warnings(self):
        main_deck = [self._make_card(f"oid-{i}", f"Card {i}") for i in range(99)]
        response = GeneratedDeckResponse(
            deck_id="deck-002",
            session_id="session-002",
            commander=DeckCardSchema(**self._make_card()),
            main_deck=[DeckCardSchema(**c) for c in main_deck],
            role_breakdown={},
            quota_status=[],
            package_breakdown=[],
            warnings=["QUOTA_NOT_MET: RAMP"],
            owned_count=0,
            owned_percentage=0.0,
            is_valid=False,
            validation_errors=["Deck is under quota for RAMP"],
            upgrade_suggestions=[],
            card_explanations={},
        )
        assert response.is_valid is False
        assert len(response.warnings) == 1
        assert len(response.validation_errors) == 1

    def test_generated_deck_response_serializes_upgrade_suggestions(self):
        main_deck = [self._make_card(f"oid-{i}", f"Card {i}") for i in range(99)]
        response = GeneratedDeckResponse(
            deck_id="deck-003",
            session_id="session-003",
            commander=DeckCardSchema(**self._make_card("cmd-1", "Commander")),
            main_deck=[DeckCardSchema(**c) for c in main_deck],
            role_breakdown={},
            quota_status=[],
            package_breakdown=[],
            warnings=[],
            owned_count=50,
            owned_percentage=0.5,
            is_valid=True,
            validation_errors=[],
            upgrade_suggestions=[
                UpgradeSuggestionSchema(
                    oracle_id="missing-1",
                    name="Missing Upgrade",
                    priority="core",
                    improves_roles=["RAMP"],
                    improves_packages=["pkg-1"],
                    reason="Missing Upgrade improves RAMP.",
                    impact_score=0.82,
                    replaces_or_supplements=[],
                )
            ],
            card_explanations={},
        )

        dumped = response.model_dump()
        assert dumped["upgrade_suggestions"][0]["priority"] == "core"
        assert dumped["upgrade_suggestions"][0]["improves_roles"] == ["RAMP"]

    def test_generated_deck_response_serializes_card_explanations(self):
        main_deck = [self._make_card(f"oid-{i}", f"Card {i}") for i in range(99)]
        response = GeneratedDeckResponse(
            deck_id="deck-004",
            session_id="session-004",
            commander=DeckCardSchema(**self._make_card("cmd-1", "Commander")),
            main_deck=[DeckCardSchema(**c) for c in main_deck],
            role_breakdown={},
            quota_status=[],
            package_breakdown=[],
            warnings=[],
            owned_count=50,
            owned_percentage=0.5,
            is_valid=True,
            validation_errors=[],
            upgrade_suggestions=[],
            card_explanations={
                "oid-1": CardExplanationSchema(
                    oracle_id="oid-1",
                    name="Card 1",
                    summary="Card 1 fills RAMP.",
                    evidence=["Roles: RAMP."],
                    roles=["RAMP"],
                    package_ids=[],
                    synergy_score=0.5,
                    is_owned=True,
                )
            },
        )

        dumped = response.model_dump()
        assert dumped["card_explanations"]["oid-1"]["summary"]
        assert dumped["card_explanations"]["oid-1"]["evidence"] == ["Roles: RAMP."]


class TestDeckExportSchemas:
    def _make_card(self, oracle_id: str = "oid-1", name: str = "Card") -> dict:
        return {
            "oracle_id": oracle_id,
            "name": name,
            "is_owned": True,
            "quantity": 1,
            "roles": ["RAMP"],
            "package_ids": [],
            "selection_reason": "test",
            "synergy_score": 0.5,
        }

    def _make_generated_deck(self) -> GeneratedDeckResponse:
        main_deck = [self._make_card(f"oid-{i}", f"Card {i}") for i in range(99)]
        return GeneratedDeckResponse(
            deck_id="deck-export-001",
            session_id="session-export-001",
            commander=DeckCardSchema(**self._make_card("cmd-1", "Commander")),
            main_deck=[DeckCardSchema(**c) for c in main_deck],
            role_breakdown={},
            quota_status=[],
            package_breakdown=[],
            warnings=[],
            owned_count=50,
            owned_percentage=0.5,
            is_valid=True,
            validation_errors=[],
            upgrade_suggestions=[],
            card_explanations={},
        )

    def test_deck_export_request_accepts_generated_deck_response(self):
        request = DeckExportRequest(deck=self._make_generated_deck())

        assert request.deck.deck_id == "deck-export-001"
        assert sum(card.quantity for card in request.deck.main_deck) == 99

    def test_deck_export_response_serializes_text(self):
        response = DeckExportResponse(
            text="Commander\n1 Commander\n\nMain Deck\n1 Sol Ring",
            warnings=[],
        )

        dumped = response.model_dump()
        assert dumped["format"] == "plaintext"
        assert dumped["text"].startswith("Commander")

    def test_deck_export_request_rejects_structurally_impossible_count(self):
        deck = self._make_generated_deck()
        deck.main_deck = deck.main_deck[:-1]

        with pytest.raises(ValidationError):
            DeckExportRequest(deck=deck)


class TestSCDeck008Lock:
    """SC-DECK-008: Lock MVP deck profile — no power-level input, one profile."""

    def test_deck_generation_request_has_no_power_level_requirement(self):
        """Deck generation request must not require a power_level field (SC-DECK-008)."""
        req = DeckGenerateRequest(session_id="s", commander_oracle_id="x")
        assert not hasattr(req, "power_level") or getattr(req, "power_level", None) is None

    def test_default_playable_profile_used_for_quotas(self):
        """Deck generation uses BASELINE_QUOTAS without power-level input (SC-DECK-008)."""
        from app.recommendation.quota_config import BASELINE_QUOTAS
        from app.recommendation.role_taxonomy import CardRole

        land_quota = next(q for q in BASELINE_QUOTAS if q.role == CardRole.LAND)
        assert land_quota.target_min == 36
        assert land_quota.target_max == 38

    def test_baseline_quotas_covers_all_required_roles(self):
        """BASELINE_QUOTAS defines all required MVP roles (SC-DECK-008)."""
        from app.recommendation.quota_config import BASELINE_QUOTAS
        from app.recommendation.role_taxonomy import CardRole

        quota_roles = {q.role for q in BASELINE_QUOTAS}
        required = {CardRole.LAND, CardRole.RAMP, CardRole.CARD_DRAW, CardRole.SPOT_REMOVAL}
        assert required.issubset(quota_roles)
