"""Deck generation service layer (SC-API-003 prerequisite)."""
from __future__ import annotations

from app.data_pipeline.card_resolver import CardNotFoundError, CardResolver
from app.models.card import CanonicalCard, CardData
from collections import defaultdict

from app.models.deck import (
    DeckCard,
    GeneratedDeck,
    PackageCluster,
    QuotaStatus,
    RepairBlocker,
    StrategicCoherenceReport,
)
from app.models.score_log import DATA_VERSION, ScoreLog
from app.recommendation.card_explainer import CardExplainer
from app.recommendation.commander_profiles import get_commander_profile_source
from app.recommendation.deck_candidate_pool import DeckCandidatePool
from app.recommendation.deck_generator import DeckGenerator
from app.recommendation.legality_validator import LegalityValidator
from app.recommendation.package_detector import PackageDetector
from app.recommendation.package_density import (
    active_package_ids_for_deck,
    is_orphan,
    package_core_ids_for_deck,
    package_relevant_to_plan,
    packages_with_activation_status,
)
from app.recommendation.package_labeler import PackageLabeler
from app.recommendation.quota_config import adjust_quotas_for_commander, BASELINE_QUOTAS as _BASELINE_QUOTAS
from app.recommendation.role_assignment import assign_role_slots
from app.recommendation.role_credit import role_quality_credit
from app.recommendation.role_taxonomy import RoleTag
from app.data_pipeline.scryfall_tagger import get_scryfall_tagger_store
from app.recommendation.role_tagger import HybridTagger
from app.recommendation.strategic_coherence import (
    ACTIVE_PACKAGE_MIN_CARDS,
    MAX_OFF_PLAN_CARDS,
    PLAN_ROLE_HINTS,
    StrategicCoherenceValidator,
    _commander_supports_loose_value,
    infer_primary_plan,
)
from app.recommendation.synergy_graph import RoleTagSynergyProvider, SynergyGraph, SynergyDataProvider
from app.recommendation.upgrade_suggester import UpgradeSuggester
from app.repositories.collection_repo import CollectionRepository


def _canonical_to_card_data(canonical: CanonicalCard) -> CardData:
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


class DeckGenerationService:
    def __init__(
        self,
        collection_repo: CollectionRepository,
        card_resolver: CardResolver,
        synergy_provider: SynergyDataProvider | None = None,
    ) -> None:
        self._repo = collection_repo
        self._resolver = card_resolver
        self._tagger = HybridTagger(get_scryfall_tagger_store())
        self._synergy_provider = synergy_provider or RoleTagSynergyProvider()

    def generate_deck(
        self,
        session_id: str,
        commander_oracle_id: str,
    ) -> GeneratedDeck | None:
        """Return GeneratedDeck or None if collection not found.

        Raises ValueError if commander is not legal or not in catalog.
        """
        # Step 1: Load collection
        collection = self._repo.get_collection_by_session(session_id)
        if collection is None:
            return None

        # Step 2: Load commander
        try:
            commander_canonical = self._resolver.resolve_by_oracle_id(commander_oracle_id)
        except CardNotFoundError as e:
            raise ValueError(f"Commander not found: {commander_oracle_id}") from e

        commander = _canonical_to_card_data(commander_canonical)

        # Step 3: Validate commander legality
        if commander.legalities.get("commander") != "legal":
            raise ValueError(
                f"Commander {commander.name!r} is not legal in Commander format."
            )
        if "Legendary Creature" not in commander.type_line and "Legendary" not in commander.type_line:
            raise ValueError(
                f"{commander.name!r} is not a Legendary Creature and cannot be a commander."
            )

        # Step 4: Load collection items and resolve cards
        items = self._repo.get_items(collection.id)
        owned_oracle_ids: set[str] = set()
        owned_cards: list[CardData] = []

        for item in items:
            owned_oracle_ids.add(item.oracle_id)
            try:
                canonical = self._resolver.resolve_by_oracle_id(item.oracle_id)
                owned_cards.append(_canonical_to_card_data(canonical))
            except CardNotFoundError:
                pass

        # Step 5: Build all_cards from resolver
        all_canonicals = self._resolver.get_all()
        all_cards = [_canonical_to_card_data(c) for c in all_canonicals]

        # Build oracle_id -> CardData lookup
        all_cards_lookup: dict[str, CardData] = {c.oracle_id: c for c in all_cards}

        # Step 6: Build role_tags for all cards
        role_tags: dict[str, list[RoleTag]] = {}
        for card in all_cards:
            tags = self._tagger.tag(card)
            if tags:
                role_tags[card.oracle_id] = tags

        commander_tags = role_tags.get(commander.oracle_id, [])

        # Step 7: Build candidate pool
        pool_builder = DeckCandidatePool()
        candidate_pool = pool_builder.build(
            commander=commander,
            owned_cards=owned_cards,
            all_cards=all_cards,
            role_tags=role_tags,
            owned_oracle_ids=owned_oracle_ids,
            all_cards_lookup=all_cards_lookup,
        )

        # Step 8: Build synergy graph
        graph = SynergyGraph()
        graph.build(
            candidate_cards=candidate_pool,
            role_tags=role_tags,
            provider=self._synergy_provider,
            commander_oracle_id=commander.oracle_id,
            color_identity=commander.color_identity,
        )

        # Step 9: Detect and label packages
        detector = PackageDetector()
        packages = detector.detect(candidate_pool, role_tags, graph)
        labeler = PackageLabeler()
        packages = [labeler.label(p) for p in packages]

        # Step 10: Adjust quotas
        primary_plan_for_quotas = infer_primary_plan(commander, commander_tags)
        quotas = adjust_quotas_for_commander(
            baseline=list(_BASELINE_QUOTAS),
            commander=commander,
            commander_tags=commander_tags,
            primary_plan=primary_plan_for_quotas,
        )

        # Step 11: Generate deck
        candidate_active_package_ids = _estimate_candidate_active_packages(
            candidate_pool=candidate_pool,
            packages=packages,
            primary_plan=primary_plan_for_quotas,
        )
        generator = DeckGenerator()
        deck = generator.generate(
            commander=commander,
            commander_tags=commander_tags,
            candidate_pool=candidate_pool,
            role_tags=role_tags,
            graph=graph,
            packages=packages,
            session_id=session_id,
            quotas=quotas,
            all_cards_lookup=all_cards_lookup,
            candidate_active_package_ids=candidate_active_package_ids,
        )

        enriched_candidate_pool = _enrich_candidate_pool(candidate_pool, graph, packages)

        coherence_report = StrategicCoherenceValidator().validate(
            commander=commander,
            commander_tags=commander_tags,
            deck=deck,
            all_cards_lookup=all_cards_lookup,
            packages=packages,
        )
        deck.strategic_coherence = coherence_report

        # SC-DECK-018: coherence repair pass
        deck, coherence_report = _coherence_repair_pass(
            deck=deck,
            coherence_report=coherence_report,
            enriched_candidate_pool=enriched_candidate_pool,
            all_cards_lookup=all_cards_lookup,
            commander=commander,
            commander_tags=commander_tags,
            packages=packages,
        )
        deck.strategic_coherence = coherence_report
        deck = _refresh_deck_derived_state(
            deck=deck,
            commander=commander,
            all_cards_lookup=all_cards_lookup,
            quotas=quotas,
            coherence_report=coherence_report,
        )
        deck = _finalize_coherence_fail_closed(deck=deck, packages=packages)
        deck = _multi_pass_quality_repair(
            deck=deck,
            commander=commander,
            commander_tags=commander_tags,
            all_cards_lookup=all_cards_lookup,
            quotas=quotas,
            enriched_candidate_pool=enriched_candidate_pool,
            packages=packages,
        )
        deck = _finalize_quality_generation_status(deck)

        deck.upgrade_suggestions = UpgradeSuggester().suggest(
            commander=commander,
            generated_deck=deck,
            candidate_pool=enriched_candidate_pool,
            packages=packages,
            quota_status=deck.quota_status,
        )
        deck.card_explanations = CardExplainer().explain_deck(
            deck=deck,
            packages=packages,
            quota_status=deck.quota_status,
        )
        deck.score_logs = _build_deck_score_logs(
            session_id=session_id,
            deck=deck,
        )

        return deck


