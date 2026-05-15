"""In-memory domain models for deck generation (not SQLAlchemy)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.score_log import ScoreLog


class SynergyEdge(BaseModel):
    card_a_oracle_id: str
    card_b_oracle_id: str
    weight: float
    metric: str
    sample_size: int = 0


class DeckCard(BaseModel):
    oracle_id: str
    name: str
    is_owned: bool
    quantity: int = 1  # >1 only for basic lands
    roles: list[str]
    package_ids: list[str] = Field(default_factory=list)
    selection_reason: str = ""
    synergy_score: float = 0.0


class QuotaStatus(BaseModel):
    role: str
    target_min: int
    target_max: int
    actual_count: int
    is_satisfied: bool
    warning: str | None = None


class PackageCluster(BaseModel):
    package_id: str
    label: str
    confidence: float
    card_oracle_ids: list[str]
    top_roles: list[str]


class UpgradeSuggestion(BaseModel):
    oracle_id: str
    name: str
    priority: str
    improves_roles: list[str] = Field(default_factory=list)
    improves_packages: list[str] = Field(default_factory=list)
    reason: str
    impact_score: float = 0.0
    replaces_or_supplements: list[str] = Field(default_factory=list)


class CardExplanation(BaseModel):
    oracle_id: str
    name: str
    summary: str
    evidence: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    package_ids: list[str] = Field(default_factory=list)
    synergy_score: float
    is_owned: bool


class GeneratedDeck(BaseModel):
    deck_id: str
    session_id: str
    commander: DeckCard
    main_deck: list[DeckCard]  # exactly 99 cards (with quantities)
    role_breakdown: dict[str, int]
    quota_status: list[QuotaStatus]
    package_breakdown: list[PackageCluster]
    warnings: list[str]
    owned_count: int
    owned_percentage: float
    is_valid: bool
    validation_errors: list[str]
    upgrade_suggestions: list[UpgradeSuggestion] = Field(default_factory=list)
    card_explanations: dict[str, CardExplanation] = Field(default_factory=dict)
    score_logs: list[ScoreLog] = Field(default_factory=list)
