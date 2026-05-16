"""SC-DECK-009/010: Colorless card classification and discipline rules."""
from __future__ import annotations

import re as _re

# Configurable discount applied to colorless cards without archetype synergy
# in colored Commander decks. Range 0.0 (full exclusion) to 1.0 (no discount).
COLORLESS_SYNERGY_DISCOUNT: float = 0.5

# Minimum number of dedicated colorless mana sources in the deck before
# {C}-requirement cards are allowed into the candidate pool.
C_REQUIREMENT_MIN_SOURCES: int = 3

# Roles that make a colorless card universally valuable regardless of archetype.
# Narrowed from the initial list: RAMP, CARD_DRAW, CARD_SELECTION, and
# MANA_FIXING were too broad for generic artifacts.
COLORLESS_EXEMPT_ROLES: frozenset[str] = frozenset({
    "SPOT_REMOVAL",
    "BOARD_WIPE",
    "PROTECTION",
    "TUTOR",
})


def card_is_colorless(color_identity: list[str]) -> bool:
    """Return True if the card has no color identity (colorless)."""
    return len(color_identity) == 0


def commander_has_colors(commander_color_identity: list[str]) -> bool:
    """Return True if the commander deck has colored mana requirements."""
    return len(commander_color_identity) > 0


def colorless_is_exempt(roles: list[str]) -> bool:
    """Return True if the card has at least one universally useful role."""
    return bool(COLORLESS_EXEMPT_ROLES.intersection(roles))


def has_c_mana_requirement(
    mana_cost: str | None,
    oracle_text: str | None = None,
) -> bool:
    """Return True when a card specifically requires colorless mana.

    Checks casting cost and simple oracle-text activation-cost positions such
    as "{C}:" and "{C},".
    """
    if mana_cost and "{C}" in mana_cost:
        return True
    if oracle_text and _re.search(r"\{C\}[,:]", oracle_text):
        return True
    return False


def is_dedicated_colorless_source(oracle_text: str | None, card_type_line: str) -> bool:
    """Return True if this permanent explicitly produces {C} mana."""
    text = (oracle_text or "").lower()
    is_permanent = any(t in card_type_line for t in ("Land", "Artifact", "Creature"))
    if not is_permanent:
        return False
    return "add {c}" in text
