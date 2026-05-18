"""Tests for SC-MANA-001/002/004: mana base classification rules."""
from __future__ import annotations

import pytest

from app.recommendation.mana_base_rules import (
    C_ONLY_LAND_NAMES,
    KNOWN_FIXING_LAND_NAMES,
    UTILITY_LAND_MIN_SYNERGY_SCORE,
    commander_is_colorless,
    is_c_only_land,
    is_fixing_land,
    is_mono_color,
    is_utility_land,
    land_produces_off_color_mana,
    utility_land_has_relevance,
)
from app.recommendation.deck_candidate_pool import DeckCandidatePool, _land_is_eligible
from app.models.card import CardData


# ---------------------------------------------------------------------------
# is_mono_color / commander_is_colorless helpers
# ---------------------------------------------------------------------------

def test_is_mono_color_true_for_single_color() -> None:
    assert is_mono_color(["G"]) is True


def test_is_mono_color_false_for_multicolor() -> None:
    assert is_mono_color(["B", "G"]) is False


def test_is_mono_color_false_for_colorless() -> None:
    assert is_mono_color([]) is False


def test_commander_is_colorless_true_for_no_colors() -> None:
    assert commander_is_colorless([]) is True


def test_commander_is_colorless_false_for_colored() -> None:
    assert commander_is_colorless(["U"]) is False


# ---------------------------------------------------------------------------
# is_fixing_land — name-based
# ---------------------------------------------------------------------------

def test_gemstone_mine_is_fixing_land() -> None:
    assert is_fixing_land("Gemstone Mine", "{T}: Add one mana of any color.") is True


def test_exotic_orchard_is_fixing_land() -> None:
    assert is_fixing_land("Exotic Orchard", "{T}: Add one mana of any type that a land an opponent controls could produce.") is True


def test_unclaimed_territory_is_fixing_land() -> None:
    assert is_fixing_land("Unclaimed Territory", "As Unclaimed Territory enters the battlefield, choose a creature type.") is True


# ---------------------------------------------------------------------------
# is_fixing_land — oracle text-based
# ---------------------------------------------------------------------------

def test_fixing_land_with_add_any_color_oracle_excluded() -> None:
    assert is_fixing_land("Custom Land", "T: Add one mana of any color.") is True


def test_fixing_land_add_mana_any_color_variant() -> None:
    assert is_fixing_land("Custom Land 2", "T: Add mana of any color to your mana pool.") is True


def test_reliquary_tower_not_a_fixing_land() -> None:
    # Reliquary Tower produces {C} and has "You have no maximum hand size" — not fixing
    assert is_fixing_land("Reliquary Tower", "You have no maximum hand size.\n{T}: Add {C}.") is False


def test_land_produces_off_color_mana_true_for_white_in_green_deck() -> None:
    oracle_text = "{T}, Sacrifice this land: Add {R}, {G}, or {W}."
    assert land_produces_off_color_mana(oracle_text, ["G"]) is True


def test_land_produces_off_color_mana_false_for_green_in_green_deck() -> None:
    oracle_text = "{T}: Add {G}."
    assert land_produces_off_color_mana(oracle_text, ["G"]) is False


def test_land_produces_off_color_mana_false_for_no_oracle_text() -> None:
    assert land_produces_off_color_mana(None, ["G"]) is False


def test_is_fixing_land_catches_off_color_producer_in_mono_deck() -> None:
    oracle_text = "{T}, Sacrifice Cabaretti Courtyard: Add {R}, {G}, or {W}."
    assert is_fixing_land("Cabaretti Courtyard", oracle_text, ["G"]) is True


def test_is_fixing_land_does_not_catch_on_color_producer_in_mono_deck() -> None:
    assert is_fixing_land("Forest Cave", "{T}: Add {G}.", ["G"]) is False


