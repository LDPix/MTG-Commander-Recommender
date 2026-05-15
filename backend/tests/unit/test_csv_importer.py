"""Tests for SC-IMPORT-001 + SC-IMPORT-002: CSV collection import."""
from __future__ import annotations

import pytest

from app.data_pipeline.csv_importer import CSVImporter, InvalidFileError
from tests.fixtures.sample_csv_collections import (
    EXTRA_COLUMNS_CSV,
    MALFORMED_COLLECTION_CSV,
    NEGATIVE_QUANTITY_CSV,
    VALID_COLLECTION_CSV,
    VARIANT_HEADERS_CSV,
)


@pytest.fixture
def importer() -> CSVImporter:
    return CSVImporter()


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def test_valid_csv_imports_successfully(importer: CSVImporter) -> None:
    """Standard 3-card CSV parses without warnings."""
    result = importer.parse(VALID_COLLECTION_CSV)
    assert result.valid_rows == 3
    assert len(result.rows) == 3
    assert not result.warnings


def test_csv_quantity_is_parsed(importer: CSVImporter) -> None:
    """Quantity field is correctly converted to int."""
    result = importer.parse(VALID_COLLECTION_CSV)
    qty_map = {r.raw_name: r.quantity for r in result.rows}
    assert qty_map["Sol Ring"] == 1
    assert qty_map["Command Tower"] == 1
    assert qty_map["Swords to Plowshares"] == 2


def test_unknown_card_header_variants(importer: CSVImporter) -> None:
    """'Count' and 'card_name' header variants are accepted."""
    result = importer.parse(VARIANT_HEADERS_CSV)
    assert result.valid_rows == 2
    names = {r.raw_name for r in result.rows}
    assert "Sol Ring" in names
    assert "Command Tower" in names


def test_qty_header_variant(importer: CSVImporter) -> None:
    """'qty' header variant is accepted."""
    csv = "Card Name,qty\nSol Ring,1\nCultivate,2\n"
    result = importer.parse(csv)
    assert result.valid_rows == 2


def test_import_summary_returned(importer: CSVImporter) -> None:
    """Result contains correct total_rows and valid_rows counts."""
    result = importer.parse(MALFORMED_COLLECTION_CSV)
    # rows: "Sol Ring,1", ",2" (bad name), "BadCard,abc" (bad qty), "Cultivate,3"
    assert result.total_rows == 4
    assert result.valid_rows == 2


def test_import_does_not_crash_on_extra_columns(importer: CSVImporter) -> None:
    """Extra columns beyond name/quantity are silently ignored."""
    result = importer.parse(EXTRA_COLUMNS_CSV)
    assert result.valid_rows == 2
    assert not result.warnings


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_empty_file_returns_error(importer: CSVImporter) -> None:
    """Empty file raises InvalidFileError with code EMPTY_FILE."""
    with pytest.raises(InvalidFileError) as exc_info:
        importer.parse("")
    assert exc_info.value.code == "EMPTY_FILE"


def test_empty_bytes_returns_error(importer: CSVImporter) -> None:
    """Empty bytes raises InvalidFileError with code EMPTY_FILE."""
    with pytest.raises(InvalidFileError) as exc_info:
        importer.parse(b"")
    assert exc_info.value.code == "EMPTY_FILE"


def test_header_only_file_returns_error(importer: CSVImporter) -> None:
    """CSV with only a header row raises InvalidFileError with code NO_DATA_ROWS."""
    with pytest.raises(InvalidFileError) as exc_info:
        importer.parse("name,quantity\n")
    assert exc_info.value.code == "NO_DATA_ROWS"


def test_unsupported_file_type_returns_error(importer: CSVImporter) -> None:
    """Binary content raises InvalidFileError with code UNSUPPORTED_FORMAT."""
    binary_data = bytes(range(256)) * 10
    with pytest.raises(InvalidFileError) as exc_info:
        importer.parse(binary_data)
    assert exc_info.value.code in {"UNSUPPORTED_FORMAT", "EMPTY_FILE"}


def test_missing_required_columns_returns_error(importer: CSVImporter) -> None:
    """CSV without name/quantity headers raises UNSUPPORTED_FORMAT."""
    csv = "card,copies\nSol Ring,1\n"
    with pytest.raises(InvalidFileError) as exc_info:
        importer.parse(csv)
    assert exc_info.value.code == "UNSUPPORTED_FORMAT"


# ---------------------------------------------------------------------------
# Warning cases
# ---------------------------------------------------------------------------


def test_malformed_row_skipped(importer: CSVImporter) -> None:
    """Row with non-integer quantity produces a warning; other rows still import."""
    result = importer.parse(MALFORMED_COLLECTION_CSV)
    # "BadCard,abc" should produce a warning
    bad_qty_warnings = [w for w in result.warnings if w.code == "INVALID_QUANTITY"]
    assert len(bad_qty_warnings) >= 1
    assert bad_qty_warnings[0].raw_name == "BadCard"
    # Valid rows (Sol Ring + Cultivate) still in result
    names = {r.raw_name for r in result.rows}
    assert "Sol Ring" in names
    assert "Cultivate" in names


def test_missing_name_row_skipped(importer: CSVImporter) -> None:
    """Row with missing name produces MALFORMED_ROW warning."""
    result = importer.parse(MALFORMED_COLLECTION_CSV)
    malformed = [w for w in result.warnings if w.code == "MALFORMED_ROW"]
    assert len(malformed) >= 1


def test_invalid_quantity_returns_warning(importer: CSVImporter) -> None:
    """Negative or zero quantity produces an INVALID_QUANTITY warning."""
    result = importer.parse(NEGATIVE_QUANTITY_CSV)
    qty_warnings = [w for w in result.warnings if w.code == "INVALID_QUANTITY"]
    assert len(qty_warnings) == 2  # -1 and 0
    # Only "Cultivate,3" is valid
    assert result.valid_rows == 1
    assert result.rows[0].raw_name == "Cultivate"


def test_bytes_input_parsed_correctly(importer: CSVImporter) -> None:
    """Bytes input (UTF-8) is handled the same as str input."""
    result = importer.parse(VALID_COLLECTION_CSV.encode("utf-8"))
    assert result.valid_rows == 3
