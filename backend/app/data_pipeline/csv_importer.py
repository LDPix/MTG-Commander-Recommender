"""CSV collection import layer.

Parses user-uploaded CSV files containing card collections and returns
structured ImportResult objects with validated rows and warnings.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field


MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

# Column name aliases (lower-cased for case-insensitive comparison)
_NAME_ALIASES = {"name", "card_name", "card name", "card"}
_QUANTITY_ALIASES = {"quantity", "count", "qty", "amount"}


class InvalidFileError(Exception):
    """Raised when the file cannot be parsed as a CSV collection."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class CollectionRow:
    raw_name: str
    quantity: int
    set_code: str | None = None
    collector_number: str | None = None
    row_index: int = 0


@dataclass
class ImportWarning:
    row_index: int
    raw_name: str
    code: str  # "UNKNOWN_CARD", "MALFORMED_ROW", "INVALID_QUANTITY"
    message: str


@dataclass
class ImportResult:
    rows: list[CollectionRow] = field(default_factory=list)
    warnings: list[ImportWarning] = field(default_factory=list)
    total_rows: int = 0
    valid_rows: int = 0
    unknown_cards: list[str] = field(default_factory=list)


def _detect_column(headers: list[str], aliases: set[str]) -> int | None:
    """Return index of the first header that matches one of the aliases, or None."""
    for idx, h in enumerate(headers):
        if h.strip().lower() in aliases:
            return idx
    return None


class CSVImporter:
    """Parses CSV file content into a collection of ImportResult rows."""

    def parse(self, content: str | bytes) -> ImportResult:
        """Parse CSV content into an ImportResult.

        Args:
            content: Raw file content as str or bytes.

        Returns:
            ImportResult with all valid rows and warnings for skipped rows.

        Raises:
            InvalidFileError: When the file is empty, has no data rows, is too
                large, or is not parseable as CSV.
        """
        # ------------------------------------------------------------------ #
        # 1. Decode bytes
        # ------------------------------------------------------------------ #
        if isinstance(content, bytes):
            if len(content) > MAX_FILE_SIZE:
                raise InvalidFileError("FILE_TOO_LARGE", "File exceeds 10 MB limit.")
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise InvalidFileError(
                    "UNSUPPORTED_FORMAT",
                    "File could not be decoded as UTF-8 text.",
                )
        else:
            text = content

        # ------------------------------------------------------------------ #
        # 2. Empty file check
        # ------------------------------------------------------------------ #
        stripped = text.strip()
        if not stripped:
            raise InvalidFileError("EMPTY_FILE", "The uploaded file is empty.")

        # ------------------------------------------------------------------ #
        # 3. CSV parse
        # ------------------------------------------------------------------ #
        try:
            reader = csv.reader(io.StringIO(stripped))
            all_rows = list(reader)
        except Exception:
            raise InvalidFileError(
                "UNSUPPORTED_FORMAT", "Content could not be parsed as CSV."
            )

        if not all_rows:
            raise InvalidFileError("EMPTY_FILE", "The uploaded file is empty.")

        # ------------------------------------------------------------------ #
        # 4. Binary / non-CSV content check
        #    Heuristic: if the first row has no recognisable header, check
        #    whether it looks like binary garbage (non-printable bytes).
        # ------------------------------------------------------------------ #
        first_row_raw = all_rows[0]
        # Check the original text for non-printable chars (excluding common
        # whitespace). If >5 % of chars are non-printable, treat as binary.
        non_printable = sum(
            1 for c in stripped if ord(c) < 32 and c not in "\t\r\n"
        )
        if len(stripped) > 0 and non_printable / len(stripped) > 0.05:
            raise InvalidFileError(
                "UNSUPPORTED_FORMAT",
                "File appears to be binary content, not a CSV.",
            )

        # ------------------------------------------------------------------ #
        # 5. Header detection
        # ------------------------------------------------------------------ #
        headers = [h.strip() for h in first_row_raw]
        name_col = _detect_column(headers, _NAME_ALIASES)
        qty_col = _detect_column(headers, _QUANTITY_ALIASES)

        if name_col is None or qty_col is None:
            raise InvalidFileError(
                "UNSUPPORTED_FORMAT",
                "CSV must contain 'name' and 'quantity' columns "
                "(or accepted variants).",
            )

        # Detect optional columns
        set_col: int | None = None
        cn_col: int | None = None
        for idx, h in enumerate(headers):
            hl = h.lower()
            if hl == "set_code":
                set_col = idx
            elif hl in {"collector_number", "collector number"}:
                cn_col = idx

        # ------------------------------------------------------------------ #
        # 6. Data rows
        # ------------------------------------------------------------------ #
        data_rows = all_rows[1:]
        if not data_rows:
            raise InvalidFileError(
                "NO_DATA_ROWS", "The CSV file contains a header but no data rows."
            )

        result = ImportResult()
        result.total_rows = len(data_rows)

        for row_index, row in enumerate(data_rows, start=1):
            # Skip completely blank lines
            if not any(cell.strip() for cell in row):
                result.total_rows -= 1
                continue

            # --- name ---
            raw_name = row[name_col].strip() if name_col < len(row) else ""
            if not raw_name:
                result.warnings.append(
                    ImportWarning(
                        row_index=row_index,
                        raw_name="",
                        code="MALFORMED_ROW",
                        message=f"Row {row_index}: missing card name.",
                    )
                )
                continue

            # --- quantity ---
            qty_raw = row[qty_col].strip() if qty_col < len(row) else ""
            if not qty_raw:
                result.warnings.append(
                    ImportWarning(
                        row_index=row_index,
                        raw_name=raw_name,
                        code="MALFORMED_ROW",
                        message=f"Row {row_index}: missing quantity.",
                    )
                )
                continue

            try:
                quantity = int(qty_raw)
            except ValueError:
                result.warnings.append(
                    ImportWarning(
                        row_index=row_index,
                        raw_name=raw_name,
                        code="INVALID_QUANTITY",
                        message=(
                            f"Row {row_index}: quantity {qty_raw!r} is not an integer."
                        ),
                    )
                )
                continue

            if quantity <= 0:
                result.warnings.append(
                    ImportWarning(
                        row_index=row_index,
                        raw_name=raw_name,
                        code="INVALID_QUANTITY",
                        message=(
                            f"Row {row_index}: quantity must be > 0, got {quantity}."
                        ),
                    )
                )
                continue

            # --- optional columns ---
            set_code = (
                row[set_col].strip() or None
                if set_col is not None and set_col < len(row)
                else None
            )
            collector_number = (
                row[cn_col].strip() or None
                if cn_col is not None and cn_col < len(row)
                else None
            )

            result.rows.append(
                CollectionRow(
                    raw_name=raw_name,
                    quantity=quantity,
                    set_code=set_code,
                    collector_number=collector_number,
                    row_index=row_index,
                )
            )
            result.valid_rows += 1

        return result
