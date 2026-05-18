"""SC-DECK-014: Package density enforcement for the final deck."""
from __future__ import annotations

from collections import defaultdict

from app.models.deck import DeckCard, PackageCluster

# Minimum package member count required in the final deck to consider a
# package "active." Packages below this threshold are underfilled.
# Keyed by the top_role of the package (matches SPECIFIC_ROLES values).
PACKAGE_DENSITY_THRESHOLDS: dict[str, int] = {
    "ARISTOCRATS_SYNERGY": 6,  # needs enablers + payoffs to function
    "SACRIFICE_OUTLET": 4,
    "TOKEN_MAKER": 4,
    "LANDFALL_SYNERGY": 5,
    "BLINK_SYNERGY": 5,
    "SPELLSLINGER_SYNERGY": 5,
    "TRIBAL_SUPPORT": 5,
    "RECURSION": 4,
}
_DEFAULT_DENSITY_THRESHOLD: int = 5
_LOOSE_REJECTION_MIN_CARDS: int = 3

# Roles that provide generic value independent of package activity.
INFRASTRUCTURE_ROLES: frozenset[str] = frozenset({
    "RAMP",
    "CARD_DRAW",
    "CARD_SELECTION",
    "SPOT_REMOVAL",
    "BOARD_WIPE",
    "PROTECTION",
    "TUTOR",
})

# Roles that make a selected card central to an active package. Infrastructure
# roles above are intentionally excluded because they can stand on their own.
PACKAGE_CORE_ROLES: frozenset[str] = frozenset({
    "ARISTOCRATS_SYNERGY",
    "SACRIFICE_OUTLET",
    "TOKEN_MAKER",
    "LANDFALL_SYNERGY",
    "BLINK_SYNERGY",
    "SPELLSLINGER_SYNERGY",
    "TRIBAL_SUPPORT",
    "TRIBAL_LORD",
    "RECURSION",
    "ENABLER",
    "COMBO_PIECE",
    "WIN_CONDITION",
})

PACKAGE_STATUS_DETECTED = "detected"
PACKAGE_STATUS_UNDERFILLED = "underfilled"
PACKAGE_STATUS_INACTIVE_UNRELATED = "inactive_unrelated"
PACKAGE_STATUS_INACTIVE_BAD_COMPOSITION = "inactive_bad_composition"
PACKAGE_STATUS_REJECTED_LOOSE = "rejected_loose"
PACKAGE_STATUS_ACTIVE = "active"

PLAN_PACKAGE_ROLES: dict[str, frozenset[str]] = {
    "landfall": frozenset({"LANDFALL_SYNERGY", "RAMP"}),
    "aristocrats": frozenset({
        "ARISTOCRATS_SYNERGY",
        "SACRIFICE_OUTLET",
        "TOKEN_MAKER",
        "RECURSION",
    }),
    "food-sacrifice": frozenset({
        "ARISTOCRATS_SYNERGY",
        "SACRIFICE_OUTLET",
        "TOKEN_MAKER",
        "LIFEGAIN",
    }),
    "connive": frozenset({"GRAVEYARD_SYNERGY", "RECURSION"}),
    "spellslinger": frozenset({"SPELLSLINGER_SYNERGY"}),
    "blink": frozenset({"BLINK_SYNERGY"}),
    "tribal": frozenset({"TRIBAL_SUPPORT", "TRIBAL_LORD"}),
    "artifacts": frozenset({"ENABLER", "WIN_CONDITION"}),
    "tokens": frozenset({"TOKEN_MAKER", "ARISTOCRATS_SYNERGY"}),
}

