"""Commander recommendation API endpoints (v1)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.collection import _get_db_session, get_card_resolver
from app.data_pipeline.card_resolver import CardResolver
from app.repositories.collection_repo import CollectionRepository
from app.schemas.recommendation_schema import (
    CommanderRecommendationSchema,
    ExplanationSchema,
    RecommendationResponse,
)
from app.services.recommendation_service import RecommendationService

router = APIRouter(prefix="/api/v1/recommendations", tags=["recommendations"])


def _build_service(
    db: Session = Depends(_get_db_session),
    resolver: CardResolver = Depends(get_card_resolver),
) -> RecommendationService:
    return RecommendationService(CollectionRepository(db), resolver)


@router.get("/{session_id}", response_model=RecommendationResponse)
def get_recommendations(
    session_id: str,
    service: RecommendationService = Depends(_build_service),
) -> RecommendationResponse:
    """Return ranked commander recommendations for the given session."""
    recs = service.get_recommendations(session_id)
    if recs is None:
        raise HTTPException(
            status_code=404, detail="Collection not found for this session."
        )

    return RecommendationResponse(
        session_id=session_id,
        recommendations=[
            CommanderRecommendationSchema(
                oracle_id=r.oracle_id,
                name=r.name,
                color_identity=r.color_identity,
                fit_score=r.fit_score,
                archetype=r.archetype,
                owned_count=r.owned_count,
                owned_percentage=r.owned_percentage,
                explanation=ExplanationSchema(
                    summary=r.explanation.summary,
                    owned_highlights=r.explanation.owned_highlights,
                    archetype_label=r.explanation.archetype_label,
                    missing_core_notes=r.explanation.missing_core_notes,
                ),
                roles_covered=r.roles_covered,
            )
            for r in recs
        ],
        total=len(recs),
    )
