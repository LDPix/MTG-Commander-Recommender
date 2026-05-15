"""SQLAlchemy ORM model for persisted generated deck artifacts.

FR-14, FR-15: Generated decks are saved after successful generation and
associated with the current session_id and commander.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class SavedDeck(Base):
    """A persisted generated deck artifact, scoped to a session.

    deck_data stores the full GeneratedDeckResponse payload as JSON text,
    preserving the complete card list and metadata for retrieval/export.
    """

    __tablename__ = "saved_decks"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    commander_oracle_id: Mapped[str] = mapped_column(String, nullable=False)
    commander_name: Mapped[str] = mapped_column(String, nullable=False)
    deck_data: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(tz=timezone.utc)
    )
