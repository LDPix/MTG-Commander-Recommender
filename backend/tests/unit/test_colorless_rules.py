"""Tests for SC-DECK-009/010: colorless card classification rules."""
from __future__ import annotations

from app.recommendation.colorless_rules import (
    C_REQUIREMENT_MIN_SOURCES,
    COLORLESS_EXEMPT_ROLES,
    COLORLESS_SYNERGY_DISCOUNT,
    card_is_colorless,
    colorless_is_exempt,
    commander_has_colors,
    has_c_mana_requirement,
    is_dedicated_colorless_source,
)


# ---------------------------------------------------------------------------
# card_is_colorless
# ---------------------------------------------------------------------------

def test_card_is_colorless_true_for_empty_color_identity() -> None:
    assert card_is_colorless([]) is True


def test_card_is_colorless_false_for_colored_card() -> None:
    assert card_is_colorless(["G"]) is False


def test_card_is_colorless_false_for_multicolor() -> None:
    assert card_is_colorless(["W", "U", "B", "G"]) is False


# ---------------------------------------------------------------------------
# commander_has_colors
# ---------------------------------------------------------------------------

def test_commander_has_colors_true_for_colored() -> None:
    assert commander_has_colors(["B", "G"]) is True


def test_commander_has_colors_false_for_colorless() -> None:
    assert commander_has_colors([]) is False


# ---------------------------------------------------------------------------
# colorless_is_exempt
# ---------------------------------------------------------------------------

def test_ramp_role_no_longer_exempt_from_colorless_penalty() -> None:
    assert colorless_is_exempt(["RAMP"]) is False


def test_colorless_is_exempt_true_for_removal_role() -> None:
    assert colorless_is_exempt(["SPOT_REMOVAL"]) is True


def test_colorless_is_exempt_true_for_protection_role() -> None:
    assert colorless_is_exempt(["PROTECTION"]) is True


def test_card_draw_role_no_longer_exempt_from_colorless_penalty() -> None:
    assert colorless_is_exempt(["CARD_DRAW"]) is False


def test_board_wipe_still_exempt_from_colorless_penalty() -> None:
    assert colorless_is_exempt(["BOARD_WIPE"]) is True


def test_tutor_still_exempt_from_colorless_penalty() -> None:
    assert colorless_is_exempt(["TUTOR"]) is True


def test_colorless_is_exempt_false_for_no_exempt_role() -> None:
    assert colorless_is_exempt(["TOKEN_MAKER", "PAYOFF"]) is False


def test_colorless_is_exempt_false_for_empty_roles() -> None:
    assert colorless_is_exempt([]) is False


# ---------------------------------------------------------------------------
# has_c_mana_requirement
# ---------------------------------------------------------------------------

def test_has_c_mana_requirement_true_for_c_in_cost() -> None:
    assert has_c_mana_requirement("{2}{C}") is True


def test_has_c_mana_requirement_true_for_c_in_oracle_activation_cost() -> None:
    assert has_c_mana_requirement(None, "{C}: Add one mana of any color.") is True


def test_has_c_mana_requirement_true_for_c_comma_in_oracle_cost() -> None:
    assert has_c_mana_requirement(None, "{C}, {T}: Create a 1/1 token.") is True


def test_has_c_mana_requirement_false_for_c_in_mana_production_text() -> None:
    assert has_c_mana_requirement(None, "{T}: Add {C}.") is False


def test_has_c_mana_requirement_backward_compat_without_oracle_text() -> None:
    assert has_c_mana_requirement("{2}{C}") is True


def test_has_c_mana_requirement_false_for_generic_mana() -> None:
    assert has_c_mana_requirement("{3}") is False


def test_has_c_mana_requirement_false_for_sol_ring() -> None:
    # Sol Ring costs {1} — generic, not {C}
    assert has_c_mana_requirement("{1}") is False


def test_has_c_mana_requirement_false_for_none() -> None:
    assert has_c_mana_requirement(None) is False


def test_has_c_mana_requirement_false_for_colored_cost() -> None:
    assert has_c_mana_requirement("{2}{G}") is False


# ---------------------------------------------------------------------------
# is_dedicated_colorless_source
# ---------------------------------------------------------------------------

def test_is_dedicated_colorless_source_true_for_sol_ring() -> None:
    # Sol Ring: "{T}: Add {C}{C}." — artifact that taps for {C}
    assert is_dedicated_colorless_source("{T}: Add {C}{C}.", "Artifact") is True


def test_is_dedicated_colorless_source_false_for_c_activation_cost_card() -> None:
    assert is_dedicated_colorless_source("{C}: Put a +1/+1 counter on this.", "Creature") is False


def test_is_dedicated_colorless_source_true_for_wastes() -> None:
    assert is_dedicated_colorless_source("{T}: Add {C}.", "Basic Land") is True


def test_is_dedicated_colorless_source_false_for_non_producer() -> None:
    assert is_dedicated_colorless_source("Flying. When this enters, draw a card.", "Creature") is False


def test_is_dedicated_colorless_source_false_for_generic_artifact_no_add() -> None:
    assert is_dedicated_colorless_source("{C}: Draw a card.", "Artifact") is False


def test_is_dedicated_colorless_source_false_for_non_permanent() -> None:
    assert is_dedicated_colorless_source("Counter target spell.", "Instant") is False


def test_is_dedicated_colorless_source_false_for_colored_mana_only() -> None:
    # Elvish Mystic: adds {G} — not {C}
    assert is_dedicated_colorless_source("{T}: Add {G}.", "Creature") is False


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------

def test_colorless_synergy_discount_is_between_0_and_1() -> None:
    assert 0.0 < COLORLESS_SYNERGY_DISCOUNT < 1.0


def test_c_requirement_min_sources_is_positive() -> None:
    assert C_REQUIREMENT_MIN_SOURCES > 0


def test_colorless_exempt_roles_include_interaction_not_ramp() -> None:
    assert "RAMP" not in COLORLESS_EXEMPT_ROLES
    assert "CARD_DRAW" not in COLORLESS_EXEMPT_ROLES
    assert "SPOT_REMOVAL" in COLORLESS_EXEMPT_ROLES
    assert "BOARD_WIPE" in COLORLESS_EXEMPT_ROLES
    assert "PROTECTION" in COLORLESS_EXEMPT_ROLES
    assert "TUTOR" in COLORLESS_EXEMPT_ROLES
