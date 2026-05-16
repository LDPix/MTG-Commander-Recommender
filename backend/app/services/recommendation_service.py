"""Recommendation service layer (SC-API-002)."""
from __future__ import annotations

from app.data_pipeline.card_resolver import CardNotFoundError, CardResolver
from app.models.card import CanonicalCard, CardData
from app.models.score_log import ScoreLog
from app.recommendation.commander_pool import CommanderPool
from app.recommendation.commander_recommender import (
    CommanderRecommendation,
    CommanderRecommender,
)
from app.recommendation.commander_scorer import CommanderScorer
from app.data_pipeline.scryfall_tagger import get_scryfall_tagger_store
from app.recommendation.role_tagger import HybridTagger
from app.repositories.collection_repo import CollectionRepository


def _canonical_to_card_data(canonical: CanonicalCard) -> CardData:
    """Convert a CanonicalCard to a CardData for use in recommendation scoring."""
    return CardData(
        id=canonical.oracle_id,
        oracle_id=canonical.oracle_id,
        name=canonical.name,
        color_identity=canonical.color_identity,
        legalities=canonical.legalities,
        type_line=canonical.type_line,
        oracle_text=canonical.oracle_text,
        mana_cost=canonical.mana_cost,
        cmc=canonical.cmc,
        keywords=canonical.keywords,
        card_faces=canonical.card_faces,
        layout=canonical.layout,
        edhrec_rank=canonical.edhrec_rank,
        rarity=canonical.rarity,
    )


class RecommendationService:
    """Orchestrates commander recommendations for a user session."""

    def __init__(
        self,
        collection_repo: CollectionRepository,
        card_resolver: CardResolver,
    ) -> None:
        self._repo = collection_repo
        self._resolver = card_resolver
        self._recommender = CommanderRecommender(
            pool=CommanderPool(card_resolver),
            scorer=CommanderScorer(HybridTagger(get_scryfall_tagger_store())),
        )

    def get_recommendations(
        self,
        session_id: str,
        top_k: int = 10,
    ) -> list[CommanderRecommendation] | None:
        """Return ranked recommendations for the session, or None if no collection."""
        collection = self._repo.get_collection_by_session(session_id)
        if collection is None:
            return None

        items = self._repo.get_items(collection.id)

        owned_oracle_ids: set[str] = set()
        owned_cards: list[CardData] = []

        for item in items:
            owned_oracle_ids.add(item.oracle_id)
            try:
                canonical = self._resolver.resolve_by_oracle_id(item.oracle_id)
                owned_cards.append(_canonical_to_card_data(canonical))
            except CardNotFoundError:
                pass  # Card in collection not in resolver — skip for scoring

        return self._recommender.recommend(
            owned_oracle_ids=owned_oracle_ids,
            owned_cards=owned_cards,
            top_k=top_k,
            session_id=session_id,
        )

    def get_recommendations_with_logs(
        self,
        session_id: str,
        top_k: int = 10,
    ) -> tuple[list[CommanderRecommendation], list[ScoreLog]] | None:
        recommendations = self.get_recommendations(session_id, top_k)
        if recommendations is None:
            return None
        logs = [rec.score_log for rec in recommendations if rec.score_log is not None]
        return recommendations, logs
