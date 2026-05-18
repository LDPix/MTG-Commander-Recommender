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
    """Non-basic cards not in owned_oracle_ids are marked is_owned=False.

    SC-MANA-007: regular canonical basics are always is_owned=True (virtual inventory).
    """
    from app.recommendation.deck_candidate_pool import CANONICAL_BASIC_LAND_NAMES

    pool = DeckCandidatePool().build(
        commander=meren,
        owned_cards=[],
        all_cards=sample_cards,
        role_tags=role_tags_for_all,
        owned_oracle_ids=set(),  # no owned cards
    )
    for card in pool:
        if card.name in CANONICAL_BASIC_LAND_NAMES:
            assert card.is_owned is True, f"{card.name} should be virtual-owned (SC-MANA-007)"
        else:
            assert card.is_owned is False, f"{card.name} should be unowned"


def test_candidate_pool_no_false_owned(meren: CardData, sample_cards: list[CardData], role_tags_for_all: dict[str, list[RoleTag]], cards_by_name: dict[str, CardData]) -> None:
    """is_owned is never True for a non-basic card not in owned_oracle_ids.

    SC-MANA-007: canonical basics are virtual-owned regardless of collection contents.
    """
    from app.recommendation.deck_candidate_pool import CANONICAL_BASIC_LAND_NAMES

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
        if card.oracle_id not in owned_ids and card.name not in CANONICAL_BASIC_LAND_NAMES:
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


def test_owned_cards_sort_before_unowned_within_role_bucket() -> None:
    """SC-DECK-042: within each role bucket (no quality data), owned cards sort before unowned."""
    commander = _basic_test_card("cmd-g-order", "Order Commander", ["G"], "Legendary Creature — Elf")

    owned_ramp = _basic_test_card("owned-ramp", "Owned Ramp", ["G"], "Sorcery")
    unowned_ramp = _basic_test_card("unowned-ramp", "Unowned Ramp", ["G"], "Sorcery")

    role_tags = {
        owned_ramp.oracle_id: [RoleTag(CardRole.RAMP, 1.0, "rule_based")],
        unowned_ramp.oracle_id: [RoleTag(CardRole.RAMP, 1.0, "rule_based")],
    }

    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[owned_ramp],
        all_cards=[commander, owned_ramp, unowned_ramp],
        role_tags=role_tags,
        owned_oracle_ids={owned_ramp.oracle_id},
    )

    ramp_cards = [c for c in pool if CardRole.RAMP.value in c.roles]
    # owned card should appear before unowned (no quality data → owned_bonus wins)
    owned_positions = [i for i, c in enumerate(ramp_cards) if c.is_owned]
    unowned_positions = [i for i, c in enumerate(ramp_cards) if not c.is_owned]
    if owned_positions and unowned_positions:
        assert max(owned_positions) < min(unowned_positions)


def test_per_role_cap_limits_cards_per_role() -> None:
    """SC-DECK-042: at most _PER_ROLE_CAP cards per non-land role appear in the pool."""
    from app.recommendation.deck_candidate_pool import _PER_ROLE_CAP

    commander = _basic_test_card("cmd-g-cap", "Cap Commander", ["G"], "Legendary Creature — Elf")

    # 200 RAMP cards — far more than _PER_ROLE_CAP (80)
    ramp_cards = [
        _basic_test_card(f"ramp-{i:03d}", f"Ramp Card {i}", ["G"], "Sorcery")
        for i in range(200)
    ]
    ramp_role_tags = {
        card.oracle_id: [RoleTag(CardRole.RAMP, 1.0, "rule_based")]
        for card in ramp_cards
    }

    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[],
        all_cards=[commander, *ramp_cards],
        role_tags=ramp_role_tags,
        owned_oracle_ids=set(),
    )

    ramp_in_pool = [c for c in pool if CardRole.RAMP.value in c.roles]
    assert len(ramp_in_pool) <= _PER_ROLE_CAP


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
    assert forests[0].is_owned is True  # SC-MANA-007: virtual inventory


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

    assert any(card.name == "Swamp" and card.is_owned for card in pool)  # SC-MANA-007: virtual inventory


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


