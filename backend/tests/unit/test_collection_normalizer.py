"""Tests for SC-IMPORT-003: Collection normalizer."""
from __future__ import annotations

import pytest

from app.data_pipeline.card_resolver import CardResolver
from app.data_pipeline.collection_normalizer import CollectionNormalizer
from app.data_pipeline.csv_importer import CollectionRow
from app.models.card import CardData


@pytest.fixture
def normalizer(sample_card_resolver: CardResolver) -> CollectionNormalizer:
    return CollectionNormalizer(sample_card_resolver)


def _row(name: str, qty: int = 1, idx: int = 1) -> CollectionRow:
    return CollectionRow(raw_name=name, quantity=qty, row_index=idx)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_imported_card_maps_to_canonical_id(normalizer: CollectionNormalizer) -> None:
    """A known card resolves to a non-empty oracle_id."""
    result = normalizer.normalize([_row("Sol Ring")])
    assert len(result.items) == 1
    item = result.items[0]
    assert item.oracle_id == "a2e91c27-6f81-4512-bf20-7a01cb7b6a8e"
    assert item.canonical_name == "Sol Ring"
    assert item.quantity == 1


def test_case_insensitive_resolution(normalizer: CollectionNormalizer) -> None:
    """Card resolution is case-insensitive."""
    result = normalizer.normalize([_row("sol ring")])
    assert len(result.items) == 1
    assert result.items[0].canonical_name == "Sol Ring"


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------


def test_duplicate_rows_merge_quantities(normalizer: CollectionNormalizer) -> None:
    """Two rows for the same card are merged with summed quantity."""
    rows = [_row("Sol Ring", qty=1, idx=1), _row("Sol Ring", qty=2, idx=2)]
    result = normalizer.normalize(rows)
    assert len(result.items) == 1
    assert result.items[0].quantity == 3


def test_alternate_printings_merge(
    sample_cards: list[CardData],
    sample_card_resolver: CardResolver,
) -> None:
    """Two rows for the same card (same oracle_id) merge into one item."""
    normalizer = CollectionNormalizer(sample_card_resolver)
    # Use the main name and a face name for the MDFC (both resolve to same oracle_id)
    rows = [
        _row("Valki, God of Lies", qty=1, idx=1),
        _row("Tibalt, Cosmic Impostor", qty=1, idx=2),
    ]
    result = normalizer.normalize(rows)
    assert len(result.items) == 1
    assert result.items[0].quantity == 2
    assert "Valki, God of Lies" in result.items[0].source_names or \
           "Tibalt, Cosmic Impostor" in result.items[0].source_names


# ---------------------------------------------------------------------------
# Unknown cards
# ---------------------------------------------------------------------------


def test_unknown_cards_excluded_from_owned_pool(
    normalizer: CollectionNormalizer,
) -> None:
    """Unknown card is NOT added to items."""
    result = normalizer.normalize([_row("Definitely Fake Card XYZ")])
    assert len(result.items) == 0
    assert "Definitely Fake Card XYZ" in result.unknown_cards


def test_normalization_report_includes_warnings(
    normalizer: CollectionNormalizer,
) -> None:
    """Unknown card produces an UNKNOWN_CARD warning."""
    result = normalizer.normalize([_row("Unknown Card ABC")])
    assert any(w.code == "UNKNOWN_CARD" for w in result.warnings)
    assert result.warnings[0].raw_name == "Unknown Card ABC"


def test_mixed_known_and_unknown(normalizer: CollectionNormalizer) -> None:
    """Known cards are collected even when some are unknown."""
    rows = [
        _row("Sol Ring", idx=1),
        _row("Fake Card 999", idx=2),
        _row("Command Tower", idx=3),
    ]
    result = normalizer.normalize(rows)
    assert len(result.items) == 2
    assert len(result.unknown_cards) == 1


# ---------------------------------------------------------------------------
# Basic lands
# ---------------------------------------------------------------------------


def test_basic_land_flagged_correctly(normalizer: CollectionNormalizer) -> None:
    """Basic land cards have is_basic_land=True."""
    result = normalizer.normalize([_row("Forest")])
    assert len(result.items) == 1
    assert result.items[0].is_basic_land is True


def test_non_basic_land_not_flagged(normalizer: CollectionNormalizer) -> None:
    """Non-basic land cards have is_basic_land=False."""
    result = normalizer.normalize([_row("Command Tower")])
    assert result.items[0].is_basic_land is False
