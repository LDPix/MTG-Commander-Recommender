"""Tests for SC-DECK-002-006: DeckGenerator."""
from __future__ import annotations

import pytest

from app.models.card import CardData
from app.models.deck import DeckCard, GeneratedDeck, PackageCluster
from app.recommendation.colorless_rules import C_REQUIREMENT_MIN_SOURCES
from app.recommendation.deck_candidate_pool import DeckCandidatePool
from app.recommendation.deck_generator import BASIC_LAND_NAMES, DeckGenerator
from app.recommendation.package_detector import PackageDetector
from app.recommendation.package_labeler import PackageLabeler
from app.recommendation.quota_config import BASELINE_QUOTAS, RoleQuota
from app.recommendation.role_taxonomy import CardRole, RoleTag
from app.recommendation.role_tagger import RuleTagger
from app.recommendation.synergy_graph import RoleTagSynergyProvider, SynergyGraph

MEREN_ORACLE_ID = "4b2521bc-8f94-1a0b-c3d4-5e6f7a8b9c0d"


@pytest.fixture(scope="module")
def tagger() -> RuleTagger:
    return RuleTagger()


@pytest.fixture(scope="module")
def meren(cards_by_name: dict[str, CardData]) -> CardData:
    return cards_by_name["Meren of Clan Nel Toth"]


@pytest.fixture(scope="module")
def role_tags_all(sample_cards: list[CardData], tagger: RuleTagger) -> dict[str, list[RoleTag]]:
    return {c.oracle_id: tagger.tag(c) for c in sample_cards}


@pytest.fixture(scope="module")
def all_cards_lookup(sample_cards: list[CardData]) -> dict[str, CardData]:
    return {c.oracle_id: c for c in sample_cards}


@pytest.fixture(scope="module")
def candidate_pool(
    meren: CardData,
    sample_cards: list[CardData],
    role_tags_all: dict[str, list[RoleTag]],
    cards_by_name: dict[str, CardData],
) -> list[DeckCard]:
    owned_ids = {
        meren.oracle_id,
        cards_by_name["Sol Ring"].oracle_id,
        cards_by_name["Forest"].oracle_id,
        cards_by_name["Swamp"].oracle_id,
        cards_by_name["Viscera Seer"].oracle_id,
        cards_by_name["Eternal Witness"].oracle_id,
        cards_by_name["Damnation"].oracle_id,
    }
    return DeckCandidatePool().build(
        commander=meren,
        owned_cards=[],
        all_cards=sample_cards,
        role_tags=role_tags_all,
        owned_oracle_ids=owned_ids,
    )


@pytest.fixture(scope="module")
def synergy_graph(
    candidate_pool: list[DeckCard],
    role_tags_all: dict[str, list[RoleTag]],
    meren: CardData,
) -> SynergyGraph:
    graph = SynergyGraph()
    graph.build(
        candidate_cards=candidate_pool,
        role_tags=role_tags_all,
        provider=RoleTagSynergyProvider(),
        commander_oracle_id=meren.oracle_id,
        color_identity=meren.color_identity,
    )
    return graph


@pytest.fixture(scope="module")
def packages(
    candidate_pool: list[DeckCard],
    role_tags_all: dict[str, list[RoleTag]],
    synergy_graph: SynergyGraph,
) -> list[PackageCluster]:
    raw = PackageDetector().detect(candidate_pool, role_tags_all, synergy_graph)
    return [PackageLabeler().label(p) for p in raw]


@pytest.fixture(scope="module")
def generated_deck(
    meren: CardData,
    candidate_pool: list[DeckCard],
    role_tags_all: dict[str, list[RoleTag]],
    synergy_graph: SynergyGraph,
    packages: list[PackageCluster],
    all_cards_lookup: dict[str, CardData],
) -> GeneratedDeck:
    meren_tags = role_tags_all.get(meren.oracle_id, [])
    generator = DeckGenerator()
    return generator.generate(
        commander=meren,
        commander_tags=meren_tags,
        candidate_pool=candidate_pool,
        role_tags=role_tags_all,
        graph=synergy_graph,
        packages=packages,
        session_id="test-session",
        all_cards_lookup=all_cards_lookup,
    )


# -------------------------------------------------------------------------
# Core structure tests
# -------------------------------------------------------------------------

def test_generated_deck_has_99_main_deck_cards(generated_deck: GeneratedDeck) -> None:
    """Main deck must contain exactly 99 cards (counting quantities)."""
    total = sum(c.quantity for c in generated_deck.main_deck)
    assert total == 99, f"Expected 99 main deck cards, got {total}"


def test_generated_deck_has_one_commander(generated_deck: GeneratedDeck, meren: CardData) -> None:
    """Deck has exactly one commander matching the requested oracle_id."""
    assert generated_deck.commander.oracle_id == meren.oracle_id
    assert generated_deck.commander.name == "Meren of Clan Nel Toth"


def test_generated_deck_total_100(generated_deck: GeneratedDeck) -> None:
    """Commander + main deck = 100 cards total."""
    main_total = sum(c.quantity for c in generated_deck.main_deck)
    assert main_total + 1 == 100, f"Expected 100 total, got {main_total + 1}"


def test_generated_deck_passes_legality_validation(generated_deck: GeneratedDeck) -> None:
    """Generated deck should be valid or have only informational errors."""
    if not generated_deck.is_valid:
        # Allow underfill errors (not enough cards for quota), but not structural errors
        structural_errors = [
            e for e in generated_deck.validation_errors
            if "singleton" in e.lower() or "off-color" in e.lower() or "banned" in e.lower()
        ]
        assert not structural_errors, f"Structural errors: {structural_errors}"


