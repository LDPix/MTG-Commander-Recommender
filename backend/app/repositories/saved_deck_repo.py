"""Repository for persisted saved/generated deck artifacts.

FR-14, FR-15, FR-16, FR-17: Provides save, list-by-session, and
get-by-id data-access methods for SavedDeck records.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.saved_deck import SavedDeck


class SavedDeckRepository:
    """Data-access layer for SavedDeck records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, saved_deck: SavedDeck) -> SavedDeck:
        """Persist a SavedDeck record and return it."""
        self._session.add(saved_deck)
        self._session.commit()
        self._session.refresh(saved_deck)
        return saved_deck

    def list_by_session(self, session_id: str) -> list[SavedDeck]:
        """Return all saved decks for *session_id*, ordered by creation time."""
        return (
            self._session.query(SavedDeck)
            .filter(SavedDeck.session_id == session_id)
            .order_by(SavedDeck.created_at.desc())
            .all()
        )

    def get_by_id(self, deck_id: str) -> SavedDeck | None:
        """Return a saved deck by primary key, or None."""
        return self._session.get(SavedDeck, deck_id)

    def get_by_id_and_session(
        self, deck_id: str, session_id: str
    ) -> SavedDeck | None:
        """Return a saved deck by id scoped to session_id, or None.

        NFR-13: enforces session-scoped access so one session cannot
        retrieve another session's saved deck by guessing the id.
        """
        return (
            self._session.query(SavedDeck)
            .filter(
                SavedDeck.id == deck_id,
                SavedDeck.session_id == session_id,
            )
            .first()
        )
