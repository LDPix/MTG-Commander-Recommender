"""Tests for SC-DECK-003/004/035: quota_config module."""
from __future__ import annotations

import pytest

from app.models.card import CardData
from app.recommendation.quota_config import (
    ARCHETYPE_QUOTA_PROFILES,
    BASELINE_QUOTAS,
    RoleQuota,
    adjust_quotas_for_commander,
)
from app.recommendation.role_taxonomy import CardRole, RoleTag


def _make_card(
    name: str = "Test Commander",
    cmc: float = 4.0,
    color_identity: list[str] | None = None,
) -> CardData:
    return CardData(
        id=f"test-{name.lower().replace(' ', '-')}",
        oracle_id=f"test-{name.lower().replace(' ', '-')}",
        name=name,
        color_identity=color_identity or ["B", "G"],
        legalities={"commander": "legal"},
        type_line="Legendary Creature — Test",
        cmc=cmc,
    )


def _make_tag(role: CardRole) -> RoleTag:
    return RoleTag(role=role, confidence=0.9, source="rule_based")


def test_baseline_quotas_cover_core_roles() -> None:
    """All 7 core roles are present in the baseline quotas."""
    roles = {q.role for q in BASELINE_QUOTAS}
    assert CardRole.LAND in roles
    assert CardRole.RAMP in roles
    assert CardRole.CARD_DRAW in roles
    assert CardRole.SPOT_REMOVAL in roles
    assert CardRole.BOARD_WIPE in roles
    assert CardRole.PROTECTION in roles
    assert CardRole.WIN_CONDITION in roles


def test_baseline_quotas_have_positive_targets() -> None:
    """All baseline quotas have positive target_min and target_max."""
    for quota in BASELINE_QUOTAS:
        assert quota.target_min > 0
        assert quota.target_max >= quota.target_min


def test_adjust_quotas_no_change_for_average_commander() -> None:
    """A 4 CMC commander with no relevant tags returns standard quotas."""
    commander = _make_card(cmc=4.0)
    adjusted = adjust_quotas_for_commander(BASELINE_QUOTAS, commander, commander_tags=[])

    baseline_ramp = next(q for q in BASELINE_QUOTAS if q.role == CardRole.RAMP)
    adjusted_ramp = next(q for q in adjusted if q.role == CardRole.RAMP)
    assert adjusted_ramp.target_min == baseline_ramp.target_min


def test_adjust_quotas_high_cmc_commander() -> None:
    """Commander with CMC >= 6 increases RAMP target_min by 2."""
    commander = _make_card(cmc=7.0)
    baseline_ramp = next(q for q in BASELINE_QUOTAS if q.role == CardRole.RAMP)

    adjusted = adjust_quotas_for_commander(BASELINE_QUOTAS, commander, commander_tags=[])
    adjusted_ramp = next(q for q in adjusted if q.role == CardRole.RAMP)

    assert adjusted_ramp.target_min == baseline_ramp.target_min + 2


def test_adjust_quotas_cmc_5_no_ramp_increase() -> None:
    """Commander with CMC == 5 does NOT trigger high-CMC ramp increase."""
    commander = _make_card(cmc=5.0)
    baseline_ramp = next(q for q in BASELINE_QUOTAS if q.role == CardRole.RAMP)

    adjusted = adjust_quotas_for_commander(BASELINE_QUOTAS, commander, commander_tags=[])
    adjusted_ramp = next(q for q in adjusted if q.role == CardRole.RAMP)

    assert adjusted_ramp.target_min == baseline_ramp.target_min


def test_adjust_quotas_draw_commander() -> None:
    """Commander with CARD_DRAW tag reduces CARD_DRAW target_min by 2 (floor 6)."""
    commander = _make_card(cmc=3.0)
    tags = [_make_tag(CardRole.CARD_DRAW)]

    baseline_draw = next(q for q in BASELINE_QUOTAS if q.role == CardRole.CARD_DRAW)
    adjusted = adjust_quotas_for_commander(BASELINE_QUOTAS, commander, commander_tags=tags)
    adjusted_draw = next(q for q in adjusted if q.role == CardRole.CARD_DRAW)

    expected = max(6, baseline_draw.target_min - 2)
    assert adjusted_draw.target_min == expected


