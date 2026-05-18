"""SC-DECK-002/003/004/005/006: Greedy Commander deck generator."""
from __future__ import annotations

import uuid
from collections import defaultdict

from app.models.card import CardData
from app.models.deck import DeckCard, GeneratedDeck, PackageCluster, QuotaStatus
from app.recommendation.card_quality_scorer import compute_quality_score
from app.recommendation.colorless_rules import (
    COLORLESS_EXEMPT_ROLES,
    COLORLESS_STRATEGY_ACTIVE_FACTOR,
    COLORLESS_SYNERGY_DISCOUNT,
    card_is_colorless,
    colorless_is_exempt,
    commander_has_colors,
    evaluate_colorless_strategy_signal,
    has_c_mana_requirement,
)
from app.recommendation.legality_validator import LegalityValidator, DeckEntry
from app.recommendation.mana_base_rules import (
    MONO_COLOR_BASIC_LAND_MIN,
    is_mono_color,
    utility_land_has_relevance,
)
from app.recommendation.package_density import (
    active_package_ids_for_deck,
    count_package_core_members_in_deck,
    count_package_members_in_deck,
    is_orphan,
    package_core_ids_for_deck,
    package_density_threshold,
    package_relevant_to_plan,
    packages_with_activation_status,
    INFRASTRUCTURE_ROLES,
)
from app.recommendation.quota_config import BASELINE_QUOTAS, RoleQuota
from app.recommendation.role_credit import role_quality_credit
from app.recommendation.role_assignment import assign_role_slots
from app.recommendation.role_taxonomy import CardRole, RoleTag
from app.recommendation.strategic_coherence import (
    ACTIVE_PACKAGE_MIN_CARDS,
    _commander_supports_loose_value,
    infer_primary_plan,
)
from app.recommendation.synergy_graph import SynergyGraph


OWNED_PRIORITY_BONUS = 0.3
QUALITY_TIEBREAKER_WEIGHT: float = 0.20
QUALITY_WEAKNESS_THRESHOLD: float = 0.35
SYNERGY_WEAKNESS_THRESHOLD: float = 0.40
REPLACEMENT_SCORE_MARGIN: float = 0.15
OWNED_RELEVANCE_LIMIT: float = 0.25
FULL_ROLE_CREDIT_THRESHOLD: float = 0.75
FLEXIBLE_STAPLE_QUALITY: float = 0.70
OWNED_BONUS_CREDIT_ROLES: frozenset[str] = frozenset({
    CardRole.RAMP.value,
    CardRole.CARD_DRAW.value,
    CardRole.SPOT_REMOVAL.value,
    CardRole.BOARD_WIPE.value,
})
COLORLESS_STAPLE_NAMES: frozenset[str] = frozenset({
    "Sol Ring",
    "Arcane Signet",
})

BASIC_LAND_NAMES: frozenset[str] = frozenset({
    "Plains",
    "Island",
    "Swamp",
    "Mountain",
    "Forest",
    "Wastes",
    "Snow-Covered Plains",
    "Snow-Covered Island",
    "Snow-Covered Swamp",
    "Snow-Covered Mountain",
    "Snow-Covered Forest",
})


def _score(
    card: DeckCard,
    commander_color_identity: list[str],
    c_strategy_factor: float = 1.0,
    c_requirement_ids: frozenset[str] = frozenset(),
    active_package_ids: frozenset[str] = frozenset(),
    package_core_ids: frozenset[str] = frozenset(),
    role_credit: float | None = None,
    quality_score: float | None = None,
) -> float:
    """Score for greedy selection: synergy + owned bonus + colorless discipline."""
    base = card.synergy_score

    # SC-DECK-009: discount non-exempt colorless cards in colored decks
    if commander_has_colors(commander_color_identity) and card_is_colorless(card.color_identity):
        if not colorless_is_exempt(card.roles):
            base *= COLORLESS_SYNERGY_DISCOUNT

    # SC-DECK-010 v2: suppress {C}-requirement cards without a colorless strategy;
    # scale owned bonus by the same factor so ownership cannot override suppression
    if card.oracle_id in c_requirement_ids:
        base *= c_strategy_factor
    if card.is_owned:
        base += OWNED_PRIORITY_BONUS * owned_priority_multiplier(
            card=card,
            commander_color_identity=commander_color_identity,
            c_strategy_factor=c_strategy_factor,
            active_package_ids=active_package_ids,
            package_core_ids=package_core_ids,
            role_credit=role_credit,
            quality_score=quality_score,
        )
    return base