def test_generated_deck_no_singleton_violations(generated_deck: GeneratedDeck) -> None:
    """No non-basic card appears more than once."""
    from collections import Counter
    non_basic_counts = Counter()
    for card in generated_deck.main_deck:
        if card.name not in BASIC_LAND_NAMES:
            non_basic_counts[card.oracle_id] += card.quantity
    for oracle_id, count in non_basic_counts.items():
        assert count == 1, f"Non-basic {oracle_id} appears {count} times"


def test_basic_lands_may_have_quantity_gt_1(generated_deck: GeneratedDeck) -> None:
    """Basic land DeckCards may have quantity > 1, all others must have quantity == 1."""
    for card in generated_deck.main_deck:
        if card.name not in BASIC_LAND_NAMES:
            assert card.quantity == 1, f"{card.name} is not basic but has quantity {card.quantity}"


def test_all_selection_reasons_are_non_empty(generated_deck: GeneratedDeck) -> None:
    """Every DeckCard in main_deck has a non-empty selection_reason."""
    for card in generated_deck.main_deck:
        assert card.selection_reason, f"{card.name} has empty selection_reason"


# -------------------------------------------------------------------------
# Role quota tests
# -------------------------------------------------------------------------

def test_deck_attempts_land_quota(generated_deck: GeneratedDeck) -> None:
    """Deck fills land quota (at least 30 lands, given available pool)."""
    land_count = generated_deck.role_breakdown.get(CardRole.LAND.value, 0)
    assert land_count >= 30, f"Expected >= 30 lands, got {land_count}"


def test_deck_attempts_ramp_quota(generated_deck: GeneratedDeck) -> None:
    """Deck fills ramp quota (at least 6 ramp cards)."""
    ramp_count = generated_deck.role_breakdown.get(CardRole.RAMP.value, 0)
    assert ramp_count >= 6, f"Expected >= 6 ramp cards, got {ramp_count}"


def test_deck_attempts_draw_quota(generated_deck: GeneratedDeck) -> None:
    """Deck fills card draw quota (at least 6 draw cards)."""
    draw_count = generated_deck.role_breakdown.get(CardRole.CARD_DRAW.value, 0)
    assert draw_count >= 6, f"Expected >= 6 card draw cards, got {draw_count}"


def test_deck_attempts_interaction_quota(generated_deck: GeneratedDeck) -> None:
    """Deck fills spot removal quota (at least 3 removal spells)."""
    removal_count = generated_deck.role_breakdown.get(CardRole.SPOT_REMOVAL.value, 0)
    assert removal_count >= 3, f"Expected >= 3 spot removal, got {removal_count}"


def test_deck_attempts_board_wipe_quota(generated_deck: GeneratedDeck) -> None:
    """Deck includes at least 1 board wipe."""
    wipe_count = generated_deck.role_breakdown.get(CardRole.BOARD_WIPE.value, 0)
    assert wipe_count >= 1, f"Expected >= 1 board wipe, got {wipe_count}"


# -------------------------------------------------------------------------
# Quota status tests
# -------------------------------------------------------------------------

def test_quota_status_has_one_entry_per_tracked_role(generated_deck: GeneratedDeck) -> None:
    """quota_status has exactly one entry per quota role."""
    roles = [qs.role for qs in generated_deck.quota_status]
    assert len(roles) == len(set(roles)), "Duplicate roles in quota_status"
    assert len(roles) >= 7  # at least the 7 baseline roles


def test_quota_status_actual_count_matches_breakdown(generated_deck: GeneratedDeck) -> None:
    """quota_status.actual_count matches role_breakdown values."""
    for qs in generated_deck.quota_status:
        breakdown_count = generated_deck.role_breakdown.get(qs.role, 0)
        assert qs.actual_count == breakdown_count, (
            f"Role {qs.role}: quota_status says {qs.actual_count} but breakdown says {breakdown_count}"
        )


def test_underfilled_quota_returns_warning(
    meren: CardData,
    role_tags_all: dict[str, list[RoleTag]],
    all_cards_lookup: dict[str, CardData],
) -> None:
    """When pool is tiny, underfilled quotas produce warnings."""
    # Create a tiny pool with very few cards
    tiny_pool = [
        DeckCard(
            oracle_id="tiny-001",
            name="Test Land",
            is_owned=False,
            quantity=1,
            roles=["LAND"],
            selection_reason="candidate",
        )
    ]
    # Build graph with tiny pool
    graph = SynergyGraph()
    graph.build(tiny_pool, {}, RoleTagSynergyProvider(), meren.oracle_id, meren.color_identity)

    gen = DeckGenerator()
    deck = gen.generate(
        commander=meren,
        commander_tags=[],
        candidate_pool=tiny_pool,
        role_tags={},
        graph=graph,
        packages=[],
        session_id="test-underfill",
        all_cards_lookup=all_cards_lookup,
    )

    # Warnings should be non-empty since most quotas are underfilled
    assert len(deck.warnings) > 0, "Expected warnings for underfilled deck"


# -------------------------------------------------------------------------
# Ownership tests
# -------------------------------------------------------------------------

def test_owned_count_is_correct(generated_deck: GeneratedDeck) -> None:
    """owned_count matches the sum of quantities for is_owned cards."""
    expected_owned = sum(c.quantity for c in generated_deck.main_deck if c.is_owned)
    assert generated_deck.owned_count == expected_owned


def test_owned_percentage_in_range(generated_deck: GeneratedDeck) -> None:
    """owned_percentage is in [0.0, 1.0]."""
    assert 0.0 <= generated_deck.owned_percentage <= 1.0


def test_deck_id_is_uuid_string(generated_deck: GeneratedDeck) -> None:
    """deck_id is a non-empty UUID string."""
    import uuid
    assert generated_deck.deck_id
    uuid.UUID(generated_deck.deck_id)  # raises ValueError if not valid UUID


