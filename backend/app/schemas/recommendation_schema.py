"""Pydantic schemas for the commander recommendation API."""
from __future__ import annotations

from pydantic import BaseModel


class ExplanationSchema(BaseModel):
    summary: str
    owned_highlights: list[str]
    archetype_label: str
    missing_core_notes: list[str]


class CommanderRecommendationSchema(BaseModel):
    oracle_id: str
    name: str
    color_identity: list[str]
    fit_score: float
    archetype: str
    owned_count: int
    owned_percentage: float
    explanation: ExplanationSchema
    roles_covered: dict[str, int]


class RecommendationResponse(BaseModel):
    session_id: str
    recommendations: list[CommanderRecommendationSchema]
    total: int
