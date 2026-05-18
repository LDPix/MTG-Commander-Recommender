"""Tests for SC-DECK-014 package density enforcement."""
from __future__ import annotations

from app.models.deck import DeckCard, PackageCluster
from app.recommendation.package_density import (
    PACKAGE_STATUS_ACTIVE,
    PACKAGE_STATUS_INACTIVE_BAD_COMPOSITION,
    PACKAGE_STATUS_INACTIVE_UNRELATED,
    active_package_ids_for_deck,
    count_package_core_members_in_deck,
    count_package_members_in_deck,
    is_orphan,
    package_activation_status,
    package_core_ids_for_deck,
    package_density_threshold,
    package_is_loose_value,
    package_repair_status,
    packages_with_activation_status,
)


def _pkg(
    package_id: str,
    top_role: str,
    card_oracle_ids: list[str],
) -> PackageCluster:
    return PackageCluster(
        package_id=package_id,
        label=package_id,
        confidence=0.8,
        card_oracle_ids=card_oracle_ids,
        top_roles=[top_role],
    )


def _card(
    oracle_id: str,
    roles: list[str],
    package_ids: list[str] | None = None,
    quantity: int = 1,
) -> DeckCard:
    return DeckCard(
        oracle_id=oracle_id,
        name=oracle_id,
        is_owned=False,
        quantity=quantity,
        roles=roles,
        package_ids=package_ids or [],
        selection_reason="test",
    )


# ---------------------------------------------------------------------------
# package_density_threshold
# ---------------------------------------------------------------------------

def test_package_density_threshold_aristocrats_is_6() -> None:
    pkg = _pkg("aristocrats_synergy", "ARISTOCRATS_SYNERGY", [])
    assert package_density_threshold(pkg) == 6


def test_package_density_threshold_sacrifice_outlet_is_4() -> None:
    pkg = _pkg("sacrifice_outlet", "SACRIFICE_OUTLET", [])
    assert package_density_threshold(pkg) == 4


def test_package_density_threshold_default_is_5() -> None:
    pkg = _pkg("unknown_pkg", "UNKNOWN_ROLE", [])
    assert package_density_threshold(pkg) == 5


def test_package_density_threshold_empty_top_roles_uses_default() -> None:
    pkg = PackageCluster(
        package_id="no-role",
        label="no role",
        confidence=0.5,
        card_oracle_ids=[],
        top_roles=[],
    )
    assert package_density_threshold(pkg) == 5


# ---------------------------------------------------------------------------
# SC-GRAPH-004 loose value labels
# ---------------------------------------------------------------------------

def test_landfall_conservative_label_not_loose_value() -> None:
    pkg = PackageCluster(
        package_id="landfall-low-confidence",
        label="green value package",
        confidence=0.4,
        card_oracle_ids=[],
        top_roles=["LANDFALL_SYNERGY"],
    )

    assert package_is_loose_value(pkg) is False


def test_aristocrats_conservative_label_not_loose_value() -> None:
    pkg = PackageCluster(
        package_id="aristocrats-low-confidence",
        label="black value package",
        confidence=0.4,
        card_oracle_ids=[],
        top_roles=["ARISTOCRATS_SYNERGY"],
    )

    assert package_is_loose_value(pkg) is False


def test_treasure_package_still_loose_value() -> None:
    pkg = _pkg("treasure-engine", "TOKEN_MAKER", [])
    pkg = pkg.model_copy(update={"label": "treasure generation"})

    assert package_is_loose_value(pkg) is True


def test_food_package_still_loose_value() -> None:
    pkg = _pkg("food-engine", "TOKEN_MAKER", [])
    pkg = pkg.model_copy(update={"label": "food production package"})

    assert package_is_loose_value(pkg) is True


def test_artifact_value_package_still_loose_value() -> None:
    pkg = _pkg("artifact-engine", "RECURSION", [])
    pkg = pkg.model_copy(update={"label": "artifact value engine"})

    assert package_is_loose_value(pkg) is True


# ---------------------------------------------------------------------------
# count_package_members_in_deck
# ---------------------------------------------------------------------------

def test_count_package_members_in_deck_counts_correctly() -> None:
    pkg = _pkg("p1", "SACRIFICE_OUTLET", ["A", "B", "C"])
    deck = [_card("A", ["SACRIFICE_OUTLET"]), _card("C", ["SACRIFICE_OUTLET"])]
    assert count_package_members_in_deck(deck, pkg) == 2


def test_count_package_members_in_deck_zero_when_none_present() -> None:
    pkg = _pkg("p1", "SACRIFICE_OUTLET", ["A", "B"])
    deck = [_card("X", ["RAMP"])]
    assert count_package_members_in_deck(deck, pkg) == 0


def test_count_package_members_in_deck_all_present() -> None:
    pkg = _pkg("p1", "TOKEN_MAKER", ["A", "B", "C", "D"])
    deck = [_card(oid, ["TOKEN_MAKER"]) for oid in ["A", "B", "C", "D"]]
    assert count_package_members_in_deck(deck, pkg) == 4


