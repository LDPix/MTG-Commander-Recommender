"""Tests for SC-DECK-001: DeckCandidatePool."""
from __future__ import annotations

import pytest

from app.models.card import CardData
from app.models.deck import DeckCard
from app.recommendation.deck_candidate_pool import DeckCandidatePool
from app.recommendation.role_taxonomy import CardRole, RoleTag
from app.recommendation.role_tagger import RuleTagger

MEREN_ORACLE_ID = "4b2521bc-8f94-1a0b-c3d4-5e6f7a8b9c0d"


@pytest.fixture(scope="module")
def tagger() -> RuleTagger:
    return RuleTagger()


@pytest.fixture(scope="module")
def role_tags_for_all(sample_cards: list[CardData], tagger: RuleTagger) -> dict[str, list[RoleTag]]:
    return {card.oracle_id: tagger.tag(card) for card in sample_cards}


@pytest.fixture(scope="module")
def meren(cards_by_name: dict[str, CardData]) -> CardData:
    return cards_by_name["Meren of Clan Nel Toth"]


@pytest.fixture(scope="module")
def candidate_pool(meren: CardData, sample_cards: list[CardData], role_tags_for_all: dict[str, list[RoleTag]]) -> list[DeckCard]:
    pool_builder = DeckCandidatePool()
    return pool_builder.build(
        commander=meren,
        owned_cards=[],
        all_cards=sample_cards,
        role_tags=role_tags_for_all,
        owned_oracle_ids=set(),
    )


def test_candidate_pool_excludes_illegal_cards(meren: CardData, sample_cards: list[CardData], role_tags_for_all: dict[str, list[RoleTag]]) -> None:
    """Cards with commander legality != 'legal' are excluded from the pool."""
    illegal_card = CardData(
        id="illegal-test-001",
        oracle_id="illegal-test-001",
        name="Illegal Test Card",
        color_identity=["B"],
        legalities={"commander": "not_legal"},
        type_line="Sorcery",
        oracle_text="Do something.",
        cmc=1.0,
    )
    all_cards = list(sample_cards) + [illegal_card]
    role_tags_copy = dict(role_tags_for_all)

    pool = DeckCandidatePool().build(
        commander=meren,
        owned_cards=[],
        all_cards=all_cards,
        role_tags=role_tags_copy,
        owned_oracle_ids=set(),
    )
    oracle_ids = {c.oracle_id for c in pool}
    assert illegal_card.oracle_id not in oracle_ids


def test_candidate_pool_excludes_banned_cards(meren: CardData, sample_cards: list[CardData], role_tags_for_all: dict[str, list[RoleTag]]) -> None:
    """Cards with commander legality 'banned' are excluded from the pool."""
    banned_card = CardData(
        id="banned-test-001",
        oracle_id="banned-test-001",
        name="Banned Test Card",
        color_identity=["B"],
        legalities={"commander": "banned"},
        type_line="Instant",
        oracle_text="Counter target spell.",
        cmc=2.0,
    )
    all_cards = list(sample_cards) + [banned_card]

    pool = DeckCandidatePool().build(
        commander=meren,
        owned_cards=[],
        all_cards=all_cards,
        role_tags=dict(role_tags_for_all),
        owned_oracle_ids=set(),
    )
    oracle_ids = {c.oracle_id for c in pool}
    assert banned_card.oracle_id not in oracle_ids


def test_candidate_pool_excludes_off_color_cards(meren: CardData, sample_cards: list[CardData], role_tags_for_all: dict[str, list[RoleTag]]) -> None:
    """Cards outside the commander's color identity are excluded."""
    # Meren is B/G. White cards should be excluded.
    off_color_card = CardData(
        id="off-color-test-001",
        oracle_id="off-color-test-001",
        name="White Only Card",
        color_identity=["W"],
        legalities={"commander": "legal"},
        type_line="Instant",
        oracle_text="Gain 3 life.",
        cmc=1.0,
    )
    all_cards = list(sample_cards) + [off_color_card]

    pool = DeckCandidatePool().build(
        commander=meren,
        owned_cards=[],
        all_cards=all_cards,
        role_tags=dict(role_tags_for_all),
        owned_oracle_ids=set(),
    )
    oracle_ids = {c.oracle_id for c in pool}
    assert off_color_card.oracle_id not in oracle_ids

    # U-only cards also excluded from BG commander
    blue_oracle_id = "aa000085-0000-4000-0000-000000000085"  # Counterspell
    assert blue_oracle_id not in oracle_ids