def _enrich_candidate_pool(
    candidate_pool: list[DeckCard],
    graph: SynergyGraph,
    packages: list[PackageCluster],
) -> list[DeckCard]:
    card_to_packages: dict[str, list[str]] = defaultdict(list)
    for package in packages:
        for oracle_id in package.card_oracle_ids:
            card_to_packages[oracle_id].append(package.package_id)

    return [
        card.model_copy(
            update={
                "synergy_score": graph.get_synergy_score(card.oracle_id),
                "package_ids": sorted(card_to_packages.get(card.oracle_id, [])),
            }
        )
        for card in candidate_pool
    ]


_BASIC_LAND_NAMES: frozenset[str] = frozenset({
    "Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes",
    "Snow-Covered Plains", "Snow-Covered Island", "Snow-Covered Swamp",
    "Snow-Covered Mountain", "Snow-Covered Forest",
})


def _estimate_candidate_active_packages(
    candidate_pool: list[DeckCard],
    packages: list[PackageCluster],
    primary_plan: str | None,
) -> frozenset[str]:
    """Return package_ids likely to activate given the owned candidate pool.

    Uses density count only (no graph scoring) — this is a pre-generation estimate.
    A package is candidate-active if it has >= ACTIVE_PACKAGE_MIN_CARDS owned members
    and is plan-relevant when primary_plan is known.
    """
    owned_pool_ids = {c.oracle_id for c in candidate_pool if c.is_owned}
    candidate_active: set[str] = set()
    for pkg in packages:
        owned_member_count = sum(1 for oid in pkg.card_oracle_ids if oid in owned_pool_ids)
        if owned_member_count < ACTIVE_PACKAGE_MIN_CARDS:
            continue
        if primary_plan is not None and not package_relevant_to_plan(pkg, primary_plan):
            continue
        candidate_active.add(pkg.package_id)
    return frozenset(candidate_active)


def _coherence_repair_pass(
    deck: GeneratedDeck,
    coherence_report: StrategicCoherenceReport,
    enriched_candidate_pool: list[DeckCard],
    all_cards_lookup: dict[str, CardData],
    commander: CardData,
    commander_tags: list[RoleTag],
    packages: list[PackageCluster],
) -> tuple[GeneratedDeck, StrategicCoherenceReport]:
    """Replace off-plan warning cards with on-plan alternatives (SC-DECK-018).

    Best-effort: skips cards when no valid replacement exists.
    Runs coherence validation once after repair and returns the updated report.
    """
    from app.recommendation.strategic_coherence import (
        MAX_OFF_PLAN_CARDS,
        REQUIRED_ROLE_FILLERS,
        StrategicCoherenceValidator,
    )

    if not coherence_report.warning_card_oracle_ids:
        return deck, coherence_report

    main_deck = list(deck.main_deck)
    selected_ids = {c.oracle_id for c in main_deck}

    quota_counts: dict[str, int] = defaultdict(int)
    for c in main_deck:
        for r in c.roles:
            quota_counts[r] += c.quantity
    quota_mins: dict[str, int] = {
        qs.role: qs.target_min for qs in deck.quota_status
    }

    on_plan_pool = [
        c for c in enriched_candidate_pool
        if c.oracle_id not in selected_ids
        and "LAND" not in c.roles
        and c.name not in _BASIC_LAND_NAMES
        and _is_on_plan_candidate(c, all_cards_lookup, coherence_report, commander, packages)
    ]
    on_plan_pool.sort(
        key=lambda c: (
            not c.is_owned,
            -c.synergy_score,
            c.oracle_id,
        )
    )

    repairs_done = 0

    for warning_oid in coherence_report.warning_card_oracle_ids:
        if repairs_done >= MAX_OFF_PLAN_CARDS:
            break

        card_idx = next(
            (i for i, c in enumerate(main_deck) if c.oracle_id == warning_oid),
            None,
        )
        if card_idx is None:
            continue

        warning_card = main_deck[card_idx]

        if REQUIRED_ROLE_FILLERS.intersection(warning_card.roles):
            role_safe = all(
                quota_counts.get(r, 0) - 1 >= quota_mins.get(r, 0)
                for r in warning_card.roles
            )
            if not role_safe:
                continue

        replacement = next(
            (c for c in on_plan_pool if c.oracle_id not in selected_ids),
            None,
        )
        if replacement is None:
            break

        main_deck[card_idx] = replacement.model_copy(
            update={
                "quantity": 1,
                "selection_reason": f"coherence repair: replaced off-plan {warning_card.name}",
            }
        )
        selected_ids.discard(warning_oid)
        selected_ids.add(replacement.oracle_id)
        on_plan_pool = [c for c in on_plan_pool if c.oracle_id != replacement.oracle_id]

        for r in warning_card.roles:
            quota_counts[r] = max(0, quota_counts[r] - 1)
        for r in replacement.roles:
            quota_counts[r] = quota_counts.get(r, 0) + 1

        repairs_done += 1

    updated_deck = deck.model_copy(update={"main_deck": main_deck})

    new_report = StrategicCoherenceValidator().validate(
        commander=commander,
        commander_tags=commander_tags,
        deck=updated_deck,
        all_cards_lookup=all_cards_lookup,
        packages=packages,
    )

    return updated_deck, new_report