# ---------------------------------------------------------------------------
# is_orphan
# ---------------------------------------------------------------------------

def test_is_orphan_true_when_all_packages_underfilled_no_infra_role() -> None:
    card = _card("orphan-1", ["SACRIFICE_OUTLET"], package_ids=["pkg-a"])
    underfilled = frozenset({"pkg-a"})
    assert is_orphan(card, underfilled) is True


def test_is_orphan_false_when_card_has_infrastructure_role() -> None:
    # RAMP is in INFRASTRUCTURE_ROLES → never an orphan
    card = _card("infra-1", ["SACRIFICE_OUTLET", "RAMP"], package_ids=["pkg-a"])
    underfilled = frozenset({"pkg-a"})
    assert is_orphan(card, underfilled) is False


def test_is_orphan_false_when_one_package_is_active() -> None:
    # card is in two packages; only one is underfilled
    card = _card("multi-pkg", ["TOKEN_MAKER"], package_ids=["pkg-a", "pkg-b"])
    underfilled = frozenset({"pkg-a"})  # pkg-b is active
    assert is_orphan(card, underfilled) is False


def test_is_orphan_false_for_quantity_gt_1() -> None:
    # Basic lands have quantity > 1 and should never be orphans
    card = _card("forest", ["LAND"], package_ids=["pkg-a"], quantity=20)
    underfilled = frozenset({"pkg-a"})
    assert is_orphan(card, underfilled) is False


def test_is_orphan_false_when_no_package_ids() -> None:
    # Card not in any package → cannot be orphan
    card = _card("no-pkg", ["SACRIFICE_OUTLET"], package_ids=[])
    underfilled = frozenset({"pkg-a"})
    assert is_orphan(card, underfilled) is False


# ---------------------------------------------------------------------------
# package-core repair protection
# ---------------------------------------------------------------------------

def test_inactive_package_members_not_package_core() -> None:
    pkg = _pkg("treasure", "TOKEN_MAKER", ["A", "B", "C", "D"])
    deck = [_card("A", ["WIN_CONDITION"], package_ids=["treasure"])]

    active_ids = active_package_ids_for_deck(deck, [pkg])
    core_ids = package_core_ids_for_deck(deck, [pkg], active_package_ids=active_ids)

    assert active_ids == frozenset()
    assert core_ids == frozenset()
    assert package_repair_status(deck[0], active_ids, core_ids) == (
        "removable_incidental_package_member"
    )


def test_package_core_ids_only_active_package_members() -> None:
    pkg = _pkg("landfall", "LANDFALL_SYNERGY", ["A", "B", "C", "D", "E"])
    deck = [
        _card(oid, ["LANDFALL_SYNERGY"], package_ids=["landfall"])
        for oid in ["A", "B", "C", "D", "E"]
    ]

    active_ids = active_package_ids_for_deck(deck, [pkg])
    core_ids = package_core_ids_for_deck(deck, [pkg], active_package_ids=active_ids)

    assert active_ids == frozenset({"landfall"})
    assert core_ids == frozenset({"A", "B", "C", "D", "E"})
    assert package_repair_status(deck[0], active_ids, core_ids) == (
        "protected_package_core"
    )


def test_package_core_status_exposes_active_but_noncore_member() -> None:
    pkg = _pkg("generic-value", "TOKEN_MAKER", ["A", "B", "C", "D", "E", "F"])
    deck = [
        *[_card(oid, ["TOKEN_MAKER"], package_ids=["generic-value"]) for oid in ["A", "B", "C", "D"]],
        _card("E", ["WIN_CONDITION"], package_ids=["generic-value"]),
        _card("F", ["FILLER"], package_ids=["generic-value"]),
    ]

    active_ids = active_package_ids_for_deck(deck, [pkg])
    core_ids = package_core_ids_for_deck(deck, [pkg], active_package_ids=active_ids)

    assert active_ids == frozenset({"generic-value"})
    assert "F" not in core_ids
    assert package_repair_status(deck[-1], active_ids, core_ids) == (
        "removable_active_package_member"
    )


# ---------------------------------------------------------------------------
# SC-DECK-025 commander-relevant activation
# ---------------------------------------------------------------------------

def test_dense_unrelated_token_package_not_active_for_nissa() -> None:
    pkg = _pkg("token-pile", "TOKEN_MAKER", ["A", "B", "C", "D"])
    deck = [
        _card(oid, ["TOKEN_MAKER"], package_ids=["token-pile"])
        for oid in ["A", "B", "C", "D"]
    ]

    status = package_activation_status(
        deck,
        pkg,
        primary_plan="landfall",
        enforce_commander_relevance=True,
    )
    active_ids = active_package_ids_for_deck(
        deck,
        [pkg],
        primary_plan="landfall",
        enforce_commander_relevance=True,
    )

    assert status == PACKAGE_STATUS_INACTIVE_UNRELATED
    assert active_ids == frozenset()