def test_session_id_preserved(generated_deck: GeneratedDeck) -> None:
    """session_id is preserved in the generated deck."""
    assert generated_deck.session_id == "test-session"


# -------------------------------------------------------------------------
# Determinism test
# -------------------------------------------------------------------------

def test_generation_is_deterministic(
    meren: CardData,
    candidate_pool: list[DeckCard],
    role_tags_all: dict[str, list[RoleTag]],
    synergy_graph: SynergyGraph,
    packages: list[PackageCluster],
    all_cards_lookup: dict[str, CardData],
) -> None:
    """Generating a deck twice from the same inputs yields the same role breakdown."""
    meren_tags = role_tags_all.get(meren.oracle_id, [])
    gen = DeckGenerator()

    deck1 = gen.generate(meren, meren_tags, candidate_pool, role_tags_all, synergy_graph, packages, "det-test", all_cards_lookup=all_cards_lookup)
    deck2 = gen.generate(meren, meren_tags, candidate_pool, role_tags_all, synergy_graph, packages, "det-test", all_cards_lookup=all_cards_lookup)

    assert deck1.role_breakdown == deck2.role_breakdown
    # Main deck oracle_ids (sorted) should match
    ids1 = sorted(c.oracle_id for c in deck1.main_deck)
    ids2 = sorted(c.oracle_id for c in deck2.main_deck)
    assert ids1 == ids2


# -------------------------------------------------------------------------
# Package coherence regression tests (SC-DECK-006)
# -------------------------------------------------------------------------

def _test_commander() -> CardData:
    return CardData(
        id="cmd-package-test",
        oracle_id="cmd-package-test",
        name="Package Test Commander",
        color_identity=["G"],
        legalities={"commander": "legal"},
        type_line="Legendary Creature — Test",
        oracle_text="",
        mana_cost="{2}{G}",
        cmc=3.0,
    )


def _deck_card(
    oracle_id: str,
    name: str,
    roles: list[str],
    is_owned: bool = False,
) -> DeckCard:
    return DeckCard(
        oracle_id=oracle_id,
        name=name,
        is_owned=is_owned,
        quantity=1,
        roles=roles,
        selection_reason="candidate",
    )


def test_package_coherent_cards_receive_selection_preference() -> None:
    """Equal-role candidates prefer the card with package-derived synergy."""
    commander = _test_commander()
    package_ramp = _deck_card("pkg-ramp", "Package Ramp", ["RAMP", "TOKEN_MAKER"])
    generic_ramp = _deck_card("generic-ramp", "Generic Ramp", ["RAMP"])
    package_support = [
        _deck_card(f"pkg-support-{i}", f"Package Support {i}", ["TOKEN_MAKER"])
        for i in range(4)
    ]
    forest = _deck_card("forest-basic", "Forest", ["LAND"], is_owned=True)
    pool = [generic_ramp, package_ramp, *package_support, forest]
    role_tags = {
        card.oracle_id: [
            RoleTag(CardRole(role), confidence=1.0, source="manual")
            for role in card.roles
        ]
        for card in pool
    }
    graph = SynergyGraph()
    graph.build(pool, role_tags, RoleTagSynergyProvider(), commander.oracle_id, commander.color_identity)
    packages = [
        PackageLabeler().label(p)
        for p in PackageDetector().detect(pool, role_tags, graph, min_package_size=4)
    ]

    deck = DeckGenerator().generate(
        commander=commander,
        commander_tags=[],
        candidate_pool=pool,
        role_tags=role_tags,
        graph=graph,
        packages=packages,
        session_id="package-preference",
        quotas=[
            RoleQuota(CardRole.RAMP, target_min=1, target_max=1),
            RoleQuota(CardRole.LAND, target_min=98, target_max=98),
        ],
    )

    selected_by_quota = {
        card.oracle_id
        for card in deck.main_deck
        if card.selection_reason == "fills RAMP role"
    }
    assert "pkg-ramp" in selected_by_quota
    assert "generic-ramp" not in selected_by_quota


def test_package_preference_does_not_break_role_quotas(generated_deck: GeneratedDeck) -> None:
    """Package coherence must remain subordinate to tracked role balance."""
    for quota in generated_deck.quota_status:
        if quota.is_satisfied:
            assert quota.actual_count >= quota.target_min
        elif quota.warning:
            assert "underfilled" in quota.warning or "overfilled" in quota.warning


def test_package_preference_does_not_break_singleton_or_color_identity(
    generated_deck: GeneratedDeck,
) -> None:
    """Package selection must preserve structural Commander legality checks."""
    from collections import Counter

    non_basic_counts = Counter(
        card.oracle_id
        for card in generated_deck.main_deck
        if card.name not in BASIC_LAND_NAMES
        for _ in range(card.quantity)
    )
    assert all(count == 1 for count in non_basic_counts.values())

    structural_errors = [
        error for error in generated_deck.validation_errors
        if "singleton" in error.lower() or "off-color" in error.lower()
    ]
    assert structural_errors == []


def test_selected_cards_include_package_ids(generated_deck: GeneratedDeck) -> None:
    """Selected cards expose package membership when package evidence exists."""
    packaged_cards = [card for card in generated_deck.main_deck if card.package_ids]

    assert packaged_cards
    assert all(card.package_ids for card in packaged_cards)


# =========================================================================
# SC-MANA-001: Mono-color basic land priority
# =========================================================================

AZUSA_ORACLE_ID = "aa000092-0000-4000-0000-000000000092"


@pytest.fixture(scope="module")
def azusa(cards_by_name: dict[str, CardData]) -> CardData:
    return cards_by_name["Azusa, Lost but Seeking"]


