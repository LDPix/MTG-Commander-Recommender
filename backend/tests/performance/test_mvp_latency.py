"""Performance smoke gates for MVP backend flows (SC-NFR-001/002/003)."""
from __future__ import annotations

import os
import time

import pytest
from sqlalchemy.orm import Session

from app.data_pipeline.card_resolver import CardResolver
from app.data_pipeline.collection_normalizer import CollectionNormalizer
from app.data_pipeline.csv_importer import CSVImporter
from app.models.card import CardData
from app.recommendation.deck_candidate_pool import DeckCandidatePool
from app.repositories.collection_repo import CollectionRepository
from app.services.collection_service import CollectionService
from app.services.deck_generation_service import DeckGenerationService
from app.services.recommendation_service import RecommendationService
from tests.conftest import MEREN_ORACLE_ID
from tests.fixtures.sample_csv_collections import DECK_TEST_COLLECTION_CSV


def _threshold(env_name: str, default: float) -> float:
    return float(os.getenv(env_name, str(default)))


IMPORT_THRESHOLD_SECONDS = _threshold("MTG_PERF_IMPORT_SECONDS", 10.0)
RECOMMENDATION_THRESHOLD_SECONDS = _threshold("MTG_PERF_RECOMMEND_SECONDS", 15.0)
DECK_GENERATION_THRESHOLD_SECONDS = _threshold("MTG_PERF_DECK_SECONDS", 15.0)
CANDIDATE_POOL_CAP = 600


def assert_under_seconds(label: str, elapsed: float, threshold: float) -> None:
    assert elapsed < threshold, (
        f"{label} took {elapsed:.3f}s, threshold {threshold:.3f}s"
    )


@pytest.fixture
def repo(db_session: Session) -> CollectionRepository:
    return CollectionRepository(db_session)


@pytest.fixture
def collection_service(
    repo: CollectionRepository,
    sample_card_resolver: CardResolver,
) -> CollectionService:
    return CollectionService(
        importer=CSVImporter(),
        normalizer=CollectionNormalizer(sample_card_resolver),
        repo=repo,
    )


@pytest.fixture
def recommendation_service(
    repo: CollectionRepository,
    sample_card_resolver: CardResolver,
) -> RecommendationService:
    return RecommendationService(repo, sample_card_resolver)


@pytest.fixture
def deck_generation_service(
    repo: CollectionRepository,
    sample_card_resolver: CardResolver,
) -> DeckGenerationService:
    return DeckGenerationService(repo, sample_card_resolver)


def test_import_20k_cards_under_10_seconds(
    collection_service: CollectionService,
) -> None:
    csv_content = _large_collection_csv(["Sol Ring", "Command Tower", "Cultivate"])

    elapsed, response = _measure(
        lambda: collection_service.import_collection(
            "perf-import-20k",
            csv_content.encode(),
            "large_collection_20k.csv",
        )
    )

    assert response.success is True
    assert response.imported_count == 3
    assert_under_seconds("20k-card import", elapsed, IMPORT_THRESHOLD_SECONDS)


def test_import_with_unknown_cards_under_10_seconds(
    collection_service: CollectionService,
) -> None:
    names = ["Sol Ring", "Command Tower", "Unknown Performance Card"]
    csv_content = _large_collection_csv(names)

    elapsed, response = _measure(
        lambda: collection_service.import_collection(
            "perf-import-unknowns",
            csv_content.encode(),
            "large_collection_with_unknowns.csv",
        )
    )

    assert response.success is True
    assert "Unknown Performance Card" in response.unknown_cards
    assert_under_seconds(
        "20k-card import with unknowns",
        elapsed,
        IMPORT_THRESHOLD_SECONDS,
    )


def test_import_with_duplicates_under_10_seconds(
    collection_service: CollectionService,
) -> None:
    csv_content = _large_collection_csv(["Sol Ring"])

    elapsed, response = _measure(
        lambda: collection_service.import_collection(
            "perf-import-duplicates",
            csv_content.encode(),
            "large_collection_with_duplicates.csv",
        )
    )

    assert response.success is True
    assert response.imported_count == 1
    assert_under_seconds(
        "20k-card duplicate import",
        elapsed,
        IMPORT_THRESHOLD_SECONDS,
    )


def test_recommendations_under_15_seconds(
    collection_service: CollectionService,
    recommendation_service: RecommendationService,
) -> None:
    session_id = "perf-recommendations"
    collection_service.import_collection(
        session_id,
        DECK_TEST_COLLECTION_CSV.encode(),
        "recommendations.csv",
    )

    elapsed, recommendations = _measure(
        lambda: recommendation_service.get_recommendations(session_id)
    )

    assert recommendations is not None
    assert recommendations
    assert_under_seconds(
        "commander recommendations",
        elapsed,
        RECOMMENDATION_THRESHOLD_SECONDS,
    )


def test_recommendations_are_deterministic_under_repeated_calls(
    collection_service: CollectionService,
    recommendation_service: RecommendationService,
) -> None:
    session_id = "perf-recommendations-deterministic"
    collection_service.import_collection(
        session_id,
        DECK_TEST_COLLECTION_CSV.encode(),
        "recommendations.csv",
    )

    first = recommendation_service.get_recommendations(session_id)
    second = recommendation_service.get_recommendations(session_id)

    assert first is not None
    assert second is not None
    assert [(r.oracle_id, r.fit_score) for r in first] == [
        (r.oracle_id, r.fit_score) for r in second
    ]


def test_deck_generation_under_15_seconds(
    collection_service: CollectionService,
    deck_generation_service: DeckGenerationService,
) -> None:
    session_id = "perf-deck-generation"
    collection_service.import_collection(
        session_id,
        DECK_TEST_COLLECTION_CSV.encode(),
        "deck_generation.csv",
    )

    elapsed, deck = _measure(
        lambda: deck_generation_service.generate_deck(session_id, MEREN_ORACLE_ID)
    )

    assert deck is not None
    assert deck.commander.oracle_id == MEREN_ORACLE_ID
    assert sum(card.quantity for card in deck.main_deck) == 99
    assert_under_seconds(
        "deck generation",
        elapsed,
        DECK_GENERATION_THRESHOLD_SECONDS,
    )


def test_deck_generation_candidate_pool_cap_respected() -> None:
    commander = _card("commander-000", "Perf Commander", color_identity=[])
    all_cards = [commander] + [
        _card(f"candidate-{i:04d}", f"Candidate {i}", color_identity=[])
        for i in range(CANDIDATE_POOL_CAP + 100)
    ]

    pool = DeckCandidatePool().build(
        commander=commander,
        owned_cards=[],
        all_cards=all_cards,
        role_tags={},
        owned_oracle_ids=set(),
    )

    assert len(pool) == CANDIDATE_POOL_CAP


def _measure(operation):
    start = time.perf_counter()
    result = operation()
    return time.perf_counter() - start, result


def _large_collection_csv(names: list[str], row_count: int = 20_000) -> str:
    lines = ["name,quantity"]
    for index in range(row_count):
        lines.append(f"{names[index % len(names)]},1")
    return "\n".join(lines)


def _card(
    oracle_id: str,
    name: str,
    *,
    color_identity: list[str],
) -> CardData:
    return CardData(
        id=oracle_id,
        oracle_id=oracle_id,
        name=name,
        color_identity=color_identity,
        legalities={"commander": "legal"},
        type_line="Legendary Creature" if oracle_id == "commander-000" else "Creature",
        oracle_text="",
        cmc=1.0,
    )
