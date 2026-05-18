"""Unit tests for missing-card upgrade suggestions."""
from __future__ import annotations

from app.models.card import CardData
from app.models.deck import DeckCard, GeneratedDeck, PackageCluster, QuotaStatus
from app.recommendation.upgrade_suggester import UpgradeSuggester


def _commander() -> CardData:
    return CardData(
        id="cmd",
        oracle_id="cmd",
        name="Test Commander",
        color_identity=["B", "G"],
        legalities={"commander": "legal"},
        type_line="Legendary Creature",
        oracle_text="",
        mana_cost="",
        cmc=2.0,
    )


def _card(
    oracle_id: str,
    name: str,
    is_owned: bool,
    roles: list[str],
    synergy_score: float = 0.0,
    package_ids: list[str] | None = None,
) -> DeckCard:
    return DeckCard(
        oracle_id=oracle_id,
        name=name,
        is_owned=is_owned,
        quantity=1,
        roles=roles,
        package_ids=package_ids or [],
        selection_reason="candidate",
        synergy_score=synergy_score,
    )


def _deck(main_deck: list[DeckCard]) -> GeneratedDeck:
    return GeneratedDeck(
        deck_id="deck",
        session_id="session",
        commander=_card("cmd", "Test Commander", True, []),
        main_deck=main_deck,
        role_breakdown={},
        quota_status=[],
        package_breakdown=[],
        warnings=[],
        owned_count=0,
        owned_percentage=0.0,
        is_valid=True,
        validation_errors=[],
    )


def _quota(role: str, actual: int, target_min: int = 2) -> QuotaStatus:
    return QuotaStatus(
        role=role,
        target_min=target_min,
        target_max=4,
        actual_count=actual,
        is_satisfied=actual >= target_min,
        warning=None if actual >= target_min else f"{role} underfilled",
    )


def test_upgrade_suggester_returns_only_missing_cards() -> None:
    missing = _card("missing-ramp", "Missing Ramp", False, ["RAMP"], 0.4)
    owned = _card("owned-draw", "Owned Draw", True, ["CARD_DRAW"], 0.9)

    suggestions = UpgradeSuggester().suggest(
        commander=_commander(),
        generated_deck=_deck([owned]),
        candidate_pool=[missing, owned],
        packages=[],
        quota_status=[_quota("RAMP", actual=0)],
    )

    assert [s.oracle_id for s in suggestions] == ["missing-ramp"]


def test_upgrade_suggester_prioritizes_underfilled_roles() -> None:
    ramp = _card("missing-ramp", "Missing Ramp", False, ["RAMP"], 0.2)
    draw = _card("missing-draw", "Missing Draw", False, ["CARD_DRAW"], 0.5)

    suggestions = UpgradeSuggester().suggest(
        commander=_commander(),
        generated_deck=_deck([]),
        candidate_pool=[draw, ramp],
        packages=[],
        quota_status=[_quota("RAMP", actual=0), _quota("CARD_DRAW", actual=3)],
    )

    assert suggestions[0].oracle_id == "missing-ramp"
    assert suggestions[0].priority == "core"


def test_upgrade_suggester_groups_by_priority_deterministically() -> None:
    core = _card("a-core", "A Core", False, ["RAMP"], 0.8)
    optional = _card("b-optional", "B Optional", False, ["WIN_CONDITION"], 0.1)
    package_card = _card("c-package", "C Package", False, ["TOKEN_MAKER"], 0.3)
    package = PackageCluster(
        package_id="pkg-sacrifice",
        label="sacrifice package",
        confidence=0.8,
        card_oracle_ids=["c-package", "deck-1", "deck-2", "deck-3"],
        top_roles=["TOKEN_MAKER"],
    )
    deck = _deck([
        _card("deck-1", "Deck 1", True, ["TOKEN_MAKER"], 0.2, ["pkg-sacrifice"]),
        _card("deck-2", "Deck 2", True, ["WIN_CONDITION"], 0.2, ["pkg-sacrifice"]),
        _card("deck-3", "Deck 3", True, ["SACRIFICE_OUTLET"], 0.2, ["pkg-sacrifice"]),
    ])

    first = UpgradeSuggester().suggest(
        commander=_commander(),
        generated_deck=deck,
        candidate_pool=[optional, package_card, core],
        packages=[package],
        quota_status=[],
    )
    second = UpgradeSuggester().suggest(
        commander=_commander(),
        generated_deck=deck,
        candidate_pool=[core, optional, package_card],
        packages=[package],
        quota_status=[],
    )

    assert [s.oracle_id for s in first] == [s.oracle_id for s in second]
    assert [s.priority for s in first] == ["core", "core", "optional"]


def test_upgrade_suggester_reason_references_role_or_package() -> None:
    card = _card("missing-payoff", "Missing Payoff", False, ["WIN_CONDITION"], 0.1, ["pkg-value"])
    package = PackageCluster(
        package_id="pkg-value",
        label="green value package",
        confidence=0.7,
        card_oracle_ids=["missing-payoff", "deck-1"],
        top_roles=["WIN_CONDITION"],
    )

    suggestions = UpgradeSuggester().suggest(
        commander=_commander(),
        generated_deck=_deck([_card("deck-1", "Deck 1", True, ["WIN_CONDITION"], 0.2)]),
        candidate_pool=[card],
        packages=[package],
        quota_status=[],
    )

    reason = suggestions[0].reason
    assert "WIN_CONDITION" in reason or "green value package" in reason
