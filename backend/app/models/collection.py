"""SQLAlchemy ORM models for user card collections."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Collection(Base):
    """A user collection, scoped to a session."""

    __tablename__ = "collections"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )

    items: Mapped[list[CollectionItem]] = relationship(
        "CollectionItem",
        back_populates="collection",
        cascade="all, delete-orphan",
    )


class CollectionItem(Base):
    """A single card entry within a collection."""

    __tablename__ = "collection_items"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    collection_id: Mapped[str] = mapped_column(
        String, ForeignKey("collections.id", ondelete="CASCADE"), nullable=False
    )
    oracle_id: Mapped[str] = mapped_column(String, nullable=False)
    canonical_name: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_basic_land: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    collection: Mapped[Collection] = relationship(
        "Collection", back_populates="items"
    )
