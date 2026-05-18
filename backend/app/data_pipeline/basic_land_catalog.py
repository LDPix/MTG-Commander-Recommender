"""Canonical basic-land metadata helpers for catalog ingestion."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from app.models.card import CardData, is_basic_land_type_line


BASIC_LAND_TYPE_LINES: dict[str, str] = {
    "Plains": "Basic Land — Plains",
    "Island": "Basic Land — Island",
    "Swamp": "Basic Land — Swamp",
    "Mountain": "Basic Land — Mountain",
    "Forest": "Basic Land — Forest",
    "Wastes": "Basic Land",
    "Snow-Covered Plains": "Basic Snow Land — Plains",
    "Snow-Covered Island": "Basic Snow Land — Island",
    "Snow-Covered Swamp": "Basic Snow Land — Swamp",
    "Snow-Covered Mountain": "Basic Snow Land — Mountain",
    "Snow-Covered Forest": "Basic Snow Land — Forest",
    "Snow-Covered Wastes": "Basic Snow Land",
}

BASIC_LAND_NAMES: frozenset[str] = frozenset(BASIC_LAND_TYPE_LINES)


class BasicLandRecord(Protocol):
    name: str
    oracle_id: str
    type_line: str
    is_basic_land: bool


@dataclass(frozen=True)
class BasicLandAuditIssue:
    """A basic-land catalog record that does not match canonical metadata."""

    name: str
    oracle_id: str | None
    type_line: str | None
    reason: str


def normalize_basic_land_card(card: CardData) -> CardData:
    """Backfill known basic-land type lines before canonical indexing."""
    canonical_type_line = BASIC_LAND_TYPE_LINES.get(card.name)
    if canonical_type_line is None:
        return card
    if card.is_basic_land and card.type_line == canonical_type_line:
        return card
    return card.model_copy(update={"type_line": canonical_type_line})


def audit_basic_land_records(
    cards: Iterable[BasicLandRecord],
) -> list[BasicLandAuditIssue]:
    """Validate that required basics resolve as basic lands in a catalog view."""
    records_by_name: dict[str, BasicLandRecord] = {
        card.name: card for card in cards if card.name in BASIC_LAND_NAMES
    }
    issues: list[BasicLandAuditIssue] = []

    for name, expected_type_line in BASIC_LAND_TYPE_LINES.items():
        record = records_by_name.get(name)
        if record is None:
            issues.append(
                BasicLandAuditIssue(
                    name=name,
                    oracle_id=None,
                    type_line=None,
                    reason="missing required basic-land record",
                )
            )
            continue

        if record.type_line != expected_type_line:
            issues.append(
                BasicLandAuditIssue(
                    name=name,
                    oracle_id=record.oracle_id,
                    type_line=record.type_line,
                    reason=f"expected type line {expected_type_line!r}",
                )
            )
        if not record.is_basic_land or not is_basic_land_type_line(record.type_line):
            issues.append(
                BasicLandAuditIssue(
                    name=name,
                    oracle_id=record.oracle_id,
                    type_line=record.type_line,
                    reason="record is not flagged as a basic land",
                )
            )

    return issues