def test_is_fixing_land_no_commander_identity_skips_oracle_check() -> None:
    oracle_text = "{T}, Sacrifice Cabaretti Courtyard: Add {R}, {G}, or {W}."
    assert is_fixing_land("Cabaretti Courtyard", oracle_text) is False


# ---------------------------------------------------------------------------
# SC-MANA-002: Pool-stage filter — fixing land exclusion
# ---------------------------------------------------------------------------

def _make_card(name: str, oracle_text: str, color_identity: list[str], type_line: str = "Land") -> CardData:
    return CardData(
        id=f"test-{name.lower().replace(' ', '-')}",
        oracle_id=f"test-{name.lower().replace(' ', '-')}",
        name=name,
        color_identity=color_identity,
        legalities={"commander": "legal"},
        type_line=type_line,
        oracle_text=oracle_text,
        mana_cost=None,
        cmc=0.0,
    )


def test_gemstone_mine_excluded_from_mono_color() -> None:
    card = _make_card("Gemstone Mine", "T: Add one mana of any color.", [])
    assert _land_is_eligible(card, ["G"]) is False


def test_exotic_orchard_excluded_from_mono_color() -> None:
    card = _make_card("Exotic Orchard", "T: Add one mana of any type.", [])
    assert _land_is_eligible(card, ["B"]) is False


def test_unclaimed_territory_excluded_from_mono_color() -> None:
    card = _make_card("Unclaimed Territory", "As this enters, choose a creature type.", [])
    assert _land_is_eligible(card, ["R"]) is False


def test_fixing_land_with_add_any_color_oracle_excluded_from_mono_color() -> None:
    card = _make_card("Generic Fixing Land", "T: Add one mana of any color.", [])
    assert _land_is_eligible(card, ["W"]) is False


def test_off_color_oracle_producer_excluded_from_mono_color() -> None:
    card = _make_card(
        "Cabaretti Courtyard",
        "{T}, Sacrifice Cabaretti Courtyard: Add {R}, {G}, or {W}.",
        [],
    )
    assert _land_is_eligible(card, ["G"]) is False


def test_reliquary_tower_allowed_in_mono_color() -> None:
    card = _make_card("Reliquary Tower", "You have no maximum hand size.\n{T}: Add {C}.", [])
    assert _land_is_eligible(card, ["G"]) is True


def test_command_tower_allowed_in_multicolor() -> None:
    card = _make_card("Command Tower", "T: Add one mana of any color in your commander's color identity.", [])
    # Multi-color: fixing lands are allowed
    assert _land_is_eligible(card, ["B", "G"]) is True


def test_non_land_always_eligible() -> None:
    card = _make_card("Sol Ring", "T: Add {C}{C}.", [], type_line="Artifact")
    assert _land_is_eligible(card, ["G"]) is True


# ---------------------------------------------------------------------------
# SC-MANA-004: Pool-stage filter — {C}-only land exclusion
# ---------------------------------------------------------------------------

def test_wastes_excluded_from_colored_deck() -> None:
    card = _make_card("Wastes", "{T}: Add {C}.", [])
    assert _land_is_eligible(card, ["G"]) is False


def test_snow_covered_wastes_excluded_from_mono_color_noncolorless() -> None:
    card = _make_card("Snow-Covered Wastes", "{T}: Add {C}.", [])
    assert _land_is_eligible(card, ["U"]) is False


def test_snow_covered_wastes_included_when_commander_is_colorless() -> None:
    card = _make_card("Snow-Covered Wastes", "{T}: Add {C}.", [])
    # Colorless commander — Wastes is valid
    assert _land_is_eligible(card, []) is True