def test_dense_unrelated_sacrifice_package_not_active_for_toluz() -> None:
    pkg = _pkg("sacrifice-pile", "SACRIFICE_OUTLET", ["A", "B", "C", "D"])
    deck = [
        _card(oid, ["SACRIFICE_OUTLET"], package_ids=["sacrifice-pile"])
        for oid in ["A", "B", "C", "D"]
    ]

    status = package_activation_status(
        deck,
        pkg,
        primary_plan="connive",
        enforce_commander_relevance=True,
    )

    assert status == PACKAGE_STATUS_INACTIVE_UNRELATED


def test_food_sacrifice_package_active_for_greta_when_composition_viable() -> None:
    pkg = PackageCluster(
        package_id="food-sacrifice",
        label="food sacrifice package",
        confidence=0.8,
        card_oracle_ids=["A", "B", "C", "D"],
        top_roles=["SACRIFICE_OUTLET", "TOKEN_MAKER", "WIN_CONDITION"],
    )
    deck = [
        _card("A", ["SACRIFICE_OUTLET"], package_ids=["food-sacrifice"]),
        _card("B", ["TOKEN_MAKER"], package_ids=["food-sacrifice"]),
        _card("C", ["WIN_CONDITION"], package_ids=["food-sacrifice"]),
        _card("D", ["LIFEGAIN"], package_ids=["food-sacrifice"]),
    ]

    status = package_activation_status(
        deck,
        pkg,
        primary_plan="food-sacrifice",
        commander_supports_loose_value=True,
        enforce_commander_relevance=True,
    )

    assert status == PACKAGE_STATUS_ACTIVE


def test_active_package_requires_enabler_payoff_mix() -> None:
    pkg = _pkg("same-tag-token-pile", "TOKEN_MAKER", ["A", "B", "C", "D"])
    deck = [
        _card(oid, ["TOKEN_MAKER"], package_ids=["same-tag-token-pile"])
        for oid in ["A", "B", "C", "D"]
    ]

    status = package_activation_status(
        deck,
        pkg,
        primary_plan="tokens",
        enforce_commander_relevance=True,
    )

    assert status == PACKAGE_STATUS_INACTIVE_BAD_COMPOSITION


def test_package_breakdown_displays_activation_status() -> None:
    pkg = _pkg("landfall", "LANDFALL_SYNERGY", ["A", "B", "C", "D", "E"])
    deck = [
        _card("A", ["LANDFALL_SYNERGY"], package_ids=["landfall"]),
        _card("B", ["RAMP"], package_ids=["landfall"]),
        _card("C", ["LANDFALL_SYNERGY"], package_ids=["landfall"]),
        _card("D", ["RAMP"], package_ids=["landfall"]),
        _card("E", ["WIN_CONDITION"], package_ids=["landfall"]),
    ]

    [status_pkg] = packages_with_activation_status(
        [pkg],
        deck,
        primary_plan="landfall",
        enforce_commander_relevance=True,
    )

    assert status_pkg.activation_status == PACKAGE_STATUS_ACTIVE
    assert status_pkg.selected_count == 5
    assert status_pkg.raw_selected_count == 5


def test_package_selected_count_uses_assigned_core_members() -> None:
    pkg = _pkg("token-pile", "TOKEN_MAKER", ["A", "B", "C", "D"])
    deck = [
        _card("A", ["TOKEN_MAKER"], package_ids=["token-pile"]).model_copy(
            update={"assigned_role": "TOKEN_MAKER"}
        ),
        _card("B", ["TOKEN_MAKER", "CARD_DRAW"], package_ids=["token-pile"]).model_copy(
            update={"assigned_role": "CARD_DRAW"}
        ),
        _card("C", ["WIN_CONDITION"], package_ids=["token-pile"]).model_copy(
            update={"assigned_role": "WIN_CONDITION"}
        ),
        _card("D", ["FILLER"], package_ids=["token-pile"]),
    ]

    assert count_package_members_in_deck(deck, pkg) == 4
    assert count_package_core_members_in_deck(deck, pkg) == 2


def test_package_breakdown_exposes_core_vs_raw_counts() -> None:
    pkg = _pkg("token-pile", "TOKEN_MAKER", ["A", "B", "C", "D"])
    deck = [
        _card("A", ["TOKEN_MAKER"], package_ids=["token-pile"]).model_copy(
            update={"assigned_role": "TOKEN_MAKER"}
        ),
        _card("B", ["TOKEN_MAKER", "CARD_DRAW"], package_ids=["token-pile"]).model_copy(
            update={"assigned_role": "CARD_DRAW"}
        ),
        _card("C", ["WIN_CONDITION"], package_ids=["token-pile"]).model_copy(
            update={"assigned_role": "WIN_CONDITION"}
        ),
        _card("D", ["FILLER"], package_ids=["token-pile"]),
    ]

    [status_pkg] = packages_with_activation_status(
        [pkg],
        deck,
        primary_plan="tokens",
        enforce_commander_relevance=True,
    )

    assert status_pkg.selected_count == 2
    assert status_pkg.raw_selected_count == 4
    assert status_pkg.activation_status == "underfilled"