def test_candidate_pool_excludes_commander_itself(meren: CardData, sample_cards: list[CardData], role_tags_for_all: dict[str, list[RoleTag]]) -> None:
    """The commander itself is never in the candidate pool."""
    pool = DeckCandidatePool().build(
        commander=meren,
        owned_cards=[],
        all_cards=sample_cards,
        role_tags=role_tags_for_all,
        owned_oracle_ids=set(),
    )
    oracle_ids = {c.oracle_id for c in pool}
    assert meren.oracle_id not in oracle_ids


def test_candidate_pool_marks_owned_cards(meren: CardData, sample_cards: list[CardData], role_tags_for_all: dict[str, list[RoleTag]], cards_by_name: dict[str, CardData]) -> None:
    """Cards in owned_oracle_ids are marked is_owned=True."""
    sol_ring = cards_by_name["Sol Ring"]
    owned_ids = {sol_ring.oracle_id}

    pool = DeckCandidatePool().build(
        commander=meren,
        owned_cards=[sol_ring],
        all_cards=sample_cards,
        role_tags=role_tags_for_all,
        owned_oracle_ids=owned_ids,
    )
    pool_by_id = {c.oracle_id: c for c in pool}

    # Sol Ring should be owned (it's colorless, so legal for BG)
    assert sol_ring.oracle_id in pool_by_id
    assert pool_by_id[sol_ring.oracle_id].is_owned is True


def test_candidate_pool_marks_missing_cards(meren: CardData, sample_cards: list[CardData], role_tags_for_all: dict[str, list[RoleTag]], cards_by_name: dict[str, CardData]) -> None:
    """Cards not in owned_oracle_ids are marked is_owned=False."""
    pool = DeckCandidatePool().build(
        commander=meren,
        owned_cards=[],
        all_cards=sample_cards,
        role_tags=role_tags_for_all,
        owned_oracle_ids=set(),  # no owned cards
    )
    # All cards should be not owned
    for card in pool:
        assert card.is_owned is False


def test_candidate_pool_no_false_owned(meren: CardData, sample_cards: list[CardData], role_tags_for_all: dict[str, list[RoleTag]], cards_by_name: dict[str, CardData]) -> None:
    """is_owned is never True for a card not in owned_oracle_ids."""
    forest = cards_by_name["Forest"]
    owned_ids = {forest.oracle_id}

    pool = DeckCandidatePool().build(
        commander=meren,
        owned_cards=[forest],
        all_cards=sample_cards,
        role_tags=role_tags_for_all,
        owned_oracle_ids=owned_ids,
    )
    for card in pool:
        if card.oracle_id not in owned_ids:
            assert card.is_owned is False, f"{card.name} should not be marked owned"


def test_candidate_pool_has_role_candidates(candidate_pool: list[DeckCard]) -> None:
    """Pool includes cards covering the main role categories."""
    all_roles = set()
    for card in candidate_pool:
        all_roles.update(card.roles)

    assert CardRole.RAMP.value in all_roles
    assert CardRole.CARD_DRAW.value in all_roles
    assert CardRole.SPOT_REMOVAL.value in all_roles
    assert CardRole.LAND.value in all_roles
    assert CardRole.BOARD_WIPE.value in all_roles
    assert CardRole.SACRIFICE_OUTLET.value in all_roles
    assert CardRole.RECURSION.value in all_roles
    assert CardRole.TOKEN_MAKER.value in all_roles
    assert CardRole.PROTECTION.value in all_roles


def test_candidate_pool_is_deduplicated(candidate_pool: list[DeckCard]) -> None:
    """No oracle_id appears more than once in the pool."""
    oracle_ids = [c.oracle_id for c in candidate_pool]
    assert len(oracle_ids) == len(set(oracle_ids))