@pytest.fixture(scope="module")
def mono_green_pool(
    azusa: CardData,
    sample_cards: list[CardData],
    role_tags_all: dict[str, list[RoleTag]],
) -> list[DeckCard]:
    """Candidate pool for the mono-Green Azusa commander."""
    return DeckCandidatePool().build(
        commander=azusa,
        owned_cards=[],
        all_cards=sample_cards,
        role_tags=role_tags_all,
        owned_oracle_ids=set(),
    )


@pytest.fixture(scope="module")
def mono_green_deck(
    azusa: CardData,
    mono_green_pool: list[DeckCard],
    role_tags_all: dict[str, list[RoleTag]],
    all_cards_lookup: dict[str, CardData],
) -> GeneratedDeck:
    graph = SynergyGraph()
    graph.build(mono_green_pool, role_tags_all, RoleTagSynergyProvider(), azusa.oracle_id, azusa.color_identity)
    packages = [PackageLabeler().label(p) for p in PackageDetector().detect(mono_green_pool, role_tags_all, graph)]
    return DeckGenerator().generate(
        commander=azusa,
        commander_tags=role_tags_all.get(azusa.oracle_id, []),
        candidate_pool=mono_green_pool,
        role_tags=role_tags_all,
        graph=graph,
        packages=packages,
        session_id="mono-green-test",
        all_cards_lookup=all_cards_lookup,
    )


def test_mono_green_deck_includes_basic_forests(mono_green_deck: GeneratedDeck) -> None:
    """A mono-Green deck must include Forest cards."""
    forests = [c for c in mono_green_deck.main_deck if c.name == "Forest"]
    assert forests, "Mono-green deck must include at least one Forest entry"


def test_mono_green_deck_basic_land_count_at_least_minimum(mono_green_deck: GeneratedDeck) -> None:
    """Mono-color deck must hit MONO_COLOR_BASIC_LAND_MIN basic lands."""
    from app.recommendation.mana_base_rules import MONO_COLOR_BASIC_LAND_MIN

    basic_count = sum(
        c.quantity for c in mono_green_deck.main_deck
        if c.name in BASIC_LAND_NAMES
    )
    assert basic_count >= MONO_COLOR_BASIC_LAND_MIN, (
        f"Expected >= {MONO_COLOR_BASIC_LAND_MIN} basic lands, got {basic_count}"
    )


def test_zero_basic_lands_not_produced_for_mono_color_commander(mono_green_deck: GeneratedDeck) -> None:
    """SC-MANA-001 regression: mono-color deck must never have 0 basic lands."""
    basic_count = sum(c.quantity for c in mono_green_deck.main_deck if c.name in BASIC_LAND_NAMES)
    assert basic_count > 0


def test_basic_lands_prioritized_over_nonbasic_in_mono_color(mono_green_deck: GeneratedDeck) -> None:
    """In a mono-color deck, basic land count >= non-basic land count."""
    basic_count = sum(c.quantity for c in mono_green_deck.main_deck if c.name in BASIC_LAND_NAMES)
    non_basic_count = sum(
        c.quantity for c in mono_green_deck.main_deck
        if "LAND" in c.roles and c.name not in BASIC_LAND_NAMES
    )
    assert basic_count >= non_basic_count, (
        f"Basics ({basic_count}) should outnumber non-basics ({non_basic_count}) in mono-color"
    )


def test_multicolor_deck_land_selection_unchanged(generated_deck: GeneratedDeck) -> None:
    """Multi-color (Meren BG) deck still produces valid land distribution."""
    land_count = generated_deck.role_breakdown.get(CardRole.LAND.value, 0)
    assert land_count >= 30, f"Multicolor land count regression: {land_count}"
    total = sum(c.quantity for c in generated_deck.main_deck)
    assert total == 99


def test_snow_covered_forest_classified_as_basic_land() -> None:
    assert "Snow-Covered Forest" in BASIC_LAND_NAMES


def test_snow_covered_swamp_classified_as_basic_land() -> None:
    assert "Snow-Covered Swamp" in BASIC_LAND_NAMES


def test_owned_snow_covered_forest_competes_for_basic_land_quota_slots() -> None:
    commander = _test_commander()
    snow_forest = DeckCard(
        oracle_id="snow-forest",
        name="Snow-Covered Forest",
        is_owned=True,
        quantity=1,
        roles=["LAND"],
        color_identity=["G"],
        selection_reason="candidate",
    )
    nonbasic_land = DeckCard(
        oracle_id="nonbasic-land",
        name="Green Utility Land",
        is_owned=True,
        quantity=1,
        roles=["LAND"],
        color_identity=["G"],
        selection_reason="candidate",
    )
    graph = SynergyGraph()
    pool = [snow_forest, nonbasic_land]
    graph.build(pool, {}, RoleTagSynergyProvider(), commander.oracle_id, commander.color_identity)

    deck = DeckGenerator().generate(
        commander=commander,
        commander_tags=[],
        candidate_pool=pool,
        role_tags={},
        graph=graph,
        packages=[],
        session_id="snow-basic-test",
        quotas=[RoleQuota(CardRole.LAND, 1, 1)],
    )

    selected_snow = next(card for card in deck.main_deck if card.name == "Snow-Covered Forest")
    assert selected_snow.selection_reason == "fills LAND role (basic priority)"
    selected_nonbasic = next(
        card for card in deck.main_deck if card.name == "Green Utility Land"
    )
    assert selected_nonbasic.selection_reason != "fills LAND role"