PLAN_PACKAGE_TEXT_HINTS: dict[str, tuple[str, ...]] = {
    "landfall": ("landfall", "land", "lands", "ramp"),
    "aristocrats": ("aristocrat", "sacrifice", "dies", "graveyard", "token"),
    "food-sacrifice": ("food", "sacrifice", "lifegain", "life gain"),
    "connive": ("connive", "discard", "looting", "graveyard"),
    "spellslinger": ("spellslinger", "instant", "sorcery"),
    "blink": ("blink", "etb", "enters the battlefield"),
    "tribal": ("tribal", "lord"),
    "artifacts": ("artifact",),
    "tokens": ("token", "populate"),
}

LOOSE_VALUE_TERMS: tuple[str, ...] = (
    "treasure",
    "clue",
    "food",
    "map",
    "artifact token",
    "artifact value",
)

COMPOSITION_ENABLER_ROLES: frozenset[str] = frozenset({
    "SACRIFICE_OUTLET",
    "TOKEN_MAKER",
    "ENABLER",
    "RECURSION",
    "GRAVEYARD_SYNERGY",
    "LIFEGAIN",
    "RAMP",
    "CARD_SELECTION",
})

COMPOSITION_OUTCOME_ROLES: frozenset[str] = frozenset({
    "WIN_CONDITION",
    "ARISTOCRATS_SYNERGY",
    "LANDFALL_SYNERGY",
    "SPELLSLINGER_SYNERGY",
    "TRIBAL_LORD",
    "COMBO_PIECE",
})


PACKAGE_COMPONENT_TEMPLATES: dict[str, dict[str, int]] = {
    "TOKEN_MAKER": {
        "TOKEN_MAKER": 3,
        "SACRIFICE_OUTLET": 1,
    },
    "ARISTOCRATS_SYNERGY": {
        "SACRIFICE_OUTLET": 2,
        "ARISTOCRATS_SYNERGY": 3,
        "TOKEN_MAKER": 1,
    },
    "LANDFALL_SYNERGY": {
        "LANDFALL_SYNERGY": 2,
        "RAMP": 2,
    },
    "BLINK_SYNERGY": {
        "BLINK_SYNERGY": 2,
    },
    "SACRIFICE_OUTLET": {
        "SACRIFICE_OUTLET": 2,
        "TOKEN_MAKER": 1,
    },
    "SPELLSLINGER_SYNERGY": {
        "SPELLSLINGER_SYNERGY": 3,
        "CARD_DRAW": 2,
    },
    "RECURSION": {
        "RECURSION": 2,
    },
}


def package_density_threshold(package: PackageCluster) -> int:
    """Return the minimum deck-member count for this package to be active."""
    top_role = package.top_roles[0] if package.top_roles else ""
    return PACKAGE_DENSITY_THRESHOLDS.get(top_role, _DEFAULT_DENSITY_THRESHOLD)


def count_package_members_in_deck(
    main_deck: list[DeckCard],
    package: PackageCluster,
) -> int:
    """Count how many of this package's card_oracle_ids appear in main_deck."""
    deck_ids = {c.oracle_id for c in main_deck}
    return sum(1 for oid in package.card_oracle_ids if oid in deck_ids)


def count_package_core_members_in_deck(
    main_deck: list[DeckCard],
    package: PackageCluster,
) -> int:
    """Count selected package members with assigned/core package participation."""
    deck_by_id = {c.oracle_id: c for c in main_deck}
    return sum(
        1
        for oid in package.card_oracle_ids
        if (card := deck_by_id.get(oid)) is not None
        and card_counts_as_package_core(card, package)
    )


def card_counts_as_package_core(card: DeckCard, package: PackageCluster) -> bool:
    package_roles = set(package.top_roles)
    core_roles = PACKAGE_CORE_ROLES | COMPOSITION_ENABLER_ROLES | COMPOSITION_OUTCOME_ROLES
    if card.assigned_role is not None:
        return card.assigned_role in package_roles or card.assigned_role in core_roles
    return bool(package_roles.intersection(card.roles)) or bool(
        core_roles.intersection(card.roles)
    )