def test_freely_injected_basic_is_marked_owned() -> None:
    """SC-MANA-007: injected regular basic is virtual inventory → is_owned=True."""
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
    assert injected_forest.is_owned is True


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


def test_c_requirement_cards_no_longer_excluded_at_pool_stage() -> None:
    """SC-DECK-010 binary gate removed: {C}-mana-cost cards always enter the pool."""
    commander = _basic_test_card(
        "cmd-green", "Mono Green Commander", ["G"], "Legendary Creature — Elf",
    )
    forest = _basic_test_card(
        "forest-oracle", "Forest", ["G"], "Basic Land — Forest", "({T}: Add {G}.)",
    )
    eldrazi_confluence = _basic_test_card(
        "eldrazi-confluence", "Eldrazi Confluence", [], "Instant",
        "Choose three. You may choose the same mode more than once.",
    )
    eldrazi_confluence.mana_cost = "{2}{C}"

    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[],
        all_cards=[commander, forest, eldrazi_confluence],
        role_tags={forest.oracle_id: [RoleTag(CardRole.LAND, 1.0, "rule_based")]},
        owned_oracle_ids=set(),
    )

    assert eldrazi_confluence.oracle_id in {card.oracle_id for card in pool}, (
        "Eldrazi Confluence must now appear in the pool (binary gate removed)"
    )


def test_deck_candidate_pool_builds_without_colorless_source_count() -> None:
    """SC-DECK-010 binary gate removed: pool builds identically regardless of owned mana rocks."""
    commander = _basic_test_card(
        "cmd-green-2", "Mono Green Commander 2", ["G"], "Legendary Creature — Elf",
    )
    forest = _basic_test_card(
        "forest-oracle-2", "Forest", ["G"], "Basic Land — Forest", "({T}: Add {G}.)",
    )
    eldrazi = _basic_test_card(
        "eldrazi-test-002", "Test Eldrazi", [], "Creature — Eldrazi", "",
    )
    eldrazi.mana_cost = "{3}{C}"

    pool_no_rocks = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[],
        all_cards=[commander, forest, eldrazi],
        role_tags={forest.oracle_id: [RoleTag(CardRole.LAND, 1.0, "rule_based")]},
        owned_oracle_ids=set(),
    )
    pool_ids = {card.oracle_id for card in pool_no_rocks}
    assert eldrazi.oracle_id in pool_ids, (
        "Pool build must not gate {C}-requirement cards based on owned source count"
    )


# ---------------------------------------------------------------------------
# SC-MANA-007: Basic land virtual inventory
# ---------------------------------------------------------------------------


def test_injected_regular_basic_is_marked_owned_sc_mana_007() -> None:
    """SC-MANA-007: injected regular basic gets is_owned=True (virtual inventory)."""
    commander = _basic_test_card("cmd-g", "Commander", ["G"], "Legendary Creature — Elf")
    forest = _basic_test_card("forest-oid", "Forest", ["G"], "Basic Land — Forest", "({T}: Add {G}.)")

    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[],
        all_cards=[commander, forest],
        role_tags={forest.oracle_id: [RoleTag(CardRole.LAND, 1.0, "rule_based")]},
        owned_oracle_ids=set(),
        max_pool_size=0,
    )

    injected = next(c for c in pool if c.name == "Forest")
    assert injected.is_owned is True, "Regular injected Forest must be virtual-owned"


def test_unowned_basic_in_main_pool_is_upgraded_to_virtual_owned() -> None:
    """SC-MANA-007: Forest present in all_cards but not owned → still marked is_owned=True."""
    commander = _basic_test_card("cmd-g2", "Commander", ["G"], "Legendary Creature — Elf")
    forest = _basic_test_card("forest-oid2", "Forest", ["G"], "Basic Land — Forest", "({T}: Add {G}.)")

    # Forest is in all_cards but NOT in owned_oracle_ids — max_pool_size=10 so it enters main loop
    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[],
        all_cards=[commander, forest],
        role_tags={forest.oracle_id: [RoleTag(CardRole.LAND, 1.0, "rule_based")]},
        owned_oracle_ids=set(),
        max_pool_size=10,
    )

    forest_card = next(c for c in pool if c.name == "Forest")
    assert forest_card.is_owned is True, "Forest in main pool but not owned must still be virtual-owned"