def test_mono_green_deck_with_injected_forest_hits_basic_minimum() -> None:
    from app.recommendation.mana_base_rules import MONO_COLOR_BASIC_LAND_MIN

    commander = _test_commander()
    forest_card = CardData(
        id="forest-injection",
        oracle_id="forest-injection",
        name="Forest",
        color_identity=["G"],
        legalities={"commander": "legal"},
        type_line="Basic Land — Forest",
        oracle_text="({T}: Add {G}.)",
        cmc=0.0,
    )
    filler_cards = [
        CardData(
            id=f"filler-{i}",
            oracle_id=f"filler-{i}",
            name=f"Filler {i}",
            color_identity=["G"],
            legalities={"commander": "legal"},
            type_line="Creature",
            oracle_text="",
            cmc=2.0,
        )
        for i in range(5)
    ]
    role_tags = {
        forest_card.oracle_id: [
            RoleTag(CardRole.LAND, confidence=1.0, source="rule_based")
        ]
    }
    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[],
        all_cards=[commander, *filler_cards, forest_card],
        role_tags=role_tags,
        owned_oracle_ids=set(),
        max_pool_size=1,
    )
    graph = SynergyGraph()
    graph.build(pool, role_tags, RoleTagSynergyProvider(), commander.oracle_id, commander.color_identity)

    deck = DeckGenerator().generate(
        commander=commander,
        commander_tags=[],
        candidate_pool=pool,
        role_tags=role_tags,
        graph=graph,
        packages=[],
        session_id="injected-forest-deck",
    )

    forests = [card for card in deck.main_deck if card.name == "Forest"]
    assert forests
    assert sum(card.quantity for card in forests) >= MONO_COLOR_BASIC_LAND_MIN
    assert all(card.is_owned is False for card in forests)


# =========================================================================
# SC-DECK-009: Colorless synergy discount
# =========================================================================

def test_colorless_card_with_no_archetype_synergy_is_deprioritized() -> None:
    """A colorless card with no exempt roles scores lower than an equal colored card."""
    from app.recommendation.deck_generator import _score

    synergy = 0.6  # non-zero so discount is visible
    colorless_generic = DeckCard(
        oracle_id="colorless-generic",
        name="Colorless Generic",
        is_owned=False,
        roles=["TOKEN_MAKER"],       # not in COLORLESS_EXEMPT_ROLES
        color_identity=[],
        synergy_score=synergy,
        selection_reason="candidate",
    )
    colored_equivalent = DeckCard(
        oracle_id="colored-equiv",
        name="Colored Equivalent",
        is_owned=False,
        roles=["TOKEN_MAKER"],
        color_identity=["G"],
        synergy_score=synergy,
        selection_reason="candidate",
    )
    commander_ci = ["B", "G"]

    assert _score(colorless_generic, commander_ci) < _score(colored_equivalent, commander_ci)


def test_owned_colorless_score_is_owned_bonus_when_synergy_is_zero() -> None:
    from app.recommendation.deck_generator import _score

    owned_colorless = DeckCard(
        oracle_id="owned-colorless",
        name="Owned Colorless",
        is_owned=True,
        roles=["TOKEN_MAKER"],
        color_identity=[],
        synergy_score=0.0,
        selection_reason="candidate",
    )

    assert _score(owned_colorless, ["G"]) == 0.3


def test_unowned_thematic_card_beats_zero_synergy_owned_colorless_when_synergy_present() -> None:
    from app.recommendation.deck_generator import _score

    owned_colorless = DeckCard(
        oracle_id="owned-colorless",
        name="Owned Colorless",
        is_owned=True,
        roles=["TOKEN_MAKER"],
        color_identity=[],
        synergy_score=0.0,
        selection_reason="candidate",
    )
    thematic_card = DeckCard(
        oracle_id="thematic",
        name="Thematic Card",
        is_owned=False,
        roles=["TOKEN_MAKER"],
        color_identity=["G"],
        synergy_score=0.4,
        selection_reason="candidate",
    )

    assert _score(thematic_card, ["G"]) > _score(owned_colorless, ["G"])


def test_ramp_tagged_colorless_card_receives_discount_after_narrowing() -> None:
    from app.recommendation.deck_generator import _score

    ramp_artifact = DeckCard(
        oracle_id="ramp-artifact",
        name="Ramp Artifact",
        is_owned=False,
        roles=["RAMP"],
        color_identity=[],
        synergy_score=0.6,
        selection_reason="candidate",
    )
    colored_ramp = DeckCard(
        oracle_id="colored-ramp",
        name="Colored Ramp",
        is_owned=False,
        roles=["RAMP"],
        color_identity=["G"],
        synergy_score=0.6,
        selection_reason="candidate",
    )

    assert _score(ramp_artifact, ["G"]) < _score(colored_ramp, ["G"])


def test_sol_ring_score_reflects_discount_on_synergy_portion() -> None:
    from app.recommendation.colorless_rules import COLORLESS_SYNERGY_DISCOUNT
    from app.recommendation.deck_generator import _score

    sol_ring = DeckCard(
        oracle_id="sol-ring",
        name="Sol Ring",
        is_owned=True,
        roles=["RAMP"],
        color_identity=[],
        synergy_score=0.6,
        selection_reason="candidate",
    )

    assert _score(sol_ring, ["G"]) == 0.6 * COLORLESS_SYNERGY_DISCOUNT + 0.3


def test_colorless_removal_is_exempt_from_colorless_penalty() -> None:
    """A colorless card with SPOT_REMOVAL is exempt."""
    from app.recommendation.deck_generator import _score

    synergy = 0.6
    removal = DeckCard(
        oracle_id="colorless-removal",
        name="Colorless Removal",
        is_owned=False,
        roles=["SPOT_REMOVAL"],
        color_identity=[],
        synergy_score=synergy,
        selection_reason="candidate",
    )
    filler = DeckCard(
        oracle_id="colorless-filler",
        name="Colorless Filler",
        is_owned=False,
        roles=["PAYOFF"],
        color_identity=[],
        synergy_score=synergy,
        selection_reason="candidate",
    )
    commander_ci = ["W", "U", "B", "G"]
    assert _score(removal, commander_ci) > _score(filler, commander_ci)


