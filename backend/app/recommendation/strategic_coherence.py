"""SC-DECK-012: strategic coherence analysis for generated decks."""
from __future__ import annotations

from app.models.card import CardData
from app.models.deck import (
    DeckCard,
    GeneratedDeck,
    PackageCluster,
    StrategicCoherenceReport,
)
from app.recommendation.card_quality_scorer import compute_quality_score
from app.recommendation.commander_profiles import get_support_tier
from app.recommendation.package_density import (
    PACKAGE_STATUS_ACTIVE,
    PACKAGE_STATUS_REJECTED_LOOSE,
    package_activation_status,
    packages_with_activation_status,
)
from app.recommendation.role_taxonomy import CardRole, RoleTag

MIN_ON_PLAN_SHARE: float = 0.60
MAX_OFF_PLAN_CARDS: int = 5
ACTIVE_PACKAGE_MIN_CARDS: int = 3
LOOSE_VALUE_PACKAGE_MIN_CARDS: int = 5
FLEXIBLE_STAPLE_QUALITY: float = 0.70

REQUIRED_ROLE_FILLERS: frozenset[str] = frozenset({
    CardRole.RAMP.value,
    CardRole.CARD_DRAW.value,
    CardRole.CARD_SELECTION.value,
    CardRole.SPOT_REMOVAL.value,
    CardRole.BOARD_WIPE.value,
    CardRole.PROTECTION.value,
    CardRole.TUTOR.value,
    CardRole.RECURSION.value,
})

PLAN_ROLE_HINTS: dict[str, frozenset[str]] = {
    "landfall": frozenset({CardRole.LANDFALL_SYNERGY.value, CardRole.RAMP.value}),
    "aristocrats": frozenset({
        CardRole.ARISTOCRATS_SYNERGY.value,
        CardRole.SACRIFICE_OUTLET.value,
        CardRole.RECURSION.value,
        CardRole.TOKEN_MAKER.value,
    }),
    "spellslinger": frozenset({CardRole.SPELLSLINGER_SYNERGY.value}),
    "blink": frozenset({CardRole.BLINK_SYNERGY.value}),
    "tribal": frozenset({CardRole.TRIBAL_SUPPORT.value, CardRole.TRIBAL_LORD.value}),
    "artifacts": frozenset({CardRole.ENABLER.value, CardRole.WIN_CONDITION.value}),
    "tokens": frozenset({CardRole.TOKEN_MAKER.value, CardRole.ARISTOCRATS_SYNERGY.value}),
    # "food-sacrifice" after "aristocrats" so ARISTOCRATS_SYNERGY/SACRIFICE_OUTLET tags
    # still resolve to "aristocrats"; LIFEGAIN alone uniquely routes here.
    "food-sacrifice": frozenset({
        CardRole.ARISTOCRATS_SYNERGY.value,
        CardRole.SACRIFICE_OUTLET.value,
        CardRole.TOKEN_MAKER.value,
        CardRole.LIFEGAIN.value,
    }),
    "connive": frozenset({
        CardRole.CARD_DRAW.value,
        CardRole.GRAVEYARD_SYNERGY.value,
        CardRole.RECURSION.value,
    }),
}

PLAN_TEXT_HINTS: dict[str, tuple[str, ...]] = {
    "landfall": ("landfall", "land card", "lands you control", "land you control enters"),
    "energy": ("{e}", "energy counter"),
    # "food-sacrifice" before "aristocrats" so "food" in oracle text takes priority
    # over the generic aristocrats hints.  Also placed before "artifacts" to prevent
    # "food" from misfiring into the artifacts plan.
    "food-sacrifice": (
        "food",
        "sacrifice",
        "you gain",
        "life",
        "dies",
        "die",
        "graveyard",
        "create a food",
    ),
    "aristocrats": ("dies", "die", "sacrifice", "graveyard"),
    "connive": (
        "connive",
        "discard",
        "then discard",
        "draw a card, then discard",
        "looting",
        "put into your graveyard from your hand",
    ),
    "spellslinger": ("instant", "sorcery", "cast an instant", "cast a sorcery"),
    "blink": ("exile", "return it to the battlefield", "enters the battlefield"),
    "artifacts": ("artifact", "treasure", "clue", "food", "map"),
    "tokens": ("token", "populate"),
}