def owned_priority_multiplier(
    card: DeckCard,
    commander_color_identity: list[str],
    c_strategy_factor: float,
    active_package_ids: frozenset[str],
    package_core_ids: frozenset[str],
    role_credit: float | None = None,
    quality_score: float | None = None,
) -> float:
    """Return the relevance-gated multiplier for the owned-card bonus."""
    return owned_priority_adjustment(
        card=card,
        commander_color_identity=commander_color_identity,
        c_strategy_factor=c_strategy_factor,
        active_package_ids=active_package_ids,
        package_core_ids=package_core_ids,
        role_credit=role_credit,
        quality_score=quality_score,
    )[0]


def owned_priority_adjustment(
    card: DeckCard,
    commander_color_identity: list[str],
    c_strategy_factor: float,
    active_package_ids: frozenset[str],
    package_core_ids: frozenset[str],
    role_credit: float | None = None,
    quality_score: float | None = None,
) -> tuple[float, str]:
    """Return owned-bonus multiplier and deterministic reason label."""
    if not card.is_owned:
        return 0.0, "not_owned"

    package_relevant = bool(set(card.package_ids).intersection(active_package_ids))
    package_core = card.oracle_id in package_core_ids
    full_role_credit = (
        role_credit is not None and role_credit >= FULL_ROLE_CREDIT_THRESHOLD
    )
    high_quality = quality_score is not None and quality_score >= FLEXIBLE_STAPLE_QUALITY

    if commander_has_colors(commander_color_identity) and card_is_colorless(card.color_identity):
        if not colorless_is_exempt(card.roles) and c_strategy_factor < 1.0:
            if package_relevant or package_core:
                return 1.0, "active_package"
            if full_role_credit:
                return 1.0, "full_role_credit"
            if high_quality:
                return 1.0, "high_quality_staple"
            return min(c_strategy_factor, OWNED_RELEVANCE_LIMIT), "off_plan_colorless"

    if package_relevant or package_core:
        return 1.0, "active_package"
    if full_role_credit:
        return 1.0, "full_role_credit"
    if high_quality:
        return 1.0, "high_quality_staple"
    return 1.0, "default"


def _card_score(
    card: DeckCard,
    card_data: CardData,
    role: str,
    commander_oracle_id: str,
    archetype: str | None,
    commander_color_identity: list[str] | None = None,
    c_strategy_factor: float = 1.0,
    active_package_ids: frozenset[str] = frozenset(),
    package_core_ids: frozenset[str] = frozenset(),
) -> float:
    """Final score used by the quality replacement pass."""
    quality = compute_quality_score(card_data, role, commander_oracle_id, archetype)
    role_credit = _owned_bonus_role_credit(card_data, role)
    owned_multiplier = owned_priority_multiplier(
        card=card,
        commander_color_identity=commander_color_identity or [],
        c_strategy_factor=c_strategy_factor,
        active_package_ids=active_package_ids,
        package_core_ids=package_core_ids,
        role_credit=role_credit,
        quality_score=quality,
    )
    return (
        card.synergy_score
        + (OWNED_PRIORITY_BONUS * owned_multiplier if card.is_owned else 0.0)
        + quality * QUALITY_TIEBREAKER_WEIGHT
    )


def _primary_role(card: DeckCard) -> str:
    return card.roles[0] if card.roles else ""


def _owned_bonus_role_credit(card_data: CardData, role: str) -> float | None:
    if role not in OWNED_BONUS_CREDIT_ROLES:
        return None
    return role_quality_credit(card_data, role)


def _owned_bonus_quality_score(
    card_data: CardData,
    role: str,
    commander_oracle_id: str,
) -> float | None:
    if not role:
        return None
    return compute_quality_score(card_data, role, commander_oracle_id)


def _selection_score(
    card: DeckCard,
    commander: CardData,
    c_strategy_factor: float,
    c_requirement_ids: frozenset[str],
    active_package_ids: frozenset[str],
    package_core_ids: frozenset[str],
    all_cards_lookup: dict[str, CardData] | None,
) -> float:
    role_credit: float | None = None
    quality_score: float | None = None
    card_data = all_cards_lookup.get(card.oracle_id) if all_cards_lookup else None
    role = _primary_role(card)
    if card_data is not None:
        role_credit = _owned_bonus_role_credit(card_data, role)
        quality_score = _owned_bonus_quality_score(
            card_data, role, commander.oracle_id
        )

    base = _score(
        card,
        commander.color_identity,
        c_strategy_factor,
        c_requirement_ids,
        active_package_ids,
        package_core_ids,
        role_credit,
        quality_score,
    )
    if quality_score is not None:
        base += quality_score * QUALITY_TIEBREAKER_WEIGHT
    return base


