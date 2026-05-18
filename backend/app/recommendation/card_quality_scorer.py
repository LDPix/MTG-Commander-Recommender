"""SC-DECK-011: composite card quality score for role-slot tiebreaking."""
from __future__ import annotations

import math

from app.models.card import CardData
from app.recommendation.quality_overrides import get_quality_override

_MAX_EDHREC_RANK: int = 25_000

_RARITY_HINT: dict[str, float] = {
    "common": 0.00,
    "uncommon": 0.02,
    "rare": 0.04,
    "mythic": 0.05,
}

_FLEXIBILITY_KEYWORDS = frozenset({
    "cycling",
    "channel",
    "flashback",
    "escape",
    "adventure",
    "foretell",
    "evoke",
    "kicker",
    "overload",
    "replicate",
})


def _is_instant_speed(card: CardData) -> bool:
    """Return True when any face can be cast at instant speed."""
    return "Instant" in card.type_line or (
        card.card_faces is not None
        and any("Instant" in face.type_line for face in card.card_faces)
    )


def format_staple_score(card: CardData) -> float:
    """Normalize EDHREC popularity using log decay. Lower rank → higher score."""
    if card.edhrec_rank is None:
        return 0.0
    if card.edhrec_rank <= 0:
        return 1.0
    return max(0.0, 1.0 - math.log(card.edhrec_rank + 1) / math.log(_MAX_EDHREC_RANK + 1))


def rarity_hint(card: CardData) -> float:
    """Return the small last-resort rarity hint value."""
    return _RARITY_HINT.get(card.rarity or "", 0.0)


def flexibility_score(card: CardData) -> float:
    """Score versatility indicators such as instant speed, modal text, and keywords."""
    score = 0.0
    text = card.get_all_oracle_text().lower()
    keywords = {kw.lower() for kw in card.keywords}

    if _is_instant_speed(card):
        score += 0.3
    if _FLEXIBILITY_KEYWORDS.intersection(keywords):
        score += 0.3
    if "choose one" in text or "choose two" in text or "choose" in text:
        score += 0.2

    return min(1.0, score)


def efficiency_score(card: CardData, role: str) -> float:
    """Compute a simple role-relative efficiency score."""
    cmc = card.cmc
    text = card.get_all_oracle_text().lower()
    instant = _is_instant_speed(card)

    if role == "SPOT_REMOVAL":
        score = 0.5
        if cmc <= 2:
            score += 0.3
        elif cmc >= 5:
            score -= 0.3
        if instant:
            score += 0.1
        if "exile" in text or "destroy" in text:
            score += 0.1
        return max(0.0, min(1.0, score))

    if role == "RAMP":
        score = 0.5
        if cmc <= 2:
            score += 0.3
        elif cmc >= 4:
            score -= 0.2
        if "each turn" in text or "whenever" in text:
            score += 0.1
        return max(0.0, min(1.0, score))

    if role == "CARD_DRAW":
        score = 0.5
        if cmc <= 3:
            score += 0.2
        elif cmc >= 5:
            score -= 0.2
        if "whenever" in text or "each upkeep" in text:
            score += 0.2
        if "draw 3" in text or "draw three" in text:
            score += 0.1
        return max(0.0, min(1.0, score))

    return max(0.0, min(1.0, 0.5 - max(0.0, cmc - 4) * 0.05))


def compute_quality_score(
    card: CardData,
    role: str,
    commander_oracle_id: str | None = None,
    archetype: str | None = None,
) -> float:
    """Compute a bounded, role-relative quality score for one card."""
    override = get_quality_override(card.oracle_id, commander_oracle_id, archetype)
    if override is not None:
        return override

    # Hierarchical fallback: when n_commander_decks = 0 (no per-commander data),
    # use color_identity_inclusion_rate proxied by edhrec_rank.
    # Stub at 0.5 is contraindicated — it inflates all scores above the 0.35 threshold.
    # commander_weight = n / (n + 100) → 0 when n = 0, so:
    #   commander_inclusion = 0 × specific_rate + 1 × color_identity_rate
    #                       = format_staple_score(card)
    # Per-commander rates can be injected via quality_overrides when available.
    commander_inclusion = format_staple_score(card)
    score = (
        0.40 * commander_inclusion
        + 0.25 * format_staple_score(card)
        + 0.20 * efficiency_score(card, role)
        + 0.10 * flexibility_score(card)
        + 0.05 * rarity_hint(card)
    )
    return max(0.0, min(1.0, score))
