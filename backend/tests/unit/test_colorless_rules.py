"""Tests for SC-DECK-009/010: colorless card classification rules."""
from __future__ import annotations

from app.recommendation.colorless_rules import (
    COLORLESS_EXEMPT_ROLES,
    COLORLESS_STRATEGY_BASE_FACTOR,
    COLORLESS_SYNERGY_DISCOUNT,
    card_is_colorless,
    colorless_is_exempt,
    commander_has_colors,
    compute_colorless_strategy_factor,
    evaluate_colorless_strategy_signal,
    has_c_mana_requirement,
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
    assert colorless_is_exempt(["TOKEN_MAKER", "WIN_CONDITION"]) is False


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
# Constants sanity
# ---------------------------------------------------------------------------

def test_colorless_synergy_discount_is_between_0_and_1() -> None:
    assert 0.0 < COLORLESS_SYNERGY_DISCOUNT < 1.0


def test_colorless_exempt_roles_include_interaction_not_ramp() -> None:
    assert "RAMP" not in COLORLESS_EXEMPT_ROLES
    assert "CARD_DRAW" not in COLORLESS_EXEMPT_ROLES
    assert "SPOT_REMOVAL" in COLORLESS_EXEMPT_ROLES
    assert "BOARD_WIPE" in COLORLESS_EXEMPT_ROLES
    assert "PROTECTION" in COLORLESS_EXEMPT_ROLES
    assert "TUTOR" in COLORLESS_EXEMPT_ROLES


# ---------------------------------------------------------------------------
# SC-DECK-010 v2: compute_colorless_strategy_factor
# ---------------------------------------------------------------------------

def test_compute_colorless_strategy_factor_returns_1_for_colorless_commander() -> None:
    """Colorless commander: no suppression, full factor."""
    assert compute_colorless_strategy_factor([], []) == 1.0


def test_candidate_pool_eldrazi_package_does_not_activate_colorless_strategy() -> None:
    """SC-DECK-017: candidate-pool Eldrazi labels are collection evidence only."""
    factor = compute_colorless_strategy_factor(["G"], ["eldrazi-synergy-package"])
    assert factor == COLORLESS_STRATEGY_BASE_FACTOR


def test_compute_colorless_strategy_factor_returns_base_factor_for_colored_commander() -> None:
    """Colored commander without colorless strategy: factor is COLORLESS_STRATEGY_BASE_FACTOR."""
    factor = compute_colorless_strategy_factor(["G"], [])
    assert factor == COLORLESS_STRATEGY_BASE_FACTOR


def test_compute_colorless_strategy_factor_base_factor_is_near_zero() -> None:
    """Base factor is near zero so {C}-requirement cards are effectively excluded."""
    assert COLORLESS_STRATEGY_BASE_FACTOR < 0.1


def test_compute_colorless_strategy_factor_with_no_packages() -> None:
    """Multi-color commander, no packages: returns base factor."""
    assert compute_colorless_strategy_factor(["B", "G"], []) == COLORLESS_STRATEGY_BASE_FACTOR


def test_nissa_colorless_strategy_factor_remains_low() -> None:
    """SC-DECK-017: mono-green Nissa-style commander ignores collection Eldrazi packages."""
    signal = evaluate_colorless_strategy_signal(
        commander_color_identity=["G"],
        commander_name="Nissa, Worldsoul Speaker",
        commander_type_line="Legendary Creature — Elf Druid",
        commander_oracle_text="Landfall — Add one mana of any color.",
        candidate_package_labels=["Eldrazi package", "colorless matters"],
    )
    assert signal.factor == COLORLESS_STRATEGY_BASE_FACTOR
    assert signal.source == "base_colored_commander"


def test_colorless_commander_strategy_factor_high() -> None:
    """SC-DECK-017: colorless commanders keep full colorless strategy support."""
    signal = evaluate_colorless_strategy_signal(
        commander_color_identity=[],
        commander_name="Kozilek, the Great Distortion",
        commander_type_line="Legendary Creature — Eldrazi",
    )
    assert signal.factor == 1.0
    assert signal.source == "commander_identity"


def test_profiled_eldrazi_commander_strategy_factor_high() -> None:
    """SC-DECK-017: explicit colored Eldrazi/colorless commanders can activate."""
    signal = evaluate_colorless_strategy_signal(
        commander_color_identity=["G"],
        commander_name="Colorless Matters Commander",
        commander_type_line="Legendary Creature — Eldrazi Druid",
        commander_oracle_text="Eldrazi spells you cast cost {1} less.",
    )
    assert signal.factor == 0.8
    assert signal.source == "commander_profile"


def test_selected_deck_density_can_activate_colorless_strategy() -> None:
    """SC-DECK-017: active selected-deck colorless packages may activate."""
    signal = evaluate_colorless_strategy_signal(
        commander_color_identity=["G"],
        commander_name="Package Test Commander",
        commander_type_line="Legendary Creature — Test",
        selected_package_labels=["Active Eldrazi package"],
    )
    assert signal.factor == 0.8
    assert signal.source == "selected_deck_density"


def test_colorless_strategy_activation_source_is_deterministic() -> None:
    """SC-DECK-017: commander support wins deterministically over selected packages."""
    signal = evaluate_colorless_strategy_signal(
        commander_color_identity=["G"],
        commander_name="Devoid Commander",
        commander_type_line="Legendary Creature — Eldrazi",
        candidate_package_labels=["Candidate Eldrazi cluster"],
        selected_package_labels=["Active Eldrazi package"],
    )
    assert signal.factor == 0.8
    assert signal.source == "commander_profile"
