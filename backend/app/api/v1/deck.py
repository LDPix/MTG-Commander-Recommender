"""Deck generation API endpoints (v1) — SC-API-003."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.collection import _get_db_session, get_card_resolver
from app.data_pipeline.card_resolver import CardResolver
from app.models.deck import GeneratedDeck
from app.recommendation.deck_exporter import export_deck_to_plaintext
from app.repositories.collection_repo import CollectionRepository
from app.repositories.saved_deck_repo import SavedDeckRepository
from app.schemas.deck_schema import (
    CardExplanationSchema,
    DeckCardSchema,
    DeckExportRequest,
    DeckExportResponse,
    DeckGenerateRequest,
    GeneratedDeckResponse,
    PackageSchema,
    QuotaStatusSchema,
    RepairBlockerSchema,
    SavedDeckDetailResponse,
    SavedDeckListResponse,
    StrategicCoherenceSchema,
    UpgradeSuggestionSchema,
)
from app.services.deck_generation_service import DeckGenerationService
from app.services.saved_deck_service import SavedDeckService

router = APIRouter()


def _build_service(
    db: Session = Depends(_get_db_session),
    resolver: CardResolver = Depends(get_card_resolver),
) -> DeckGenerationService:
    return DeckGenerationService(CollectionRepository(db), resolver)


def _build_saved_deck_service(
    db: Session = Depends(_get_db_session),
) -> SavedDeckService:
    return SavedDeckService(SavedDeckRepository(db))


def _serialize(deck: GeneratedDeck) -> GeneratedDeckResponse:
    def card(c):
        return DeckCardSchema(
            oracle_id=c.oracle_id,
            name=c.name,
            is_owned=c.is_owned,
            quantity=c.quantity,
            roles=[r.value if hasattr(r, "value") else str(r) for r in c.roles],
            assigned_role=c.assigned_role,
            secondary_role_credit=c.secondary_role_credit,
            package_ids=c.package_ids,
            selection_reason=c.selection_reason,
            synergy_score=c.synergy_score,
        )

    return GeneratedDeckResponse(
        deck_id=deck.deck_id,
        session_id=deck.session_id,
        generation_status=deck.generation_status,
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
                credit_sum=q.credit_sum,
                credit_satisfied=q.credit_satisfied,
                credit_warning=q.credit_warning,
                effective_satisfied=q.effective_satisfied,
                count_credit_covered=q.count_credit_covered,
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
                activation_status=p.activation_status,
                selected_count=p.selected_count,
                raw_selected_count=p.raw_selected_count,
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
        strategic_coherence=(
            StrategicCoherenceSchema(
                primary_plan=deck.strategic_coherence.primary_plan,
                confidence=deck.strategic_coherence.confidence,
                active_package_ids=deck.strategic_coherence.active_package_ids,
                on_plan_count=deck.strategic_coherence.on_plan_count,
                off_plan_count=deck.strategic_coherence.off_plan_count,
                warning_card_oracle_ids=deck.strategic_coherence.warning_card_oracle_ids,
                warnings=deck.strategic_coherence.warnings,
                confidence_cap_reasons=deck.strategic_coherence.confidence_cap_reasons,
            )
            if deck.strategic_coherence is not None
            else None
        ),
        repair_blockers=[
            RepairBlockerSchema(
                failure_type=blocker.failure_type,
                role=blocker.role,
                package_id=blocker.package_id,
                oracle_id=blocker.oracle_id,
                reason=blocker.reason,
                detail=blocker.detail,
            )
            for blocker in deck.repair_blockers
        ],
    )


@router.post("/generate", response_model=GeneratedDeckResponse)
def generate_deck(
    request: DeckGenerateRequest,
    service: DeckGenerationService = Depends(_build_service),
    saved_deck_service: SavedDeckService = Depends(_build_saved_deck_service),
) -> GeneratedDeckResponse:
    """Generate a Commander deck for the given session and commander.

    FR-016, FR-017: On success, the generated deck is persisted as a saved
    artifact associated with session_id and commander. The deck_id in the
    response doubles as the saved deck id for detail retrieval.
    NFR-12: response schema is backward-compatible; deck_id was already present.
    """
    try:
        deck = service.generate_deck(request.session_id, request.commander_oracle_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if deck is None:
        raise HTTPException(
            status_code=404, detail="Collection not found for session"
        )

    response = _serialize(deck)
    if response.generation_status != "failed_validation":
        saved_deck_service.save_generated_deck(response)
    return response


@router.get("/saved", response_model=SavedDeckListResponse)
def list_saved_decks(
    session_id: str = Query(..., description="Session id to list saved decks for"),
    saved_deck_service: SavedDeckService = Depends(_build_saved_deck_service),
) -> SavedDeckListResponse:
    """List saved/generated deck summaries for a session.

    FR-16, NFR-13: returns only decks belonging to the given session_id.
    """
    summaries = saved_deck_service.list_by_session(session_id)
    return SavedDeckListResponse(decks=summaries)


@router.get("/saved/{deck_id}", response_model=SavedDeckDetailResponse)
def get_saved_deck(
    deck_id: str,
    session_id: str = Query(..., description="Session id for ownership verification"),
    saved_deck_service: SavedDeckService = Depends(_build_saved_deck_service),
) -> SavedDeckDetailResponse:
    """Retrieve a saved/generated deck detail by id.

    FR-17, NFR-13: retrieval is session-scoped — a deck saved under
    session_a cannot be retrieved by providing session_b as the session_id.
    """
    detail = saved_deck_service.get_by_id_for_session(deck_id, session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Saved deck not found.")
    return detail


@router.post("/export/plaintext", response_model=DeckExportResponse)
def export_plaintext_deck(request: DeckExportRequest) -> DeckExportResponse:
    """Format an already-generated deck payload as plaintext.

    FR-18: export accepts the generated deck payload and does not require
    saved deck persistence — deck_id is not needed for export.
    """
    text, warnings = export_deck_to_plaintext(request.deck)
    return DeckExportResponse(text=text, warnings=warnings)
