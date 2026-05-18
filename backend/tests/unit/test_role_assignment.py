"""Tests for SC-DECK-023 role-slot quota accounting."""
from __future__ import annotations

from app.models.card import CardData
from app.models.deck import DeckCard
from app.recommendation.quota_config import RoleQuota
from app.recommendation.role_assignment import assign_role_slots
from app.recommendation.role_taxonomy import CardRole


def _card_data(
    oracle_id: str,
    name: str,
    oracle_text: str = "",
    type_line: str = "Creature",
    cmc: float = 2.0,
) -> CardData:
    return CardData(
        id=oracle_id,
        oracle_id=oracle_id,
        name=name,
        color_identity=["B", "G"],
        legalities={"commander": "legal"},
        type_line=type_line,
        oracle_text=oracle_text,
        cmc=cmc,
    )


def _deck_card(
    oracle_id: str,
    name: str,
    roles: list[str],
    selection_reason: str = "test selection",
    quantity: int = 1,
) -> DeckCard:
    return DeckCard(
        oracle_id=oracle_id,
        name=name,
        is_owned=False,
        quantity=quantity,
        roles=roles,
        selection_reason=selection_reason,
        synergy_score=0.0,
    )


def test_role_breakdown_uses_primary_slot_assignment() -> None:
    card = _deck_card(
        "multi-role-draw",
        "Multi Role Draw",
        [
            CardRole.CARD_DRAW.value,
            CardRole.RAMP.value,
            CardRole.TOKEN_MAKER.value,
        ],
        selection_reason="fills card_draw role",
    )

    result = assign_role_slots(
        main_deck=[card],
        quotas=[
            RoleQuota(CardRole.CARD_DRAW, 1, 4),
            RoleQuota(CardRole.RAMP, 1, 4),
        ],
        all_cards_lookup={
            card.oracle_id: _card_data(card.oracle_id, card.name, "Draw two cards.")
        },
    )

    assert result.main_deck[0].assigned_role == CardRole.CARD_DRAW.value
    assert result.role_breakdown == {CardRole.CARD_DRAW.value: 1}
    assert result.quota_status[0].actual_count == 1
    assert result.quota_status[1].actual_count == 0


def test_secondary_roles_contribute_fractional_credit_only() -> None:
    card = _deck_card(
        "draw-removal",
        "Draw Removal",
        [CardRole.CARD_DRAW.value, CardRole.SPOT_REMOVAL.value],
        selection_reason="fills card_draw role",
    )

    result = assign_role_slots(
        main_deck=[card],
        quotas=[
            RoleQuota(CardRole.CARD_DRAW, 1, 4),
            RoleQuota(CardRole.SPOT_REMOVAL, 1, 4),
        ],
        all_cards_lookup={
            card.oracle_id: _card_data(
                card.oracle_id,
                card.name,
                "Destroy target creature. Draw a card.",
                type_line="Instant",
            )
        },
    )

    assigned = result.main_deck[0]
    removal_status = next(
        quota for quota in result.quota_status if quota.role == CardRole.SPOT_REMOVAL.value
    )

    assert assigned.assigned_role == CardRole.CARD_DRAW.value
    assert assigned.secondary_role_credit == {CardRole.SPOT_REMOVAL.value: 0.5}
    assert result.role_breakdown == {CardRole.CARD_DRAW.value: 1}
    assert removal_status.actual_count == 0
    assert removal_status.credit_sum == 0.5
    assert removal_status.is_satisfied is False


def test_quota_overfill_is_hard_quality_failure() -> None:
    card = _deck_card(
        "overfull-ramp",
        "Overfull Ramp",
        [CardRole.RAMP.value],
        quantity=3,
    )

    result = assign_role_slots(
        main_deck=[card],
        quotas=[RoleQuota(CardRole.RAMP, 1, 2)],
        all_cards_lookup={
            card.oracle_id: _card_data(
                card.oracle_id,
                card.name,
                "Whenever you cast a spell, add {G}.",
            )
        },
    )

    status = result.quota_status[0]
    assert status.actual_count == 3
    assert status.is_satisfied is False
    assert status.warning is not None
    assert "overfilled" in status.warning


