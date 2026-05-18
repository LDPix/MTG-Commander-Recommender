"""Tests for SC-CMD-005: commander support confidence tier."""
from __future__ import annotations

import functools
from pathlib import Path

from app.data_pipeline.card_resolver import CardResolver
from app.data_pipeline.scryfall_ingest import load_scryfall_bulk_data
from app.models.deck import DeckCard, GeneratedDeck, StrategicCoherenceReport
from app.services.deck_generation_service import _build_deck_score_logs
from app.recommendation.commander_pool import CommanderPool
from app.recommendation.commander_profiles import (
    COMMANDER_SUPPORT_TIERS,
    GRETA_FIXTURE_ORACLE_ID,
    GRETA_REAL_ORACLE_ID,
    TOLUZ_FIXTURE_ORACLE_ID,
    TOLUZ_REAL_ORACLE_ID,
    get_commander_profile_source,
    get_commander_negative_evidence,
    get_commander_plan_override,
    get_commander_positive_evidence,
    get_support_tier,
)
from app.recommendation.commander_recommender import CommanderRecommender
from app.recommendation.commander_scorer import CommanderScorer
from app.recommendation.role_tagger import RuleTagger

MEREN_ORACLE_ID = "4b2521bc-8f94-1a0b-c3d4-5e6f7a8b9c0d"
ATRAXA_ORACLE_ID = "aa000082-0000-4000-0000-000000000082"
PROSSH_ORACLE_ID = "aa000083-0000-4000-0000-000000000083"
UNKNOWN_ORACLE_ID = "00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# get_support_tier pure function
# ---------------------------------------------------------------------------

def test_get_support_tier_defaults_to_fallback() -> None:
    """Any oracle_id not in the tier map returns 'fallback'."""
    assert get_support_tier(UNKNOWN_ORACLE_ID) == "fallback"


def test_curated_commander_has_curated_confidence() -> None:
    """Meren and Atraxa are classified as 'curated'."""
    assert get_support_tier(MEREN_ORACLE_ID) == "curated"
    assert get_support_tier(ATRAXA_ORACLE_ID) == "curated"


def test_profiled_commander_has_profiled_confidence() -> None:
    """Prossh is classified as 'profiled'."""
    assert get_support_tier(PROSSH_ORACLE_ID) == "profiled"


def test_unknown_legal_commander_has_fallback_confidence() -> None:
    """An oracle_id absent from the tier map gets 'fallback'."""
    assert get_support_tier("totally-unknown-id") == "fallback"


def test_support_confidence_is_deterministic() -> None:
    """Calling get_support_tier twice with the same id returns the same result."""
    tier_1 = get_support_tier(MEREN_ORACLE_ID)
    tier_2 = get_support_tier(MEREN_ORACLE_ID)
    assert tier_1 == tier_2


# ---------------------------------------------------------------------------
# CandidateCommander.support_tier propagation through the pool
# ---------------------------------------------------------------------------

def test_candidate_commander_carries_support_tier(sample_card_resolver) -> None:
    """CommanderPool.build_candidate_pool populates support_tier on each candidate."""
    pool = CommanderPool(sample_card_resolver)
    candidates = pool.build_candidate_pool(owned_oracle_ids=set())

    meren = next((c for c in candidates if c.oracle_id == MEREN_ORACLE_ID), None)
    assert meren is not None, "Meren must appear in candidate pool"
    assert meren.support_tier == "curated"

    prossh = next((c for c in candidates if c.oracle_id == PROSSH_ORACLE_ID), None)
    assert prossh is not None, "Prossh must appear in candidate pool"
    assert prossh.support_tier == "profiled"


def test_non_curated_candidate_defaults_to_fallback(sample_card_resolver) -> None:
    """Commanders not listed in COMMANDER_SUPPORT_TIERS get 'fallback'."""
    pool = CommanderPool(sample_card_resolver)
    candidates = pool.build_candidate_pool(owned_oracle_ids=set())

    fallback_candidates = [
        c for c in candidates if c.oracle_id not in COMMANDER_SUPPORT_TIERS
    ]
    assert all(c.support_tier == "fallback" for c in fallback_candidates)


# ---------------------------------------------------------------------------
# CommanderRecommendation.support_tier propagation through recommender
# ---------------------------------------------------------------------------

def test_recommendation_carries_support_tier(sample_card_resolver) -> None:
    """CommanderRecommender passes support_tier from candidate to recommendation."""
    recommender = CommanderRecommender(
        pool=CommanderPool(sample_card_resolver),
        scorer=CommanderScorer(RuleTagger()),
    )
    recs = recommender.recommend(owned_oracle_ids={MEREN_ORACLE_ID}, owned_cards=[])

    meren_rec = next((r for r in recs if r.oracle_id == MEREN_ORACLE_ID), None)
    if meren_rec is None:
        # Meren may not rank top_k; use top_k large enough
        recs = recommender.recommend(
            owned_oracle_ids={MEREN_ORACLE_ID}, owned_cards=[], top_k=100
        )
        meren_rec = next((r for r in recs if r.oracle_id == MEREN_ORACLE_ID), None)

    assert meren_rec is not None, "Meren should appear in recommendations"
    assert meren_rec.support_tier == "curated"


