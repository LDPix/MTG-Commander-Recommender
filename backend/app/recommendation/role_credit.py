"""SC-DECK-013: Fractional role-quality credit for quota auditing."""
from __future__ import annotations

from app.models.card import CardData

# Roles where credit discrimination is applied.
# Other roles default to 1.0 (no fractional credit yet).
_CREDIT_ROLES: frozenset[str] = frozenset({"RAMP", "CARD_DRAW", "SPOT_REMOVAL", "BOARD_WIPE"})


def role_quality_credit(card_data: CardData, role: str) -> float:
    """Return fractional credit (0.0, 0.25, 0.5, 0.75, 1.0) for one card in one role.

    Credit measures how fully the card fulfills the role — not card quality.
    A card that incidentally cantrips is 0.25 CARD_DRAW; a dedicated draw engine is 1.0.
    """
    if role not in _CREDIT_ROLES:
        return 1.0

    text = (card_data.oracle_text or "").lower()
    cmc = card_data.cmc

    if role == "RAMP":
        return _ramp_credit(text, cmc)
    if role == "CARD_DRAW":
        return _draw_credit(text)
    if role == "SPOT_REMOVAL":
        return _removal_credit(text, card_data.type_line)
    if role == "BOARD_WIPE":
        return _wipe_credit(text)
    return 1.0


def _ramp_credit(text: str, cmc: float) -> float:
    """Ramp credit tiers."""
    # Repeatable ramp engine
    if any(phrase in text for phrase in ("whenever", "each turn", "each upkeep", "at the beginning of")):
        return 1.0
    # Land-search that puts two lands into play (Cultivate, Kodama's Reach)
    if "two" in text and ("land" in text or "lands" in text) and "put" in text:
        return 0.75
    # One-time ramp: low-CMC mana rock or one land into play
    if cmc <= 3:
        return 0.5
    # High-CMC or slow ramp
    return 0.25


def _draw_credit(text: str) -> float:
    """Draw credit tiers."""
    # Repeatable draw trigger
    if any(phrase in text for phrase in ("whenever", "each upkeep", "each turn", "at the beginning of")):
        return 1.0
    # Multi-card draw (draw 2+)
    if any(phrase in text for phrase in ("draw 2", "draw two", "draw 3", "draw three", "draw four", "draw x")):
        return 0.5
    # Cantrip (draw 1)
    return 0.25


def _removal_credit(text: str, type_line: str) -> float:
    """Spot removal credit tiers."""
    strong_effect = "exile" in text or "destroy" in text
    instant_speed = "Instant" in type_line
    if strong_effect and instant_speed:
        return 1.0
    if strong_effect:
        return 0.75
    # Bounce or conditional
    if "return" in text and "hand" in text:
        return 0.5
    return 0.25


def _wipe_credit(text: str) -> float:
    """Board wipe credit tiers."""
    # True mass removal (all creatures / all permanents)
    if any(phrase in text for phrase in ("all creatures", "all permanents", "all nonland")):
        return 1.0
    # Partial or selective wipe
    return 0.5