def _colorless_candidate_allowed(
    card: DeckCard,
    commander: CardData,
    c_strategy_factor: float,
    all_cards_lookup: dict[str, CardData] | None,
) -> tuple[bool, str | None]:
    """Return whether a colorless card has enough relevance for a colored deck."""
    if not commander_has_colors(commander.color_identity):
        return True, None
    if CardRole.LAND.value in card.roles:
        return True, None
    card_data = all_cards_lookup.get(card.oracle_id) if all_cards_lookup else None
    if card_data is None:
        return True, None
    color_identity = card_data.color_identity if card_data is not None else card.color_identity
    if not card_is_colorless(color_identity):
        return True, None
    if c_strategy_factor >= COLORLESS_STRATEGY_ACTIVE_FACTOR:
        return True, None
    if card.name in COLORLESS_STAPLE_NAMES:
        return True, None

    for role in card.roles:
        if role in OWNED_BONUS_CREDIT_ROLES and role_quality_credit(card_data, role) >= FULL_ROLE_CREDIT_THRESHOLD:
            return True, None
        if role in COLORLESS_EXEMPT_ROLES:
            quality = compute_quality_score(card_data, role, commander.oracle_id)
            if quality >= FLEXIBLE_STAPLE_QUALITY:
                return True, None

    return False, "off_plan_colorless_excluded"


def _color_identity_subset(candidate: DeckCard, current: DeckCard) -> bool:
    """Return True when candidate does not broaden the selected card's colors."""
    return set(candidate.color_identity).issubset(set(current.color_identity))


def _replacement_pass(
    main_deck: list[DeckCard],
    pool_with_scores: list[DeckCard],
    selected: set[str],
    all_cards_lookup: dict[str, CardData],
    commander_oracle_id: str,
    archetype: str | None,
    commander_color_identity: list[str],
    c_strategy_factor: float,
    active_package_ids: frozenset[str],
    package_core_ids: frozenset[str],
) -> list[DeckCard]:
    """Replace weak nonland cards with higher-quality same-role alternatives."""
    result = list(main_deck)
    selected_ids = set(selected)
    selected_ids.update(
        card.oracle_id for card in result if card.name not in BASIC_LAND_NAMES
    )
    replacements_made: set[str] = set()

    for index, card in enumerate(result):
        if card.quantity != 1 or CardRole.LAND.value in card.roles:
            continue

        card_data = all_cards_lookup.get(card.oracle_id)
        if card_data is None:
            continue

        primary_role = card.roles[0] if card.roles else ""
        if not primary_role:
            continue

        quality = compute_quality_score(
            card_data, primary_role, commander_oracle_id, archetype
        )
        if (
            quality >= QUALITY_WEAKNESS_THRESHOLD
            or card.synergy_score >= SYNERGY_WEAKNESS_THRESHOLD
        ):
            continue

        current_final = _card_score(
            card,
            card_data,
            primary_role,
            commander_oracle_id,
            archetype,
            commander_color_identity,
            c_strategy_factor,
            active_package_ids,
            package_core_ids,
        )
        eligible: list[tuple[float, DeckCard]] = []
        for candidate in pool_with_scores:
            if candidate.oracle_id == card.oracle_id:
                continue
            if candidate.oracle_id in selected_ids or candidate.oracle_id in replacements_made:
                continue
            if CardRole.LAND.value in candidate.roles or primary_role not in candidate.roles:
                continue
            if not _color_identity_subset(candidate, card):
                continue

            candidate_data = all_cards_lookup.get(candidate.oracle_id)
            if candidate_data is None:
                continue

            candidate_final = _card_score(
                candidate,
                candidate_data,
                primary_role,
                commander_oracle_id,
                archetype,
                commander_color_identity,
                c_strategy_factor,
                active_package_ids,
                package_core_ids,
            )
            if candidate_final >= current_final + REPLACEMENT_SCORE_MARGIN:
                eligible.append((candidate_final, candidate))

        if not eligible:
            continue

        eligible.sort(key=lambda item: (not item[1].is_owned, -item[0], item[1].oracle_id))
        _, replacement = eligible[0]
        result[index] = replacement.model_copy(
            update={
                "quantity": card.quantity,
                "selection_reason": (
                    f"quality replacement for {card.name} ({primary_role})"
                ),
            }
        )
        selected_ids.discard(card.oracle_id)
        selected_ids.add(replacement.oracle_id)
        replacements_made.add(replacement.oracle_id)

    return result


def _package_memberships(
    packages: list[PackageCluster],
) -> dict[str, list[str]]:
    card_to_packages: dict[str, list[str]] = defaultdict(list)
    for package in packages:
        for oracle_id in package.card_oracle_ids:
            card_to_packages[oracle_id].append(package.package_id)
    return card_to_packages


