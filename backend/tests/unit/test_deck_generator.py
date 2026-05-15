"""Tests for SC-DECK-002-006: DeckGenerator."""
from __future__ import annotations

import pytest

from app.models.card import CardData
from app.models.deck import DeckCard, GeneratedDeck, PackageCluster
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
