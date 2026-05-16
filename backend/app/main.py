"""FastAPI application entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import os
from pathlib import Path

import app.models.card  # noqa: F401
import app.models.collection  # noqa: F401
import app.models.deck  # noqa: F401
import app.models.saved_deck  # noqa: F401
import app.models.score_log  # noqa: F401
from app.api.v1.collection import router as collection_router, set_card_resolver
from app.api.v1.deck import router as deck_router
from app.api.v1.recommendation import router as recommendation_router
from app.data_pipeline.card_resolver import CardResolver
from app.data_pipeline.scryfall_ingest import load_scryfall_bulk_data
from app.data_pipeline.scryfall_tagger import ScryfallTaggerStore, set_scryfall_tagger_store
from app.db.database import Base, _get_async_engine

_DEFAULT_DATA_PATH = Path(__file__).parent.parent / "data" / "oracle-cards.json"
_DEFAULT_TAGGER_PATH = Path(__file__).parent.parent / "data" / "scryfall-tagger-tags.json"


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = _get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    data_path = Path(os.environ.get("SCRYFALL_DATA_PATH", str(_DEFAULT_DATA_PATH)))
    if data_path.exists():
        cards = load_scryfall_bulk_data(data_path)
        set_card_resolver(CardResolver(cards))
    else:
        import logging
        logging.getLogger(__name__).warning(
            "Scryfall data not found at %s — card resolution will be empty. "
            "Download oracle-cards.json and place it at that path.",
            data_path,
        )

    tagger_path = Path(os.environ.get("SCRYFALL_TAGGER_PATH", str(_DEFAULT_TAGGER_PATH)))
    if tagger_path.exists():
        store = ScryfallTaggerStore.from_file(tagger_path)
        set_scryfall_tagger_store(store)
        print(f"Scryfall Tagger store loaded: {len(store)} cards tagged.")

    yield


app = FastAPI(
    title="MTG Commander Recommender",
    version="0.1.0",
    description="Recommends Commander decks based on a player's card collection.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(collection_router)
app.include_router(recommendation_router)
app.include_router(deck_router, prefix="/api/v1/decks", tags=["decks"])


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Simple health check endpoint."""
    return {"status": "ok"}
