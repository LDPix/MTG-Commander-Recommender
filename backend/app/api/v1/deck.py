"""Deck generation API endpoints (v1) — SC-API-003."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.collection import _get_db_session, get_card_resolver
from app.data_pipeline.card_resolver import CardResolver
from app.models.deck import GeneratedDeck
from app.recommendation.deck_exporter import export_deck_to_plaintext
from app.repositories.collection_repo import CollectionRepository
from app.schemas.deck_schema import (
    CardExplanationSchema,
    DeckCardSchema,
    DeckExportRequest,
    DeckExportResponse,
    DeckGenerateRequest,
    GeneratedDeckResponse,
    PackageSchema,
    QuotaStatusSchema,
    UpgradeSuggestionSchema,
)
from app.services.deck_generation_service import DeckGenerationService

router = APIRouter()


def _build_service(
    db: Session = Depends(_get_db_session),
    resolver: CardResolver = Depends(get_card_resolver),
) -> DeckGenerationService:
    return DeckGenerationService(CollectionRepository(db), resolver)


def _serialize(deck: GeneratedDeck) -> GeneratedDeckResponse:
    def card(c):
        return DeckCardSchema(
            oracle_id=c.oracle_id,
            name=c.name,
            is_owned=c.is_owned,
            quantity=c.quantity,
            roles=[r.value if hasattr(r, "value") else str(r) for r in c.roles],
            package_ids=c.package_ids,
            selection_reason=c.selection_reason,
            synergy_score=c.synergy_score,
        )

    return GeneratedDeckResponse(
        deck_id=deck.deck_id,
        session_id=deck.session_id,
        commander=card(deck.commander),
        main_deck=[card(c) for c in deck.main_deck],
        role_breakdown={
            (k.value if hasattr(k, "value") else str(k)): v
            for k, v in deck.role_breakdown.items()
        },
        quota_status=[
            QuotaStatusSchema(
                role=q.role.value if hasattr(q.role, "value") else str(q.role),
                target_min=q.target_min,
                target_max=q.target_max,
                actual_count=q.actual_count,
                is_satisfied=q.is_satisfied,
                warning=q.warning,
            )
            for q in deck.quota_status
        ],
        package_breakdown=[
            PackageSchema(
                package_id=p.package_id,
                label=p.label,
                confidence=p.confidence,
                card_oracle_ids=p.card_oracle_ids,
                top_roles=[
                    r.value if hasattr(r, "value") else str(r) for r in p.top_roles
                ],
            )
            for p in deck.package_breakdown
        ],
        warnings=deck.warnings,
        owned_count=deck.owned_count,
        owned_percentage=deck.owned_percentage,
        is_valid=deck.is_valid,
        validation_errors=deck.validation_errors,
        upgrade_suggestions=[
            UpgradeSuggestionSchema(
                oracle_id=s.oracle_id,
                name=s.name,
                priority=s.priority,
                improves_roles=s.improves_roles,
                improves_packages=s.improves_packages,
                reason=s.reason,
                impact_score=s.impact_score,
                replaces_or_supplements=s.replaces_or_supplements,
            )
            for s in deck.upgrade_suggestions
        ],
        card_explanations={
            oracle_id: CardExplanationSchema(
                oracle_id=e.oracle_id,
                name=e.name,
                summary=e.summary,
                evidence=e.evidence,
                roles=e.roles,
                package_ids=e.package_ids,
                synergy_score=e.synergy_score,
                is_owned=e.is_owned,
            )
            for oracle_id, e in deck.card_explanations.items()
        },
    )


@router.post("/generate", response_model=GeneratedDeckResponse)
def generate_deck(
    request: DeckGenerateRequest,
    service: DeckGenerationService = Depends(_build_service),
) -> GeneratedDeckResponse:
    """Generate a Commander deck for the given session and commander."""
    try:
        deck = service.generate_deck(request.session_id, request.commander_oracle_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if deck is None:
        raise HTTPException(
            status_code=404, detail="Collection not found for session"
        )

    return _serialize(deck)


@router.post("/export/plaintext", response_model=DeckExportResponse)
def export_plaintext_deck(request: DeckExportRequest) -> DeckExportResponse:
    """Format an already-generated deck payload as plaintext."""
    text, warnings = export_deck_to_plaintext(request.deck)
    return DeckExportResponse(text=text, warnings=warnings)