def _filter_irrelevant_utility_lands(
    pool_with_scores: list[DeckCard],
    all_cards_lookup: dict[str, CardData] | None,
    packages: list[PackageCluster],
) -> tuple[list[DeckCard], list[str]]:
    """Exclude utility lands that lack synergy or active package relevance."""
    if all_cards_lookup is None:
        return pool_with_scores, []

    card_to_packages = _package_memberships(packages)
    active_package_ids = {package.package_id for package in packages}
    filtered: list[DeckCard] = []
    warnings: list[str] = []

    for card in pool_with_scores:
        card_data = all_cards_lookup.get(card.oracle_id)
        if card_data is None:
            filtered.append(card)
            continue

        package_ids = card_to_packages.get(card.oracle_id, [])
        if utility_land_has_relevance(
            card_name=card_data.name,
            oracle_text=card_data.oracle_text,
            type_line=card_data.type_line,
            synergy_score=card.synergy_score,
            package_ids=package_ids,
            active_package_ids=active_package_ids,
        ):
            filtered.append(card)
            continue

        warnings.append(
            f"Utility land excluded for low strategic relevance: {card_data.name}"
        )

    return filtered, warnings


class DeckGenerator:
    """Greedy role-fill deck generator with synergy-score tiebreaking."""

    def generate(
        self,
        commander: CardData,
        commander_tags: list[RoleTag],
        candidate_pool: list[DeckCard],
        role_tags: dict[str, list[RoleTag]],
        graph: SynergyGraph,
        packages: list[PackageCluster],
        session_id: str,
        quotas: list[RoleQuota] | None = None,
        all_cards_lookup: dict[str, CardData] | None = None,
    ) -> GeneratedDeck:
        """Generate a 99-card main deck (+ commander = 100)."""

        # Step 1: Resolve quotas
        active_quotas = quotas if quotas is not None else BASELINE_QUOTAS
        primary_plan = infer_primary_plan(commander, commander_tags)
        enforce_package_relevance = primary_plan is not None

        # Inject synergy scores from graph into candidate pool cards
        pool_with_scores: list[DeckCard] = []
        for card in candidate_pool:
            updated = card.model_copy(
                update={"synergy_score": graph.get_synergy_score(card.oracle_id)}
            )
            pool_with_scores.append(updated)

        card_to_packages = _package_memberships(packages)
        pool_with_scores = [
            card.model_copy(update={"package_ids": card_to_packages.get(card.oracle_id, [])})
            for card in pool_with_scores
        ]
        # Bug H fix: start empty so owned_priority_adjustment cannot reach "active_package"
        # for colorless cards before deck contents are known.  The correct active-package
        # set is computed later at Step 5.5 after filler selection.
        _active_package_ids: frozenset[str] = frozenset()
        _package_core_ids: frozenset[str] = frozenset()

        pool_with_scores, utility_land_warnings = _filter_irrelevant_utility_lands(
            pool_with_scores=pool_with_scores,
            all_cards_lookup=all_cards_lookup,
            packages=packages,
        )

        # SC-DECK-010 v2/017: Compute colorless strategy factor for {C}-requirement scoring.
        # Candidate-pool package labels are diagnostic only; they do not activate
        # a colorless plan for colored commanders.
        _package_labels = [pkg.label for pkg in packages]
        _c_strategy_signal = evaluate_colorless_strategy_signal(
            commander_color_identity=commander.color_identity,
            commander_name=commander.name,
            commander_type_line=commander.type_line,
            commander_oracle_text=commander.oracle_text,
            commander_profile_tags=[tag.role.value for tag in commander_tags],
            candidate_package_labels=_package_labels,
        )
        _c_strategy_factor = _c_strategy_signal.factor

        # Build set of oracle IDs that carry {C} mana requirements
        # (only if factor is meaningful — skip for colorless commanders)
        if _c_strategy_factor < 1.0 and all_cards_lookup:
            _c_requirement_ids: frozenset[str] = frozenset(
                oracle_id
                for oracle_id, card_data in all_cards_lookup.items()
                if has_c_mana_requirement(card_data.mana_cost, card_data.oracle_text)
            )
        else:
            _c_requirement_ids = frozenset()

        # Step 2: Separate basic lands from non-basic cards
        basic_lands = [c for c in pool_with_scores if c.name in BASIC_LAND_NAMES]
        colorless_exclusion_count = 0
        non_basics = []
        for card in pool_with_scores:
            if card.name in BASIC_LAND_NAMES:
                continue
            allowed, _reason = _colorless_candidate_allowed(
                card=card,
                commander=commander,
                c_strategy_factor=_c_strategy_factor,
                all_cards_lookup=all_cards_lookup,
            )
            if allowed:
                non_basics.append(card)
            else:
                colorless_exclusion_count += 1
        pool_with_scores = [*basic_lands, *non_basics]

        selected: set[str] = set()
        main_deck: list[DeckCard] = []
        if colorless_exclusion_count:
            utility_land_warnings.append(
                f"Colorless gate excluded {colorless_exclusion_count} off-plan colorless card(s)"
            )

        # Step 3: Find land quota
        land_quota = next(
            (q for q in active_quotas if q.role == CardRole.LAND),
            RoleQuota(CardRole.LAND, 36, 38),
        )

        # Step 4: Fill non-LAND role quotas first
        for quota in active_quotas:
            if quota.role == CardRole.LAND:
                continue  # handled separately

            role_value = quota.role.value
            target = quota.target_max

            eligible = [
                c for c in non_basics
                if role_value in c.roles and c.oracle_id not in selected
            ]
            # Sort by score desc, then oracle_id asc for determinism
            eligible.sort(
                key=lambda c: (
                    -_selection_score(
                        c,
                        commander,
                        _c_strategy_factor,
                        _c_requirement_ids,
                        _active_package_ids,
                        _package_core_ids,
                        all_cards_lookup,
                    ),
                    c.oracle_id,
                )
            )

            picks = eligible[:target]
            for card in picks:
                reason = f"fills {role_value} role"
                main_deck.append(card.model_copy(update={"selection_reason": reason}))
                selected.add(card.oracle_id)

        # Step 5: LAND selection
        land_target = land_quota.target_max

        if is_mono_color(commander.color_identity) and basic_lands:
            # SC-MANA-001: Basics first, then fill remaining with non-basics
            sorted_basics = sorted(basic_lands, key=lambda c: c.oracle_id)
            num_basics = len(sorted_basics)
            basic_target = min(MONO_COLOR_BASIC_LAND_MIN, land_target)
            base_qty = basic_target // num_basics
            extra = basic_target % num_basics
            for i, basic in enumerate(sorted_basics):
                qty = base_qty + (1 if i < extra else 0)
                if qty > 0:
                    main_deck.append(
                        basic.model_copy(
                            update={
                                "quantity": qty,
                                "selection_reason": "fills LAND role (basic priority)",
                            }
                        )
                    )

            remaining_land_slots = max(0, land_target - basic_target)
            if remaining_land_slots > 0:
                non_basic_lands = [
                    c for c in pool_with_scores
                    if CardRole.LAND.value in c.roles
                    and c.name not in BASIC_LAND_NAMES
                    and c.oracle_id not in selected
                ]
                non_basic_lands.sort(
                    key=lambda c: (
                        -_selection_score(
                            c,
                            commander,
                            _c_strategy_factor,
                            _c_requirement_ids,
                            _active_package_ids,
                            _package_core_ids,
                            all_cards_lookup,
                        ),
                        c.oracle_id,
                    )
                )
                for card in non_basic_lands[:remaining_land_slots]:
                    main_deck.append(card.model_copy(update={"selection_reason": "fills LAND role"}))
                    selected.add(card.oracle_id)

        else:
            # Multi-color (or colorless): non-basics first, then fill remaining with basics
            non_basic_lands = [
                c for c in pool_with_scores
                if CardRole.LAND.value in c.roles
                and c.name not in BASIC_LAND_NAMES
                and c.oracle_id not in selected
            ]
            non_basic_lands.sort(
                key=lambda c: (
                    -_selection_score(
                        c,
                        commander,
                        _c_strategy_factor,
                        _c_requirement_ids,
                        _active_package_ids,
                        _package_core_ids,
                        all_cards_lookup,
                    ),
                    c.oracle_id,
                )
            )
            non_basic_picks = non_basic_lands[:land_target]
            for card in non_basic_picks:
                main_deck.append(card.model_copy(update={"selection_reason": "fills LAND role"}))
                selected.add(card.oracle_id)

            remaining_land_slots = max(0, land_target - len(non_basic_picks))

            if remaining_land_slots > 0 and basic_lands:
                sorted_basics = sorted(basic_lands, key=lambda c: c.oracle_id)
                num_basics = len(sorted_basics)
                base_qty = remaining_land_slots // num_basics
                extra = remaining_land_slots % num_basics
                for i, basic in enumerate(sorted_basics):
                    qty = base_qty + (1 if i < extra else 0)
                    if qty <= 0:
                        continue
                    main_deck.append(
                        basic.model_copy(
                            update={
                                "quantity": qty,
                                "selection_reason": "fills LAND role",
                            }
                        )
                    )

        # SC-DECK-019: provisional active packages for filler preference
        # Packages with ≥ ACTIVE_PACKAGE_MIN_CARDS members already in selected
        # sort ahead of unpackaged or inactive-package cards in filler fill.
        _provisional_active_pkg_ids: frozenset[str] = frozenset(
            pkg.package_id
            for pkg in packages
            if sum(1 for oid in pkg.card_oracle_ids if oid in selected)
            >= ACTIVE_PACKAGE_MIN_CARDS
            and primary_plan is not None
            and package_relevant_to_plan(pkg, primary_plan)
        )

        # Step 6: Fill remaining slots with synergy/utility cards
        current_count = sum(c.quantity for c in main_deck)
        remaining_needed = 99 - current_count

        if remaining_needed > 0:
            quota_max: dict[str, int] = {
                quota.role.value: quota.target_max for quota in active_quotas
            }
            filler_role_counts: dict[str, int] = defaultdict(int)
            for card in main_deck:
                primary = card.roles[0] if card.roles else ""
                if primary:
                    filler_role_counts[primary] += card.quantity

            filler_eligible: list[DeckCard] = []
            for card in non_basics:
                if card.oracle_id in selected:
                    continue
                primary = card.roles[0] if card.roles else ""
                cap = quota_max.get(primary)
                if cap is not None and filler_role_counts.get(primary, 0) >= cap:
                    continue
                filler_eligible.append(card)

            def _filler_key(c: DeckCard) -> tuple:
                in_active_pkg = any(
                    pkg.package_id in _provisional_active_pkg_ids
                    for pkg in packages
                    if c.oracle_id in pkg.card_oracle_ids
                )
                return (
                    not in_active_pkg,  # active-package cards sort first (False < True)
                    -_selection_score(
                        c,
                        commander,
                        _c_strategy_factor,
                        _c_requirement_ids,
                        _active_package_ids,
                        _package_core_ids,
                        all_cards_lookup,
                    ),
                    c.oracle_id,
                )

            filler_eligible.sort(key=_filler_key)
            filler_picks: list[DeckCard] = []
            for card in filler_eligible:
                if len(filler_picks) >= remaining_needed:
                    break
                primary = card.roles[0] if card.roles else ""
                cap = quota_max.get(primary)
                if cap is not None and filler_role_counts.get(primary, 0) >= cap:
                    continue
                filler_picks.append(card)
                if primary:
                    filler_role_counts[primary] += card.quantity

            for card in filler_picks:
                # SC-DECK-009: reflect colorless discount in selection_reason
                if (
                    commander_has_colors(commander.color_identity)
                    and card_is_colorless(card.color_identity)
                    and not colorless_is_exempt(card.roles)
                ):
                    reason = "synergy/utility (colorless discount applied)"
                else:
                    reason = "synergy/utility"
                main_deck.append(card.model_copy(update={"selection_reason": reason}))
                selected.add(card.oracle_id)

        # Step 5.5 (placed after Step 6 so filler cards are available to remove):
        # Land quota repair — SWAP lowest-scoring non-essential non-land cards for basics.
        # Total stays at 99; safety trim cannot undo the repair.
        LAND_SOFT_MIN = land_quota.target_min
        current_land_count = sum(c.quantity for c in main_deck if CardRole.LAND.value in c.roles)
        land_deficit = max(0, LAND_SOFT_MIN - current_land_count)

        _active_package_ids = active_package_ids_for_deck(
            main_deck,
            packages,
            primary_plan=primary_plan,
            commander_supports_loose_value=_commander_supports_loose_value(
                commander, primary_plan
            ),
            enforce_commander_relevance=enforce_package_relevance,
        )
        _package_core_ids = package_core_ids_for_deck(
            main_deck,
            packages,
            active_package_ids=_active_package_ids,
        )
        _selected_package_labels = [
            pkg.label for pkg in packages if pkg.package_id in _active_package_ids
        ]
        _c_strategy_signal = evaluate_colorless_strategy_signal(
            commander_color_identity=commander.color_identity,
            commander_name=commander.name,
            commander_type_line=commander.type_line,
            commander_oracle_text=commander.oracle_text,
            commander_profile_tags=[tag.role.value for tag in commander_tags],
            candidate_package_labels=_package_labels,
            selected_package_labels=_selected_package_labels,
        )
        _c_strategy_factor = _c_strategy_signal.factor

        if land_deficit > 0 and basic_lands:
            if packages:
                selected_package_member_ids = {
                    _c.oracle_id
                    for _c in main_deck
                    if _c.package_ids
                }
                _protected_in_deck = sum(
                    1 for _c in main_deck if _c.oracle_id in _package_core_ids
                )
                incidental_count = len(selected_package_member_ids - _package_core_ids)
                utility_land_warnings.append(
                    "Package activation gates: "
                    f"protected {_protected_in_deck} active package member(s); "
                    f"{incidental_count} incidental package member(s) remain removable"
                )

            role_counts: dict[str, int] = defaultdict(int)
            for _rc in main_deck:
                for _role in _rc.roles:
                    role_counts[_role] += _rc.quantity
            quota_min: dict[str, int] = {q.role.value: q.target_min for q in active_quotas}
            sorted_basics_repair = sorted(basic_lands, key=lambda c: c.oracle_id)
            num_basics_avail = len(sorted_basics_repair)
            swaps_done = 0

            for _ in range(land_deficit):
                removable: list[tuple[int, DeckCard]] = [
                    (i, _c)
                    for i, _c in enumerate(main_deck)
                    if _c.quantity == 1
                    and CardRole.LAND.value not in _c.roles
                    and _c.oracle_id not in _package_core_ids
                    and all(
                        role_counts.get(_r, 0) - 1 >= quota_min.get(_r, 0)
                        for _r in _c.roles
                    )
                ]
                if not removable:
                    break

                removable.sort(
                    key=lambda t: (
                        _selection_score(
                            t[1],
                            commander,
                            _c_strategy_factor,
                            _c_requirement_ids,
                            _active_package_ids,
                            _package_core_ids,
                            all_cards_lookup,
                        ),
                        t[1].oracle_id,
                    )
                )
                remove_idx, remove_card = removable[0]
                main_deck.pop(remove_idx)
                for _role in remove_card.roles:
                    role_counts[_role] = max(0, role_counts[_role] - 1)

                basic_template = sorted_basics_repair[swaps_done % num_basics_avail]
                existing_idx = next(
                    (i for i, _c in enumerate(main_deck) if _c.oracle_id == basic_template.oracle_id),
                    None,
                )
                if existing_idx is not None:
                    _existing = main_deck[existing_idx]
                    main_deck[existing_idx] = _existing.model_copy(
                        update={
                            "quantity": _existing.quantity + 1,
                            "selection_reason": "fills LAND role (repair pass)",
                        }
                    )
                else:
                    main_deck.append(
                        basic_template.model_copy(
                            update={
                                "quantity": 1,
                                "selection_reason": "fills LAND role (repair pass)",
                            }
                        )
                    )
                role_counts[CardRole.LAND.value] += 1
                swaps_done += 1

        # Step 7: If still short, add more basic land quantity
        current_count = sum(c.quantity for c in main_deck)
        if current_count < 99:
            still_needed = 99 - current_count
            # Find first basic land entry in main_deck and increase its quantity
            for i, card in enumerate(main_deck):
                if card.name in BASIC_LAND_NAMES:
                    main_deck[i] = card.model_copy(
                        update={"quantity": card.quantity + still_needed}
                    )
                    break
            else:
                # No basic land in deck at all — add Swamp/Forest if available in pool
                if basic_lands:
                    filler_basic = sorted(basic_lands, key=lambda c: c.oracle_id)[0]
                    main_deck.append(
                        filler_basic.model_copy(
                            update={
                                "quantity": still_needed,
                                "selection_reason": "filler land",
                            }
                        )
                    )

        # Final safety: trim if somehow over 99
        current_count = sum(c.quantity for c in main_deck)
        if current_count > 99:
            excess = current_count - 99
            # Reduce from the last basic land entry
            for i in range(len(main_deck) - 1, -1, -1):
                card = main_deck[i]
                if card.name in BASIC_LAND_NAMES and card.quantity > excess:
                    main_deck[i] = card.model_copy(
                        update={"quantity": card.quantity - excess}
                    )
                    break
                elif card.name in BASIC_LAND_NAMES and card.quantity <= excess:
                    excess -= card.quantity
                    main_deck.pop(i)
                    if excess == 0:
                        break

        # Step 8: Replace weak nonland cards with stronger same-role options.
        if all_cards_lookup:
            main_deck = _replacement_pass(
                main_deck=main_deck,
                pool_with_scores=pool_with_scores,
                selected=selected,
                all_cards_lookup=all_cards_lookup,
                commander_oracle_id=commander.oracle_id,
                archetype=None,
                commander_color_identity=commander.color_identity,
                c_strategy_factor=_c_strategy_factor,
                active_package_ids=_active_package_ids,
                package_core_ids=_package_core_ids,
            )

        # Step 9: Attach package_ids to cards
        main_deck = [
            card.model_copy(update={"package_ids": card_to_packages.get(card.oracle_id, [])})
            for card in main_deck
        ]

        # Step 9.5: Package density enforcement — replace orphan package-only cards
        underfilled_package_ids: frozenset[str] = frozenset(
            pkg.package_id
            for pkg in packages
            if count_package_core_members_in_deck(main_deck, pkg) < package_density_threshold(pkg)
        )

        if underfilled_package_ids:
            for pkg in packages:
                if pkg.package_id in underfilled_package_ids:
                    in_deck = count_package_core_members_in_deck(main_deck, pkg)
                    threshold = package_density_threshold(pkg)
                    utility_land_warnings.append(
                        f"Package '{pkg.label}' underfilled: {in_deck}/{threshold} cards in deck"
                    )

            _pkg_role_counts: dict[str, int] = defaultdict(int)
            for _c in main_deck:
                for _r in _c.roles:
                    _pkg_role_counts[_r] += _c.quantity
            _pkg_quota_min: dict[str, int] = {q.role.value: q.target_min for q in active_quotas}

            orphan_indices = [
                i for i, c in enumerate(main_deck)
                if is_orphan(c, underfilled_package_ids)
            ]

            _infra_pool = [
                c for c in pool_with_scores
                if c.oracle_id not in selected
                and CardRole.LAND.value not in c.roles
                and c.name not in BASIC_LAND_NAMES
                and any(r in INFRASTRUCTURE_ROLES for r in c.roles)
            ]
            _infra_pool.sort(
                key=lambda c: (
                    -_selection_score(
                        c,
                        commander,
                        _c_strategy_factor,
                        _c_requirement_ids,
                        _active_package_ids,
                        _package_core_ids,
                        all_cards_lookup,
                    ),
                    c.oracle_id,
                )
            )

            replacement_iter = iter(_infra_pool)
            for orphan_idx in orphan_indices:
                orphan_card = main_deck[orphan_idx]
                role_safe = all(
                    _pkg_role_counts.get(r, 0) - 1 >= _pkg_quota_min.get(r, 0)
                    for r in orphan_card.roles
                )
                if not role_safe:
                    continue

                replacement = next(replacement_iter, None)
                if replacement is None:
                    break

                main_deck[orphan_idx] = replacement.model_copy(
                    update={
                        "quantity": 1,
                        "selection_reason": (
                            f"infrastructure replacement for orphan {orphan_card.name}"
                        ),
                    }
                )
                selected.discard(orphan_card.oracle_id)
                selected.add(replacement.oracle_id)

                for r in orphan_card.roles:
                    _pkg_role_counts[r] = max(0, _pkg_role_counts[r] - 1)
                for r in replacement.roles:
                    _pkg_role_counts[r] = _pkg_role_counts.get(r, 0) + 1

            # Re-attach package_ids after orphan replacement (new cards may have packages)
            card_to_packages = _package_memberships(packages)
            main_deck = [
                c.model_copy(update={"package_ids": card_to_packages.get(c.oracle_id, [])})
                for c in main_deck
            ]

        # Step 10/11: Assign role slots and compute quota status.
        assignment = assign_role_slots(main_deck, active_quotas, all_cards_lookup)
        main_deck = assignment.main_deck
        role_breakdown = assignment.role_breakdown
        quota_status = assignment.quota_status

        # Step 12: Legality validation
        is_valid = True
        validation_errors: list[str] = []

        if all_cards_lookup is not None:
            validator = LegalityValidator()
            # Build list[tuple[CardData, int]] for validator
            main_for_validation: list[tuple[CardData, int]] = []
            for deck_card in main_deck:
                card_data = all_cards_lookup.get(deck_card.oracle_id)
                if card_data is not None:
                    main_for_validation.append((card_data, deck_card.quantity))
            result = validator.validate_deck(commander, main_for_validation)
            is_valid = result.valid
            validation_errors = [e.reason for e in result.errors]
        else:
            # No lookup provided — skip full validation
            total = sum(c.quantity for c in main_deck) + 1
            if total != 100:
                is_valid = False
                validation_errors.append(
                    f"Deck has {total} cards (including commander) but must have exactly 100."
                )

        # Step 13: Compute owned stats
        owned_count = sum(c.quantity for c in main_deck if c.is_owned)
        owned_percentage = owned_count / 99 if 99 > 0 else 0.0

        # Step 14: Build commander DeckCard
        commander_roles = [tag.role.value for tag in commander_tags]
        commander_card = DeckCard(
            oracle_id=commander.oracle_id,
            name=commander.name,
            is_owned=True,  # commander is always considered "available"
            quantity=1,
            roles=commander_roles,
            selection_reason="commander",
        )

        # Step 15: Collect warnings
        warnings = [
            *utility_land_warnings,
            *[qs.warning for qs in quota_status if qs.warning is not None],
            *[qs.credit_warning for qs in quota_status if qs.credit_warning is not None],
        ]

        return GeneratedDeck(
            deck_id=str(uuid.uuid4()),
            session_id=session_id,
            commander=commander_card,
            main_deck=main_deck,
            role_breakdown=dict(role_breakdown),
            quota_status=quota_status,
            package_breakdown=packages_with_activation_status(
                packages=packages,
                main_deck=main_deck,
                primary_plan=primary_plan,
                commander_supports_loose_value=_commander_supports_loose_value(
                    commander, primary_plan
                ),
                enforce_commander_relevance=enforce_package_relevance,
            ),
            warnings=warnings,
            owned_count=owned_count,
            owned_percentage=owned_percentage,
            is_valid=is_valid,
            validation_errors=validation_errors,
        )