def is_orphan(card: DeckCard, underfilled_package_ids: frozenset[str]) -> bool:
    """Return True when a card is isolated in underfilled packages with no infra role."""
    if card.quantity != 1:
        return False
    if not card.package_ids:
        return False
    if any(role in INFRASTRUCTURE_ROLES for role in card.roles):
        return False
    # Orphan only if ALL of its packages are underfilled
    return all(pkg_id in underfilled_package_ids for pkg_id in card.package_ids)


def active_package_ids_for_deck(
    main_deck: list[DeckCard],
    packages: list[PackageCluster],
    forced_package_ids: frozenset[str] = frozenset(),
    primary_plan: str | None = None,
    commander_supports_loose_value: bool = False,
    enforce_commander_relevance: bool = False,
) -> frozenset[str]:
    """Return packages that are activation-valid, or explicitly forced, in this deck."""
    active_ids = set(forced_package_ids)
    for package in packages:
        status = package_activation_status(
            main_deck=main_deck,
            package=package,
            forced_package_ids=forced_package_ids,
            primary_plan=primary_plan,
            commander_supports_loose_value=commander_supports_loose_value,
            enforce_commander_relevance=enforce_commander_relevance,
        )
        if status == PACKAGE_STATUS_ACTIVE:
            active_ids.add(package.package_id)
    return frozenset(active_ids)


def package_activation_status(
    main_deck: list[DeckCard],
    package: PackageCluster,
    forced_package_ids: frozenset[str] = frozenset(),
    primary_plan: str | None = None,
    commander_supports_loose_value: bool = False,
    enforce_commander_relevance: bool = False,
) -> str:
    """Return the final activation status for a package in a selected deck."""
    selected_count = count_package_core_members_in_deck(main_deck, package)
    if package.package_id in forced_package_ids:
        return PACKAGE_STATUS_ACTIVE
    if selected_count == 0:
        return PACKAGE_STATUS_DETECTED
    if not enforce_commander_relevance and primary_plan is None:
        if selected_count < package_density_threshold(package):
            return PACKAGE_STATUS_UNDERFILLED
        return PACKAGE_STATUS_ACTIVE
    if (
        package_is_loose_value(package)
        and selected_count >= _LOOSE_REJECTION_MIN_CARDS
        and not commander_supports_loose_value
    ):
        return PACKAGE_STATUS_REJECTED_LOOSE
    if selected_count < package_density_threshold(package):
        return PACKAGE_STATUS_UNDERFILLED

    if package_is_loose_value(package) and not commander_supports_loose_value:
        return PACKAGE_STATUS_REJECTED_LOOSE
    if enforce_commander_relevance:
        if primary_plan is None:
            return PACKAGE_STATUS_INACTIVE_UNRELATED
        if not package_relevant_to_plan(package, primary_plan):
            return PACKAGE_STATUS_INACTIVE_UNRELATED
    if not package_meets_component_template(main_deck, package):
        return PACKAGE_STATUS_INACTIVE_BAD_COMPOSITION
    return PACKAGE_STATUS_ACTIVE


def packages_with_activation_status(
    packages: list[PackageCluster],
    main_deck: list[DeckCard],
    primary_plan: str | None,
    commander_supports_loose_value: bool = False,
    forced_package_ids: frozenset[str] = frozenset(),
    enforce_commander_relevance: bool = True,
) -> list[PackageCluster]:
    """Return packages annotated with selected count and activation status."""
    return [
        package.model_copy(
            update={
                "raw_selected_count": count_package_members_in_deck(main_deck, package),
                "selected_count": count_package_core_members_in_deck(main_deck, package),
                "activation_status": package_activation_status(
                    main_deck=main_deck,
                    package=package,
                    forced_package_ids=forced_package_ids,
                    primary_plan=primary_plan,
                    commander_supports_loose_value=commander_supports_loose_value,
                    enforce_commander_relevance=enforce_commander_relevance,
                ),
            }
        )
        for package in packages
    ]


