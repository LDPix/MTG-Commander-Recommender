"""Commander collection fit scorer (SC-CMD-002, SC-CMD-007)."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from app.models.card import CardData
from app.recommendation.commander_profiles import get_commander_plan_override
from app.recommendation.legality_validator import LegalityValidator
from app.recommendation.role_taxonomy import CardRole
from app.recommendation.role_tagger import RuleTagger

_CORE_ROLES: list[CardRole] = [
    CardRole.RAMP,
    CardRole.CARD_DRAW,
    CardRole.SPOT_REMOVAL,
    CardRole.BOARD_WIPE,
    CardRole.LAND,
]

_OWNED_SUPPORT_SCALE = 1200  # asymptotic scale; broad collections never all round to 1.0
_ROLE_DEPTH_CAP = 5  # 5+ cards per core role = full credit for that role

# SC-CMD-007: penalty applied to owned_ratio based on commander color identity breadth
_COLOR_BREADTH_PENALTY: dict[int, float] = {
    1: 0.00,
    2: 0.05,
    3: 0.10,
    4: 0.18,
    5: 0.28,
}

# SC-CMD-007: roles relevant to each plan for specificity scoring
_PLAN_RELEVANT_ROLES: dict[str, frozenset[CardRole]] = {
    "food-sacrifice": frozenset({CardRole.SACRIFICE_OUTLET, CardRole.ARISTOCRATS_SYNERGY, CardRole.TOKEN_MAKER}),
    "aristocrats": frozenset({CardRole.SACRIFICE_OUTLET, CardRole.ARISTOCRATS_SYNERGY, CardRole.TOKEN_MAKER}),
    "landfall": frozenset({CardRole.LANDFALL_SYNERGY, CardRole.RAMP}),
    "spellslinger": frozenset({CardRole.SPELLSLINGER_SYNERGY, CardRole.CARD_DRAW}),
    "connive": frozenset({CardRole.GRAVEYARD_SYNERGY, CardRole.CARD_DRAW}),
}
_SPECIFICITY_CAP = 20


@dataclass
class CommanderFitScore:
    oracle_id: str
    commander_name: str
    total_score: float  # 0.0 – 1.0
    owned_count: int
    owned_percentage: float
    roles_covered: dict[str, int]  # role value → card count
    score_breakdown: dict[str, float]


class CommanderScorer:
    """Scores how well a user's collection supports a given commander.

    Only counts owned cards that are Commander-legal and fit the
    commander's color identity. Off-color and illegal cards are silently
    ignored so they cannot artificially inflate the score.
    """

    def __init__(self, role_tagger: RuleTagger) -> None:
        self._tagger = role_tagger
        self._validator = LegalityValidator()

    def compute_fit_score(
        self,
        commander: CardData,
        owned_cards: list[CardData],
    ) -> CommanderFitScore:
        """Return a CommanderFitScore for the given commander and owned cards."""
        valid = self._validator.filter_legal_cards(owned_cards)
        valid = self._validator.filter_color_identity(commander, valid)

        owned_count = len(valid)
        owned_ratio = 1.0 - math.exp(-owned_count / _OWNED_SUPPORT_SCALE)

        # SC-CMD-007: apply color-breadth penalty in the formula; keep raw ratio for display
        breadth_penalty = _COLOR_BREADTH_PENALTY.get(len(commander.color_identity), 0.0)
        effective_owned_ratio = owned_ratio * (1.0 - breadth_penalty)

        # SC-CMD-007: plan-specific specificity
        primary_plan = get_commander_plan_override(commander.oracle_id)
        plan_roles = _PLAN_RELEVANT_ROLES.get(primary_plan or "", frozenset())

        roles_covered: dict[str, int] = defaultdict(int)
        specificity_count = 0
        for card in valid:
            for tag in self._tagger.tag(card):
                roles_covered[tag.role.value] += 1
                if tag.role in plan_roles:
                    specificity_count += 1

        role_score = sum(
            min(roles_covered.get(role.value, 0), _ROLE_DEPTH_CAP) / _ROLE_DEPTH_CAP
            for role in _CORE_ROLES
        ) / len(_CORE_ROLES)

        specificity_score = min(specificity_count, _SPECIFICITY_CAP) / _SPECIFICITY_CAP

        total = 0.50 * effective_owned_ratio + 0.30 * role_score + 0.20 * specificity_score

        return CommanderFitScore(
            oracle_id=commander.oracle_id,
            commander_name=commander.name,
            total_score=round(total, 6),
            owned_count=owned_count,
            owned_percentage=round(owned_ratio, 6),  # raw, unpenalized for display
            roles_covered=dict(roles_covered),
            score_breakdown={
                "owned_ratio": effective_owned_ratio,
                "role_score": role_score,
                "specificity_score": specificity_score,
            },
        )