def test_adjust_quotas_ramp_commander() -> None:
    """Commander with RAMP tag reduces RAMP target_min by 1 (floor 8)."""
    commander = _make_card(cmc=2.0)
    tags = [_make_tag(CardRole.RAMP)]

    baseline_ramp = next(q for q in BASELINE_QUOTAS if q.role == CardRole.RAMP)
    adjusted = adjust_quotas_for_commander(BASELINE_QUOTAS, commander, commander_tags=tags)
    adjusted_ramp = next(q for q in adjusted if q.role == CardRole.RAMP)

    expected = max(8, baseline_ramp.target_min - 1)
    assert adjusted_ramp.target_min == expected


def test_adjust_quotas_sacrifice_commander() -> None:
    """Commander with SACRIFICE_OUTLET tag adds a SACRIFICE_OUTLET quota (3, 5)."""
    commander = _make_card(cmc=4.0)
    tags = [_make_tag(CardRole.SACRIFICE_OUTLET)]

    adjusted = adjust_quotas_for_commander(BASELINE_QUOTAS, commander, commander_tags=tags)
    sacrifice_quotas = [q for q in adjusted if q.role == CardRole.SACRIFICE_OUTLET]

    assert len(sacrifice_quotas) == 1
    assert sacrifice_quotas[0].target_min == 3
    assert sacrifice_quotas[0].target_max == 5


def test_adjust_quotas_does_not_mutate_baseline() -> None:
    """adjust_quotas_for_commander does not mutate the input baseline list."""
    original_ramp_min = next(q for q in BASELINE_QUOTAS if q.role == CardRole.RAMP).target_min

    commander = _make_card(cmc=8.0)
    adjust_quotas_for_commander(BASELINE_QUOTAS, commander, commander_tags=[])

    after_ramp_min = next(q for q in BASELINE_QUOTAS if q.role == CardRole.RAMP).target_min
    assert after_ramp_min == original_ramp_min


def test_adjust_quotas_returns_all_baseline_roles() -> None:
    """All baseline roles are present in adjusted quotas (plus any additions)."""
    commander = _make_card(cmc=4.0)
    adjusted = adjust_quotas_for_commander(BASELINE_QUOTAS, commander, commander_tags=[])

    adjusted_roles = {q.role for q in adjusted}
    for q in BASELINE_QUOTAS:
        assert q.role in adjusted_roles


# ---------------------------------------------------------------------------
# SC-DECK-035: Archetype quota profiles
# ---------------------------------------------------------------------------

def test_food_sacrifice_plan_loads_aristocrats_synergy_quota() -> None:
    """food-sacrifice plan includes ARISTOCRATS_SYNERGY with target_min >= 5."""
    commander = _make_card(cmc=3.0)
    adjusted = adjust_quotas_for_commander(
        BASELINE_QUOTAS, commander, commander_tags=[], primary_plan="food-sacrifice"
    )
    synergy = next((q for q in adjusted if q.role == CardRole.ARISTOCRATS_SYNERGY), None)
    assert synergy is not None
    assert synergy.target_min >= 5


def test_food_sacrifice_plan_loads_sacrifice_outlet_quota() -> None:
    """food-sacrifice plan includes SACRIFICE_OUTLET with target_min >= 4."""
    commander = _make_card(cmc=3.0)
    adjusted = adjust_quotas_for_commander(
        BASELINE_QUOTAS, commander, commander_tags=[], primary_plan="food-sacrifice"
    )
    outlet = next((q for q in adjusted if q.role == CardRole.SACRIFICE_OUTLET), None)
    assert outlet is not None
    assert outlet.target_min >= 4