def _refresh_deck_derived_state(
    deck: GeneratedDeck,
    commander: CardData,
    all_cards_lookup: dict[str, CardData],
    quotas: list,
    coherence_report: StrategicCoherenceReport,
) -> GeneratedDeck:
    """Rebuild fields derived from main_deck after coherence repair."""
    assignment = assign_role_slots(deck.main_deck, quotas, all_cards_lookup)
    main_deck = assignment.main_deck
    role_breakdown = assignment.role_breakdown
    quota_status = assignment.quota_status
    package_breakdown = packages_with_activation_status(
        packages=deck.package_breakdown,
        main_deck=main_deck,
        primary_plan=coherence_report.primary_plan,
        commander_supports_loose_value=_commander_supports_loose_value(
            commander, coherence_report.primary_plan
        ),
        enforce_commander_relevance=True,
    )

    main_for_validation: list[tuple[CardData, int]] = []
    for deck_card in main_deck:
        card_data = all_cards_lookup.get(deck_card.oracle_id)
        if card_data is not None:
            main_for_validation.append((card_data, deck_card.quantity))
    validation = LegalityValidator().validate_deck(commander, main_for_validation)

    derived_warnings = [
        warning
        for warning in deck.warnings
        if not _is_quota_warning(warning, quotas)
        and not _is_coherence_warning(warning)
    ]
    fresh_warnings = [
        *derived_warnings,
        *[qs.warning for qs in quota_status if qs.warning is not None],
        *[qs.credit_warning for qs in quota_status if qs.credit_warning is not None],
        *coherence_report.warnings,
    ]
    warnings = _merge_warnings([], fresh_warnings)

    owned_count = sum(c.quantity for c in main_deck if c.is_owned)
    return deck.model_copy(
        update={
            "main_deck": main_deck,
            "role_breakdown": dict(role_breakdown),
            "quota_status": quota_status,
            "package_breakdown": package_breakdown,
            "warnings": warnings,
            "owned_count": owned_count,
            "owned_percentage": owned_count / 99 if 99 > 0 else 0.0,
            "is_valid": validation.valid,
            "validation_errors": [error.reason for error in validation.errors],
            "strategic_coherence": coherence_report,
        }
    )


def _is_quota_warning(warning: str, quotas: list) -> bool:
    for quota in quotas:
        role_value = quota.role.value
        if warning.startswith(f"{role_value}: need ") or warning.startswith(
            f"{role_value}: credit "
        ):
            return True
    return False


def _is_coherence_warning(warning: str) -> bool:
    return (
        warning.startswith("Strategic coherence")
        or warning.startswith("Loose Treasure/Clue/Food/Map")
        or warning.startswith("Commander support is fallback")
    )


COHERENCE_FAIL_CLOSED_CONFIDENCE_CAP: float = 0.35
COHERENCE_VALIDATION_CONFIDENCE_CAP: float = 0.20
INFRASTRUCTURE_CREDIT_COVERABLE_ROLES: frozenset[str] = frozenset({
    "RAMP",
    "CARD_DRAW",
    "SPOT_REMOVAL",
    "PROTECTION",
})


def quota_effectively_satisfied(
    quota: QuotaStatus,
    strategic_coherence: StrategicCoherenceReport | None,
) -> bool:
    """Return True when raw quota status passes, including credit-covered infra gaps."""
    if quota.is_satisfied and quota.credit_satisfied:
        return True
    return quota_count_credit_covered(quota, strategic_coherence)


def quota_count_credit_covered(
    quota: QuotaStatus,
    strategic_coherence: StrategicCoherenceReport | None,
) -> bool:
    """Return True when a one-slot infrastructure count gap is covered by credit."""
    if quota.role not in INFRASTRUCTURE_CREDIT_COVERABLE_ROLES:
        return False
    if quota.actual_count != quota.target_min - 1:
        return False
    if quota.actual_count > quota.target_max:
        return False
    if quota.credit_sum < quota.target_min or not quota.credit_satisfied:
        return False
    if strategic_coherence is None:
        return False
    if strategic_coherence.confidence < COHERENCE_FAIL_CLOSED_CONFIDENCE_CAP:
        return False
    if strategic_coherence.confidence_cap_reasons:
        return False
    return True


def _apply_effective_quota_semantics(deck: GeneratedDeck) -> GeneratedDeck:
    quota_status = [
        quota.model_copy(
            update={
                "effective_satisfied": quota_effectively_satisfied(
                    quota, deck.strategic_coherence
                ),
                "count_credit_covered": quota_count_credit_covered(
                    quota, deck.strategic_coherence
                ),
            }
        )
        for quota in deck.quota_status
    ]
    return deck.model_copy(update={"quota_status": quota_status})


def _finalize_quality_generation_status(deck: GeneratedDeck) -> GeneratedDeck:
    """Mark legal-but-structurally-failed drafts distinctly from successes."""
    if not deck.is_valid or deck.validation_errors:
        return deck.model_copy(update={"generation_status": "failed_validation"})

    deck = _apply_effective_quota_semantics(deck)

    # Pool-limited gaps already annotated; export remains enabled
    if deck.generation_status == "generated_with_collection_gap":
        return deck

    failures = _quality_failure_reasons(deck)
    if not failures:
        return deck.model_copy(update={"generation_status": "success"})

    warnings = _merge_warnings(
        deck.warnings,
        [f"Deck quality failure: {reason}" for reason in failures],
    )
    repair_blockers = deck.repair_blockers or _generic_repair_blockers(deck)
    return deck.model_copy(
        update={
            "generation_status": "failed_quality",
            "warnings": warnings,
            "repair_blockers": repair_blockers,
        }
    )


def _generic_repair_blockers(deck: GeneratedDeck) -> list[RepairBlocker]:
    blockers: list[RepairBlocker] = []
    for quota in deck.quota_status:
        if quota.warning and not quota.effective_satisfied:
            blockers.append(
                RepairBlocker(
                    failure_type="quota_underfill" if quota.actual_count < quota.target_min else "quota_overfill",
                    role=quota.role,
                    reason="role_count_semantics",
                    detail=quota.warning,
                )
            )
        if quota.credit_warning and not quota.credit_satisfied:
            blockers.append(
                RepairBlocker(
                    failure_type="quota_credit",
                    role=quota.role,
                    reason="credit_candidate_not_better",
                    detail=quota.credit_warning,
                )
            )
    report = deck.strategic_coherence
    if report is not None:
        for reason in report.confidence_cap_reasons:
            blockers.append(
                RepairBlocker(
                    failure_type="strategic_coherence",
                    reason="coherence_blocked",
                    detail=f"Coherence confidence remains capped by {reason}.",
                )
            )
    return blockers


