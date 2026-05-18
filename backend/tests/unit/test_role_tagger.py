"""Tests for SC-TAG-001 and SC-TAG-002: Rule-based role tagger and manual overrides."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.models.card import CardData
from app.recommendation.manual_tag_overrides import (
    ManualTagOverride,
    ManualTagStore,
    apply_overrides,
)
from app.recommendation.role_taxonomy import CardRole, RoleTag
from app.recommendation.role_tagger import RuleTagger


@pytest.fixture
def tagger() -> RuleTagger:
    return RuleTagger()


def _roles(tags: list[RoleTag]) -> set[CardRole]:
    return {t.role for t in tags}


# ---------------------------------------------------------------------------
# SC-TAG-001: Rule-based tagger
# ---------------------------------------------------------------------------

def test_sol_ring_tagged_as_ramp(tagger: RuleTagger, cards_by_name: dict[str, CardData]) -> None:
    """Sol Ring (mana rock) receives a RAMP tag."""
    card = cards_by_name["Sol Ring"]
    tags = tagger.tag(card)
    assert CardRole.RAMP in _roles(tags), f"Expected RAMP in {_roles(tags)}"


def test_command_tower_tagged_as_land_and_fixing(
    tagger: RuleTagger, cards_by_name: dict[str, CardData]
) -> None:
    """Command Tower receives LAND and MANA_FIXING tags."""
    card = cards_by_name["Command Tower"]
    tags = tagger.tag(card)
    roles = _roles(tags)
    assert CardRole.LAND in roles, f"Expected LAND in {roles}"
    assert CardRole.MANA_FIXING in roles, f"Expected MANA_FIXING in {roles}"


def test_pain_land_tagged_as_land_and_fixing(tagger: RuleTagger) -> None:
    card = CardData(
        id="llanowar-wastes-test",
        oracle_id="llanowar-wastes-test",
        name="Llanowar Wastes",
        color_identity=[],
        legalities={"commander": "legal"},
        type_line="Land",
        oracle_text="{T}: Add {C}.\n{T}: Add {B} or {G}. Llanowar Wastes deals 1 damage to you.",
        cmc=0.0,
    )

    roles = _roles(tagger.tag(card))

    assert CardRole.LAND in roles
    assert CardRole.MANA_FIXING in roles


def test_swords_to_plowshares_tagged_as_removal(
    tagger: RuleTagger, cards_by_name: dict[str, CardData]
) -> None:
    """Swords to Plowshares receives a SPOT_REMOVAL tag."""
    card = cards_by_name["Swords to Plowshares"]
    tags = tagger.tag(card)
    assert CardRole.SPOT_REMOVAL in _roles(tags), f"Expected SPOT_REMOVAL in {_roles(tags)}"


def test_wrath_of_god_tagged_as_board_wipe(
    tagger: RuleTagger, cards_by_name: dict[str, CardData]
) -> None:
    """Wrath of God receives a BOARD_WIPE tag."""
    card = cards_by_name["Wrath of God"]
    tags = tagger.tag(card)
    assert CardRole.BOARD_WIPE in _roles(tags), f"Expected BOARD_WIPE in {_roles(tags)}"


def test_skullclamp_tagged_as_draw_and_synergy(
    tagger: RuleTagger, cards_by_name: dict[str, CardData]
) -> None:
    """Skullclamp receives a CARD_DRAW tag (draws 2 when equipped creature dies)."""
    card = cards_by_name["Skullclamp"]
    tags = tagger.tag(card)
    roles = _roles(tags)
    assert CardRole.CARD_DRAW in roles, f"Expected CARD_DRAW in {roles}"


def test_cultivate_tagged_as_ramp(
    tagger: RuleTagger, cards_by_name: dict[str, CardData]
) -> None:
    """Cultivate (searches for basic lands) receives a RAMP tag."""
    card = cards_by_name["Cultivate"]
    tags = tagger.tag(card)
    assert CardRole.RAMP in _roles(tags), f"Expected RAMP in {_roles(tags)}"


def test_forest_tagged_as_land(
    tagger: RuleTagger, cards_by_name: dict[str, CardData]
) -> None:
    """Forest receives a LAND tag."""
    card = cards_by_name["Forest"]
    tags = tagger.tag(card)
    assert CardRole.LAND in _roles(tags), f"Expected LAND in {_roles(tags)}"


def test_lightning_greaves_tagged_as_protection(
    tagger: RuleTagger, cards_by_name: dict[str, CardData]
) -> None:
    """Lightning Greaves (grants shroud) receives a PROTECTION tag."""
    card = cards_by_name["Lightning Greaves"]
    tags = tagger.tag(card)
    assert CardRole.PROTECTION in _roles(tags), f"Expected PROTECTION in {_roles(tags)}"


# ---------------------------------------------------------------------------
# Multiple roles
# ---------------------------------------------------------------------------

def test_tags_are_deduplicated(
    tagger: RuleTagger, cards_by_name: dict[str, CardData]
) -> None:
    """No role appears twice in the tag list for a single card."""
    for card in cards_by_name.values():
        tags = tagger.tag(card)
        roles = [t.role for t in tags]
        assert len(roles) == len(set(roles)), (
            f"Duplicate roles in tags for {card.name}: {roles}"
        )


def test_confidence_in_valid_range(
    tagger: RuleTagger, cards_by_name: dict[str, CardData]
) -> None:
    """All confidence values are in [0.0, 1.0]."""
    for card in cards_by_name.values():
        for tag in tagger.tag(card):
            assert 0.0 <= tag.confidence <= 1.0, (
                f"{card.name} has tag {tag.role} with confidence {tag.confidence}"
            )


# ---------------------------------------------------------------------------
# SC-TAG-002: Manual tag overrides
# ---------------------------------------------------------------------------

def test_manual_tag_addition_applied(
    tagger: RuleTagger, cards_by_name: dict[str, CardData]
) -> None:
    """A manual override that adds a role results in that role being present."""
    card = cards_by_name["Sol Ring"]
    rule_tags = tagger.tag(card)

    override = ManualTagOverride(
        card_name="Sol Ring",
        add=["WIN_CONDITION"],
        remove=[],
        confidence_overrides={"WIN_CONDITION": 0.5},
        source="manual",
    )
    final_tags = apply_overrides(rule_tags, override)
    roles = _roles(final_tags)

    assert CardRole.WIN_CONDITION in roles
    win_tag = next(t for t in final_tags if t.role == CardRole.WIN_CONDITION)
    assert win_tag.source == "manual"
    assert win_tag.confidence == 0.5


def test_manual_tag_removal_applied(
    tagger: RuleTagger, cards_by_name: dict[str, CardData]
) -> None:
    """A manual override that removes a role results in that role being absent."""
    card = cards_by_name["Sol Ring"]
    # Confirm RAMP is there before removal
    rule_tags = tagger.tag(card)
    assert CardRole.RAMP in _roles(rule_tags), "Pre-condition: Sol Ring should have RAMP"

    override = ManualTagOverride(
        card_name="Sol Ring",
        add=[],
        remove=["RAMP"],
        confidence_overrides={},
        source="manual",
    )
    final_tags = apply_overrides(rule_tags, override)
    assert CardRole.RAMP not in _roles(final_tags)


def test_manual_tag_confidence_overrides_generated(
    tagger: RuleTagger, cards_by_name: dict[str, CardData]
) -> None:
    """A confidence override changes the confidence value of an existing tag."""
    card = cards_by_name["Sol Ring"]
    rule_tags = tagger.tag(card)

    override = ManualTagOverride(
        card_name="Sol Ring",
        add=[],
        remove=[],
        confidence_overrides={"RAMP": 0.99},
        source="manual",
    )
    final_tags = apply_overrides(rule_tags, override)
    ramp_tag = next(t for t in final_tags if t.role == CardRole.RAMP)
    assert ramp_tag.confidence == 0.99
    assert ramp_tag.source == "manual"


def test_generated_tag_source_preserved(
    tagger: RuleTagger, cards_by_name: dict[str, CardData]
) -> None:
    """Tags not touched by an override retain their original source."""
    card = cards_by_name["Command Tower"]
    rule_tags = tagger.tag(card)

    # Only override MANA_FIXING confidence; LAND tag should keep rule_based source
    override = ManualTagOverride(
        card_name="Command Tower",
        add=[],
        remove=[],
        confidence_overrides={"MANA_FIXING": 0.99},
        source="manual",
    )
    final_tags = apply_overrides(rule_tags, override)

    land_tag = next((t for t in final_tags if t.role == CardRole.LAND), None)
    assert land_tag is not None
    assert land_tag.source == "rule_based"


def test_manual_tag_store_loads_from_file(manual_overrides_path: Path) -> None:
    """ManualTagStore loads overrides from a JSON file without error."""
    store = ManualTagStore.from_file(manual_overrides_path)
    assert store.has_override("Sol Ring")
    assert store.has_override("Command Tower")
    assert store.has_override("Skullclamp")


def test_manual_tag_store_returns_none_for_unknown(manual_overrides_path: Path) -> None:
    """ManualTagStore returns None for a card with no override."""
    store = ManualTagStore.from_file(manual_overrides_path)
    assert store.get_override("Definitely Not A Card") is None
    assert not store.has_override("Definitely Not A Card")
