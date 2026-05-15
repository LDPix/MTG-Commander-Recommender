"""SC-DECK-002/003/004/005/006: Greedy Commander deck generator."""
from __future__ import annotations

import uuid
from collections import defaultdict

from app.models.card import CardData
from app.models.deck import DeckCard, GeneratedDeck, PackageCluster, QuotaStatus
from app.recommendation.legality_validator import LegalityValidator, DeckEntry
from app.recommendation.quota_config import BASELINE_QUOTAS, RoleQuota
from app.recommendation.role_taxonomy import CardRole, RoleTag
from app.recommendation.synergy_graph import SynergyGraph


OWNED_PRIORITY_BONUS = 0.3

BASIC_LAND_NAMES: frozenset[str] = frozenset({
    "Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"
})


def _score(card: DeckCard) -> float:
    """Score for greedy selection: synergy + owned bonus."""
    return card.synergy_score + (OWNED_PRIORITY_BONUS if card.is_owned else 0.0)


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
            eligible.sort(key=lambda c: (-_score(c), c.oracle_id))

            picks = eligible[:target]
            for card in picks:
                reason = f"fills {role_value} role"
                main_deck.append(card.model_copy(update={"selection_reason": reason}))
                selected.add(card.oracle_id)

        # Step 5: LAND selection
        # 5a: Pick non-basic lands from pool
        non_basic_lands = [
            c for c in pool_with_scores
            if CardRole.LAND.value in c.roles
            and c.name not in BASIC_LAND_NAMES
            and c.oracle_id not in selected
        ]
        non_basic_lands.sort(key=lambda c: (-_score(c), c.oracle_id))
        land_target = land_quota.target_max
        non_basic_picks = non_basic_lands[:land_target]
        for card in non_basic_picks:
            main_deck.append(card.model_copy(update={"selection_reason": "fills LAND role"}))
            selected.add(card.oracle_id)

        non_basic_land_count = len(non_basic_picks)
        remaining_land_slots = max(0, land_target - non_basic_land_count)

        # 5b: Distribute remaining slots among basic lands
        if remaining_land_slots > 0 and basic_lands:
            # Sort basics deterministically
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
                # Don't add to selected — basics can have qty > 1

        # Step 6: Fill remaining slots with synergy/utility cards
        current_count = sum(c.quantity for c in main_deck)
        remaining_needed = 99 - current_count

        if remaining_needed > 0:
            filler_eligible = [
                c for c in non_basics
                if c.oracle_id not in selected
            ]
            filler_eligible.sort(key=lambda c: (-_score(c), c.oracle_id))
            filler_picks = filler_eligible[:remaining_needed]
            for card in filler_picks:
                main_deck.append(
                    card.model_copy(update={"selection_reason": "synergy/utility"})
                )
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

        # Step 8: Attach package_ids to cards
        card_to_packages: dict[str, list[str]] = defaultdict(list)
        for pkg in packages:
            for oid in pkg.card_oracle_ids:
                card_to_packages[oid].append(pkg.package_id)

        main_deck = [
            card.model_copy(update={"package_ids": card_to_packages.get(card.oracle_id, [])})
            for card in main_deck
        ]

        # Step 9: Compute role_breakdown
        role_breakdown: dict[str, int] = defaultdict(int)
        for card in main_deck:
            for role in card.roles:
                role_breakdown[role] += card.quantity

        # Step 10: Compute quota_status
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

        # Step 11: Legality validation
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

        # Step 12: Compute owned stats
        owned_count = sum(c.quantity for c in main_deck if c.is_owned)
        owned_percentage = owned_count / 99 if 99 > 0 else 0.0

        # Step 13: Build commander DeckCard
        commander_roles = [tag.role.value for tag in commander_tags]
        commander_card = DeckCard(
            oracle_id=commander.oracle_id,
            name=commander.name,
            is_owned=True,  # commander is always considered "available"
            quantity=1,
            roles=commander_roles,
            selection_reason="commander",
        )

        # Step 14: Collect warnings
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
