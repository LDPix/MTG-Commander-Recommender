"""SC-DECK-011: manual card quality score overrides by scope."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

OverrideScope = Literal["global", "archetype", "commander"]


@dataclass(frozen=True)
class QualityOverride:
    """A final quality score override for one card in one scope."""

    oracle_id: str
    quality_score: float
    scope: OverrideScope = "global"
    scope_key: str | None = None


QUALITY_OVERRIDES: list[QualityOverride] = [
    # Fixture oracle IDs.
    QualityOverride("a2e91c27-6f81-4512-bf20-7a01cb7b6a8e", 1.00),
    QualityOverride("aa000011-0000-4000-0000-000000000011", 0.95),
    QualityOverride("2f0309fa-6d72-9e8f-a1b2-3c4d5e6f7a8b", 0.95),
    QualityOverride("aa000047-0000-4000-0000-000000000047", 0.90),
    QualityOverride("7aebf4a5-1e2d-4f3a-b6c7-8d9e0f1a2b3c", 0.95),
    QualityOverride("aa000037-0000-4000-0000-000000000037", 0.90),
    QualityOverride("9cdf06c7-3a4f-6b5c-d8e9-0f1a2b3c4d5e", 0.95, "archetype", "aristocrats"),
    QualityOverride("aa000056-0000-4000-0000-000000000056", 0.90, "archetype", "aristocrats"),
    # Production oracle IDs from backend/data/oracle-cards.json.
    QualityOverride("6ad8011d-3471-4369-9d68-b264cc027487", 1.00),
    QualityOverride("0bc7f093-bef0-4f1a-852c-4b75ebf54838", 0.95),
    QualityOverride("ca204b66-8d0c-431a-8d34-282f7c2d17da", 0.95),
    QualityOverride("c8b143ad-43ec-4e0d-a440-e348daa31391", 0.90),
    QualityOverride("b1544f21-7e98-461b-aed5-e748b0168c52", 0.95),
    QualityOverride("7735eeba-693b-47e2-bd51-414379cf1016", 0.90),
    QualityOverride("d75b9c82-1b49-4c3e-a1b5-aeef57d6644b", 0.95),
    QualityOverride("7d00fb28-ea6c-49a9-b4af-ffb38860a9a7", 0.15),
    QualityOverride("08c7db90-c0cf-4482-b7ee-bb033e5996d2", 0.05),
    QualityOverride("273b339c-964b-4a18-8eb5-ceb8abcdfd9e", 0.30),
    QualityOverride("1eb9e401-8975-447b-839d-f7cd23897465", 0.10),
    QualityOverride("65986c1b-8e51-4604-b685-d82fa7d1263a", 0.95, "archetype", "aristocrats"),
    QualityOverride("310f141c-7f37-4729-aed6-dd9c09db448d", 0.90, "archetype", "aristocrats"),
]


def get_quality_override(
    oracle_id: str,
    commander_oracle_id: str | None = None,
    archetype: str | None = None,
) -> float | None:
    """Return the highest-priority quality override for this card, if any."""
    for override in QUALITY_OVERRIDES:
        if (
            override.oracle_id == oracle_id
            and override.scope == "commander"
            and override.scope_key == commander_oracle_id
        ):
            return override.quality_score

    for override in QUALITY_OVERRIDES:
        if (
            override.oracle_id == oracle_id
            and override.scope == "archetype"
            and override.scope_key == archetype
        ):
            return override.quality_score

    for override in QUALITY_OVERRIDES:
        if override.oracle_id == oracle_id and override.scope == "global":
            return override.quality_score

    return None
