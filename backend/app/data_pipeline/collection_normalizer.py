"""Collection normalizer.

Resolves raw card names from a CSV import to canonical oracle identities
and merges duplicate printings into single NormalizedCollectionItem entries.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.data_pipeline.card_resolver import CardNotFoundError, CardResolver
from app.data_pipeline.csv_importer import CollectionRow, ImportWarning


@dataclass
class NormalizedCollectionItem:
    oracle_id: str
    canonical_name: str
    quantity: int
    source_names: list[str] = field(default_factory=list)
    is_basic_land: bool = False


@dataclass
class NormalizationResult:
    items: list[NormalizedCollectionItem] = field(default_factory=list)
    warnings: list[ImportWarning] = field(default_factory=list)
    unknown_cards: list[str] = field(default_factory=list)


class CollectionNormalizer:
    """Resolves raw ImportResult rows to canonical card identities."""

    def __init__(self, resolver: CardResolver) -> None:
        self._resolver = resolver

    def normalize(self, rows: list[CollectionRow]) -> NormalizationResult:
        """Normalize a list of CollectionRow objects.

        - Resolves each raw_name via CardResolver.
        - Merges rows that share the same oracle_id (summing quantities).
        - Rows that cannot be resolved are added to warnings/unknown_cards and
          excluded from items.

        Args:
            rows: Parsed and validated CSV rows.

        Returns:
            NormalizationResult with canonical items, warnings, and unknowns.
        """
        result = NormalizationResult()
        # oracle_id -> NormalizedCollectionItem (accumulator)
        accumulator: dict[str, NormalizedCollectionItem] = {}

        for row in rows:
            try:
                canonical = self._resolver.resolve(row.raw_name)
            except CardNotFoundError:
                result.unknown_cards.append(row.raw_name)
                result.warnings.append(
                    ImportWarning(
                        row_index=row.row_index,
                        raw_name=row.raw_name,
                        code="UNKNOWN_CARD",
                        message=(
                            f"Row {row.row_index}: card {row.raw_name!r} "
                            "could not be resolved."
                        ),
                    )
                )
                continue

            oid = canonical.oracle_id
            if oid in accumulator:
                item = accumulator[oid]
                item.quantity += row.quantity
                if row.raw_name not in item.source_names:
                    item.source_names.append(row.raw_name)
            else:
                accumulator[oid] = NormalizedCollectionItem(
                    oracle_id=oid,
                    canonical_name=canonical.name,
                    quantity=row.quantity,
                    source_names=[row.raw_name],
                    is_basic_land=canonical.is_basic_land,
                )

        result.items = list(accumulator.values())
        return result