def test_injected_regular_basic_not_in_missing_count() -> None:
    """SC-MANA-007: virtual-owned basics produce no missing_card warnings."""
    commander = _basic_test_card("cmd-g3", "Commander", ["G"], "Legendary Creature — Elf")
    forest = _basic_test_card("forest-oid3", "Forest", ["G"], "Basic Land — Forest", "({T}: Add {G}.)")

    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[],
        all_cards=[commander, forest],
        role_tags={forest.oracle_id: [RoleTag(CardRole.LAND, 1.0, "rule_based")]},
        owned_oracle_ids=set(),
        max_pool_size=0,
    )

    # is_owned=True means no "missing_card" warning in score logs
    forest_card = next(c for c in pool if c.name == "Forest")
    assert forest_card.is_owned is True
    unowned_in_pool = [c for c in pool if not c.is_owned]
    assert all(c.name != "Forest" for c in unowned_in_pool), "Forest must not appear in unowned list"


def test_snow_covered_basic_not_injected_as_virtual() -> None:
    """SC-MANA-007: Snow-Covered Forest is NOT marked virtual-owned (luxury variant)."""
    commander = _basic_test_card("cmd-g4", "Commander", ["G"], "Legendary Creature — Elf")
    forest = _basic_test_card("forest-oid4", "Forest", ["G"], "Basic Land — Forest", "({T}: Add {G}.)")
    snow_forest = _basic_test_card(
        "snow-forest-oid", "Snow-Covered Forest", ["G"], "Basic Snow Land — Forest", "({T}: Add {G}.)"
    )

    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[],
        all_cards=[commander, forest, snow_forest],
        role_tags={
            forest.oracle_id: [RoleTag(CardRole.LAND, 1.0, "rule_based")],
            snow_forest.oracle_id: [RoleTag(CardRole.LAND, 1.0, "rule_based")],
        },
        owned_oracle_ids=set(),
        max_pool_size=10,
    )

    snow_card = next((c for c in pool if c.name == "Snow-Covered Forest"), None)
    # Snow-Covered Forest may or may not appear in the pool, but must NOT be virtual-owned
    if snow_card is not None:
        assert snow_card.is_owned is False, "Snow-Covered Forest must remain collection-dependent"


def test_basic_land_not_in_upgrade_suggestions() -> None:
    """SC-MANA-007: virtual-owned Forest is excluded from upgrade suggestions."""
    from app.models.deck import GeneratedDeck, PackageCluster, QuotaStatus
    from app.recommendation.upgrade_suggester import UpgradeSuggester

    commander = _basic_test_card("cmd-g5", "Commander", ["G"], "Legendary Creature — Elf")
    forest = _basic_test_card("forest-oid5", "Forest", ["G"], "Basic Land — Forest", "({T}: Add {G}.)")

    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[],
        all_cards=[commander, forest],
        role_tags={forest.oracle_id: [RoleTag(CardRole.LAND, 1.0, "rule_based")]},
        owned_oracle_ids=set(),
        max_pool_size=0,
    )

    forest_deck_card = next(c for c in pool if c.name == "Forest")
    commander_deck_card = forest_deck_card.model_copy(
        update={"oracle_id": commander.oracle_id, "name": commander.name, "is_owned": True}
    )
    deck = GeneratedDeck(
        deck_id="mana007-test",
        session_id="mana007-test",
        commander=commander_deck_card,
        main_deck=[forest_deck_card],
        role_breakdown={},
        quota_status=[],
        package_breakdown=[],
        warnings=[],
        owned_count=1,
        owned_percentage=100.0,
        is_valid=True,
        validation_errors=[],
    )
    quota_status = [QuotaStatus(role="LAND", target_min=1, target_max=36, actual_count=1, is_satisfied=True)]

    suggestions = UpgradeSuggester().suggest(
        commander=commander,
        generated_deck=deck,
        candidate_pool=pool,
        packages=[],
        quota_status=quota_status,
    )

    suggested_names = {s.name for s in suggestions}
    assert "Forest" not in suggested_names, "Virtual-owned Forest must not appear in upgrade suggestions"