def test_candidate_pool_owned_cards_come_first(meren: CardData, sample_cards: list[CardData], role_tags_for_all: dict[str, list[RoleTag]], cards_by_name: dict[str, CardData]) -> None:
    """Owned cards appear before unowned cards in the sorted pool."""
    sol_ring = cards_by_name["Sol Ring"]
    forest = cards_by_name["Forest"]
    owned_ids = {sol_ring.oracle_id, forest.oracle_id}

    pool = DeckCandidatePool().build(
        commander=meren,
        owned_cards=[sol_ring, forest],
        all_cards=sample_cards,
        role_tags=role_tags_for_all,
        owned_oracle_ids=owned_ids,
    )

    # Find the last owned card position and first unowned card position
    last_owned_idx = -1
    first_unowned_idx = len(pool)
    for i, card in enumerate(pool):
        if card.is_owned:
            last_owned_idx = i
        else:
            if i < first_unowned_idx:
                first_unowned_idx = i

    # All owned come before all unowned (if there are both)
    if last_owned_idx >= 0 and first_unowned_idx < len(pool):
        assert last_owned_idx < first_unowned_idx


def test_candidate_pool_respects_max_pool_size(meren: CardData, sample_cards: list[CardData], role_tags_for_all: dict[str, list[RoleTag]]) -> None:
    """Pool is capped at max_pool_size."""
    pool = DeckCandidatePool().build(
        commander=meren,
        owned_cards=[],
        all_cards=sample_cards,
        role_tags=role_tags_for_all,
        owned_oracle_ids=set(),
        max_pool_size=10,
    )
    assert len(pool) <= 10


# ---------------------------------------------------------------------------
# SC-MANA-005: Free regular basic land injection
# ---------------------------------------------------------------------------

def _basic_test_card(
    oracle_id: str,
    name: str,
    color_identity: list[str],
    type_line: str,
    oracle_text: str = "",
) -> CardData:
    return CardData(
        id=oracle_id,
        oracle_id=oracle_id,
        name=name,
        color_identity=color_identity,
        legalities={"commander": "legal"},
        type_line=type_line,
        oracle_text=oracle_text,
        cmc=0.0,
    )


def test_forest_freely_injected_when_user_owns_zero_forests() -> None:
    commander = _basic_test_card(
        "cmd-green",
        "Mono Green Commander",
        ["G"],
        "Legendary Creature — Elf",
    )
    forest = _basic_test_card(
        "forest-oracle",
        "Forest",
        ["G"],
        "Basic Land — Forest",
        "({T}: Add {G}.)",
    )
    filler = [
        _basic_test_card(f"filler-{i:02d}", f"Filler {i}", ["G"], "Creature")
        for i in range(5)
    ]

    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[],
        all_cards=[commander, *filler, forest],
        role_tags={forest.oracle_id: [RoleTag(CardRole.LAND, 1.0, "rule_based")]},
        owned_oracle_ids=set(),
        max_pool_size=1,
    )

    forests = [card for card in pool if card.name == "Forest"]
    assert len(forests) == 1
    assert forests[0].is_owned is False


def test_swamp_freely_injected_when_user_owns_zero_swamps() -> None:
    commander = _basic_test_card(
        "cmd-black",
        "Mono Black Commander",
        ["B"],
        "Legendary Creature — Vampire",
    )
    swamp = _basic_test_card(
        "swamp-oracle",
        "Swamp",
        ["B"],
        "Basic Land — Swamp",
        "({T}: Add {B}.)",
    )

    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[],
        all_cards=[commander, swamp],
        role_tags={swamp.oracle_id: [RoleTag(CardRole.LAND, 1.0, "rule_based")]},
        owned_oracle_ids=set(),
    )

    assert any(card.name == "Swamp" and not card.is_owned for card in pool)


def test_forest_not_injected_when_user_owns_at_least_one_forest() -> None:
    commander = _basic_test_card(
        "cmd-green",
        "Mono Green Commander",
        ["G"],
        "Legendary Creature — Elf",
    )
    forest = _basic_test_card(
        "forest-oracle",
        "Forest",
        ["G"],
        "Basic Land — Forest",
        "({T}: Add {G}.)",
    )

    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[forest],
        all_cards=[commander, forest],
        role_tags={forest.oracle_id: [RoleTag(CardRole.LAND, 1.0, "rule_based")]},
        owned_oracle_ids={forest.oracle_id},
    )

    forests = [card for card in pool if card.name == "Forest"]
    assert len(forests) == 1
    assert forests[0].is_owned is True