def test_colorless_penalty_not_applied_in_colorless_commander_deck() -> None:
    """Colorless commanders must not penalise colorless cards."""
    from app.recommendation.deck_generator import _score

    colorless_card = DeckCard(
        oracle_id="colorless-card",
        name="Colorless Card",
        is_owned=False,
        roles=["ENABLER"],
        color_identity=[],
        selection_reason="candidate",
    )
    # A colored card with same synergy score
    colored_card = DeckCard(
        oracle_id="colored-card",
        name="Colored Card",
        is_owned=False,
        roles=["ENABLER"],
        color_identity=["U"],
        selection_reason="candidate",
    )
    colorless_commander_ci: list[str] = []
    # Both should score the same (no discount for colorless commander)
    assert _score(colorless_card, colorless_commander_ci) == _score(colored_card, colorless_commander_ci)


def test_colorless_penalty_visible_in_selection_reason(
    azusa: CardData,
    sample_cards: list[CardData],
    role_tags_all: dict[str, list[RoleTag]],
    all_cards_lookup: dict[str, CardData],
) -> None:
    """When a non-exempt colorless card is selected as filler, its reason notes the discount."""
    # Build a tiny pool: one colored land (basic), plus Hedron Archive (colorless, no exempt roles)
    from app.models.card import CardData as CD

    hedron = next((c for c in sample_cards if c.name == "Hedron Archive"), None)
    if hedron is None:
        pytest.skip("Hedron Archive not in fixture")

    # Build pool with azusa (mono-G) but include Hedron Archive
    pool = DeckCandidatePool().build(
        commander=azusa,
        owned_cards=[],
        all_cards=sample_cards,
        role_tags=role_tags_all,
        owned_oracle_ids=set(),
    )

    graph = SynergyGraph()
    graph.build(pool, role_tags_all, RoleTagSynergyProvider(), azusa.oracle_id, azusa.color_identity)
    packages: list[PackageCluster] = []

    deck = DeckGenerator().generate(
        commander=azusa,
        commander_tags=[],
        candidate_pool=pool,
        role_tags=role_tags_all,
        graph=graph,
        packages=packages,
        session_id="discount-reason-test",
        all_cards_lookup=all_cards_lookup,
    )

    hedron_cards = [c for c in deck.main_deck if c.oracle_id == hedron.oracle_id]
    if not hedron_cards:
        pytest.skip("Hedron Archive not selected in this deck (pool may be large enough)")

    hedron_in_deck = hedron_cards[0]
    if not hedron_in_deck.selection_reason.startswith("synergy/utility"):
        pytest.skip("Hedron Archive selected for a role quota, not as discounted filler")
    assert "colorless discount applied" in hedron_in_deck.selection_reason


# =========================================================================
# SC-DECK-010: {C}-requirement card exclusion
# =========================================================================

def test_c_requirement_card_excluded_when_no_colorless_sources(
    azusa: CardData,
    sample_cards: list[CardData],
    role_tags_all: dict[str, list[RoleTag]],
) -> None:
    """Eldrazi Mimic ({2}{C}) must be excluded when owned cards have < 3 colorless sources."""
    mimic = next((c for c in sample_cards if c.name == "Eldrazi Mimic"), None)
    if mimic is None:
        pytest.skip("Eldrazi Mimic not in fixture")

    # No owned cards → 0 colorless sources → Eldrazi Mimic excluded
    pool = DeckCandidatePool().build(
        commander=azusa,
        owned_cards=[],
        all_cards=sample_cards,
        role_tags=role_tags_all,
        owned_oracle_ids=set(),
    )
    pool_ids = {c.oracle_id for c in pool}
    assert mimic.oracle_id not in pool_ids, "Eldrazi Mimic must be excluded with 0 colorless sources"


def test_c_requirement_card_allowed_when_colorless_sources_present(
    azusa: CardData,
    sample_cards: list[CardData],
    role_tags_all: dict[str, list[RoleTag]],
    cards_by_name: dict[str, CardData],
) -> None:
    """Eldrazi Mimic is included when owned pool has >= C_REQUIREMENT_MIN_SOURCES."""
    mimic = next((c for c in sample_cards if c.name == "Eldrazi Mimic"), None)
    if mimic is None:
        pytest.skip("Eldrazi Mimic not in fixture")

    # Provide enough colorless sources: Sol Ring, Worn Powerstone, Gilded Lotus all add {C}
    colorless_sources = [
        cards_by_name[name]
        for name in ("Sol Ring", "Worn Powerstone", "Gilded Lotus")
        if name in cards_by_name
    ]
    if len(colorless_sources) < C_REQUIREMENT_MIN_SOURCES:
        pytest.skip("Not enough colorless source fixtures for this test")

    pool = DeckCandidatePool().build(
        commander=azusa,
        owned_cards=colorless_sources,
        all_cards=sample_cards,
        role_tags=role_tags_all,
        owned_oracle_ids={c.oracle_id for c in colorless_sources},
    )
    pool_ids = {c.oracle_id for c in pool}
    assert mimic.oracle_id in pool_ids, "Eldrazi Mimic must be included with enough colorless sources"


def test_sol_ring_not_treated_as_c_requirement_card(
    azusa: CardData,
    sample_cards: list[CardData],
    role_tags_all: dict[str, list[RoleTag]],
) -> None:
    """Sol Ring costs {1}, not {C} — it must never be excluded by SC-DECK-010."""
    sol_ring = next((c for c in sample_cards if c.name == "Sol Ring"), None)
    if sol_ring is None:
        pytest.skip("Sol Ring not in fixture")

    pool = DeckCandidatePool().build(
        commander=azusa,
        owned_cards=[],
        all_cards=sample_cards,
        role_tags=role_tags_all,
        owned_oracle_ids=set(),
    )
    pool_ids = {c.oracle_id for c in pool}
    assert sol_ring.oracle_id in pool_ids, "Sol Ring ({1}) must not be excluded by {C}-requirement filter"


