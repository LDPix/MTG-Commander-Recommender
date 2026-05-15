"""Card repository.

Provides data-access methods for canonical card data stored in PostgreSQL.
Follows the Repository pattern: the service layer only calls this, never
the DB directly.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class CardRepository:
    """Data-access layer for canonical card records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # Placeholder – full implementation follows SC-DATA-001 DB persistence work