LOOSE_VALUE_TERMS: tuple[str, ...] = (
    "treasure",
    "clue",
    "food",
    "map",
    "artifact token",
    "artifact you control",
    "artifacts you control",
    "value",
)


class StrategicCoherenceValidator:
    """Classify selected cards against a commander's primary plan."""

    def validate(
        self,
        commander: CardData,
        commander_tags: list[RoleTag],
        deck: GeneratedDeck,
        all_cards_lookup: dict[str, CardData],
        packages: list[PackageCluster],
    ) -> StrategicCoherenceReport:
        primary_plan = infer_primary_plan(commander, commander_tags)
        support_tier = get_support_tier(commander.oracle_id)
        package_statuses = packages_with_activation_status(
            packages=packages,
            main_deck=deck.main_deck,
            primary_plan=primary_plan,
            commander_supports_loose_value=_commander_supports_loose_value(
                commander, primary_plan
            ),
            enforce_commander_relevance=True,
        )
        active_package_ids, loose_package_ids = active_packages(
            deck=deck,
            packages=package_statuses,
            primary_plan=primary_plan,
            commander=commander,
        )

        warning_card_ids: list[str] = []
        on_plan_count = 0
        off_plan_count = 0

        for card in deck.main_deck:
            if CardRole.LAND.value in card.roles or card.quantity != 1:
                continue

            card_data = all_cards_lookup.get(card.oracle_id)
            if card_data is None:
                continue

            if is_card_justified(
                card=card,
                card_data=card_data,
                primary_plan=primary_plan,
                active_package_ids=active_package_ids,
                commander_oracle_id=commander.oracle_id,
            ):
                on_plan_count += 1
            else:
                off_plan_count += 1
                warning_card_ids.append(card.oracle_id)

        warnings: list[str] = []
        considered = on_plan_count + off_plan_count
        if primary_plan is None:
            warnings.append(
                "Strategic coherence is low: no clear primary commander plan was identified."
            )
        elif considered:
            on_plan_share = on_plan_count / considered
            if on_plan_share < MIN_ON_PLAN_SHARE:
                warnings.append(
                    "Strategic coherence is low: too many nonland cards do not support "
                    f"the {primary_plan} plan or an active package."
                )

        if off_plan_count > MAX_OFF_PLAN_CARDS:
            warnings.append(
                "Strategic coherence warning: off-plan nonland cards exceed the configured limit."
            )

        if loose_package_ids:
            warnings.append(
                "Loose Treasure/Clue/Food/Map artifact-value cards did not meet the "
                "active package threshold."
            )

        if support_tier == "fallback" and primary_plan is None:
            warnings.append(
                "Commander support is fallback and no high-confidence plan was found."
            )

        confidence = _confidence(primary_plan, support_tier, on_plan_count, off_plan_count)
        return StrategicCoherenceReport(
            primary_plan=primary_plan,
            confidence=confidence,
            active_package_ids=sorted(active_package_ids),
            on_plan_count=on_plan_count,
            off_plan_count=off_plan_count,
            warning_card_oracle_ids=sorted(warning_card_ids),
            warnings=warnings,
        )


def infer_primary_plan(
    commander: CardData,
    commander_tags: list[RoleTag],
) -> str | None:
    """Infer a conservative primary plan from commander tags and text."""
    from app.recommendation.commander_profiles import get_commander_plan_override

    override = get_commander_plan_override(commander.oracle_id, commander.name)
    if override is not None:
        return override

    for tag in commander_tags:
        role_value = tag.role.value
        for plan, roles in PLAN_ROLE_HINTS.items():
            if role_value in roles and role_value not in REQUIRED_ROLE_FILLERS:
                return plan

    text = f"{commander.name} {commander.get_all_oracle_text()}".lower()
    for plan, hints in PLAN_TEXT_HINTS.items():
        if any(hint in text for hint in hints):
            return plan

    return None