MAX_REPAIR_ITERATIONS: int = 10


def _multi_pass_quality_repair(
    deck: GeneratedDeck,
    commander: CardData,
    commander_tags: list[RoleTag],
    all_cards_lookup: dict[str, CardData],
    quotas: list,
    enriched_candidate_pool: list[DeckCard],
    packages: list[PackageCluster],
) -> GeneratedDeck:
    """Multi-pass quality repair loop (SC-DECK-030).

    Replaces _quality_retry_once. Runs up to MAX_REPAIR_ITERATIONS passes,
    each addressing the highest-priority unresolved failure.
    """
    repairs_done = 0
    while repairs_done < MAX_REPAIR_ITERATIONS:
        if not _quality_failure_reasons(deck):
            break
        improved = _attempt_one_repair(
            deck=deck,
            enriched_candidate_pool=enriched_candidate_pool,
            all_cards_lookup=all_cards_lookup,
            commander=commander,
            commander_tags=commander_tags,
            quotas=quotas,
            packages=packages,
        )
        if improved is None:
            break
        coherence_report = StrategicCoherenceValidator().validate(
            commander=commander,
            commander_tags=commander_tags,
            deck=improved,
            all_cards_lookup=all_cards_lookup,
            packages=packages,
        )
        improved = improved.model_copy(update={"strategic_coherence": coherence_report})
        improved = _refresh_deck_derived_state(
            deck=improved,
            commander=commander,
            all_cards_lookup=all_cards_lookup,
            quotas=quotas,
            coherence_report=coherence_report,
        )
        deck = _finalize_coherence_fail_closed(improved, packages)
        repairs_done += 1

    if repairs_done > 0:
        deck = deck.model_copy(
            update={
                "warnings": _merge_warnings(
                    deck.warnings,
                    [f"quality repair: {repairs_done} iteration(s)"],
                )
            }
        )

    # Detect pool-limited gaps: remaining count failures where the pool has no more candidates
    remaining_failures = _quality_failure_reasons(deck)
    repair_blockers = _repair_blockers_for_remaining_failures(
        deck=deck,
        enriched_candidate_pool=enriched_candidate_pool,
        all_cards_lookup=all_cards_lookup,
        quotas=quotas,
        iteration_budget_exhausted=(
            repairs_done >= MAX_REPAIR_ITERATIONS and bool(remaining_failures)
        ),
    )
    if remaining_failures:
        selected_ids = {c.oracle_id for c in deck.main_deck}
        pool_limited_roles = [
            role for role in _underfilled_role_names(deck)
            if _is_role_pool_limited(role, selected_ids, enriched_candidate_pool, all_cards_lookup)
        ]
        if pool_limited_roles and _only_pool_limited_count_failures(deck, pool_limited_roles):
            gap_warnings = [
                f"collection_gap: {role}: no more candidates available in collection"
                for role in pool_limited_roles
            ]
            deck = deck.model_copy(
                update={
                    "warnings": _merge_warnings(deck.warnings, gap_warnings),
                    "generation_status": "generated_with_collection_gap",
                }
            )

    if repair_blockers:
        deck = deck.model_copy(update={"repair_blockers": repair_blockers})

    return deck


def _repair_blockers_for_remaining_failures(
    deck: GeneratedDeck,
    enriched_candidate_pool: list[DeckCard],
    all_cards_lookup: dict[str, CardData],
    quotas: list,
    iteration_budget_exhausted: bool,
) -> list[RepairBlocker]:
    blockers: list[RepairBlocker] = []
    seen: set[tuple[str, str | None, str | None, str | None, str]] = set()

    def add(
        failure_type: str,
        reason: str,
        detail: str,
        role: str | None = None,
        package_id: str | None = None,
        oracle_id: str | None = None,
    ) -> None:
        key = (failure_type, role, package_id, oracle_id, reason)
        if key in seen:
            return
        seen.add(key)
        blockers.append(
            RepairBlocker(
                failure_type=failure_type,
                role=role,
                package_id=package_id,
                oracle_id=oracle_id,
                reason=reason,
                detail=detail,
            )
        )

    selected_ids = {card.oracle_id for card in deck.main_deck}
    for quota in deck.quota_status:
        if quota.actual_count < quota.target_min and not quota_effectively_satisfied(
            quota, deck.strategic_coherence
        ):
            candidates = [
                card for card in enriched_candidate_pool
                if card.oracle_id not in selected_ids
                and quota.role in card.roles
                and "LAND" not in card.roles
                and card.oracle_id in all_cards_lookup
            ]
            if not candidates:
                add(
                    "quota_underfill",
                    "no_candidate",
                    f"No unselected candidate can fill {quota.role}.",
                    role=quota.role,
                )
            elif _find_swap_target(deck, quota.role, quotas) is None:
                add(
                    "quota_underfill",
                    "no_safe_removal",
                    f"{len(candidates)} candidate(s) exist for {quota.role}, but no selected card can be removed without violating another quota.",
                    role=quota.role,
                )
            else:
                add(
                    "quota_underfill",
                    "role_count_semantics",
                    f"{quota.role} remains below target after repair; candidate and removal path exists, so assigned-role semantics or repair ordering blocked completion.",
                    role=quota.role,
                )

        if not quota.credit_satisfied:
            candidates = [
                card for card in enriched_candidate_pool
                if card.oracle_id not in selected_ids
                and quota.role in card.roles
                and "LAND" not in card.roles
                and card.oracle_id in all_cards_lookup
            ]
            if not candidates:
                reason = "no_candidate"
                detail = f"No unselected candidate can improve {quota.role} credit."
            else:
                reason = "credit_candidate_not_better"
                detail = (
                    f"{quota.role} credit remains {quota.credit_sum:.1f}/{quota.target_min}; "
                    "available candidates did not produce a usable credit-improving swap."
                )
            add("quota_credit", reason, detail, role=quota.role)

    report = deck.strategic_coherence
    if report is not None:
        for oracle_id in report.warning_card_oracle_ids:
            add(
                "strategic_coherence",
                "coherence_blocked",
                "Selected card remains an off-plan strategic coherence warning after repair.",
                oracle_id=oracle_id,
            )
        for reason in report.confidence_cap_reasons:
            add(
                "strategic_coherence",
                "coherence_blocked",
                f"Coherence confidence remains capped by {reason}.",
            )

    for package in deck.package_breakdown:
        if package.activation_status in {"underfilled", "rejected_loose", "inactive_bad_composition"}:
            add(
                "package_activation",
                "pool_limit" if package.activation_status == "underfilled" else "coherence_blocked",
                f"Package {package.package_id} remains {package.activation_status} with {package.selected_count} selected card(s).",
                package_id=package.package_id,
            )

    if iteration_budget_exhausted:
        add(
            "repair_loop",
            "iteration_budget_exhausted",
            f"Repair loop reached {MAX_REPAIR_ITERATIONS} iteration(s) with unresolved quality failures.",
        )

    return blockers