def test_fallback_recommendation_support_tier(sample_card_resolver) -> None:
    """A commander not in the tier map produces a recommendation with 'fallback'."""
    recommender = CommanderRecommender(
        pool=CommanderPool(sample_card_resolver),
        scorer=CommanderScorer(RuleTagger()),
    )
    recs = recommender.recommend(owned_oracle_ids=set(), owned_cards=[], top_k=100)

    fallback_recs = [r for r in recs if r.oracle_id not in COMMANDER_SUPPORT_TIERS]
    assert all(r.support_tier == "fallback" for r in fallback_recs)


# ---------------------------------------------------------------------------
# SC-DECK-020: Plan overrides and evidence helpers
# ---------------------------------------------------------------------------

GRETA_ORACLE_ID = GRETA_FIXTURE_ORACLE_ID
TOLUZ_ORACLE_ID = TOLUZ_FIXTURE_ORACLE_ID
REAL_CATALOG_PATH = Path(__file__).parents[2] / "data" / "oracle-cards.json"


def test_get_commander_plan_override_returns_plan_for_known_id() -> None:
    assert get_commander_plan_override(GRETA_ORACLE_ID) == "food-sacrifice"
    assert get_commander_plan_override(TOLUZ_ORACLE_ID) == "connive"


def test_get_commander_plan_override_returns_none_for_unknown_id() -> None:
    assert get_commander_plan_override(UNKNOWN_ORACLE_ID) is None


def test_get_commander_positive_evidence_returns_signals() -> None:
    signals = get_commander_positive_evidence(GRETA_ORACLE_ID)
    assert isinstance(signals, tuple)
    assert len(signals) > 0
    assert "food" in signals


def test_get_commander_negative_evidence_returns_signals() -> None:
    signals = get_commander_negative_evidence(GRETA_ORACLE_ID)
    assert isinstance(signals, tuple)
    assert "treasure" in signals


def test_get_commander_positive_evidence_empty_for_unknown() -> None:
    assert get_commander_positive_evidence(UNKNOWN_ORACLE_ID) == ()


def test_get_commander_negative_evidence_empty_for_unknown() -> None:
    assert get_commander_negative_evidence(UNKNOWN_ORACLE_ID) == ()


def test_real_greta_oracle_id_maps_to_food_sacrifice_profile() -> None:
    resolver = _real_catalog_resolver()
    greta = resolver.resolve("Greta, Sweettooth Scourge")

    assert greta.oracle_id == GRETA_REAL_ORACLE_ID
    assert get_commander_plan_override(greta.oracle_id) == "food-sacrifice"
    assert "food" in get_commander_positive_evidence(greta.oracle_id)
    assert "treasure" in get_commander_negative_evidence(greta.oracle_id)


def test_real_toluz_oracle_id_maps_to_connive_profile() -> None:
    resolver = _real_catalog_resolver()
    toluz = resolver.resolve("Toluz, Clever Conductor")

    assert toluz.oracle_id == TOLUZ_REAL_ORACLE_ID
    assert get_commander_plan_override(toluz.oracle_id) == "connive"
    assert "connive" in get_commander_positive_evidence(toluz.oracle_id)
    assert "landfall" in get_commander_negative_evidence(toluz.oracle_id)


def test_placeholder_ids_remain_supported_for_negative_fixtures() -> None:
    assert get_commander_plan_override(GRETA_FIXTURE_ORACLE_ID) == "food-sacrifice"
    assert get_commander_plan_override(TOLUZ_FIXTURE_ORACLE_ID) == "connive"


def test_profile_lookup_uses_name_fallback_only_when_catalog_id_missing() -> None:
    assert (
        get_commander_plan_override(
            "catalog-bootstrap-missing-greta-id",
            "Greta, Sweettooth Scourge",
        )
        == "food-sacrifice"
    )
    assert (
        get_commander_profile_source(
            "catalog-bootstrap-missing-greta-id",
            "Greta, Sweettooth Scourge",
        )
        == "name_fallback"
    )
    assert get_commander_profile_source(GRETA_REAL_ORACLE_ID, "Wrong Name") == "oracle_id"
    assert get_commander_plan_override("unknown-id", "Unknown Commander") is None


def test_score_log_shows_commander_profile_source() -> None:
    deck = GeneratedDeck(
        deck_id="profile-source-test",
        session_id="profile-source-session",
        commander=DeckCard(
            oracle_id=GRETA_REAL_ORACLE_ID,
            name="Greta, Sweettooth Scourge",
            is_owned=True,
            quantity=1,
            roles=["COMMANDER"],
            selection_reason="commander",
        ),
        main_deck=[],
        role_breakdown={},
        quota_status=[],
        package_breakdown=[],
        warnings=[],
        owned_count=0,
        owned_percentage=0.0,
        is_valid=True,
        validation_errors=[],
        strategic_coherence=StrategicCoherenceReport(primary_plan="food-sacrifice"),
    )

    analysis_log = next(
        log for log in _build_deck_score_logs("profile-source-session", deck)
        if log.scope == "deck_analysis"
    )

    assert "commander_profile_source:oracle_id" in analysis_log.selected_reasons


@functools.lru_cache(maxsize=1)
def _real_catalog_resolver() -> CardResolver:
    return CardResolver(load_scryfall_bulk_data(REAL_CATALOG_PATH))