def active_packages(
    deck: GeneratedDeck,
    packages: list[PackageCluster],
    primary_plan: str | None,
    commander: CardData,
) -> tuple[set[str], set[str]]:
    """Return active package IDs and package IDs rejected as loose value piles."""
    commander_supports_loose_value = _commander_supports_loose_value(
        commander, primary_plan
    )
    active: set[str] = set()
    loose_rejected: set[str] = set()

    for package in packages:
        status = (
            package.activation_status
            if package.activation_status != "detected" or package.selected_count > 0
            else package_activation_status(
                main_deck=deck.main_deck,
                package=package,
                primary_plan=primary_plan,
                commander_supports_loose_value=commander_supports_loose_value,
                enforce_commander_relevance=True,
            )
        )
        if status == PACKAGE_STATUS_ACTIVE:
            active.add(package.package_id)
        elif status == PACKAGE_STATUS_REJECTED_LOOSE:
            loose_rejected.add(package.package_id)

    return active, loose_rejected


def is_card_justified(
    card: DeckCard,
    card_data: CardData,
    primary_plan: str | None,
    active_package_ids: set[str],
    commander_oracle_id: str,
) -> bool:
    """Return True when a selected nonland has clear strategic justification."""
    from app.recommendation.commander_profiles import (
        get_commander_negative_evidence,
        get_commander_positive_evidence,
    )

    # Negative evidence overrides all other justifications
    neg_signals = get_commander_negative_evidence(commander_oracle_id)
    if neg_signals:
        text = f"{card.name} {card_data.get_all_oracle_text()}".lower()
        if any(sig in text for sig in neg_signals):
            return False

    # Positive evidence: card explicitly supports this commander's plan
    pos_signals = get_commander_positive_evidence(commander_oracle_id)
    if pos_signals:
        text = f"{card.name} {card_data.get_all_oracle_text()}".lower()
        if any(sig in text for sig in pos_signals):
            return True

    if active_package_ids.intersection(card.package_ids):
        return True

    if primary_plan is not None and _card_supports_plan(card, card_data, primary_plan):
        return True

    primary_role = card.roles[0] if card.roles else ""
    quality = compute_quality_score(card_data, primary_role, commander_oracle_id)
    return quality >= FLEXIBLE_STAPLE_QUALITY


def _card_supports_plan(card: DeckCard, card_data: CardData, primary_plan: str) -> bool:
    if card.assigned_role in PLAN_ROLE_HINTS.get(primary_plan, frozenset()):
        return True

    text = f"{card.name} {card_data.get_all_oracle_text()}".lower()
    return any(hint in text for hint in PLAN_TEXT_HINTS.get(primary_plan, ()))


def _is_loose_value_package(package: PackageCluster) -> bool:
    text = " ".join([package.label, *package.top_roles]).lower()
    return any(term in text for term in LOOSE_VALUE_TERMS)


def _commander_supports_loose_value(
    commander: CardData,
    primary_plan: str | None,
) -> bool:
    if primary_plan in {"artifacts", "tokens"}:
        return True

    text = f"{commander.name} {commander.get_all_oracle_text()}".lower()
    return any(term in text for term in LOOSE_VALUE_TERMS)


def _confidence(
    primary_plan: str | None,
    support_tier: str,
    on_plan_count: int,
    off_plan_count: int,
) -> float:
    if primary_plan is None:
        return 0.0

    considered = on_plan_count + off_plan_count
    share = on_plan_count / considered if considered else 0.0
    tier_bonus = {"curated": 0.20, "profiled": 0.10, "fallback": 0.0}.get(
        support_tier, 0.0
    )
    return round(min(1.0, 0.30 + share * 0.50 + tier_bonus), 6)