def _attempt_one_repair(
    deck: GeneratedDeck,
    enriched_candidate_pool: list[DeckCard],
    all_cards_lookup: dict[str, CardData],
    commander: CardData,
    commander_tags: list[RoleTag],
    quotas: list,
    packages: list[PackageCluster],
) -> GeneratedDeck | None:
    """Try each repair type in priority order. Return updated deck or None."""
    selected_ids = {c.oracle_id for c in deck.main_deck}

    # 1. WIN_CONDITION quota shortfall
    if _win_condition_underfilled(deck):
        result = _repair_by_role(deck, "WIN_CONDITION", selected_ids, enriched_candidate_pool, all_cards_lookup, quotas)
        if result is not None:
            return result

    # 2. Most underfilled required roles (ramp, draw, removal, etc.)
    for role in _underfilled_required_roles(deck):
        result = _repair_by_role(deck, role, selected_ids, enriched_candidate_pool, all_cards_lookup, quotas)
        if result is not None:
            return result

    # 3. Off-plan warning card
    if deck.strategic_coherence and deck.strategic_coherence.warning_card_oracle_ids:
        result = _repair_off_plan_one(deck, selected_ids, enriched_candidate_pool, all_cards_lookup, commander, packages, quotas)
        if result is not None:
            return result

    # 4. Inactive package orphan
    result = _repair_orphan_one(deck, selected_ids, enriched_candidate_pool, all_cards_lookup, packages, quotas)
    if result is not None:
        return result

    # 5. Quality-weak card
    result = _repair_quality_weak_one(deck, selected_ids, enriched_candidate_pool, all_cards_lookup, quotas)
    if result is not None:
        return result

    # 6. Credit-quality upgrade: replace lowest-credit role-filler for the worst credit gap
    return _repair_credit_quality_one(deck, selected_ids, enriched_candidate_pool, all_cards_lookup, quotas)


def _win_condition_underfilled(deck: GeneratedDeck) -> bool:
    return any(
        quota.role == "WIN_CONDITION" and quota.actual_count < quota.target_min
        for quota in deck.quota_status
    )


def _underfilled_required_roles(deck: GeneratedDeck) -> list[str]:
    """Return hard-required roles below target_min, sorted by largest deficit first."""
    from app.recommendation.strategic_coherence import REQUIRED_ROLE_FILLERS

    deficits: list[tuple[int, str]] = []
    for quota in deck.quota_status:
        if quota.role in REQUIRED_ROLE_FILLERS and quota.actual_count < quota.target_min:
            deficits.append((quota.target_min - quota.actual_count, quota.role))
    deficits.sort(reverse=True)
    return [role for _, role in deficits]


def _underfilled_role_names(deck: GeneratedDeck) -> list[str]:
    """Return all roles (not just required) with actual_count < target_min."""
    return [
        quota.role
        for quota in deck.quota_status
        if quota.actual_count < quota.target_min
    ]


def _is_role_pool_limited(
    role: str,
    selected_ids: set[str],
    enriched_candidate_pool: list[DeckCard],
    all_cards_lookup: dict[str, CardData],
) -> bool:
    """Return True when no unselected pool candidate has the given role."""
    return not any(
        c.oracle_id not in selected_ids
        and role in c.roles
        and "LAND" not in c.roles
        and c.oracle_id in all_cards_lookup
        for c in enriched_candidate_pool
    )


def _only_pool_limited_count_failures(
    deck: GeneratedDeck,
    pool_limited_roles: list[str],
) -> bool:
    """Return True when every count-based failure is covered by pool_limited_roles."""
    pool_limited_set = set(pool_limited_roles)
    for quota in deck.quota_status:
        if quota.actual_count < quota.target_min and quota.role not in pool_limited_set:
            return False
    return True


def _find_swap_target(deck: GeneratedDeck, incoming_role: str, quotas: list) -> int | None:
    """Return index of the best card to swap out to make room for incoming_role."""
    quota_min: dict[str, int] = {q.role.value: q.target_min for q in quotas}
    quota_max: dict[str, int] = {q.role.value: q.target_max for q in quotas}
    role_counts: dict[str, int] = defaultdict(int)

    def _counted_roles(card: DeckCard) -> list[str]:
        if card.assigned_role is not None:
            return [card.assigned_role]
        return list(card.roles)

    for c in deck.main_deck:
        for r in _counted_roles(c):
            role_counts[r] += c.quantity

    warning_ids = set(
        deck.strategic_coherence.warning_card_oracle_ids
        if deck.strategic_coherence is not None
        else []
    )

    def _removable(card: DeckCard) -> bool:
        counted_roles = _counted_roles(card)
        return (
            "LAND" not in card.roles
            and incoming_role not in counted_roles
            and all(role_counts.get(r, 0) - 1 >= quota_min.get(r, 0) for r in counted_roles)
        )

    def _overfill_amount(card: DeckCard) -> int:
        best = 0
        for role in _counted_roles(card):
            cap = quota_max.get(role)
            if cap is not None:
                best = max(best, role_counts.get(role, 0) - cap)
        return best

    # Prefer warning cards first
    for idx, card in enumerate(deck.main_deck):
        if card.oracle_id in warning_ids and _removable(card):
            return idx

    overfilled_candidates = [
        (idx, _overfill_amount(card))
        for idx, card in enumerate(deck.main_deck)
        if _removable(card) and _overfill_amount(card) > 0
    ]
    if overfilled_candidates:
        overfilled_candidates.sort(key=lambda item: (-item[1], item[0]))
        return overfilled_candidates[0][0]

    # Then any suitable non-land card
    for idx, card in enumerate(deck.main_deck):
        if _removable(card):
            return idx
    # Last resort: non-land card regardless of incoming_role
    for idx, card in enumerate(deck.main_deck):
        counted_roles = _counted_roles(card)
        if (
            "LAND" not in card.roles
            and incoming_role not in counted_roles
            and all(role_counts.get(r, 0) - 1 >= quota_min.get(r, 0) for r in counted_roles)
        ):
            return idx
    return None