def test_landfall_plan_has_higher_ramp_minimum_than_baseline() -> None:
    """landfall profile RAMP target_min > BASELINE_QUOTAS RAMP target_min."""
    baseline_ramp = next(q for q in BASELINE_QUOTAS if q.role == CardRole.RAMP)
    commander = _make_card(cmc=4.0)
    adjusted = adjust_quotas_for_commander(
        BASELINE_QUOTAS, commander, commander_tags=[], primary_plan="landfall"
    )
    adjusted_ramp = next(q for q in adjusted if q.role == CardRole.RAMP)
    assert adjusted_ramp.target_min > baseline_ramp.target_min


def test_spellslinger_plan_has_higher_card_draw_minimum_than_baseline() -> None:
    """spellslinger profile CARD_DRAW target_min > BASELINE_QUOTAS CARD_DRAW target_min."""
    baseline_draw = next(q for q in BASELINE_QUOTAS if q.role == CardRole.CARD_DRAW)
    commander = _make_card(cmc=4.0)
    adjusted = adjust_quotas_for_commander(
        BASELINE_QUOTAS, commander, commander_tags=[], primary_plan="spellslinger"
    )
    adjusted_draw = next(q for q in adjusted if q.role == CardRole.CARD_DRAW)
    assert adjusted_draw.target_min > baseline_draw.target_min


def test_unknown_plan_falls_back_to_baseline() -> None:
    """Unknown plan name returns baseline quotas without archetype additions."""
    commander = _make_card(cmc=4.0)
    adjusted = adjust_quotas_for_commander(
        BASELINE_QUOTAS, commander, commander_tags=[], primary_plan="unknown-plan"
    )
    adjusted_roles = {q.role for q in adjusted}
    baseline_roles = {q.role for q in BASELINE_QUOTAS}
    assert adjusted_roles == baseline_roles


def test_none_plan_returns_baseline_behavior() -> None:
    """primary_plan=None produces same roles as calling without primary_plan."""
    commander = _make_card(cmc=4.0)
    without_plan = adjust_quotas_for_commander(BASELINE_QUOTAS, commander, commander_tags=[])
    with_none = adjust_quotas_for_commander(
        BASELINE_QUOTAS, commander, commander_tags=[], primary_plan=None
    )
    assert {q.role for q in without_plan} == {q.role for q in with_none}
    assert {(q.role, q.target_min) for q in without_plan} == {
        (q.role, q.target_min) for q in with_none
    }


def test_archetype_profile_still_includes_all_baseline_roles() -> None:
    """food-sacrifice profile contains RAMP, CARD_DRAW, SPOT_REMOVAL, BOARD_WIPE, PROTECTION, WIN_CONDITION."""
    commander = _make_card(cmc=3.0)
    adjusted = adjust_quotas_for_commander(
        BASELINE_QUOTAS, commander, commander_tags=[], primary_plan="food-sacrifice"
    )
    adjusted_roles = {q.role for q in adjusted}
    required = {
        CardRole.RAMP,
        CardRole.CARD_DRAW,
        CardRole.SPOT_REMOVAL,
        CardRole.BOARD_WIPE,
        CardRole.PROTECTION,
        CardRole.WIN_CONDITION,
    }
    assert required <= adjusted_roles


def test_commander_tag_adjustments_apply_on_top_of_archetype_profile() -> None:
    """High-CMC food-sacrifice commander gets RAMP target_min += 2 on top of archetype base."""
    archetype_ramp = next(
        q for q in ARCHETYPE_QUOTA_PROFILES["food-sacrifice"] if q.role == CardRole.RAMP
    )
    commander = _make_card(cmc=7.0)
    adjusted = adjust_quotas_for_commander(
        BASELINE_QUOTAS, commander, commander_tags=[], primary_plan="food-sacrifice"
    )
    adjusted_ramp = next(q for q in adjusted if q.role == CardRole.RAMP)
    assert adjusted_ramp.target_min == archetype_ramp.target_min + 2