def package_is_loose_value(package: PackageCluster) -> bool:
    text = _package_text(package)
    return any(term in text for term in LOOSE_VALUE_TERMS)


def package_relevant_to_plan(package: PackageCluster, primary_plan: str) -> bool:
    text = _package_text(package)
    if primary_plan.replace("-", " ") in text:
        return True
    if any(hint in text for hint in PLAN_PACKAGE_TEXT_HINTS.get(primary_plan, ())):
        return True

    top_roles = set(package.top_roles)
    plan_roles = PLAN_PACKAGE_ROLES.get(primary_plan, frozenset())
    if primary_plan == "connive":
        return bool(top_roles.intersection(plan_roles)) or any(
            hint in text for hint in ("connive", "discard", "looting", "graveyard")
        )
    if primary_plan == "landfall":
        return bool(top_roles.intersection(plan_roles)) or any(
            hint in text for hint in ("landfall", "land", "lands")
        )
    return bool(top_roles.intersection(plan_roles))


def package_meets_component_template(
    main_deck: list[DeckCard],
    package: PackageCluster,
) -> bool:
    if not package.top_roles:
        return True

    deck_by_id = {c.oracle_id: c for c in main_deck}
    role_counts: dict[str, int] = defaultdict(int)
    for oid in package.card_oracle_ids:
        card = deck_by_id.get(oid)
        if card is not None:
            for role in card.roles:
                role_counts[role] += 1

    for top_role in package.top_roles:
        template = PACKAGE_COMPONENT_TEMPLATES.get(top_role)
        if template is None:
            return True  # role with no template = no component requirement
        if all(role_counts.get(r, 0) >= count for r, count in template.items()):
            return True  # this template is satisfied

    return False


def package_has_viable_composition(
    main_deck: list[DeckCard],
    package: PackageCluster,
) -> bool:
    """Deprecated: use package_meets_component_template()."""
    return package_meets_component_template(main_deck, package)


def _package_text(package: PackageCluster) -> str:
    return " ".join([package.package_id, package.label, *package.top_roles]).replace(
        "_", " "
    ).lower()


def package_core_ids_for_deck(
    main_deck: list[DeckCard],
    packages: list[PackageCluster],
    active_package_ids: frozenset[str] | None = None,
    forced_package_ids: frozenset[str] = frozenset(),
) -> frozenset[str]:
    """Return selected cards protected as package core during repair passes.

    Package membership alone is not protection. A selected card is core only
    when it belongs to an active/forced package and is either package-defining
    by role or density-critical because that package is exactly at threshold.
    """
    active_ids = (
        active_package_ids
        if active_package_ids is not None
        else active_package_ids_for_deck(main_deck, packages, forced_package_ids)
    )
    if not active_ids:
        return frozenset()

    deck_by_id = {card.oracle_id: card for card in main_deck}
    core_ids: set[str] = set()
    for package in packages:
        if package.package_id not in active_ids:
            continue

        package_deck_ids = [
            oid for oid in package.card_oracle_ids if oid in deck_by_id
        ]
        threshold = package_density_threshold(package)
        density_critical = (
            package.package_id in forced_package_ids
            or len(package_deck_ids) <= threshold
        )

        for oracle_id in package_deck_ids:
            card = deck_by_id[oracle_id]
            if density_critical or any(role in PACKAGE_CORE_ROLES for role in card.roles):
                core_ids.add(oracle_id)

    return frozenset(core_ids)


def package_repair_status(
    card: DeckCard,
    active_package_ids: frozenset[str],
    package_core_ids: frozenset[str],
) -> str:
    """Describe whether repair should treat this card as core or incidental."""
    if card.oracle_id in package_core_ids:
        return "protected_package_core"
    if card.package_ids:
        if any(pkg_id in active_package_ids for pkg_id in card.package_ids):
            return "removable_active_package_member"
        return "removable_incidental_package_member"
    return "unpackaged"
