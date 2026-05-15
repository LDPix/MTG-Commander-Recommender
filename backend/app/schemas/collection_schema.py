"""Pydantic response schemas for the collection API."""
from __future__ import annotations

from pydantic import BaseModel


class CollectionChangeSummary(BaseModel):
    added_count: int = 0
    removed_count: int = 0
    quantity_changed_count: int = 0
    unchanged_count: int = 0
    added_cards: list[str] = []
    removed_cards: list[str] = []
    quantity_changed_cards: list[str] = []


class CollectionImportResponse(BaseModel):
    collection_id: str
    session_id: str
    imported_count: int
    unknown_cards: list[str]
    warnings: list[dict]
    change_summary: CollectionChangeSummary | None = None
    success: bool
    error: str | None = None


class CollectionItemSchema(BaseModel):
    oracle_id: str
    canonical_name: str
    quantity: int
    is_basic_land: bool


class CollectionResponse(BaseModel):
    collection_id: str
    session_id: str
    items: list[CollectionItemSchema]
    total_items: int