def _repair_by_role(
    deck: GeneratedDeck,
    role: str,
    selected_ids: set[str],
    enriched_candidate_pool: list[DeckCard],
    all_cards_lookup: dict[str, CardData],
    quotas: list,
) -> GeneratedDeck | None:
    """Add or swap in the best unselected candidate that fills the given role."""
    candidates = [
        c for c in enriched_candidate_pool
        if c.oracle_id not in selected_ids
        and role in c.roles
        and "LAND" not in c.roles
        and c.oracle_id in all_cards_lookup
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (not c.is_owned, -c.synergy_score, c.oracle_id))
    replacement = candidates[0].model_copy(
        update={"quantity": 1, "selection_reason": f"quality repair: fills {role}"}
    )
    swap_idx = _find_swap_target(deck, role, quotas)
    if swap_idx is None:
        return None
    main_deck = list(deck.main_deck)
    main_deck[swap_idx] = replacement
    return deck.model_copy(update={"main_deck": main_deck, "generation_status": "needs_repair"})


def _repair_off_plan_one(
    deck: GeneratedDeck,
    selected_ids: set[str],
    enriched_candidate_pool: list[DeckCard],
    all_cards_lookup: dict[str, CardData],
    commander: CardData,
    packages: list[PackageCluster],
    quotas: list,
) -> GeneratedDeck | None:
    """Replace one off-plan warning card with the best on-plan alternative."""
    from app.recommendation.strategic_coherence import REQUIRED_ROLE_FILLERS

    coherence_report = deck.strategic_coherence
    if coherence_report is None:
        return None

    quota_min: dict[str, int] = {q.role.value: q.target_min for q in quotas}
    role_counts: dict[str, int] = defaultdict(int)
    for c in deck.main_deck:
        for r in c.roles:
            role_counts[r] += c.quantity

    on_plan_pool = [
        c for c in enriched_candidate_pool
        if c.oracle_id not in selected_ids
        and "LAND" not in c.roles
        and c.name not in _BASIC_LAND_NAMES
        and _is_on_plan_candidate(c, all_cards_lookup, coherence_report, commander, packages)
    ]
    on_plan_pool.sort(key=lambda c: (not c.is_owned, -c.synergy_score, c.oracle_id))

    for warning_oid in coherence_report.warning_card_oracle_ids:
        card_idx = next(
            (i for i, c in enumerate(deck.main_deck) if c.oracle_id == warning_oid), None
        )
        if card_idx is None:
            continue
        warning_card = deck.main_deck[card_idx]
        if REQUIRED_ROLE_FILLERS.intersection(warning_card.roles):
            if not all(
                role_counts.get(r, 0) - 1 >= quota_min.get(r, 0) for r in warning_card.roles
            ):
                continue
        replacement = next((c for c in on_plan_pool if c.oracle_id not in selected_ids), None)
        if replacement is None:
            return None
        main_deck = list(deck.main_deck)
        main_deck[card_idx] = replacement.model_copy(
            update={
                "quantity": 1,
                "selection_reason": f"quality repair: replaced off-plan {warning_card.name}",
            }
        )
        return deck.model_copy(update={"main_deck": main_deck, "generation_status": "needs_repair"})
    return None


def _repair_orphan_one(
    deck: GeneratedDeck,
    selected_ids: set[str],
    enriched_candidate_pool: list[DeckCard],
    all_cards_lookup: dict[str, CardData],
    packages: list[PackageCluster],
    quotas: list,
) -> GeneratedDeck | None:
    """Replace one inactive-package orphan with a package-active or on-plan alternative."""
    if not packages:
        return None

    active_ids = active_package_ids_for_deck(deck.main_deck, packages)
    underfilled_ids = frozenset(
        p.package_id for p in packages if p.package_id not in active_ids
    )
    if not underfilled_ids:
        return None

    card_to_pkgs: dict[str, list[str]] = {}
    for pkg in packages:
        for oid in pkg.card_oracle_ids:
            card_to_pkgs.setdefault(oid, []).append(pkg.package_id)

    quota_min: dict[str, int] = {q.role.value: q.target_min for q in quotas}
    role_counts: dict[str, int] = defaultdict(int)
    for c in deck.main_deck:
        for r in c.roles:
            role_counts[r] += c.quantity

    for idx, card in enumerate(deck.main_deck):
        if "LAND" in card.roles:
            continue
        pkg_ids = card_to_pkgs.get(card.oracle_id, [])
        if not pkg_ids:
            continue
        card_with_pkgs = card.model_copy(update={"package_ids": pkg_ids})
        if not is_orphan(card_with_pkgs, underfilled_ids):
            continue
        if not all(role_counts.get(r, 0) - 1 >= quota_min.get(r, 0) for r in card.roles):
            continue

        candidates = [
            c for c in enriched_candidate_pool
            if c.oracle_id not in selected_ids
            and "LAND" not in c.roles
            and c.oracle_id in all_cards_lookup
        ]
        candidates.sort(
            key=lambda c: (
                not any(pid in active_ids for pid in c.package_ids),
                not c.is_owned,
                -c.synergy_score,
                c.oracle_id,
            )
        )
        if not candidates:
            return None
        replacement = candidates[0].model_copy(
            update={"quantity": 1, "selection_reason": f"quality repair: replaced orphan {card.name}"}
        )
        main_deck = list(deck.main_deck)
        main_deck[idx] = replacement
        return deck.model_copy(update={"main_deck": main_deck, "generation_status": "needs_repair"})
    return None


def _repair_quality_weak_one(
    deck: GeneratedDeck,
    selected_ids: set[str],
    enriched_candidate_pool: list[DeckCard],
    all_cards_lookup: dict[str, CardData],
    quotas: list,
) -> GeneratedDeck | None:
    """Replace one quality-weak non-land card with a higher-synergy role-equivalent."""
    quota_min: dict[str, int] = {q.role.value: q.target_min for q in quotas}
    role_counts: dict[str, int] = defaultdict(int)
    for c in deck.main_deck:
        for r in c.roles:
            role_counts[r] += c.quantity

    weak_cards = [
        (idx, card)
        for idx, card in enumerate(deck.main_deck)
        if "LAND" not in card.roles
        and "WIN_CONDITION" not in card.roles
        and all(role_counts.get(r, 0) - 1 >= quota_min.get(r, 0) for r in card.roles)
    ]
    if not weak_cards:
        return None
    weak_cards.sort(key=lambda t: (t[1].is_owned, t[1].synergy_score, t[1].oracle_id))
    swap_idx, swap_card = weak_cards[0]

    candidates = [
        c for c in enriched_candidate_pool
        if c.oracle_id not in selected_ids
        and "LAND" not in c.roles
        and c.oracle_id in all_cards_lookup
        and c.synergy_score > swap_card.synergy_score
        and any(r in c.roles for r in swap_card.roles)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (not c.is_owned, -c.synergy_score, c.oracle_id))
    replacement = candidates[0].model_copy(
        update={
            "quantity": 1,
            "selection_reason": f"quality repair: replaced quality-weak {swap_card.name}",
        }
    )
    main_deck = list(deck.main_deck)
    main_deck[swap_idx] = replacement
    return deck.model_copy(update={"main_deck": main_deck, "generation_status": "needs_repair"})


