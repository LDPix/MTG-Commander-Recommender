"""SC-DECK-002/003/004/005/006: Greedy Commander deck generator."""
from __future__ import annotations

import uuid
from collections import defaultdict

from app.models.card import CardData
from app.models.deck import DeckCard, GeneratedDeck, PackageCluster, QuotaStatus
from app.recommendation.card_quality_scorer import compute_quality_score
from app.recommendation.colorless_rules import (
    COLORLESS_SYNERGY_DISCOUNT,
    card_is_colorless,
    colorless_is_exempt,
    commander_has_colors,
)
from app.recommendation.legality_validator import LegalityValidator, DeckEntry
from app.recommendation.mana_base_rules import MONO_COLOR_BASIC_LAND_MIN, is_mono_color
from app.recommendation.quota_config import BASELINE_QUOTAS, RoleQuota
from app.recommendation.role_taxonomy import CardRole, RoleTag
from app.recommendation.synergy_graph import SynergyGraph


OWNED_PRIORITY_BONUS = 0.3
QUALITY_TIEBREAKER_WEIGHT: float = 0.20
QUALITY_WEAKNESS_THRESHOLD: float = 0.35
SYNERGY_WEAKNESS_THRESHOLD: float = 0.40
REPLACEMENT_SCORE_MARGIN: float = 0.15

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


def _score(card: DeckCard, commander_color_identity: list[str]) -> float:
    """Score for greedy selection: synergy + owned bonus + colorless discipline."""
    base = card.synergy_score

    # SC-DECK-009: Apply discount to synergy before adding owned bonus.
    if commander_has_colors(commander_color_identity) and card_is_colorless(card.color_identity):
        if not colorless_is_exempt(card.roles):
            base *= COLORLESS_SYNERGY_DISCOUNT

    base += OWNED_PRIORITY_BONUS if card.is_owned else 0.0
    return base


def _card_score(
    card: DeckCard,
    card_data: CardData,
    role: str,
    commander_oracle_id: str,
    archetype: str | None,
) -> float:
    """Final score used by the quality replacement pass."""
    quality = compute_quality_score(card_data, role, commander_oracle_id, archetype)
    return (
        card.synergy_score
        + (OWNED_PRIORITY_BONUS if card.is_owned else 0.0)
        + quality * QUALITY_TIEBREAKER_WEIGHT
    )


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
            card, card_data, primary_role, commander_oracle_id, archetype
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

        # Inject synergy scores from graph into candidate pool cards
        pool_with_scores: list[DeckCard] = []
        for card in candidate_pool:
            updated = card.model_copy(
                update={"synergy_score": graph.get_synergy_score(card.oracle_id)}
            )
            pool_with_scores.append(updated)

        # Step 2: Separate basic lands from non-basic cards
        basic_lands = [c for c in pool_with_scores if c.name in BASIC_LAND_NAMES]
        non_basics = [c for c in pool_with_scores if c.name not in BASIC_LAND_NAMES]

        selected: set[str] = set()
        main_deck: list[DeckCard] = []

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
            eligible.sort(key=lambda c: (-_score(c, commander.color_identity), c.oracle_id))

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
                non_basic_lands.sort(key=lambda c: (-_score(c, commander.color_identity), c.oracle_id))
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
            non_basic_lands.sort(key=lambda c: (-_score(c, commander.color_identity), c.oracle_id))
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

        # Step 6: Fill remaining slots with synergy/utility cards
        current_count = sum(c.quantity for c in main_deck)
        remaining_needed = 99 - current_count

        if remaining_needed > 0:
            filler_eligible = [
                c for c in non_basics
                if c.oracle_id not in selected
            ]
            filler_eligible.sort(key=lambda c: (-_score(c, commander.color_identity), c.oracle_id))
            filler_picks = filler_eligible[:remaining_needed]
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
            )

        # Step 9: Attach package_ids to cards
        card_to_packages: dict[str, list[str]] = defaultdict(list)
        for pkg in packages:
            for oid in pkg.card_oracle_ids:
                card_to_packages[oid].append(pkg.package_id)

        main_deck = [
            card.model_copy(update={"package_ids": card_to_packages.get(card.oracle_id, [])})
            for card in main_deck
        ]

        # Step 10: Compute role_breakdown
        role_breakdown: dict[str, int] = defaultdict(int)
        for card in main_deck:
            for role in card.roles:
                role_breakdown[role] += card.quantity

        # Step 11: Compute quota_status
        quota_status: list[QuotaStatus] = []
        for quota in active_quotas:
            actual = role_breakdown.get(quota.role.value, 0)
            # Allow some overrun (target_max + 5)
            is_satisfied = quota.target_min <= actual <= quota.target_max + 5
            warning: str | None = None
            if not is_satisfied:
                if actual < quota.target_min:
                    warning = (
                        f"{quota.role.value}: need {quota.target_min}–{quota.target_max}, "
                        f"got {actual} (underfilled)"
                    )
                else:
                    warning = (
                        f"{quota.role.value}: need {quota.target_min}–{quota.target_max}, "
                        f"got {actual} (overfilled)"
                    )
            quota_status.append(
                QuotaStatus(
                    role=quota.role.value,
                    target_min=quota.target_min,
                    target_max=quota.target_max,
                    actual_count=actual,
                    is_satisfied=is_satisfied,
                    warning=warning,
                )
            )

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
        warnings = [qs.warning for qs in quota_status if qs.warning is not None]

        return GeneratedDeck(
            deck_id=str(uuid.uuid4()),
            session_id=session_id,
            commander=commander_card,
            main_deck=main_deck,
            role_breakdown=dict(role_breakdown),
            quota_status=quota_status,
            package_breakdown=packages,
            warnings=warnings,
            owned_count=owned_count,
            owned_percentage=owned_percentage,
            is_valid=is_valid,
            validation_errors=validation_errors,
        )