def test_displayed_role_breakdown_separates_assigned_role_from_tags() -> None:
    card = _deck_card(
        "package-evidence-card",
        "Package Evidence Card",
        [
            CardRole.CARD_DRAW.value,
            CardRole.TOKEN_MAKER.value,
            CardRole.SACRIFICE_OUTLET.value,
            CardRole.WIN_CONDITION.value,
        ],
        selection_reason="fills card_draw role",
    )

    result = assign_role_slots(
        main_deck=[card],
        quotas=[
            RoleQuota(CardRole.CARD_DRAW, 1, 4),
            RoleQuota(CardRole.TOKEN_MAKER, 1, 4),
            RoleQuota(CardRole.SACRIFICE_OUTLET, 1, 4),
            RoleQuota(CardRole.WIN_CONDITION, 1, 4),
        ],
        all_cards_lookup={
            card.oracle_id: _card_data(card.oracle_id, card.name, "Draw two cards.")
        },
    )

    assigned = result.main_deck[0]
    assert assigned.assigned_role == CardRole.CARD_DRAW.value
    assert assigned.roles == card.roles
    assert result.role_breakdown == {CardRole.CARD_DRAW.value: 1}


def test_fallback_skips_role_at_target_max() -> None:
    capped = [
        _deck_card(f"token-cap-{idx}", f"Token Cap {idx}", [CardRole.TOKEN_MAKER.value])
        for idx in range(5)
    ]
    flexible = _deck_card(
        "food-package-card",
        "Food Package Card",
        [CardRole.TOKEN_MAKER.value, CardRole.SACRIFICE_OUTLET.value],
        selection_reason="package member: food-sacrifice",
    )

    result = assign_role_slots(
        main_deck=[*capped, flexible],
        quotas=[
            RoleQuota(CardRole.TOKEN_MAKER, 0, 5),
            RoleQuota(CardRole.SACRIFICE_OUTLET, 0, 5),
        ],
        all_cards_lookup=None,
    )

    assert result.main_deck[-1].assigned_role == CardRole.SACRIFICE_OUTLET.value
    assert result.role_breakdown[CardRole.TOKEN_MAKER.value] == 5
    assert result.role_breakdown[CardRole.SACRIFICE_OUTLET.value] == 1


def test_fallback_returns_none_when_all_roles_at_cap() -> None:
    capped = [
        _deck_card(f"token-only-cap-{idx}", f"Token Only Cap {idx}", [CardRole.TOKEN_MAKER.value])
        for idx in range(5)
    ]
    extra = _deck_card(
        "extra-token-package",
        "Extra Token Package",
        [CardRole.TOKEN_MAKER.value],
        selection_reason="package member: food-sacrifice",
    )

    result = assign_role_slots(
        main_deck=[*capped, extra],
        quotas=[RoleQuota(CardRole.TOKEN_MAKER, 0, 5)],
        all_cards_lookup=None,
    )

    assert result.main_deck[-1].assigned_role is None
    assert result.role_breakdown == {CardRole.TOKEN_MAKER.value: 5}


def test_explicit_fill_reason_bypasses_quota_cap() -> None:
    capped = [
        _deck_card(
            f"explicit-cap-{idx}",
            f"Explicit Cap {idx}",
            [CardRole.TOKEN_MAKER.value],
            selection_reason="fills token_maker role",
        )
        for idx in range(5)
    ]
    explicit = _deck_card(
        "explicit-token",
        "Explicit Token",
        [CardRole.TOKEN_MAKER.value],
        selection_reason="fills token_maker role",
    )

    result = assign_role_slots(
        main_deck=[*capped, explicit],
        quotas=[RoleQuota(CardRole.TOKEN_MAKER, 0, 5)],
        all_cards_lookup=None,
    )

    assert result.main_deck[-1].assigned_role == CardRole.TOKEN_MAKER.value
    assert result.role_breakdown[CardRole.TOKEN_MAKER.value] == 6


def test_role_breakdown_increments_prevent_subsequent_overfill() -> None:
    first = _deck_card(
        "first-token",
        "First Token",
        [CardRole.TOKEN_MAKER.value],
        selection_reason="package member",
    )
    second = _deck_card(
        "second-token",
        "Second Token",
        [CardRole.TOKEN_MAKER.value],
        selection_reason="package member",
    )

    result = assign_role_slots(
        main_deck=[first, second],
        quotas=[RoleQuota(CardRole.TOKEN_MAKER, 0, 1)],
        all_cards_lookup=None,
    )

    assert result.main_deck[0].assigned_role == CardRole.TOKEN_MAKER.value
    assert result.main_deck[1].assigned_role is None
    assert result.role_breakdown == {CardRole.TOKEN_MAKER.value: 1}


def test_role_not_in_quota_order_is_not_assigned() -> None:
    card = _deck_card(
        "untracked-role",
        "Untracked Role",
        [CardRole.GRAVEYARD_SYNERGY.value],
        selection_reason="package member",
    )

    result = assign_role_slots(
        main_deck=[card],
        quotas=[RoleQuota(CardRole.TOKEN_MAKER, 0, 1)],
        all_cards_lookup=None,
    )

    assert result.main_deck[0].assigned_role is None
    assert result.role_breakdown == {}