def test_c_requirement_threshold_is_configurable() -> None:
    """C_REQUIREMENT_MIN_SOURCES must be a positive integer (allows tuning)."""
    assert isinstance(C_REQUIREMENT_MIN_SOURCES, int)
    assert C_REQUIREMENT_MIN_SOURCES > 0


# =========================================================================
# SC-DECK-011: Card quality replacement pass
# =========================================================================

def _quality_card_data(
    oracle_id: str,
    name: str,
    role: str,
    color_identity: list[str] | None = None,
    type_line: str = "Creature",
    oracle_text: str = "",
    cmc: float = 3.0,
    edhrec_rank: int | None = None,
    rarity: str | None = None,
) -> CardData:
    return CardData(
        id=oracle_id,
        oracle_id=oracle_id,
        name=name,
        color_identity=color_identity or ["G"],
        legalities={"commander": "legal"},
        type_line=type_line,
        oracle_text=oracle_text,
        cmc=cmc,
        edhrec_rank=edhrec_rank,
        rarity=rarity,
    )


def _quality_deck(
    nonlands: list[CardData],
    deck_cards: list[DeckCard],
    scores: dict[str, float] | None = None,
    all_cards_lookup: dict[str, CardData] | None = None,
) -> GeneratedDeck:
    commander = _test_commander()
    forest = _quality_card_data(
        "quality-forest",
        "Forest",
        CardRole.LAND.value,
        type_line="Basic Land — Forest",
        oracle_text="({T}: Add {G}.)",
        cmc=0.0,
    )
    forest_deck_card = _deck_card(
        forest.oracle_id,
        forest.name,
        [CardRole.LAND.value],
        is_owned=True,
    )
    utility_lands = [
        _quality_card_data(
            f"quality-utility-land-{i:02d}",
            f"Quality Utility Land {i:02d}",
            CardRole.LAND.value,
            type_line="Land",
            oracle_text="{T}: Add {G}.",
            cmc=0.0,
        )
        for i in range(78)
    ]
    utility_land_deck_cards = [
        _deck_card(card.oracle_id, card.name, [CardRole.LAND.value])
        for card in utility_lands
    ]
    pool = [*deck_cards, forest_deck_card, *utility_land_deck_cards]
    graph = SynergyGraph()
    graph.build(pool, {}, RoleTagSynergyProvider(), commander.oracle_id, commander.color_identity)
    if scores:
        graph._scores.update(scores)

    lookup = {
        forest.oracle_id: forest,
        commander.oracle_id: commander,
        **{card.oracle_id: card for card in utility_lands},
    }
    lookup.update({card.oracle_id: card for card in nonlands})

    return DeckGenerator().generate(
        commander=commander,
        commander_tags=[],
        candidate_pool=pool,
        role_tags={},
        graph=graph,
        packages=[],
        session_id="quality-replacement",
        quotas=[
            RoleQuota(CardRole.LAND, target_min=98, target_max=98),
        ],
        all_cards_lookup=all_cards_lookup if all_cards_lookup is not None else lookup,
    )


def test_weak_card_is_replaced_by_higher_quality_alternative() -> None:
    weak = _quality_card_data(
        "08c7db90-c0cf-4482-b7ee-bb033e5996d2",
        "Weak Payoff",
        CardRole.PAYOFF.value,
        cmc=6.0,
    )
    strong = _quality_card_data(
        "a2e91c27-6f81-4512-bf20-7a01cb7b6a8e",
        "Strong Payoff",
        CardRole.PAYOFF.value,
        cmc=2.0,
        edhrec_rank=100,
        rarity="rare",
    )
    deck = _quality_deck(
        [weak, strong],
        [
            _deck_card(weak.oracle_id, weak.name, [CardRole.PAYOFF.value]),
            _deck_card(strong.oracle_id, strong.name, [CardRole.PAYOFF.value]),
        ],
    )

    names = {card.name for card in deck.main_deck}
    replacement = next(card for card in deck.main_deck if card.name == "Strong Payoff")
    assert "Weak Payoff" not in names
    assert replacement.selection_reason == "quality replacement for Weak Payoff (PAYOFF)"


def test_strong_synergy_card_is_not_replaced() -> None:
    weak_quality = _quality_card_data("a-synergy-payoff", "Synergy Payoff", CardRole.PAYOFF.value, cmc=6.0)
    strong_quality = _quality_card_data(
        "z-quality-payoff",
        "Quality Payoff",
        CardRole.PAYOFF.value,
        cmc=2.0,
        edhrec_rank=10,
        rarity="rare",
    )
    deck = _quality_deck(
        [weak_quality, strong_quality],
        [
            _deck_card(weak_quality.oracle_id, weak_quality.name, [CardRole.PAYOFF.value]),
            _deck_card(strong_quality.oracle_id, strong_quality.name, [CardRole.PAYOFF.value]),
        ],
        scores={weak_quality.oracle_id: 0.40, strong_quality.oracle_id: 0.0},
    )

    assert any(card.name == "Synergy Payoff" for card in deck.main_deck)


def test_high_quality_card_is_not_replaced() -> None:
    selected = _quality_card_data(
        "a-selected-staple",
        "Selected Staple",
        CardRole.PAYOFF.value,
        cmc=2.0,
        edhrec_rank=5,
        rarity="rare",
    )
    alternative = _quality_card_data(
        "z-alternative-staple",
        "Alternative Staple",
        CardRole.PAYOFF.value,
        cmc=2.0,
        edhrec_rank=1,
        rarity="mythic",
    )
    deck = _quality_deck(
        [selected, alternative],
        [
            _deck_card(selected.oracle_id, selected.name, [CardRole.PAYOFF.value]),
            _deck_card(alternative.oracle_id, alternative.name, [CardRole.PAYOFF.value]),
        ],
    )

    assert any(card.name == "Selected Staple" for card in deck.main_deck)


