"""Unit tests for generated deck card explanations."""
from __future__ import annotations

from app.models.deck import DeckCard, GeneratedDeck, PackageCluster, QuotaStatus
from app.recommendation.card_explainer import CardExplainer


def _card(
    oracle_id: str,
    name: str,
    is_owned: bool,
    roles: list[str],
    package_ids: list[str] | None = None,
    selection_reason: str = "fills role",
) -> DeckCard:
    return DeckCard(
        oracle_id=oracle_id,
        name=name,
        is_owned=is_owned,
        quantity=1,
        roles=roles,
        package_ids=package_ids or [],
        selection_reason=selection_reason,
        synergy_score=0.6,
    )


def _deck(cards: list[DeckCard]) -> GeneratedDeck:
    return GeneratedDeck(
        deck_id="deck",
        session_id="session",
        commander=_card("cmd", "Test Commander", True, [], selection_reason="commander"),
        main_deck=cards,
        role_breakdown={},
        quota_status=[],
        package_breakdown=[],
        warnings=[],
        owned_count=0,
        owned_percentage=0.0,
        is_valid=True,
        validation_errors=[],
    )


def test_card_explainer_returns_explanation_for_each_deck_card() -> None:
    deck = _deck([
        _card("ramp", "Ramp Spell", True, ["RAMP"]),
        _card("draw", "Draw Spell", True, ["CARD_DRAW"]),
    ])

    explanations = CardExplainer().explain_deck(deck, [], [])

    assert set(explanations) == {"cmd", "ramp", "draw"}


def test_card_explainer_uses_actual_roles_and_packages() -> None:
    deck = _deck([
        _card("payoff", "Payoff", True, ["WIN_CONDITION"], ["pkg-aristocrats"]),
    ])
    package = PackageCluster(
        package_id="pkg-aristocrats",
        label="aristocrats package",
        confidence=0.9,
        card_oracle_ids=["payoff"],
        top_roles=["WIN_CONDITION"],
    )

    explanations = CardExplainer().explain_deck(
        deck,
        [package],
        [QuotaStatus(role="WIN_CONDITION", target_min=1, target_max=4, actual_count=1, is_satisfied=True)],
    )

    explanation = explanations["payoff"]
    assert explanation.roles == ["WIN_CONDITION"]
    assert explanation.package_ids == ["pkg-aristocrats"]
    assert any("aristocrats package" in evidence for evidence in explanation.evidence)


def test_card_explainer_marks_missing_cards_as_missing() -> None:
    deck = _deck([_card("missing", "Missing Card", False, ["RAMP"])])

    explanation = CardExplainer().explain_deck(deck, [], [])["missing"]

    assert explanation.is_owned is False
    assert "missing" in explanation.summary.lower()
    assert any("Missing card" in evidence for evidence in explanation.evidence)


def test_card_explainer_does_not_emit_empty_evidence() -> None:
    deck = _deck([_card("utility", "Utility Card", True, [])])

    explanations = CardExplainer().explain_deck(deck, [], [])

    for explanation in explanations.values():
        assert explanation.evidence
        assert all(item.strip() for item in explanation.evidence)
