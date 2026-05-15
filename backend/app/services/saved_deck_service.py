"""Service for persisted saved/generated deck artifacts.

FR-14, FR-15, FR-16, FR-17, NFR-13: Orchestrates saving a generated deck
artifact and retrieving it by session or id, with session-scoped isolation.
"""
from __future__ import annotations

import json

from app.models.saved_deck import SavedDeck
from app.repositories.saved_deck_repo import SavedDeckRepository
from app.schemas.deck_schema import GeneratedDeckResponse, SavedDeckDetailResponse, SavedDeckSummaryResponse


class SavedDeckService:
    """High-level service for managing persisted generated deck artifacts."""

    def __init__(self, repo: SavedDeckRepository) -> None:
        self._repo = repo

    def save_generated_deck(self, response: GeneratedDeckResponse) -> SavedDeck:
        """Persist a successfully generated deck response.

        FR-14: stores deck_id, session_id, commander reference, created
        timestamp, and full deck data sufficient for retrieval/export.
        Uses the deck_id already present in the response so clients can
        reference the saved deck by the id returned from generation.
        """
        saved = SavedDeck(
            id=response.deck_id,
            session_id=response.session_id,
            commander_oracle_id=response.commander.oracle_id,
            commander_name=response.commander.name,
            deck_data=response.model_dump_json(),
        )
        return self._repo.save(saved)

    def list_by_session(self, session_id: str) -> list[SavedDeckSummaryResponse]:
        """Return summaries of all saved decks for *session_id*.

        FR-16: returns summary list; NFR-13: scoped to the given session.
        """
        records = self._repo.list_by_session(session_id)
        return [_to_summary(r) for r in records]

    def get_by_id_for_session(
        self, deck_id: str, session_id: str
    ) -> SavedDeckDetailResponse | None:
        """Return a saved deck detail scoped to *session_id*, or None.

        FR-17, NFR-13: session-scoped retrieval so Session B cannot access
        Session A's saved decks by id.
        """
        record = self._repo.get_by_id_and_session(deck_id, session_id)
        if record is None:
            return None
        return _to_detail(record)


def _to_summary(record: SavedDeck) -> SavedDeckSummaryResponse:
    return SavedDeckSummaryResponse(
        deck_id=record.id,
        session_id=record.session_id,
        commander_oracle_id=record.commander_oracle_id,
        commander_name=record.commander_name,
        created_at=record.created_at,
    )


def _to_detail(record: SavedDeck) -> SavedDeckDetailResponse:
    deck_data = GeneratedDeckResponse.model_validate(json.loads(record.deck_data))
    return SavedDeckDetailResponse(
        deck_id=record.id,
        session_id=record.session_id,
        commander_oracle_id=record.commander_oracle_id,
        commander_name=record.commander_name,
        created_at=record.created_at,
        deck=deck_data,
    )
