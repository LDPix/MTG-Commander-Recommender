"""Tests for SC-DECK-011 quality override lookup."""
from __future__ import annotations

from app.recommendation import quality_overrides
from app.recommendation.quality_overrides import QualityOverride, get_quality_override


def test_global_override_returned_for_known_staple() -> None:
    assert get_quality_override("a2e91c27-6f81-4512-bf20-7a01cb7b6a8e") == 1.0


def test_commander_override_takes_priority_over_global(monkeypatch) -> None:
    monkeypatch.setattr(
        quality_overrides,
        "QUALITY_OVERRIDES",
        [
            QualityOverride("test-card", 0.2, "global"),
            QualityOverride("test-card", 0.9, "commander", "test-commander"),
        ],
    )

    assert get_quality_override("test-card", commander_oracle_id="test-commander") == 0.9


def test_archetype_override_takes_priority_over_global(monkeypatch) -> None:
    monkeypatch.setattr(
        quality_overrides,
        "QUALITY_OVERRIDES",
        [
            QualityOverride("test-card", 0.2, "global"),
            QualityOverride("test-card", 0.8, "archetype", "aristocrats"),
        ],
    )

    assert get_quality_override("test-card", archetype="aristocrats") == 0.8


def test_no_override_returns_none() -> None:
    assert get_quality_override("unknown-card") is None


def test_commander_override_only_applies_for_matching_commander(monkeypatch) -> None:
    monkeypatch.setattr(
        quality_overrides,
        "QUALITY_OVERRIDES",
        [
            QualityOverride("test-card", 0.2, "global"),
            QualityOverride("test-card", 0.9, "commander", "test-commander"),
        ],
    )

    assert get_quality_override("test-card", commander_oracle_id="other") == 0.2
