"""Unit tests for plaintext deck export formatting (SC-EXPORT-001)."""
from __future__ import annotations

from app.recommendation.deck_exporter import export_deck_to_plaintext
from app.schemas.deck_schema import (
    DeckCardSchema,
    GeneratedDeckResponse,
    QuotaStatusSchema,
)


def _card(
    oracle_id: str,
    name: str,
    *,
    quantity: int = 1,
    is_owned: bool = True,
) -> DeckCardSchema:
    return DeckCardSchema(
        oracle_id=oracle_id,
        name=name,
        is_owned=is_owned,
        quantity=quantity,
        roles=[],
        package_ids=[],
        selection_reason="Selected for test coverage.",
        synergy_score=0.0,
    )


def _deck(**overrides) -> GeneratedDeckResponse:
    data = {
        "deck_id": "deck-export-test",
        "session_id": "session-export-test",
        "commander": _card("cmd-1", "Meren of Clan Nel Toth"),
        "main_deck": [
            _card("sol-ring", "Sol Ring"),
            _card("forest", "Forest", quantity=12),
            _card("swamp", "Swamp", quantity=10),
            _card("skullclamp", "Skullclamp", is_owned=False),
        ],
        "role_breakdown": {},
        "quota_status": [],
        "package_breakdown": [],
        "warnings": [],
        "owned_count": 23,
        "owned_percentage": 0.95,
        "is_valid": True,
        "validation_errors": [],
        "upgrade_suggestions": [],
        "card_explanations": {},
    }
    data.update(overrides)
    return GeneratedDeckResponse(**data)


def test_plaintext_export_has_commander_section():
    text, _warnings = export_deck_to_plaintext(_deck())

    assert text.startswith("Commander\n1 Meren of Clan Nel Toth")


def test_plaintext_export_has_main_deck_section():
    text, _warnings = export_deck_to_plaintext(_deck())

    assert "\n\nMain Deck\n" in text


def test_plaintext_export_preserves_quantities():
    text, _warnings = export_deck_to_plaintext(_deck())

    assert "1 Sol Ring" in text
    assert "12 Forest" in text
    assert "10 Swamp" in text


def test_plaintext_export_groups_basic_lands():
    deck = _deck(
        main_deck=[
            _card("forest", "Forest", quantity=7),
            _card("sol-ring", "Sol Ring"),
            _card("forest", "Forest", quantity=5),
        ]
    )

    text, _warnings = export_deck_to_plaintext(deck)

    assert text.count("Forest") == 1
    assert "12 Forest" in text


def test_plaintext_export_marks_missing_cards():
    text, _warnings = export_deck_to_plaintext(_deck())

    assert "1 Skullclamp [missing]" in text


def test_plaintext_export_includes_warnings_when_present():
    deck = _deck(
        warnings=["Deck has quota warnings: RAMP underfilled."],
        validation_errors=["Deck contains 98 main-deck cards."],
        quota_status=[
            QuotaStatusSchema(
                role="RAMP",
                target_min=10,
                target_max=12,
                actual_count=8,
                is_satisfied=False,
                warning="RAMP underfilled.",
            )
        ],
    )

    text, warnings = export_deck_to_plaintext(deck)

    assert "\n\nWarnings\n" in text
    assert "- Deck has quota warnings: RAMP underfilled." in text
    assert "- Validation error: Deck contains 98 main-deck cards." in text
    assert "Deck has quota warnings: RAMP underfilled." in warnings