def test_replacement_requires_score_margin() -> None:
    weak = _quality_card_data("a-weak-margin", "Weak Margin", CardRole.PAYOFF.value, cmc=6.0)
    slight_upgrade = _quality_card_data(
        "z-slight-upgrade",
        "Slight Upgrade",
        CardRole.PAYOFF.value,
        cmc=6.0,
        rarity="rare",
    )
    deck = _quality_deck(
        [weak, slight_upgrade],
        [
            _deck_card(weak.oracle_id, weak.name, [CardRole.PAYOFF.value]),
            _deck_card(slight_upgrade.oracle_id, slight_upgrade.name, [CardRole.PAYOFF.value]),
        ],
    )

    assert any(card.name == "Weak Margin" for card in deck.main_deck)


def test_replacement_prefers_owned_over_unowned_candidate() -> None:
    weak = _quality_card_data("a-weak-owned-choice", "Weak Owned Choice", CardRole.PAYOFF.value, cmc=6.0)
    owned_upgrade = _quality_card_data(
        "b-owned-upgrade",
        "Owned Upgrade",
        CardRole.PAYOFF.value,
        cmc=2.0,
        edhrec_rank=100,
        rarity="rare",
    )
    unowned_upgrade = _quality_card_data(
        "c-unowned-upgrade",
        "Unowned Upgrade",
        CardRole.PAYOFF.value,
        cmc=2.0,
        edhrec_rank=1,
        rarity="mythic",
    )
    deck = _quality_deck(
        [weak, owned_upgrade, unowned_upgrade],
        [
            _deck_card(weak.oracle_id, weak.name, [CardRole.PAYOFF.value]),
            _deck_card(owned_upgrade.oracle_id, owned_upgrade.name, [CardRole.PAYOFF.value], is_owned=True),
            _deck_card(unowned_upgrade.oracle_id, unowned_upgrade.name, [CardRole.PAYOFF.value]),
        ],
    )

    assert any(card.name == "Owned Upgrade" for card in deck.main_deck)
    assert not any(card.name == "Unowned Upgrade" for card in deck.main_deck)


def test_replacement_respects_primary_role_match() -> None:
    weak = _quality_card_data("a-weak-role", "Weak Role", CardRole.PAYOFF.value, cmc=6.0)
    wrong_role = _quality_card_data(
        "z-wrong-role",
        "Wrong Role",
        CardRole.RAMP.value,
        cmc=2.0,
        edhrec_rank=1,
        rarity="mythic",
    )
    deck = _quality_deck(
        [weak, wrong_role],
        [
            _deck_card(weak.oracle_id, weak.name, [CardRole.PAYOFF.value]),
            _deck_card(wrong_role.oracle_id, wrong_role.name, [CardRole.RAMP.value]),
        ],
    )

    assert any(card.name == "Weak Role" for card in deck.main_deck)


def test_replacement_does_not_replace_lands() -> None:
    weak_land = _quality_card_data(
        "a-weak-land",
        "Weak Land",
        CardRole.LAND.value,
        type_line="Land",
        cmc=0.0,
    )
    strong_land = _quality_card_data(
        "z-strong-land",
        "Strong Land",
        CardRole.LAND.value,
        type_line="Land",
        edhrec_rank=1,
        rarity="rare",
        cmc=0.0,
    )
    deck = _quality_deck(
        [weak_land, strong_land],
        [
            _deck_card(weak_land.oracle_id, weak_land.name, [CardRole.LAND.value]),
            _deck_card(strong_land.oracle_id, strong_land.name, [CardRole.LAND.value]),
        ],
    )

    assert any(card.name == "Weak Land" for card in deck.main_deck)


def test_rarity_alone_does_not_win_role_slot() -> None:
    common = _quality_card_data("a-common-payoff", "Common Payoff", CardRole.PAYOFF.value, rarity="common")
    mythic = _quality_card_data("z-mythic-payoff", "Mythic Payoff", CardRole.PAYOFF.value, rarity="mythic")
    deck = _quality_deck(
        [common, mythic],
        [
            _deck_card(common.oracle_id, common.name, [CardRole.PAYOFF.value]),
            _deck_card(mythic.oracle_id, mythic.name, [CardRole.PAYOFF.value]),
        ],
        all_cards_lookup={},
    )

    assert any(card.name == "Common Payoff" for card in deck.main_deck)


def test_expensive_removal_loses_slot_to_beast_within() -> None:
    expensive = _quality_card_data(
        "7d00fb28-ea6c-49a9-b4af-ffb38860a9a7",
        "Expensive Removal",
        CardRole.SPOT_REMOVAL.value,
        type_line="Sorcery",
        oracle_text="Destroy target creature.",
        cmc=6.0,
    )
    beast_within = _quality_card_data(
        "aa000037-0000-4000-0000-000000000037",
        "Beast Within",
        CardRole.SPOT_REMOVAL.value,
        type_line="Instant",
        oracle_text="Destroy target permanent.",
        cmc=3.0,
        rarity="uncommon",
    )
    deck = _quality_deck(
        [expensive, beast_within],
        [
            _deck_card(expensive.oracle_id, expensive.name, [CardRole.SPOT_REMOVAL.value]),
            _deck_card(beast_within.oracle_id, beast_within.name, [CardRole.SPOT_REMOVAL.value]),
        ],
    )

    assert any(card.name == "Beast Within" for card in deck.main_deck)
    assert not any(card.name == "Expensive Removal" for card in deck.main_deck)