def _compute_role_credit_sum(
    deck: GeneratedDeck,
    role: str,
    all_cards_lookup: dict[str, CardData],
) -> float:
    """Sum role_quality_credit for all cards whose assigned_role matches target role."""
    return sum(
        role_quality_credit(all_cards_lookup[c.oracle_id], role)
        for c in deck.main_deck
        if c.assigned_role == role and c.oracle_id in all_cards_lookup
    )


def _find_lowest_credit_card(
    deck: GeneratedDeck,
    role: str,
    all_cards_lookup: dict[str, CardData],
    quotas: list,
) -> int | None:
    """Return index of the lowest-credit removable card assigned to target role."""
    quota_min: dict[str, int] = {q.role.value: q.target_min for q in quotas}
    role_counts: dict[str, int] = defaultdict(int)
    for c in deck.main_deck:
        for r in c.roles:
            role_counts[r] += c.quantity

    role_cards = [
        (idx, card)
        for idx, card in enumerate(deck.main_deck)
        if role in card.roles
        and "LAND" not in card.roles
        and all(
            role_counts.get(r, 0) - 1 >= quota_min.get(r, 0)
            for r in card.roles
            if r != role
        )
    ]
    if not role_cards:
        return None

    role_cards.sort(
        key=lambda t: (
            role_quality_credit(all_cards_lookup[t[1].oracle_id], role)
            if t[1].oracle_id in all_cards_lookup else 0.0,
            t[1].oracle_id,
        )
    )
    return role_cards[0][0]


def _find_highest_credit_candidate(
    pool: list[DeckCard],
    role: str,
    selected_ids: set[str],
    all_cards_lookup: dict[str, CardData],
) -> DeckCard | None:
    """Return the highest-credit unselected candidate for target role."""
    candidates = [
        c for c in pool
        if c.oracle_id not in selected_ids
        and role in c.roles
        and "LAND" not in c.roles
        and c.oracle_id in all_cards_lookup
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda c: (
            -role_quality_credit(all_cards_lookup[c.oracle_id], role),
            not c.is_owned,
            -c.synergy_score,
            c.oracle_id,
        )
    )
    return candidates[0]


def _do_swap(
    deck: GeneratedDeck,
    remove_idx: int,
    incoming: DeckCard,
    role: str,
) -> GeneratedDeck:
    """Remove card at remove_idx, insert incoming card with role assignment."""
    replacement = incoming.model_copy(
        update={
            "quantity": 1,
            "selection_reason": f"quality repair: improved {role} credit",
        }
    )
    main_deck = list(deck.main_deck)
    main_deck[remove_idx] = replacement
    return deck.model_copy(update={"main_deck": main_deck, "generation_status": "needs_repair"})


def _repair_credit_quality_one(
    deck: GeneratedDeck,
    selected_ids: set[str],
    enriched_candidate_pool: list[DeckCard],
    all_cards_lookup: dict[str, CardData],
    quotas: list,
) -> GeneratedDeck | None:
    """Exhaust swaps for the worst credit-gap role before returning.

    Only fires when is_satisfied=True but credit_satisfied=False (count-met, credit-not-met).
    Inner loop cap of 10 prevents infinite loops on pathological inputs.
    """
    credit_gaps = [
        (q.target_min - q.credit_sum, q)
        for q in deck.quota_status
        if q.is_satisfied and not q.credit_satisfied
    ]
    if not credit_gaps:
        return None
    credit_gaps.sort(key=lambda item: item[0], reverse=True)
    _, worst_quota = credit_gaps[0]
    target_role = worst_quota.role

    current_deck = deck
    made_any_swap = False

    for _ in range(10):
        current_credit = _compute_role_credit_sum(current_deck, target_role, all_cards_lookup)
        if current_credit >= worst_quota.target_min:
            break

        swap_idx = _find_lowest_credit_card(current_deck, target_role, all_cards_lookup, quotas)
        if swap_idx is None:
            break

        current_selected = {c.oracle_id for c in current_deck.main_deck}
        best_candidate = _find_highest_credit_candidate(
            enriched_candidate_pool, target_role, current_selected, all_cards_lookup
        )
        if best_candidate is None:
            break

        current_deck = _do_swap(current_deck, swap_idx, best_candidate, target_role)
        made_any_swap = True

    return current_deck if made_any_swap else None


def _quality_failure_reasons(deck: GeneratedDeck) -> list[str]:
    reasons: list[str] = []
    for quota in deck.quota_status:
        if not quota_effectively_satisfied(quota, deck.strategic_coherence) and quota.warning:
            reasons.append(quota.warning)
        if not quota.credit_satisfied and quota.credit_warning:
            reasons.append(quota.credit_warning)
        if quota.role == "WIN_CONDITION" and quota.actual_count < quota.target_min:
            reasons.append(
                f"WIN_CONDITION: need {quota.target_min}–{quota.target_max}, got {quota.actual_count}"
            )

    report = deck.strategic_coherence
    if report is not None:
        structural_caps = [
            reason
            for reason in report.confidence_cap_reasons
            if reason != "validation_error"
        ]
        if structural_caps:
            reasons.append(
                "coherence confidence capped by unresolved structural issue(s): "
                + ", ".join(structural_caps)
            )
        if report.off_plan_count > MAX_OFF_PLAN_CARDS:
            reasons.append(
                f"off-plan nonland cards exceed limit: {report.off_plan_count}/{MAX_OFF_PLAN_CARDS}"
            )

    return _merge_warnings([], reasons)