def test_freely_injected_basic_is_marked_not_owned() -> None:
    commander = _basic_test_card(
        "cmd-green",
        "Mono Green Commander",
        ["G"],
        "Legendary Creature — Elf",
    )
    forest = _basic_test_card(
        "forest-oracle",
        "Forest",
        ["G"],
        "Basic Land — Forest",
        "({T}: Add {G}.)",
    )

    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[],
        all_cards=[commander, forest],
        role_tags={forest.oracle_id: [RoleTag(CardRole.LAND, 1.0, "rule_based")]},
        owned_oracle_ids=set(),
        max_pool_size=0,
    )

    injected_forest = next(card for card in pool if card.name == "Forest")
    assert injected_forest.is_owned is False


def test_snow_covered_forest_not_injected_when_not_owned() -> None:
    commander = _basic_test_card(
        "cmd-green",
        "Mono Green Commander",
        ["G"],
        "Legendary Creature — Elf",
    )
    forest = _basic_test_card(
        "forest-oracle",
        "Forest",
        ["G"],
        "Basic Land — Forest",
        "({T}: Add {G}.)",
    )

    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[],
        all_cards=[commander, forest],
        role_tags={forest.oracle_id: [RoleTag(CardRole.LAND, 1.0, "rule_based")]},
        owned_oracle_ids=set(),
        max_pool_size=0,
    )

    assert "Snow-Covered Forest" not in {card.name for card in pool}


def test_basic_injection_uses_oracle_id_from_all_cards() -> None:
    commander = _basic_test_card(
        "cmd-green",
        "Mono Green Commander",
        ["G"],
        "Legendary Creature — Elf",
    )
    forest = _basic_test_card(
        "stable-forest-oracle",
        "Forest",
        ["G"],
        "Basic Land — Forest",
        "({T}: Add {G}.)",
    )

    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[],
        all_cards=[commander, forest],
        role_tags={forest.oracle_id: [RoleTag(CardRole.LAND, 1.0, "rule_based")]},
        owned_oracle_ids=set(),
        max_pool_size=0,
    )

    injected_forest = next(card for card in pool if card.name == "Forest")
    assert injected_forest.oracle_id == "stable-forest-oracle"


def test_c_activation_cost_card_excluded_when_not_enough_colorless_sources() -> None:
    commander = _basic_test_card(
        "cmd-green",
        "Mono Green Commander",
        ["G"],
        "Legendary Creature — Elf",
    )
    forest = _basic_test_card(
        "forest-oracle",
        "Forest",
        ["G"],
        "Basic Land — Forest",
        "({T}: Add {G}.)",
    )
    glaring_fleshraker = _basic_test_card(
        "glaring-fleshraker",
        "Glaring Fleshraker",
        [],
        "Creature — Eldrazi",
        "{C}: Glaring Fleshraker gets +1/+1 until end of turn.",
    )

    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[glaring_fleshraker],
        all_cards=[commander, forest, glaring_fleshraker],
        role_tags={forest.oracle_id: [RoleTag(CardRole.LAND, 1.0, "rule_based")]},
        owned_oracle_ids={glaring_fleshraker.oracle_id},
    )

    assert glaring_fleshraker.oracle_id not in {card.oracle_id for card in pool}


def test_c_activation_cost_card_does_not_count_as_colorless_source() -> None:
    commander = _basic_test_card(
        "cmd-green",
        "Mono Green Commander",
        ["G"],
        "Legendary Creature — Elf",
    )
    forest = _basic_test_card(
        "forest-oracle",
        "Forest",
        ["G"],
        "Basic Land — Forest",
        "({T}: Add {G}.)",
    )
    glaring_fleshraker = _basic_test_card(
        "glaring-fleshraker",
        "Glaring Fleshraker",
        [],
        "Creature — Eldrazi",
        "{C}: Glaring Fleshraker gets +1/+1 until end of turn.",
    )
    eldrazi_confluence = _basic_test_card(
        "eldrazi-confluence",
        "Eldrazi Confluence",
        [],
        "Instant",
        "Choose three. You may choose the same mode more than once.",
    )
    eldrazi_confluence.mana_cost = "{2}{C}"

    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[glaring_fleshraker],
        all_cards=[commander, forest, glaring_fleshraker, eldrazi_confluence],
        role_tags={forest.oracle_id: [RoleTag(CardRole.LAND, 1.0, "rule_based")]},
        owned_oracle_ids={glaring_fleshraker.oracle_id},
    )

    pool_ids = {card.oracle_id for card in pool}
    assert glaring_fleshraker.oracle_id not in pool_ids
    assert eldrazi_confluence.oracle_id not in pool_ids
