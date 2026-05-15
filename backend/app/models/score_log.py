"""Internal deterministic score logs for recommendation debugging."""
from __future__ import annotations

from pydantic import BaseModel, Field


DATA_VERSION = "local-card-catalog-v1"


class ScoreLog(BaseModel):
    session_id: str
    scope: str
    data_version: str = DATA_VERSION
    subject_id: str
    score_components: dict[str, float]
    selected_reasons: list[str]
    warnings: list[str] = Field(default_factory=list)