def _finalize_coherence_fail_closed(
    deck: GeneratedDeck,
    packages: list[PackageCluster],
) -> GeneratedDeck:
    """Cap strategic coherence metrics when unresolved deck failures remain."""
    report = deck.strategic_coherence
    if report is None:
        return deck

    cap_reasons = _coherence_cap_reasons(deck, report, packages)
    if not cap_reasons:
        finalized_deck = deck.model_copy(
            update={
                "strategic_coherence": report.model_copy(
                    update={"confidence_cap_reasons": []}
                )
            }
        )
        return _apply_effective_quota_semantics(finalized_deck)

    cap = (
        COHERENCE_VALIDATION_CONFIDENCE_CAP
        if "validation_error" in cap_reasons
        else COHERENCE_FAIL_CLOSED_CONFIDENCE_CAP
    )
    warnings = _merge_warnings(
        report.warnings,
        ["Strategic coherence confidence capped: unresolved deck-quality failures remain."],
    )
    finalized_report = report.model_copy(
        update={
            "confidence": min(report.confidence, cap),
            "off_plan_count": max(report.off_plan_count, 1),
            "confidence_cap_reasons": cap_reasons,
            "warnings": warnings,
        }
    )

    finalized_deck = deck.model_copy(
        update={
            "strategic_coherence": finalized_report,
            "warnings": _merge_warnings(deck.warnings, finalized_report.warnings),
            "generation_status": (
                "failed_validation"
                if (not deck.is_valid or deck.validation_errors)
                else deck.generation_status
            ),
        }
    )
    return _apply_effective_quota_semantics(finalized_deck)


def _coherence_cap_reasons(
    deck: GeneratedDeck,
    report: StrategicCoherenceReport,
    packages: list[PackageCluster],
) -> list[str]:
    reasons: list[str] = []
    if not deck.is_valid or deck.validation_errors:
        reasons.append("validation_error")
    if any(
        not quota.is_satisfied
        and not quota_count_credit_covered(quota, report)
        for quota in deck.quota_status
    ):
        reasons.append("hard_quota_failure")
    if any(not quota.credit_satisfied for quota in deck.quota_status):
        reasons.append("quota_credit_failure")
    if any(_is_loose_package_warning(w) for w in [*deck.warnings, *report.warnings]):
        reasons.append("loose_package")
    if report.warning_card_oracle_ids:
        reasons.append("unresolved_warning_cards")
    if _has_commander_irrelevant_active_package(report, packages):
        reasons.append("commander_irrelevant_active_package")
    return reasons


def _is_loose_package_warning(warning: str) -> bool:
    return "Loose Treasure/Clue/Food/Map" in warning


def _has_commander_irrelevant_active_package(
    report: StrategicCoherenceReport,
    packages: list[PackageCluster],
) -> bool:
    if not report.active_package_ids:
        return False
    if report.primary_plan is None:
        return False  # Unknown plan — cannot determine relevance

    package_by_id = {package.package_id: package for package in packages}
    for package_id in report.active_package_ids:
        package = package_by_id.get(package_id)
        if package is None:
            continue
        if not _package_matches_primary_plan(package, report.primary_plan):
            return True
    return False


def _package_matches_primary_plan(package: PackageCluster, primary_plan: str) -> bool:
    normalized_plan = primary_plan.replace("-", " ").lower()
    package_text = " ".join([package.label, *package.top_roles]).replace("_", " ").lower()
    if normalized_plan in package_text:
        return True

    plan_roles = PLAN_ROLE_HINTS.get(primary_plan, frozenset())
    return any(role.replace("_", " ").lower() in package_text for role in plan_roles)


def _is_on_plan_candidate(
    card: DeckCard,
    all_cards_lookup: dict[str, CardData],
    coherence_report: StrategicCoherenceReport,
    commander: CardData,
    packages: list[PackageCluster],
) -> bool:
    """Return True when a candidate card is justified for the commander's plan."""
    from app.recommendation.strategic_coherence import is_card_justified

    card_data = all_cards_lookup.get(card.oracle_id)
    if card_data is None:
        return False
    active_pkg_ids = set(coherence_report.active_package_ids)
    return is_card_justified(
        card=card,
        card_data=card_data,
        primary_plan=coherence_report.primary_plan,
        active_package_ids=active_pkg_ids,
        commander_oracle_id=commander.oracle_id,
    )


def _build_deck_score_logs(session_id: str, deck: GeneratedDeck) -> list[ScoreLog]:
    logs: list[ScoreLog] = []
    if deck.strategic_coherence is not None:
        report = deck.strategic_coherence
        report_warnings = _merge_warnings(report.warnings, deck.warnings)
        logs.append(
            ScoreLog(
                session_id=session_id,
                scope="deck_analysis",
                data_version=DATA_VERSION,
                subject_id=deck.deck_id,
                score_components={
                    "strategic_confidence": round(report.confidence, 6),
                    "on_plan_count": float(report.on_plan_count),
                    "off_plan_count": float(report.off_plan_count),
                    "warning_candidate_count": float(len(report.warning_card_oracle_ids)),
                },
                selected_reasons=[
                    f"primary_plan:{report.primary_plan or 'unknown'}",
                    f"commander_profile_source:{get_commander_profile_source(deck.commander.oracle_id, deck.commander.name)}",
                    *[f"active_package:{pid}" for pid in report.active_package_ids],
                    *[
                        f"coherence_cap:{reason}"
                        for reason in report.confidence_cap_reasons
                    ],
                ],
                warnings=[
                    *report_warnings,
                    *[f"warning_card:{oid}" for oid in report.warning_card_oracle_ids],
                ],
            )
        )
    elif deck.warnings:
        logs.append(
            ScoreLog(
                session_id=session_id,
                scope="deck_analysis",
                data_version=DATA_VERSION,
                subject_id=deck.deck_id,
                score_components={
                    "warning_count": float(len(deck.warnings)),
                },
                selected_reasons=[],
                warnings=list(deck.warnings),
            )
        )

    for card in [deck.commander] + sorted(deck.main_deck, key=lambda c: c.oracle_id):
        logs.append(
            ScoreLog(
                session_id=session_id,
                scope="deck_generation",
                data_version=DATA_VERSION,
                subject_id=card.oracle_id,
                score_components={
                    "quantity": float(card.quantity),
                    "synergy_score": round(card.synergy_score, 6),
                    "owned": 1.0 if card.is_owned else 0.0,
                    "role_count": float(len(card.roles)),
                    "package_count": float(len(card.package_ids)),
                },
                selected_reasons=[card.selection_reason] if card.selection_reason else [],
                warnings=[] if card.is_owned else ["missing_card"],
            )
        )
    return logs


def _merge_warnings(existing: list[str], new: list[str]) -> list[str]:
    merged: list[str] = []
    for warning in [*existing, *new]:
        if warning not in merged:
            merged.append(warning)
    return merged
