"""Commander collection fit scorer (SC-CMD-002)."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from app.models.card import CardData
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

        roles_covered: dict[str, int] = defaultdict(int)
        for card in valid:
            for tag in self._tagger.tag(card):
                roles_covered[tag.role.value] += 1

        role_score = sum(
            min(roles_covered.get(role.value, 0), _ROLE_DEPTH_CAP) / _ROLE_DEPTH_CAP
            for role in _CORE_ROLES
        ) / len(_CORE_ROLES)

        total = 0.6 * owned_ratio + 0.4 * role_score

        return CommanderFitScore(
            oracle_id=commander.oracle_id,
            commander_name=commander.name,
            total_score=round(total, 6),
            owned_count=owned_count,
            owned_percentage=round(owned_ratio, 6),
            roles_covered=dict(roles_covered),
            score_breakdown={"owned_ratio": owned_ratio, "role_score": role_score},
        )
