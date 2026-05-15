"""Tests for SC-GRAPH-003: PackageLabeler."""
from __future__ import annotations

import pytest

from app.models.deck import PackageCluster
from app.recommendation.package_labeler import (
    CONSERVATIVE_LABELS,
    ROLE_TO_LABEL,
    PackageLabeler,
)


def _make_cluster(
    package_id: str,
    top_roles: list[str],
    confidence: float = 0.7,
    num_cards: int = 5,
) -> PackageCluster:
    return PackageCluster(
        package_id=package_id,
        label="",
        confidence=confidence,
        card_oracle_ids=[f"card-{i}" for i in range(num_cards)],
        top_roles=top_roles,
    )


def test_package_label_from_role_tags_aristocrats() -> None:
    """ARISTOCRATS_SYNERGY role → 'sacrifice/aristocrats package' for high confidence."""
    labeler = PackageLabeler()
    cluster = _make_cluster("aristocrats_synergy", ["ARISTOCRATS_SYNERGY"], confidence=0.7)
    labeled = labeler.label(cluster)
    assert labeled.label == "sacrifice/aristocrats package"


def test_package_label_from_role_tags_landfall() -> None:
    """LANDFALL_SYNERGY role → 'landfall package' for high confidence."""
    labeler = PackageLabeler()
    cluster = _make_cluster("landfall_synergy", ["LANDFALL_SYNERGY"], confidence=0.6)
    labeled = labeler.label(cluster)
    assert labeled.label == "landfall package"


def test_package_label_from_role_tags_recursion() -> None:
    """RECURSION role → 'graveyard recursion package' for high confidence."""
    labeler = PackageLabeler()
    cluster = _make_cluster("recursion", ["RECURSION"], confidence=0.65)
    labeled = labeler.label(cluster)
    assert labeled.label == "graveyard recursion package"


def test_package_label_from_role_tags_token_maker() -> None:
    """TOKEN_MAKER role → 'token creation package' for high confidence."""
    labeler = PackageLabeler()
    cluster = _make_cluster("token_maker", ["TOKEN_MAKER"], confidence=0.75)
    labeled = labeler.label(cluster)
    assert labeled.label == "token creation package"


def test_low_confidence_package_marked_utility() -> None:
    """SACRIFICE_OUTLET with confidence < 0.5 → conservative 'utility package'."""
    labeler = PackageLabeler()
    cluster = _make_cluster("sacrifice_outlet", ["SACRIFICE_OUTLET"], confidence=0.3)
    labeled = labeler.label(cluster)
    assert labeled.label == "utility package"
    assert labeled.label != "sacrifice outlet package"


def test_low_confidence_aristocrats_gets_conservative() -> None:
    """ARISTOCRATS_SYNERGY with confidence < 0.5 → 'black value package'."""
    labeler = PackageLabeler()
    cluster = _make_cluster("aristocrats_synergy", ["ARISTOCRATS_SYNERGY"], confidence=0.4)
    labeled = labeler.label(cluster)
    assert labeled.label == "black value package"


def test_low_confidence_landfall_gets_conservative() -> None:
    """LANDFALL_SYNERGY with confidence < 0.5 → 'green value package'."""
    labeler = PackageLabeler()
    cluster = _make_cluster("landfall_synergy", ["LANDFALL_SYNERGY"], confidence=0.1)
    labeled = labeler.label(cluster)
    assert labeled.label == "green value package"


def test_package_label_explanation_returned() -> None:
    """label() returns a PackageCluster with a non-empty label."""
    labeler = PackageLabeler()
    cluster = _make_cluster("recursion", ["RECURSION"], confidence=0.8)
    labeled = labeler.label(cluster)
    assert labeled.label
    assert isinstance(labeled.label, str)
    assert len(labeled.label) > 0


def test_label_preserves_other_fields() -> None:
    """label() preserves package_id, confidence, card_oracle_ids, top_roles."""
    labeler = PackageLabeler()
    cluster = _make_cluster("token_maker", ["TOKEN_MAKER"], confidence=0.9, num_cards=6)
    labeled = labeler.label(cluster)
    assert labeled.package_id == "token_maker"
    assert labeled.confidence == 0.9
    assert len(labeled.card_oracle_ids) == 6
    assert labeled.top_roles == ["TOKEN_MAKER"]


def test_exact_confidence_threshold() -> None:
    """confidence == 0.5 should use the specific (non-conservative) label."""
    labeler = PackageLabeler()
    cluster = _make_cluster("recursion", ["RECURSION"], confidence=0.5)
    labeled = labeler.label(cluster)
    assert labeled.label == "graveyard recursion package"


def test_all_role_labels_defined() -> None:
    """All roles in ROLE_TO_LABEL also have a CONSERVATIVE_LABELS entry."""
    for role_key in ROLE_TO_LABEL:
        assert role_key in CONSERVATIVE_LABELS, f"{role_key} missing from CONSERVATIVE_LABELS"
