"""Request and response schemas for deck generation (SC-API-003)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class DeckGenerateRequest(BaseModel):
    session_id: str
    commander_oracle_id: str

    @field_validator("session_id", "commander_oracle_id")
    @classmethod
    def must_be_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must be a non-empty string")
        return v


class DeckCardSchema(BaseModel):
    oracle_id: str
    name: str
    is_owned: bool
    quantity: int
    roles: list[str]
    assigned_role: str | None = None
    secondary_role_credit: dict[str, float] = Field(default_factory=dict)
    package_ids: list[str]
    selection_reason: str
    synergy_score: float


class QuotaStatusSchema(BaseModel):
    role: str
    target_min: int
    target_max: int
    actual_count: int
    is_satisfied: bool
    warning: str | None
    credit_sum: float = 0.0
    credit_satisfied: bool = True
    credit_warning: str | None = None


class PackageSchema(BaseModel):
    package_id: str
    label: str
    confidence: float
    card_oracle_ids: list[str]
    top_roles: list[str]
    activation_status: str = "detected"
    selected_count: int = 0
    raw_selected_count: int = 0


class UpgradeSuggestionSchema(BaseModel):
    oracle_id: str
    name: str
    priority: str
    improves_roles: list[str]
    improves_packages: list[str]
    reason: str
    impact_score: float
    replaces_or_supplements: list[str]


class CardExplanationSchema(BaseModel):
    oracle_id: str
    name: str
    summary: str
    evidence: list[str]
    roles: list[str]
    package_ids: list[str]
    synergy_score: float
    is_owned: bool


class StrategicCoherenceSchema(BaseModel):
    primary_plan: str | None = None
    confidence: float
    active_package_ids: list[str]
    on_plan_count: int
    off_plan_count: int
    warning_card_oracle_ids: list[str]
    warnings: list[str]
    confidence_cap_reasons: list[str] = Field(default_factory=list)


class GeneratedDeckResponse(BaseModel):
    deck_id: str
    session_id: str
    generation_status: Literal[
        "success",
        "failed_validation",
        "failed_quality",
        "needs_repair",
        "low_confidence",
        "generated_with_collection_gap",
    ] = "success"
    commander: DeckCardSchema
    main_deck: list[DeckCardSchema]
    role_breakdown: dict[str, int]
    quota_status: list[QuotaStatusSchema]
    package_breakdown: list[PackageSchema]
    warnings: list[str]
    owned_count: int
    owned_percentage: float
    is_valid: bool
    validation_errors: list[str]
    upgrade_suggestions: list[UpgradeSuggestionSchema] = Field(default_factory=list)
    card_explanations: dict[str, CardExplanationSchema] = Field(default_factory=dict)
    strategic_coherence: StrategicCoherenceSchema | None = None

    @model_validator(mode="after")
    def failed_validation_status_must_be_explicit(self) -> "GeneratedDeckResponse":
        if not self.is_valid or self.validation_errors:
            self.generation_status = "failed_validation"
        return self


class SavedDeckSummaryResponse(BaseModel):
    """Summary of a persisted saved/generated deck (FR-16)."""

    deck_id: str
    session_id: str
    commander_oracle_id: str
    commander_name: str
    created_at: datetime


class SavedDeckDetailResponse(BaseModel):
    """Full detail of a persisted saved/generated deck (FR-17)."""

    deck_id: str
    session_id: str
    commander_oracle_id: str
    commander_name: str
    created_at: datetime
    deck: GeneratedDeckResponse


class SavedDeckListResponse(BaseModel):
    """Envelope for saved deck summary list (FR-16)."""

    decks: list[SavedDeckSummaryResponse]


class DeckExportRequest(BaseModel):
    deck: GeneratedDeckResponse

    @model_validator(mode="after")
    def deck_count_must_be_structurally_possible(self) -> "DeckExportRequest":
        if self.deck.generation_status == "failed_validation" or not self.deck.is_valid:
            raise ValueError("Cannot export invalid generated deck")
        if self.deck.validation_errors:
            raise ValueError("Cannot export deck with validation errors")
        if self.deck.commander.quantity != 1:
            raise ValueError("Commander export requires exactly one commander")

        main_deck_count = sum(card.quantity for card in self.deck.main_deck)
        if main_deck_count != 99:
            raise ValueError("Commander export requires 99 main-deck cards")

        return self


class DeckExportResponse(BaseModel):
    format: str = "plaintext"
    text: str
    warnings: list[str]
