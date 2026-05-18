"""SC-DECK-023: assigned role-slot accounting for generated decks."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.models.card import CardData
from app.models.deck import DeckCard, QuotaStatus
from app.recommendation.quota_config import RoleQuota
from app.recommendation.role_credit import role_quality_credit
from app.recommendation.role_taxonomy import CardRole

FRACTIONAL_SECONDARY_ROLES: frozenset[str] = frozenset({
    CardRole.RAMP.value,
    CardRole.CARD_DRAW.value,
    CardRole.SPOT_REMOVAL.value,
    CardRole.BOARD_WIPE.value,
})
SECONDARY_CREDIT_CAP: float = 0.5


@dataclass(frozen=True)
class RoleAssignmentResult:
    main_deck: list[DeckCard]
    role_breakdown: dict[str, int]
    quota_status: list[QuotaStatus]


def assign_role_slots(
    main_deck: list[DeckCard],
    quotas: list[RoleQuota],
    all_cards_lookup: dict[str, CardData] | None,
) -> RoleAssignmentResult:
    """Assign one primary role slot per selected card and recompute quotas."""
    quota_order = [quota.role.value for quota in quotas]
    quota_roles = set(quota_order)
    quota_max: dict[str, int] = {quota.role.value: quota.target_max for quota in quotas}
    assigned_cards: list[DeckCard] = []
    role_breakdown: dict[str, int] = defaultdict(int)
    explicit_roles = [_explicit_assigned_role(card, quota_order) for card in main_deck]
    reserved_explicit_counts: dict[str, int] = defaultdict(int)
    for card, explicit_role in zip(main_deck, explicit_roles):
        if explicit_role is not None:
            reserved_explicit_counts[explicit_role] += card.quantity

    for card, explicit_role in zip(main_deck, explicit_roles):
        if explicit_role is not None:
            reserved_explicit_counts[explicit_role] = max(
                0, reserved_explicit_counts[explicit_role] - card.quantity
            )
        assigned_role = _assigned_role(
            card,
            quota_order,
            role_breakdown,
            quota_max,
            reserved_explicit_counts,
            explicit_role,
        )
        secondary_credit = _secondary_role_credit(
            card=card,
            assigned_role=assigned_role,
            quota_roles=quota_roles,
            all_cards_lookup=all_cards_lookup,
        )
        assigned = card.model_copy(
            update={
                "assigned_role": assigned_role,
                "secondary_role_credit": secondary_credit,
            }
        )
        assigned_cards.append(assigned)
        if assigned_role is not None:
            role_breakdown[assigned_role] += assigned.quantity

    quota_status = [
        _quota_status(
            quota=quota,
            main_deck=assigned_cards,
            role_breakdown=role_breakdown,
            all_cards_lookup=all_cards_lookup,
        )
        for quota in quotas
    ]
    return RoleAssignmentResult(
        main_deck=assigned_cards,
        role_breakdown=dict(role_breakdown),
        quota_status=quota_status,
    )


def _assigned_role(
    card: DeckCard,
    quota_order: list[str],
    role_breakdown: dict[str, int],
    quota_max: dict[str, int],
    reserved_explicit_counts: dict[str, int],
    explicit_role: str | None = None,
) -> str | None:
    if CardRole.LAND.value in card.roles:
        return CardRole.LAND.value

    if explicit_role is not None:
        return explicit_role

    for role in quota_order:
        if role in card.roles:
            cap = quota_max.get(role)
            reserved = reserved_explicit_counts.get(role, 0)
            if cap is not None and role_breakdown.get(role, 0) + reserved >= cap:
                continue
            return role
    return None


def _explicit_assigned_role(card: DeckCard, quota_order: list[str]) -> str | None:
    if CardRole.LAND.value in card.roles:
        return None

    reason = card.selection_reason.lower()
    for role in quota_order:
        if role in card.roles and f"fills {role.lower()} role" in reason:
            return role
    return None


def _secondary_role_credit(
    card: DeckCard,
    assigned_role: str | None,
    quota_roles: set[str],
    all_cards_lookup: dict[str, CardData] | None,
) -> dict[str, float]:
    if all_cards_lookup is None:
        return {}

    card_data = all_cards_lookup.get(card.oracle_id)
    if card_data is None:
        return {}

    credit: dict[str, float] = {}
    for role in card.roles:
        if role == assigned_role:
            continue
        if role not in quota_roles or role not in FRACTIONAL_SECONDARY_ROLES:
            continue
        role_credit = role_quality_credit(card_data, role)
        if role_credit <= 0:
            continue
        credit[role] = round(min(role_credit, SECONDARY_CREDIT_CAP) * card.quantity, 2)
    return credit


def _quota_status(
    quota: RoleQuota,
    main_deck: list[DeckCard],
    role_breakdown: dict[str, int],
    all_cards_lookup: dict[str, CardData] | None,
) -> QuotaStatus:
    role_value = quota.role.value
    if role_value == CardRole.WIN_CONDITION.value:
        assigned_count = role_breakdown.get(role_value, 0)
        tagged_count = sum(card.quantity for card in main_deck if role_value in card.roles)
        actual = max(assigned_count, min(tagged_count, quota.target_min))
    else:
        actual = role_breakdown.get(role_value, 0)
    credit_sum = _quota_credit_sum(
        role_value=role_value,
        main_deck=main_deck,
        all_cards_lookup=all_cards_lookup,
    )
    count_satisfied = quota.target_min <= actual <= quota.target_max
    credit_satisfied = credit_sum >= quota.target_min
    # Count status and credit status are tracked separately. Keeping
    # is_satisfied count-only lets the repair loop target low-quality fillers
    # when slot counts are met but role-quality credit is still short.
    is_satisfied = count_satisfied

    warning: str | None = None
    if actual < quota.target_min:
        warning = (
            f"{role_value}: need {quota.target_min}–{quota.target_max}, "
            f"got {actual} assigned slot(s) (underfilled)"
        )
    elif actual > quota.target_max:
        warning = (
            f"{role_value}: need {quota.target_min}–{quota.target_max}, "
            f"got {actual} assigned slot(s) (overfilled)"
        )

    credit_warning: str | None = None
    if not credit_satisfied:
        credit_warning = (
            f"{role_value}: credit {credit_sum:.1f} < minimum {quota.target_min} "
            f"(assigned {actual} slot(s) plus bounded secondary credit)"
        )

    return QuotaStatus(
        role=role_value,
        target_min=quota.target_min,
        target_max=quota.target_max,
        actual_count=actual,
        is_satisfied=is_satisfied,
        warning=warning,
        credit_sum=round(credit_sum, 2),
        credit_satisfied=credit_satisfied,
        credit_warning=credit_warning,
    )


def _quota_credit_sum(
    role_value: str,
    main_deck: list[DeckCard],
    all_cards_lookup: dict[str, CardData] | None,
) -> float:
    credit_sum = 0.0
    for card in main_deck:
        if role_value == CardRole.WIN_CONDITION.value:
            if role_value not in card.roles:
                continue
            card_data = all_cards_lookup.get(card.oracle_id) if all_cards_lookup else None
            credit_sum += (
                role_quality_credit(card_data, role_value) if card_data is not None else card.quantity
            )
            continue
        if card.assigned_role == role_value:
            card_data = all_cards_lookup.get(card.oracle_id) if all_cards_lookup else None
            if card_data is None:
                credit_sum += card.quantity
            else:
                credit_sum += role_quality_credit(card_data, role_value) * card.quantity
        else:
            credit_sum += card.secondary_role_credit.get(role_value, 0.0)
    return credit_sum