def test_c_only_filter_at_pool_stage(sample_cards, cards_by_name) -> None:
    """Wastes (if in fixture) is absent from colored commander candidate pool."""
    from app.recommendation.role_tagger import RuleTagger

    wastes = cards_by_name.get("Wastes")
    if wastes is None:
        pytest.skip("Wastes not in fixture")

    meren = cards_by_name["Meren of Clan Nel Toth"]
    tagger = RuleTagger()
    role_tags = {c.oracle_id: tagger.tag(c) for c in sample_cards}

    pool = DeckCandidatePool().build(
        commander=meren,
        owned_cards=[],
        all_cards=sample_cards,
        role_tags=role_tags,
        owned_oracle_ids=set(),
    )
    pool_ids = {c.oracle_id for c in pool}
    assert wastes.oracle_id not in pool_ids, "Wastes must not appear in a colored commander's pool"


# ---------------------------------------------------------------------------
# SC-MANA-003: Utility land synergy gate helpers
# ---------------------------------------------------------------------------

def test_utility_land_excluded_when_no_synergy() -> None:
    assert utility_land_has_relevance(
        "Mystifying Maze",
        "{T}: Add {C}.\n{4}, {T}: Exile target attacking creature.",
        "Land",
        synergy_score=0.0,
        package_ids=[],
        active_package_ids=set(),
    ) is False


def test_utility_land_included_when_synergy_active() -> None:
    assert utility_land_has_relevance(
        "Mystifying Maze",
        "{T}: Add {C}.\n{4}, {T}: Exile target attacking creature.",
        "Land",
        synergy_score=UTILITY_LAND_MIN_SYNERGY_SCORE,
        package_ids=[],
        active_package_ids=set(),
    ) is True


def test_utility_land_included_when_active_package_matches() -> None:
    assert utility_land_has_relevance(
        "The Seedcore",
        "{T}: Add one mana of any color. Spend this mana only to cast Phyrexian creature spells.",
        "Land — Sphere",
        synergy_score=0.0,
        package_ids=["phyrexian-package"],
        active_package_ids={"phyrexian-package"},
    ) is True


def test_mana_producing_land_not_gated_by_synergy_rule() -> None:
    assert is_utility_land("Forest Cave", "{T}: Add {G}.", "Land") is False
    assert utility_land_has_relevance(
        "Forest Cave",
        "{T}: Add {G}.",
        "Land",
        synergy_score=0.0,
        package_ids=[],
        active_package_ids=set(),
    ) is True


def test_snow_basic_land_not_gated_by_synergy_rule() -> None:
    assert is_utility_land(
        "Snow-Covered Forest",
        "({T}: Add {G}.)",
        "Basic Snow Land — Forest",
    ) is False


def test_synergy_gate_threshold_is_configurable() -> None:
    assert isinstance(UTILITY_LAND_MIN_SYNERGY_SCORE, float)
    assert 0.0 < UTILITY_LAND_MIN_SYNERGY_SCORE < 1.0


def test_seedcore_excluded_without_phyrexian_or_compleated_package() -> None:
    assert utility_land_has_relevance(
        "The Seedcore",
        "{T}: Add one mana of any color. Spend this mana only to cast Phyrexian creature spells.",
        "Land — Sphere",
        synergy_score=0.0,
        package_ids=[],
        active_package_ids=set(),
    ) is False


def test_white_lotus_hideout_excluded_without_lifegain_or_white_relevance() -> None:
    assert utility_land_has_relevance(
        "White Lotus Hideout",
        "{T}: Add {C}.\n{T}: Add one mana of any color. Spend this mana only to cast a Lesson or Shrine spell.",
        "Land",
        synergy_score=0.0,
        package_ids=[],
        active_package_ids=set(),
    ) is False


def test_eclipsed_realms_excluded_without_enchantment_or_day_night_package() -> None:
    assert utility_land_has_relevance(
        "Eclipsed Realms",
        "As this land enters, choose Elemental, Elf, Faerie, Giant, Goblin, Kithkin, Merfolk, or Treefolk.\n{T}: Add {C}.",
        "Land",
        synergy_score=0.0,
        package_ids=[],
        active_package_ids=set(),
    ) is False
