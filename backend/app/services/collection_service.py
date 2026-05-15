"""Collection service.

Orchestrates CSV import, normalization, and persistence of card collections.
"""
from __future__ import annotations

from app.data_pipeline.collection_normalizer import CollectionNormalizer
from app.data_pipeline.csv_importer import CSVImporter, InvalidFileError
from app.models.collection import Collection
from app.models.collection import CollectionItem
from app.repositories.collection_repo import CollectionRepository
from app.schemas.collection_schema import (
    CollectionChangeSummary,
    CollectionImportResponse,
)


class CollectionService:
    """High-level service for managing user card collections."""

    def __init__(
        self,
        importer: CSVImporter,
        normalizer: CollectionNormalizer,
        repo: CollectionRepository,
    ) -> None:
        self._importer = importer
        self._normalizer = normalizer
        self._repo = repo

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def import_collection(
        self,
        session_id: str,
        file_content: bytes,
        filename: str,
    ) -> CollectionImportResponse:
        """Parse, normalize, and persist a CSV collection for *session_id*.

        If a collection already exists for the session it is replaced
        (reimport semantics).
        """
        return self._do_import(session_id, file_content, filename, replace=False)

    def reimport_collection(
        self,
        session_id: str,
        file_content: bytes,
        filename: str,
    ) -> CollectionImportResponse:
        """Replace an existing collection with fresh CSV content."""
        return self._do_import(session_id, file_content, filename, replace=True)

    def _do_import(
        self,
        session_id: str,
        file_content: bytes,
        filename: str,
        replace: bool,
    ) -> CollectionImportResponse:
        # --- parse ---
        try:
            import_result = self._importer.parse(file_content)
        except InvalidFileError as exc:
            return CollectionImportResponse(
                collection_id="",
                session_id=session_id,
                imported_count=0,
                unknown_cards=[],
                warnings=[],
                success=False,
                error=f"{exc.code}: {exc.message}",
            )

        # --- normalize ---
        norm_result = self._normalizer.normalize(import_result.rows)

        # --- persist ---
        collection = self._repo.get_collection_by_session(session_id)
        previous_items = self._repo.get_items(collection.id) if collection else []
        change_summary = (
            _build_change_summary(previous_items, norm_result.items)
            if collection is not None
            else None
        )
        if collection is None or replace:
            if collection is not None:
                # Delete old collection; create a fresh one below
                self._repo.delete_collection(collection.id)
            collection = self._repo.create_collection(session_id)

        self._repo.upsert_items(collection.id, norm_result.items)

        # Merge warnings from both stages
        all_warnings = [
            {
                "row_index": w.row_index,
                "raw_name": w.raw_name,
                "code": w.code,
                "message": w.message,
            }
            for w in import_result.warnings + norm_result.warnings
        ]

        return CollectionImportResponse(
            collection_id=collection.id,
            session_id=session_id,
            imported_count=len(norm_result.items),
            unknown_cards=norm_result.unknown_cards,
            warnings=all_warnings,
            change_summary=change_summary,
            success=True,
        )

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_collection(self, session_id: str) -> Collection | None:
        """Return the Collection ORM object for *session_id*, or None."""
        return self._repo.get_collection_by_session(session_id)


def _build_change_summary(
    previous_items: list[CollectionItem],
    next_items: list,
) -> CollectionChangeSummary:
    previous_by_id = {
        item.oracle_id: (item.canonical_name, item.quantity) for item in previous_items
    }
    next_by_id = {
        item.oracle_id: (item.canonical_name, item.quantity) for item in next_items
    }

    previous_ids = set(previous_by_id)
    next_ids = set(next_by_id)
    added_ids = next_ids - previous_ids
    removed_ids = previous_ids - next_ids
    shared_ids = previous_ids & next_ids

    quantity_changed_ids = {
        oracle_id
        for oracle_id in shared_ids
        if previous_by_id[oracle_id][1] != next_by_id[oracle_id][1]
    }
    unchanged_ids = shared_ids - quantity_changed_ids

    return CollectionChangeSummary(
        added_count=len(added_ids),
        removed_count=len(removed_ids),
        quantity_changed_count=len(quantity_changed_ids),
        unchanged_count=len(unchanged_ids),
        added_cards=_sorted_names(added_ids, next_by_id),
        removed_cards=_sorted_names(removed_ids, previous_by_id),
        quantity_changed_cards=_sorted_names(quantity_changed_ids, next_by_id),
    )


def _sorted_names(
    oracle_ids: set[str],
    item_map: dict[str, tuple[str, int]],
) -> list[str]:
    return sorted(item_map[oracle_id][0] for oracle_id in oracle_ids)
