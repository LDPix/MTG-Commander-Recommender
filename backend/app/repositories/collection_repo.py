"""Collection repository.

Provides data-access methods for Collection and CollectionItem records.
Uses synchronous SQLAlchemy sessions so it works with both SQLite (tests)
and PostgreSQL (production via a sync engine wrapper).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.data_pipeline.collection_normalizer import NormalizedCollectionItem
from app.models.collection import Collection, CollectionItem


class CollectionRepository:
    """Data-access layer for collection records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Create / query
    # ------------------------------------------------------------------

    def create_collection(self, session_id: str) -> Collection:
        """Create a new empty collection for *session_id*."""
        now = datetime.now(tz=timezone.utc)
        collection = Collection(
            id=str(uuid.uuid4()),
            session_id=session_id,
            created_at=now,
            updated_at=now,
        )
        self._session.add(collection)
        self._session.commit()
        self._session.refresh(collection)
        return collection

    def get_collection(self, collection_id: str) -> Collection | None:
        """Return a collection by its primary key, or None."""
        return self._session.get(Collection, collection_id)

    def get_collection_by_session(self, session_id: str) -> Collection | None:
        """Return the collection for *session_id*, or None."""
        return (
            self._session.query(Collection)
            .filter(Collection.session_id == session_id)
            .first()
        )

    # ------------------------------------------------------------------
    # Items
    # ------------------------------------------------------------------

    def upsert_items(
        self, collection_id: str, items: list[NormalizedCollectionItem]
    ) -> None:
        """Replace all items in *collection_id* with *items*.

        Deletes existing items first, then inserts the new set.
        """
        self._session.query(CollectionItem).filter(
            CollectionItem.collection_id == collection_id
        ).delete()
        for item in items:
            db_item = CollectionItem(
                id=str(uuid.uuid4()),
                collection_id=collection_id,
                oracle_id=item.oracle_id,
                canonical_name=item.canonical_name,
                quantity=item.quantity,
                is_basic_land=item.is_basic_land,
            )
            self._session.add(db_item)
        # Update updated_at timestamp on the parent collection
        collection = self._session.get(Collection, collection_id)
        if collection is not None:
            collection.updated_at = datetime.now(tz=timezone.utc)
        self._session.commit()

    def get_items(self, collection_id: str) -> list[CollectionItem]:
        """Return all items for *collection_id*."""
        return (
            self._session.query(CollectionItem)
            .filter(CollectionItem.collection_id == collection_id)
            .all()
        )

    def get_items_by_color_identity(
        self, collection_id: str, colors: list[str]
    ) -> list[CollectionItem]:
        """Return items filtered by color identity.

        Note: color_identity is not stored on CollectionItem — this method
        is a placeholder that currently returns all items for the collection.
        A full implementation would join against a card catalogue table.
        """
        return self.get_items(collection_id)

    def delete_collection(self, collection_id: str) -> None:
        """Delete a collection and all its items (cascade)."""
        collection = self._session.get(Collection, collection_id)
        if collection is not None:
            self._session.delete(collection)
            self._session.commit()
