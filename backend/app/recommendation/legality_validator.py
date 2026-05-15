from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.models.card import CardData


@dataclass
class LegalityError:
    card_name: str
    oracle_id: str
    reason: str
    error_type: str  # "banned" | "illegal" | "off_color" | "duplicate" | "count"


@dataclass
class LegalityWarning:
    message: str
    warning_type: str  # "missing_card"


@dataclass
class LegalityResult:
    valid: bool
    errors: list[LegalityError] = field(default_factory=list)
    warnings: list[LegalityWarning] = field(default_factory=list)


@dataclass
class DeckEntry:
    oracle_id: str
    name: str
    quantity: int
    is_basic_land: bool


class LegalityValidator:
    """Validates Commander format rules for cards and decks.

    Stateless — safe to instantiate once and reuse across multiple calls.
    """

    def validate_card_legality(self, cards: list[CardData]) -> LegalityResult:
        """SC-LEGAL-001: Check that every card is legal in Commander."""
        errors: list[LegalityError] = []
        for card in cards:
            legality = card.legalities.get("commander", "not_legal")
            if legality == "banned":
                errors.append(
                    LegalityError(
                        card_name=card.name,
                        oracle_id=card.oracle_id,
                        reason=f"{card.name} is banned in Commander.",
                        error_type="banned",
                    )
                )
            elif legality != "legal":
                errors.append(
                    LegalityError(
                        card_name=card.name,
                        oracle_id=card.oracle_id,
                        reason=f"{card.name} is not legal in Commander.",
                        error_type="illegal",
                    )
                )
        return LegalityResult(valid=not errors, errors=errors)

    def filter_legal_cards(self, cards: list[CardData]) -> list[CardData]:
        """Return only cards with Commander legality == 'legal'."""
        return [c for c in cards if c.legalities.get("commander") == "legal"]

    def validate_color_identity(
        self, commander: CardData, cards: list[CardData]
    ) -> LegalityResult:
        """SC-LEGAL-002: Check every card fits the commander's color identity."""
        commander_colors = set(commander.color_identity)
        errors: list[LegalityError] = []
        for card in cards:
            card_colors = set(card.color_identity)
            if not card_colors.issubset(commander_colors):
                errors.append(
                    LegalityError(
                        card_name=card.name,
                        oracle_id=card.oracle_id,
                        reason=(
                            f"{card.name} has color identity {sorted(card_colors)} "
                            f"which is outside the commander's color identity "
                            f"{sorted(commander_colors)}."
                        ),
                        error_type="off_color",
                    )
                )
        return LegalityResult(valid=not errors, errors=errors)

    def filter_color_identity(
        self, commander: CardData, cards: list[CardData]
    ) -> list[CardData]:
        """Return only cards whose color identity fits the commander's."""
        commander_colors = set(commander.color_identity)
        return [c for c in cards if set(c.color_identity).issubset(commander_colors)]

    def validate_singleton(
        self,
        entries: list[DeckEntry],
        owned_quantities: dict[str, int] | None = None,
    ) -> LegalityResult:
        """SC-LEGAL-003: Check singleton rule and owned-quantity constraints."""
        errors: list[LegalityError] = []
        warnings: list[LegalityWarning] = []

        totals: dict[str, int] = defaultdict(int)
        names: dict[str, str] = {}
        basic_flags: dict[str, bool] = {}

        for entry in entries:
            totals[entry.oracle_id] += entry.quantity
            names[entry.oracle_id] = entry.name
            basic_flags[entry.oracle_id] = entry.is_basic_land

        for oracle_id, total_qty in totals.items():
            name = names[oracle_id]
            is_basic = basic_flags[oracle_id]

            if not is_basic and total_qty > 1:
                errors.append(
                    LegalityError(
                        card_name=name,
                        oracle_id=oracle_id,
                        reason=(
                            f"{name} appears {total_qty} times but Commander requires singleton "
                            f"for non-basic cards."
                        ),
                        error_type="duplicate",
                    )
                )

            if owned_quantities is not None:
                owned = owned_quantities.get(oracle_id, 0)
                if owned < total_qty:
                    warnings.append(
                        LegalityWarning(
                            message=(
                                f"{name} is missing from your collection "
                                f"({owned} owned, {total_qty} needed)."
                            ),
                            warning_type="missing_card",
                        )
                    )

        return LegalityResult(valid=not errors, errors=errors, warnings=warnings)

    def validate_deck(
        self,
        commander: CardData,
        main_deck: list[tuple[CardData, int]],
        owned_quantities: dict[str, int] | None = None,
    ) -> LegalityResult:
        """SC-DECK-007: Full deck validation — count, legality, color, singleton."""
        errors: list[LegalityError] = []
        warnings: list[LegalityWarning] = []

        # Card count: commander + main deck must equal 100
        main_count = sum(qty for _, qty in main_deck)
        total = main_count + 1
        if total != 100:
            errors.append(
                LegalityError(
                    card_name="Deck",
                    oracle_id="",
                    reason=f"Deck has {total} cards (including commander) but must have exactly 100.",
                    error_type="count",
                )
            )

        # Commander legality
        cmd_result = self.validate_card_legality([commander])
        errors.extend(cmd_result.errors)

        # Main deck card legality
        all_cards = [card for card, _ in main_deck]
        legal_result = self.validate_card_legality(all_cards)
        errors.extend(legal_result.errors)

        # Color identity
        color_result = self.validate_color_identity(commander, all_cards)
        errors.extend(color_result.errors)

        # Singleton and owned quantities
        entries = [
            DeckEntry(
                oracle_id=card.oracle_id,
                name=card.name,
                quantity=qty,
                is_basic_land=card.is_basic_land,
            )
            for card, qty in main_deck
        ]
        singleton_result = self.validate_singleton(entries, owned_quantities)
        errors.extend(singleton_result.errors)
        warnings.extend(singleton_result.warnings)

        return LegalityResult(valid=not errors, errors=errors, warnings=warnings)
