"""SC-DECK-009/010: Colorless card classification and discipline rules."""
from __future__ import annotations

from dataclasses import dataclass
import re as _re

# Configurable discount applied to colorless cards without archetype synergy
# in colored Commander decks. Range 0.0 (full exclusion) to 1.0 (no discount).
COLORLESS_SYNERGY_DISCOUNT: float = 0.5

# SC-DECK-010 v2: Factor applied to {C}-requirement card scores.
# Near-zero suppresses Eldrazi/devoid cards in non-colorless decks.
COLORLESS_STRATEGY_BASE_FACTOR: float = 0.05

# Roles that make a colorless card universally valuable regardless of archetype.
# Narrowed from the initial list: RAMP, CARD_DRAW, CARD_SELECTION, and
# MANA_FIXING were too broad for generic artifacts.
COLORLESS_EXEMPT_ROLES: frozenset[str] = frozenset({
    "SPOT_REMOVAL",
    "BOARD_WIPE",
    "PROTECTION",
    "TUTOR",
})

# Package label fragments that indicate an active colorless strategy.
_COLORLESS_PACKAGE_LABELS: frozenset[str] = frozenset({
    "eldrazi", "colorless", "devoid", "colorless matters",
})

COLORLESS_STRATEGY_ACTIVE_FACTOR: float = 0.8


@dataclass(frozen=True)
class ColorlessStrategySignal:
    """Deterministic explanation for the colorless strategy multiplier."""

    factor: float
    source: str


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


def _contains_colorless_strategy_text(values: list[str | None]) -> bool:
    text = " ".join(value or "" for value in values).lower()
    return any(fragment in text for fragment in _COLORLESS_PACKAGE_LABELS)


def evaluate_colorless_strategy_signal(
    commander_color_identity: list[str],
    commander_name: str | None = None,
    commander_type_line: str | None = None,
    commander_oracle_text: str | None = None,
    commander_profile_tags: list[str] | None = None,
    candidate_package_labels: list[str] | None = None,
    selected_package_labels: list[str] | None = None,
) -> ColorlessStrategySignal:
    """Return the colorless strategy factor and activation source.

    1.0 → colorless commander: full colorless strategy, no suppression.
    0.8 → explicit commander support or committed selected-deck package.
    COLORLESS_STRATEGY_BASE_FACTOR → colored commander, no colorless strategy.

    Candidate-pool package labels are intentionally non-activating. They can
    describe collection contents, not a committed commander/deck plan.
    Sol Ring is not a {C}-requirement card ({1} ≠ {C}), so it is unaffected.
    """
    if not commander_has_colors(commander_color_identity):
        return ColorlessStrategySignal(1.0, "commander_identity")

    if _contains_colorless_strategy_text([
        commander_name,
        commander_type_line,
        commander_oracle_text,
        *(commander_profile_tags or []),
    ]):
        return ColorlessStrategySignal(
            COLORLESS_STRATEGY_ACTIVE_FACTOR,
            "commander_profile",
        )

    if _contains_colorless_strategy_text(selected_package_labels or []):
        return ColorlessStrategySignal(
            COLORLESS_STRATEGY_ACTIVE_FACTOR,
            "selected_deck_density",
        )

    # Keep the parameter visible for call sites/tests, but collection-only
    # package detection must not activate colorless strategy for colored decks.
    _ = candidate_package_labels
    return ColorlessStrategySignal(
        COLORLESS_STRATEGY_BASE_FACTOR,
        "base_colored_commander",
    )


def compute_colorless_strategy_factor(
    commander_color_identity: list[str],
    package_labels: list[str],
) -> float:
    """Return a score multiplier for {C}-requirement cards.

    Backward-compatible float wrapper. The package_labels argument is treated
    as candidate-pool evidence and does not activate colored commanders.
    """
    return evaluate_colorless_strategy_signal(
        commander_color_identity,
        candidate_package_labels=package_labels,
    ).factor
