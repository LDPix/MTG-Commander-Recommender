"""Plaintext deck export formatting for generated Commander decks."""
from __future__ import annotations

from app.schemas.deck_schema import DeckCardSchema, GeneratedDeckResponse

BASIC_LANDS = {"Forest", "Island", "Mountain", "Plains", "Swamp", "Wastes"}


def export_deck_to_plaintext(deck: GeneratedDeckResponse) -> tuple[str, list[str]]:
    """Return stable plaintext decklist output and warnings for a generated deck."""
    if deck.generation_status in {"failed_validation", "failed_quality"} or not deck.is_valid:
        raise ValueError("Cannot export failed generated deck.")
    if deck.validation_errors:
        raise ValueError("Cannot export deck with validation errors.")

    warnings = _collect_warnings(deck)
    sections = [
        "Commander",
        _format_card_line(deck.commander),
        "",
        "Main Deck",
        *[_format_card_line(card, mark_missing=True) for card in _main_deck_lines(deck)],
    ]

    if warnings:
        sections.extend(["", "Warnings", *[f"- {warning}" for warning in warnings]])

    return "\n".join(sections), warnings


def _main_deck_lines(deck: GeneratedDeckResponse) -> list[DeckCardSchema]:
    grouped_basics: dict[str, DeckCardSchema] = {}
    output: list[DeckCardSchema] = []

    for card in deck.main_deck:
        if card.name not in BASIC_LANDS:
            output.append(card)
            continue

        if card.name in grouped_basics:
            grouped_basics[card.name].quantity += card.quantity
            continue

        grouped_basics[card.name] = card.model_copy()
        output.append(grouped_basics[card.name])

    return output


def _format_card_line(card: DeckCardSchema, *, mark_missing: bool = False) -> str:
    line = f"{card.quantity} {card.name}"
    if mark_missing and not card.is_owned:
        line = f"{line} [missing]"
    return line


def _collect_warnings(deck: GeneratedDeckResponse) -> list[str]:
    warnings: list[str] = []

    for warning in deck.warnings:
        _append_unique(warnings, warning)

    quota_warnings = [
        quota.warning.strip()
        for quota in deck.quota_status
        if quota.warning and quota.warning.strip()
    ]
    if quota_warnings:
        _append_unique(
            warnings,
            f"Deck has quota warnings: {'; '.join(quota_warnings)}",
        )

    for error in deck.validation_errors:
        _append_unique(warnings, f"Validation error: {error}")

    return warnings


def _append_unique(values: list[str], value: str) -> None:
    clean_value = value.strip()
    if clean_value and clean_value not in values:
        values.append(clean_value)