# ---------------------------------------------------------------------------
# SC-DECK-042: Quality-aware per-role pool capping
# ---------------------------------------------------------------------------

def test_high_quality_unowned_card_included_over_low_quality_owned() -> None:
    """High-quality unowned RAMP cards beat low-quality owned RAMP cards when bucket is full."""
    from app.recommendation.deck_candidate_pool import _PER_ROLE_CAP

    commander = _basic_test_card("cmd-g-hq", "HQ Commander", ["G"], "Legendary Creature — Elf")

    # _PER_ROLE_CAP + 10 owned RAMP cards with no edhrec_rank (quality ≈ 0.20 + 0.0)
    low_quality_owned = [
        _basic_test_card(f"lo-own-{i:03d}", f"Low Owned {i}", ["G"], "Sorcery")
        for i in range(_PER_ROLE_CAP + 10)
    ]
    # 10 unowned RAMP cards with edhrec_rank=1 (highest quality)
    high_quality_unowned = []
    for i in range(10):
        card = _basic_test_card(f"hi-unown-{i:02d}", f"High Unowned {i}", ["G"], "Sorcery")
        card.edhrec_rank = 1  # near-perfect quality score
        high_quality_unowned.append(card)

    all_ramp = low_quality_owned + high_quality_unowned
    owned_ids = {c.oracle_id for c in low_quality_owned}
    ramp_role_tags = {
        card.oracle_id: [RoleTag(CardRole.RAMP, 1.0, "rule_based")]
        for card in all_ramp
    }
    all_cards_lookup = {c.oracle_id: c for c in all_ramp + [commander]}

    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=low_quality_owned,
        all_cards=[commander, *all_ramp],
        role_tags=ramp_role_tags,
        owned_oracle_ids=owned_ids,
        all_cards_lookup=all_cards_lookup,
    )

    pool_ids = {c.oracle_id for c in pool}
    # All 10 high-quality unowned cards must be in the pool
    for card in high_quality_unowned:
        assert card.oracle_id in pool_ids, f"{card.name} should be in pool (high quality)"


def test_land_bucket_uses_land_cap() -> None:
    """SC-DECK-042: land role bucket uses _LAND_CAP (120), not _PER_ROLE_CAP (80)."""
    from app.recommendation.deck_candidate_pool import _LAND_CAP

    commander = _basic_test_card("cmd-g-land", "Land Commander", ["G"], "Legendary Creature — Elf")
    land_cards = [
        _basic_test_card(f"land-{i:03d}", f"Land {i}", ["G"], "Land")
        for i in range(150)
    ]
    land_role_tags = {
        card.oracle_id: [RoleTag(CardRole.LAND, 1.0, "rule_based")]
        for card in land_cards
    }

    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[],
        all_cards=[commander, *land_cards],
        role_tags=land_role_tags,
        owned_oracle_ids=set(),
    )

    land_in_pool = [c for c in pool if CardRole.LAND.value in c.roles]
    assert len(land_in_pool) <= _LAND_CAP


def test_roleless_cards_in_fallback_bucket() -> None:
    """SC-DECK-042: cards with no roles go into fallback bucket capped at _FALLBACK_CAP."""
    from app.recommendation.deck_candidate_pool import _FALLBACK_CAP, CANONICAL_BASIC_LAND_NAMES

    commander = _basic_test_card("cmd-g-fb", "Fallback Commander", ["G"], "Legendary Creature — Elf")
    roleless_cards = [
        _basic_test_card(f"roleless-{i:03d}", f"Roleless Card {i}", ["G"], "Creature")
        for i in range(200)
    ]

    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[],
        all_cards=[commander, *roleless_cards],
        role_tags={},  # no roles → all go to fallback bucket
        owned_oracle_ids=set(),
    )

    # Pool should have at most _FALLBACK_CAP cards (plus any free basics injected)
    non_basic = [c for c in pool if c.name not in CANONICAL_BASIC_LAND_NAMES]
    assert len(non_basic) <= _FALLBACK_CAP
