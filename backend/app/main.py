"""FastAPI application entry point."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.collection import router as collection_router
from app.api.v1.deck import router as deck_router
from app.api.v1.recommendation import router as recommendation_router

app = FastAPI(
    title="MTG Commander Recommender",
    version="0.1.0",
    description="Recommends Commander decks based on a player's card collection.",
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
