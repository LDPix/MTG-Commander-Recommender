"""Tests for deterministic recommendation/deck score logs."""
from __future__ import annotations

from app.data_pipeline.card_resolver import CardResolver
from app.models.deck import DeckCard, GeneratedDeck
from app.models.score_log import DATA_VERSION, ScoreLog
from app.recommendation.commander_pool import CommanderPool
from app.recommendation.commander_recommender import CommanderRecommender
from app.recommendation.commander_scorer import CommanderScorer
from app.recommendation.role_tagger import RuleTagger
from app.services.deck_generation_service import _build_deck_score_logs

from tests.unit.test_commander_recommender import CULTIVATE, MEREN, SOL_RING


def _recommender() -> CommanderRecommender:
    resolver = CardResolver([MEREN])
    return CommanderRecommender(
        pool=CommanderPool(resolver),
        scorer=CommanderScorer(RuleTagger()),
    )


def _deck(session_id: str = "deck-log-session") -> GeneratedDeck:
    commander = DeckCard(
        oracle_id="cmd",
        name="Commander",
        is_owned=True,
        quantity=1,
        roles=[],
        selection_reason="commander",
        synergy_score=0.0,
    )
    main_deck = [
        DeckCard(
            oracle_id="ramp",
            name="Ramp",
            is_owned=True,
            quantity=1,
            roles=["RAMP"],
            selection_reason="fills RAMP role",
            synergy_score=0.4,
        )
    ]
    return GeneratedDeck(
        deck_id="deck",
        session_id=session_id,
        commander=commander,
        main_deck=main_deck,
        role_breakdown={"RAMP": 1},
        quota_status=[],
        package_breakdown=[],
        warnings=[],
        owned_count=1,
        owned_percentage=1.0,
        is_valid=True,
        validation_errors=[],
    )


def test_commander_score_breakdown_logged() -> None:
    recs = _recommender().recommend(
        owned_oracle_ids={SOL_RING.oracle_id, CULTIVATE.oracle_id},
        owned_cards=[SOL_RING, CULTIVATE],
        session_id="score-session",
    )

    log = recs[0].score_log
    assert isinstance(log, ScoreLog)
    assert log.scope == "commander_recommendation"
    assert "total_score" in log.score_components
    assert "owned_ratio" in log.score_components
    assert "role_score" in log.score_components


def test_card_selection_reason_logged() -> None:
    logs = _build_deck_score_logs("deck-log-session", _deck())

    ramp_log = next(log for log in logs if log.subject_id == "ramp")
    assert ramp_log.scope == "deck_generation"
    assert ramp_log.selected_reasons == ["fills RAMP role"]
    assert ramp_log.score_components["synergy_score"] == 0.4


def test_data_version_logged() -> None:
    recs = _recommender().recommend(
        owned_oracle_ids={SOL_RING.oracle_id},
        owned_cards=[SOL_RING],
        session_id="version-session",
    )
    deck_logs = _build_deck_score_logs("version-session", _deck("version-session"))

    assert recs[0].score_log.data_version == DATA_VERSION
    assert all(log.data_version == DATA_VERSION for log in deck_logs)


def test_score_log_is_deterministic() -> None:
    recommender = _recommender()
    first = recommender.recommend(
        owned_oracle_ids={SOL_RING.oracle_id, CULTIVATE.oracle_id},
        owned_cards=[SOL_RING, CULTIVATE],
        session_id="det-session",
    )
    second = recommender.recommend(
        owned_oracle_ids={SOL_RING.oracle_id, CULTIVATE.oracle_id},
        owned_cards=[SOL_RING, CULTIVATE],
        session_id="det-session",
    )

    assert [r.score_log.model_dump() for r in first] == [
        r.score_log.model_dump() for r in second
    ]
    assert [log.model_dump() for log in _build_deck_score_logs("det-session", _deck())] == [
        log.model_dump() for log in _build_deck_score_logs("det-session", _deck())
    ]


def test_score_log_is_session_scoped() -> None:
    first = _recommender().recommend(
        owned_oracle_ids={SOL_RING.oracle_id},
        owned_cards=[SOL_RING],
        session_id="session-a",
    )[0].score_log
    second = _recommender().recommend(
        owned_oracle_ids={SOL_RING.oracle_id},
        owned_cards=[SOL_RING],
        session_id="session-b",
    )[0].score_log

    assert first.session_id == "session-a"
    assert second.session_id == "session-b"
    assert first.subject_id == second.subject_id
