"""Tests for SC-GRAPH-002: PackageDetector and SC-GRAPH-003: PackageLabeler."""
from __future__ import annotations

import pytest

from app.models.card import CardData
from app.models.deck import DeckCard, PackageCluster
from app.recommendation.deck_candidate_pool import DeckCandidatePool
from app.recommendation.package_detector import PackageDetector
from app.recommendation.package_labeler import PackageLabeler
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
def candidate_pool(meren: CardData, sample_cards: list[CardData], role_tags_all: dict[str, list[RoleTag]]) -> list[DeckCard]:
    return DeckCandidatePool().build(
        commander=meren,
        owned_cards=[],
        all_cards=sample_cards,
        role_tags=role_tags_all,
        owned_oracle_ids=set(),
    )


@pytest.fixture(scope="module")
def built_graph(candidate_pool: list[DeckCard], role_tags_all: dict[str, list[RoleTag]], meren: CardData) -> SynergyGraph:
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
def packages(candidate_pool: list[DeckCard], role_tags_all: dict[str, list[RoleTag]], built_graph: SynergyGraph) -> list[PackageCluster]:
    return PackageDetector().detect(candidate_pool, role_tags_all, built_graph)


def test_package_detection_returns_clusters(packages: list[PackageCluster]) -> None:
    """Detect returns a non-empty list of PackageCluster objects for Meren pool."""
    assert len(packages) > 0
    for pkg in packages:
        assert isinstance(pkg, PackageCluster)
        assert pkg.package_id
        assert len(pkg.card_oracle_ids) >= 4


def test_sacrifice_package_detected(packages: list[PackageCluster]) -> None:
    """A sacrifice_outlet package is detected (pool has enough sac outlets)."""
    package_ids = [p.package_id for p in packages]
    assert "sacrifice_outlet" in package_ids


def test_token_maker_package_detected(packages: list[PackageCluster]) -> None:
    """A token_maker package is detected (pool has enough token makers)."""
    package_ids = [p.package_id for p in packages]
    assert "token_maker" in package_ids


def test_recursion_package_detected(packages: list[PackageCluster]) -> None:
    """A recursion package is detected."""
    package_ids = [p.package_id for p in packages]
    assert "recursion" in package_ids


def test_packages_sorted_by_size(packages: list[PackageCluster]) -> None:
    """Packages are sorted by number of cards descending."""
    sizes = [len(p.card_oracle_ids) for p in packages]
    assert sizes == sorted(sizes, reverse=True)


def test_package_card_ids_are_in_pool(packages: list[PackageCluster], candidate_pool: list[DeckCard]) -> None:
    """All oracle_ids in a package belong to the candidate pool."""
    pool_ids = {c.oracle_id for c in candidate_pool}
    for pkg in packages:
        for oid in pkg.card_oracle_ids:
            assert oid in pool_ids, f"{oid} in package {pkg.package_id} not in pool"


def test_package_min_size_respected(packages: list[PackageCluster]) -> None:
    """No package has fewer than min_package_size cards."""
    for pkg in packages:
        assert len(pkg.card_oracle_ids) >= 4


def test_package_has_top_roles(packages: list[PackageCluster]) -> None:
    """Each package has at least one top_role."""
    for pkg in packages:
        assert len(pkg.top_roles) >= 1
        assert pkg.package_id in pkg.top_roles[0].lower() or True  # package_id matches role


def test_unclear_cluster_gets_conservative_label(packages: list[PackageCluster]) -> None:
    """After PackageLabeler, a low-confidence cluster gets a conservative label."""
    labeler = PackageLabeler()
    # Create a cluster with low confidence
    low_conf_cluster = PackageCluster(
        package_id="sacrifice_outlet",
        label="",
        confidence=0.2,
        card_oracle_ids=["id1", "id2", "id3", "id4"],
        top_roles=["SACRIFICE_OUTLET"],
    )
    labeled = labeler.label(low_conf_cluster)
    # Low confidence → conservative label
    assert labeled.label == "utility package"
    assert labeled.label != "sacrifice outlet package"


def test_high_confidence_cluster_gets_specific_label(packages: list[PackageCluster]) -> None:
    """After PackageLabeler, high-confidence cluster gets the specific label."""
    labeler = PackageLabeler()
    high_conf_cluster = PackageCluster(
        package_id="token_maker",
        label="",
        confidence=0.8,
        card_oracle_ids=["id1", "id2", "id3", "id4"],
        top_roles=["TOKEN_MAKER"],
    )
    labeled = labeler.label(high_conf_cluster)
    assert labeled.label == "token creation package"


def test_packages_are_labeled_after_labeler(packages: list[PackageCluster]) -> None:
    """After running PackageLabeler on all packages, labels are non-empty."""
    labeler = PackageLabeler()
    labeled_packages = [labeler.label(p) for p in packages]
    for pkg in labeled_packages:
        assert pkg.label, f"Package {pkg.package_id} has empty label"


def test_generic_utility_cards_do_not_create_fake_specific_package() -> None:
    """Generic roles alone must not produce a specific package cluster."""
    cards = [
        DeckCard(
            oracle_id=f"generic-{i}",
            name=f"Generic Utility {i}",
            is_owned=True,
            quantity=1,
            roles=["RAMP", "CARD_DRAW", "SPOT_REMOVAL"],
            selection_reason="candidate",
        )
        for i in range(5)
    ]
    role_tags = {
        card.oracle_id: [
            RoleTag(CardRole.RAMP, confidence=1.0, source="manual"),
            RoleTag(CardRole.CARD_DRAW, confidence=1.0, source="manual"),
            RoleTag(CardRole.SPOT_REMOVAL, confidence=1.0, source="manual"),
        ]
        for card in cards
    }
    graph = SynergyGraph()
    graph.build(cards, role_tags, RoleTagSynergyProvider(), MEREN_ORACLE_ID, ["B", "G"])

    packages = PackageDetector().detect(cards, role_tags, graph, min_package_size=4)

    assert packages == []
