"""SC-DECK-003/004: Role quota configuration and commander-based adjustment."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models.card import CardData
from app.recommendation.role_taxonomy import CardRole, RoleTag


@dataclass
class RoleQuota:
    role: CardRole
    target_min: int
    target_max: int
    adjustment_reason: str = ""


# SC-DECK-008: MVP uses this single default_playable profile.
# No user-facing power-level selector is exposed in MVP.
# Future profiles must be documented and regression-tested before activation.
BASELINE_QUOTAS: list[RoleQuota] = [
    RoleQuota(CardRole.LAND,          36, 38),
    RoleQuota(CardRole.RAMP,          10, 12),
    RoleQuota(CardRole.CARD_DRAW,     10, 12),
    RoleQuota(CardRole.SPOT_REMOVAL,   6,  8),
    RoleQuota(CardRole.BOARD_WIPE,     2,  3),
    RoleQuota(CardRole.PROTECTION,     2,  5),
    RoleQuota(CardRole.WIN_CONDITION,  3,  8),
]

# SC-DECK-035: Per-archetype quota overrides. When primary_plan matches a key,
# this profile replaces BASELINE_QUOTAS as the starting point before
# commander-tag adjustments are applied.
ARCHETYPE_QUOTA_PROFILES: dict[str, list[RoleQuota]] = {
    "food-sacrifice": [
        RoleQuota(CardRole.RAMP,                   8, 10),
        RoleQuota(CardRole.CARD_DRAW,             10, 12),
        RoleQuota(CardRole.SPOT_REMOVAL,           5,  7),
        RoleQuota(CardRole.BOARD_WIPE,             2,  3),
        RoleQuota(CardRole.PROTECTION,             2,  4),
        RoleQuota(CardRole.WIN_CONDITION,          2,  5),
        RoleQuota(CardRole.SACRIFICE_OUTLET,       4,  6),
        RoleQuota(CardRole.ARISTOCRATS_SYNERGY,    5,  8),
        RoleQuota(CardRole.TOKEN_MAKER,            3,  5),
    ],
    "aristocrats": [
        RoleQuota(CardRole.RAMP,                   8, 10),
        RoleQuota(CardRole.CARD_DRAW,             10, 12),
        RoleQuota(CardRole.SPOT_REMOVAL,           5,  7),
        RoleQuota(CardRole.BOARD_WIPE,             2,  3),
        RoleQuota(CardRole.PROTECTION,             2,  4),
        RoleQuota(CardRole.WIN_CONDITION,          2,  5),
        RoleQuota(CardRole.SACRIFICE_OUTLET,       4,  6),
        RoleQuota(CardRole.ARISTOCRATS_SYNERGY,    5,  8),
        RoleQuota(CardRole.TOKEN_MAKER,            3,  5),
    ],
    "landfall": [
        RoleQuota(CardRole.RAMP,                  12, 14),
        RoleQuota(CardRole.CARD_DRAW,              8, 10),
        RoleQuota(CardRole.SPOT_REMOVAL,           5,  7),
        RoleQuota(CardRole.BOARD_WIPE,             2,  3),
        RoleQuota(CardRole.PROTECTION,             2,  4),
        RoleQuota(CardRole.WIN_CONDITION,          3,  6),
        RoleQuota(CardRole.LANDFALL_SYNERGY,       5,  8),
    ],
    "spellslinger": [
        RoleQuota(CardRole.RAMP,                   8, 10),
        RoleQuota(CardRole.CARD_DRAW,             14, 16),
        RoleQuota(CardRole.SPOT_REMOVAL,           6,  8),
        RoleQuota(CardRole.BOARD_WIPE,             2,  3),
        RoleQuota(CardRole.PROTECTION,             3,  5),
        RoleQuota(CardRole.WIN_CONDITION,          3,  6),
        RoleQuota(CardRole.SPELLSLINGER_SYNERGY,   5,  8),
    ],
    "connive": [
        RoleQuota(CardRole.RAMP,                   8, 10),
        RoleQuota(CardRole.CARD_DRAW,             12, 14),
        RoleQuota(CardRole.SPOT_REMOVAL,           5,  7),
        RoleQuota(CardRole.BOARD_WIPE,             2,  3),
        RoleQuota(CardRole.PROTECTION,             2,  4),
        RoleQuota(CardRole.WIN_CONDITION,          3,  6),
        RoleQuota(CardRole.GRAVEYARD_SYNERGY,      4,  6),
    ],
}


def adjust_quotas_for_commander(
    baseline: list[RoleQuota],
    commander: CardData,
    commander_tags: list[RoleTag],
    primary_plan: str | None = None,
) -> list[RoleQuota]:
    """Return adjusted quotas based on commander characteristics.

    When primary_plan matches a profile in ARCHETYPE_QUOTA_PROFILES, that
    profile is used as the starting base instead of baseline. Commander-tag
    adjustments are applied on top of whichever base is used.

    Adjustments:
    - Commander CMC >= 6: increase RAMP min by 2
    - Commander has CARD_DRAW tag: decrease CARD_DRAW min by 2 (floor 6)
    - Commander has RAMP tag: decrease RAMP min by 1 (floor 8)
    - Commander has SACRIFICE_OUTLET tag: add SACRIFICE_OUTLET quota (3, 5)
      (skipped when archetype profile already includes SACRIFICE_OUTLET)
    """
    base = ARCHETYPE_QUOTA_PROFILES.get(primary_plan or "", baseline)
    commander_role_values = {tag.role for tag in commander_tags}

    adjusted: list[RoleQuota] = [
        RoleQuota(
            role=q.role,
            target_min=q.target_min,
            target_max=q.target_max,
            adjustment_reason=q.adjustment_reason,
        )
        for q in base
    ]

    for quota in adjusted:
        if quota.role == CardRole.RAMP:
            if commander.cmc >= 6:
                quota.target_min = quota.target_min + 2
                quota.adjustment_reason = "commander CMC >= 6 requires more ramp"
            if CardRole.RAMP in commander_role_values:
                quota.target_min = max(8, quota.target_min - 1)
                quota.adjustment_reason = (quota.adjustment_reason + "; commander provides ramp").lstrip("; ")

        if quota.role == CardRole.CARD_DRAW:
            if CardRole.CARD_DRAW in commander_role_values:
                quota.target_min = max(6, quota.target_min - 2)
                quota.adjustment_reason = "commander provides card draw"

    # Add SACRIFICE_OUTLET quota if commander has that tag and profile doesn't already include it
    profile_roles = {q.role for q in adjusted}
    if CardRole.SACRIFICE_OUTLET in commander_role_values and CardRole.SACRIFICE_OUTLET not in profile_roles:
        adjusted.append(
            RoleQuota(
                role=CardRole.SACRIFICE_OUTLET,
                target_min=3,
                target_max=5,
                adjustment_reason="commander has sacrifice outlet synergy",
            )
        )

    return adjusted
