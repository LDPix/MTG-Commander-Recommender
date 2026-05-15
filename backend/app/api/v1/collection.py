"""Collection import API endpoints (v1)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.data_pipeline.card_resolver import CardResolver
from app.data_pipeline.collection_normalizer import CollectionNormalizer
from app.data_pipeline.csv_importer import CSVImporter
from app.db.database import get_sync_db
from app.repositories.collection_repo import CollectionRepository
from app.schemas.collection_schema import (
    CollectionImportResponse,
    CollectionItemSchema,
    CollectionResponse,
)
from app.services.collection_service import CollectionService

router = APIRouter(prefix="/api/v1/collections", tags=["collections"])

# ---------------------------------------------------------------------------
# Dependency: card resolver
# A production app would load this once at startup from the DB; here we
# provide a module-level singleton that tests can override via
# dependency injection.
# ---------------------------------------------------------------------------
_card_resolver: CardResolver | None = None


def get_card_resolver() -> CardResolver:
    """Return the global CardResolver instance."""
    if _card_resolver is None:
        return CardResolver([])
    return _card_resolver


def set_card_resolver(resolver: CardResolver) -> None:
    """Set the global CardResolver (used in tests and startup)."""
    global _card_resolver
    _card_resolver = resolver


# ---------------------------------------------------------------------------
# Dependency: DB session
# Override this in tests to inject an in-memory SQLite session.
# ---------------------------------------------------------------------------


def _get_db_session() -> Session:  # type: ignore[return]
    """Wrapped dependency so tests can override via app.dependency_overrides."""
    yield from get_sync_db()


# ---------------------------------------------------------------------------
# Dependency: CollectionService
# ---------------------------------------------------------------------------


def _build_service(
    db: Session = Depends(_get_db_session),
    resolver: CardResolver = Depends(get_card_resolver),
) -> CollectionService:
    importer = CSVImporter()
    normalizer = CollectionNormalizer(resolver)
    repo = CollectionRepository(db)
    return CollectionService(importer, normalizer, repo)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/import", response_model=CollectionImportResponse)
async def import_collection(
    file: UploadFile,
    x_session_id: str = Header(..., alias="X-Session-Id"),
    service: CollectionService = Depends(_build_service),
) -> CollectionImportResponse:
    """Import a CSV collection file for the authenticated session."""
    content = await file.read()
    return service.import_collection(
        session_id=x_session_id,
        file_content=content,
        filename=file.filename or "",
    )


@router.get("/{session_id}", response_model=CollectionResponse)
def get_collection(
    session_id: str,
    service: CollectionService = Depends(_build_service),
) -> CollectionResponse:
    """Retrieve the collection for a given session."""
    collection = service.get_collection(session_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found.")

    items = service._repo.get_items(collection.id)
    return CollectionResponse(
        collection_id=collection.id,
        session_id=collection.session_id,
        items=[
            CollectionItemSchema(
                oracle_id=i.oracle_id,
                canonical_name=i.canonical_name,
                quantity=i.quantity,
                is_basic_land=i.is_basic_land,
            )
            for i in items
        ],
        total_items=len(items),
    )
