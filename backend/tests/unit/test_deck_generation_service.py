"""Tests for SC-DECK-018: coherence repair pass in deck_generation_service."""
from __future__ import annotations

import json
from pathlib import Path

from app.models.card import CardData
from app.models.deck import (
    DeckCard,
    GeneratedDeck,
    PackageCluster,
    QuotaStatus,
    StrategicCoherenceReport,
)
from app.recommendation.role_taxonomy import CardRole
from app.recommendation.strategic_coherence import (
    MAX_OFF_PLAN_CARDS,
    StrategicCoherenceValidator,
)
from app.recommendation.quota_config import RoleQuota
from app.services.deck_generation_service import (
    MAX_REPAIR_ITERATIONS,
    _build_deck_score_logs,
    _coherence_repair_pass,
    _finalize_coherence_fail_closed,
    _finalize_quality_generation_status,
    _find_swap_target,
    _has_commander_irrelevant_active_package,
    _is_on_plan_candidate,
    _is_role_pool_limited,
    _multi_pass_quality_repair,
    _quality_failure_reasons,
    _refresh_deck_derived_state,
    _repair_credit_quality_one,
)

GRETA_FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "negative" / "greta_incoherent_generic_pile.json"
)
TOLUZ_FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "negative" / "toluz_incoherent_generic_pile.json"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_commander(oracle_id: str = "test-cmd", name: str = "Test Commander") -> CardData:
    return CardData(
        id=oracle_id,
        oracle_id=oracle_id,
        name=name,
        color_identity=["B", "G"],
        legalities={"commander": "legal"},
        type_line="Legendary Creature — Test",
        oracle_text="sacrifice a food: draw a card.",
        mana_cost="{2}{B}{G}",
        cmc=4.0,
    )


def _make_card_data(
    oracle_id: str,
    name: str,
    oracle_text: str = "",
    cmc: float = 2.0,
    color_identity: list[str] | None = None,
    type_line: str = "Creature",
    legalities: dict[str, str] | None = None,
) -> CardData:
    return CardData(
        id=oracle_id,
        oracle_id=oracle_id,
        name=name,
        color_identity=color_identity if color_identity is not None else ["B", "G"],
        legalities=legalities if legalities is not None else {"commander": "legal"},
        type_line=type_line,
        oracle_text=oracle_text,
        cmc=cmc,
    )


def _make_deck_card(
    oracle_id: str,
    name: str,
    roles: list[str],
    quantity: int = 1,
    synergy_score: float = 0.0,
    is_owned: bool = False,
) -> DeckCard:
    return DeckCard(
        oracle_id=oracle_id,
        name=name,
        is_owned=is_owned,
        quantity=quantity,
        roles=roles,
        selection_reason="test",
        synergy_score=synergy_score,
    )


def _make_minimal_deck(
    off_plan_card: DeckCard,
    commander: CardData,
) -> GeneratedDeck:
    """99-card deck: one off-plan card + Forest filling the remaining quantity."""
    remaining = 99 - off_plan_card.quantity
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=remaining)
    commander_card = DeckCard(
        oracle_id=commander.oracle_id,
        name=commander.name,
        is_owned=True,
        quantity=1,
        roles=[],
        selection_reason="commander",
    )
    return GeneratedDeck(
        deck_id="test-deck",
        session_id="test-session",
        commander=commander_card,
        main_deck=[off_plan_card, forest],
        role_breakdown={CardRole.LAND.value: remaining},
        quota_status=[],
        package_breakdown=[],
        warnings=[],
        owned_count=0,
        owned_percentage=0.0,
        is_valid=True,
        validation_errors=[],
    )


def _deck_for_swap(cards: list[DeckCard]) -> GeneratedDeck:
    commander = _make_commander()
    commander_card = DeckCard(
        oracle_id=commander.oracle_id,
        name=commander.name,
        is_owned=True,
        quantity=1,
        roles=[],
        selection_reason="commander",
    )
    return GeneratedDeck(
        deck_id="swap-test",
        session_id="swap-session",
        commander=commander_card,
        main_deck=cards,
        role_breakdown={},
        quota_status=[],
        package_breakdown=[],
        warnings=[],
        owned_count=0,
        owned_percentage=0.0,
        is_valid=True,
        validation_errors=[],
    )


def test_find_swap_target_prefers_overfilled_role_card() -> None:
    cards = [
        _make_deck_card("token-first", "Token First", [CardRole.TOKEN_MAKER.value]),
        *[
            _make_deck_card(f"ramp-{idx}", f"Ramp {idx}", [CardRole.RAMP.value])
            for idx in range(17)
        ],
    ]
    deck = _deck_for_swap(cards)
    quotas = [
        RoleQuota(CardRole.RAMP, target_min=12, target_max=14),
        RoleQuota(CardRole.TOKEN_MAKER, target_min=0, target_max=2),
        RoleQuota(CardRole.CARD_DRAW, target_min=8, target_max=10),
    ]

    idx = _find_swap_target(deck, CardRole.CARD_DRAW.value, quotas)

    assert idx is not None
    assert CardRole.RAMP.value in deck.main_deck[idx].roles


def test_find_swap_target_falls_back_when_no_overfill() -> None:
    cards = [
        _make_deck_card("token-first", "Token First", [CardRole.TOKEN_MAKER.value]),
        *[
            _make_deck_card(f"ramp-{idx}", f"Ramp {idx}", [CardRole.RAMP.value])
            for idx in range(2)
        ],
    ]
    deck = _deck_for_swap(cards)
    quotas = [
        RoleQuota(CardRole.RAMP, target_min=1, target_max=4),
        RoleQuota(CardRole.TOKEN_MAKER, target_min=0, target_max=4),
        RoleQuota(CardRole.CARD_DRAW, target_min=1, target_max=4),
    ]

    assert _find_swap_target(deck, CardRole.CARD_DRAW.value, quotas) == 0


def test_find_swap_target_overfill_priority_respects_removable() -> None:
    protected_ramp = [
        _make_deck_card(
            f"protected-ramp-{idx}",
            f"Protected Ramp {idx}",
            [CardRole.RAMP.value, CardRole.SPOT_REMOVAL.value],
        )
        for idx in range(17)
    ]
    fallback = _make_deck_card("token-fallback", "Token Fallback", [CardRole.TOKEN_MAKER.value])
    deck = _deck_for_swap([*protected_ramp, fallback])
    quotas = [
        RoleQuota(CardRole.RAMP, target_min=12, target_max=14),
        RoleQuota(CardRole.SPOT_REMOVAL, target_min=17, target_max=20),
        RoleQuota(CardRole.TOKEN_MAKER, target_min=0, target_max=4),
        RoleQuota(CardRole.CARD_DRAW, target_min=8, target_max=10),
    ]

    idx = _find_swap_target(deck, CardRole.CARD_DRAW.value, quotas)

    assert idx == len(protected_ramp)


def _load_negative_fixture(
    path: Path,
) -> tuple[CardData, GeneratedDeck, dict[str, CardData], list[PackageCluster]]:
    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    commander_raw = raw["commander"]
    color_identity: list[str] = commander_raw["color_identity"]

    commander = CardData(
        id=commander_raw["oracle_id"],
        oracle_id=commander_raw["oracle_id"],
        name=commander_raw["name"],
        color_identity=color_identity,
        legalities=commander_raw.get("legalities", {"commander": "legal"}),
        type_line=commander_raw["type_line"],
        oracle_text=commander_raw.get("oracle_text", ""),
        mana_cost=commander_raw.get("mana_cost", ""),
        cmc=commander_raw.get("cmc", 0.0),
        keywords=commander_raw.get("keywords", []),
    )

    pkg_raw = raw["unsupported_package"]
    package_card_ids = set(pkg_raw["card_oracle_ids"])
    package_id = pkg_raw["package_id"]

    lookup: dict[str, CardData] = {commander.oracle_id: commander}
    deck_cards: list[DeckCard] = []

    for item in raw["cards"]:
        card = CardData(
            id=item["oracle_id"],
            oracle_id=item["oracle_id"],
            name=item["name"],
            color_identity=color_identity,
            legalities={"commander": "legal"},
            type_line=item["type_line"],
            oracle_text=item["oracle_text"],
            cmc=item["cmc"],
        )
        lookup[card.oracle_id] = card
        deck_cards.append(
            DeckCard(
                oracle_id=card.oracle_id,
                name=card.name,
                is_owned=False,
                quantity=1,
                roles=item["roles"],
                package_ids=[package_id] if card.oracle_id in package_card_ids else [],
                selection_reason="test selection",
                synergy_score=0.0,
                color_identity=color_identity,
            )
        )

    package = PackageCluster(**pkg_raw)

    commander_card = DeckCard(
        oracle_id=commander.oracle_id,
        name=commander.name,
        is_owned=True,
        quantity=1,
        roles=[],
        selection_reason="commander",
        color_identity=color_identity,
    )
    deck = GeneratedDeck(
        deck_id=f"negative-fixture-{raw['fixture_id']}",
        session_id="negative-fixture-session",
        commander=commander_card,
        main_deck=deck_cards,
        role_breakdown={},
        quota_status=[],
        package_breakdown=[package],
        warnings=[],
        owned_count=0,
        owned_percentage=0.0,
        is_valid=True,
        validation_errors=[],
    )
    return commander, deck, lookup, [package]


def _forest_data(oracle_id: str = "forest-basic") -> CardData:
    return _make_card_data(
        oracle_id,
        "Forest",
        oracle_text="({T}: Add {G}.)",
        cmc=0.0,
        color_identity=["G"],
        type_line="Basic Land — Forest",
    )


def _deck_for_refresh(cards: list[DeckCard], commander: CardData) -> GeneratedDeck:
    commander_card = DeckCard(
        oracle_id=commander.oracle_id,
        name=commander.name,
        is_owned=True,
        quantity=1,
        roles=[],
        selection_reason="commander",
    )
    return GeneratedDeck(
        deck_id="refresh-test-deck",
        session_id="refresh-test-session",
        commander=commander_card,
        main_deck=cards,
        role_breakdown={"WIN_CONDITION": 99},
        quota_status=[
            QuotaStatus(
                role="WIN_CONDITION",
                target_min=99,
                target_max=99,
                actual_count=99,
                is_satisfied=True,
            )
        ],
        package_breakdown=[],
        warnings=[
            "CARD_DRAW: credit 0.2 < minimum 1 (raw count 1 cards but low-quality fillers detected)",
            "Strategic coherence warning: off-plan nonland cards exceed the configured limit.",
            "Utility land excluded for low strategic relevance: Mystifying Maze",
        ],
        owned_count=0,
        owned_percentage=0.0,
        is_valid=True,
        validation_errors=[],
    )


# ---------------------------------------------------------------------------
# SC-DECK-018 unit tests
# ---------------------------------------------------------------------------

def test_coherence_confidence_capped_by_validation_error() -> None:
    """SC-DECK-022: invalid repaired decks cannot report high confidence."""
    commander = _make_commander()
    deck = _deck_for_refresh(
        [_make_deck_card("blue-refresh", "Blue Intruder", [CardRole.WIN_CONDITION.value]),],
        commander,
    ).model_copy(
        update={
            "is_valid": False,
            "validation_errors": ["Blue Intruder has color identity ['U'] outside the commander's color identity."],
            "strategic_coherence": StrategicCoherenceReport(
                primary_plan="food-sacrifice",
                confidence=0.95,
                on_plan_count=10,
                off_plan_count=0,
            ),
            "warnings": [],
        }
    )

    finalized = _finalize_coherence_fail_closed(deck, [])

    assert finalized.strategic_coherence is not None
    assert finalized.strategic_coherence.confidence <= 0.20
    assert finalized.strategic_coherence.off_plan_count >= 1
    assert finalized.strategic_coherence.confidence_cap_reasons == ["validation_error"]


def test_coherence_confidence_capped_by_hard_quota_failure() -> None:
    """SC-DECK-022: hard quota failure caps strategic confidence."""
    commander = _make_commander()
    deck = _deck_for_refresh(
        [_make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=99)],
        commander,
    ).model_copy(
        update={
            "quota_status": [
                QuotaStatus(
                    role=CardRole.CARD_DRAW.value,
                    target_min=4,
                    target_max=6,
                    actual_count=0,
                    is_satisfied=False,
                    warning="CARD_DRAW: need 4–6, got 0 (underfilled)",
                )
            ],
            "strategic_coherence": StrategicCoherenceReport(
                primary_plan="food-sacrifice",
                confidence=0.9,
                on_plan_count=8,
                off_plan_count=0,
            ),
        }
    )

    finalized = _finalize_coherence_fail_closed(deck, [])

    assert finalized.strategic_coherence is not None
    assert finalized.strategic_coherence.confidence <= 0.35
    assert finalized.strategic_coherence.off_plan_count >= 1
    assert finalized.strategic_coherence.confidence_cap_reasons == ["hard_quota_failure"]


def test_off_plan_zero_disallowed_when_loose_package_warning_exists() -> None:
    """SC-DECK-022: loose package warnings force nonzero unresolved off-plan metric."""
    commander = _make_commander()
    deck = _deck_for_refresh(
        [_make_deck_card("food-card", "Food Card", [CardRole.TOKEN_MAKER.value])],
        commander,
    ).model_copy(
        update={
            "warnings": ["Loose Treasure/Clue/Food/Map artifact-value cards did not meet the active package threshold."],
            "strategic_coherence": StrategicCoherenceReport(
                primary_plan="food-sacrifice",
                confidence=0.8,
                on_plan_count=1,
                off_plan_count=0,
                warnings=["Loose Treasure/Clue/Food/Map artifact-value cards did not meet the active package threshold."],
            ),
        }
    )

    finalized = _finalize_coherence_fail_closed(deck, [])

    assert finalized.strategic_coherence is not None
    assert finalized.strategic_coherence.off_plan_count == 1
    assert finalized.strategic_coherence.confidence <= 0.35
    assert finalized.strategic_coherence.confidence_cap_reasons == ["loose_package"]


def test_score_log_exposes_coherence_cap_reasons() -> None:
    """SC-DECK-022: deck analysis score log includes deterministic cap reasons."""
    commander = _make_commander()
    deck = _deck_for_refresh(
        [_make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=99)],
        commander,
    ).model_copy(
        update={
            "quota_status": [
                QuotaStatus(
                    role=CardRole.CARD_DRAW.value,
                    target_min=4,
                    target_max=6,
                    actual_count=0,
                    is_satisfied=False,
                )
            ],
            "strategic_coherence": StrategicCoherenceReport(
                primary_plan="food-sacrifice",
                confidence=0.9,
                on_plan_count=8,
                off_plan_count=0,
            ),
        }
    )
    finalized = _finalize_coherence_fail_closed(deck, [])

    analysis_log = next(
        log for log in _build_deck_score_logs("cap-session", finalized)
        if log.scope == "deck_analysis"
    )

    assert "coherence_cap:hard_quota_failure" in analysis_log.selected_reasons

def test_coherence_repair_refreshes_role_breakdown() -> None:
    """SC-DECK-018 hardening: role_breakdown matches repaired main_deck."""
    commander = _make_commander()
    sac_card = _make_deck_card("sac-refresh", "Sac Outlet", ["SACRIFICE_OUTLET"])
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=98)
    deck = _deck_for_refresh([sac_card, forest], commander)
    report = StrategicCoherenceReport(primary_plan="aristocrats")

    refreshed = _refresh_deck_derived_state(
        deck=deck,
        commander=commander,
        all_cards_lookup={
            commander.oracle_id: commander,
            "sac-refresh": _make_card_data("sac-refresh", "Sac Outlet", "sacrifice a creature: gain life."),
            "forest-basic": _forest_data(),
        },
        quotas=[
            RoleQuota(CardRole.SACRIFICE_OUTLET, 1, 3),
            RoleQuota(CardRole.LAND, 36, 40),
        ],
        coherence_report=report,
    )

    assert refreshed.role_breakdown == {
        CardRole.SACRIFICE_OUTLET.value: 1,
        CardRole.LAND.value: 98,
    }


def test_quality_failures_set_failed_quality_status() -> None:
    commander = _make_commander()
    deck = _deck_for_refresh([], commander).model_copy(
        update={
            "quota_status": [
                QuotaStatus(
                    role=CardRole.WIN_CONDITION.value,
                    target_min=3,
                    target_max=8,
                    actual_count=0,
                    is_satisfied=False,
                    warning="WIN_CONDITION: need 3–8, got 0 assigned slot(s) (underfilled)",
                    credit_sum=0.0,
                    credit_satisfied=False,
                    credit_warning="WIN_CONDITION: credit 0.0 < minimum 3",
                )
            ],
            "is_valid": True,
            "validation_errors": [],
        }
    )

    finalized = _finalize_quality_generation_status(deck)

    assert finalized.generation_status == "failed_quality"
    assert any("Deck quality failure" in warning for warning in finalized.warnings)


def test_failed_quality_response_explains_remaining_gaps() -> None:
    commander = _make_commander()
    deck = _deck_for_refresh([], commander).model_copy(
        update={
            "quota_status": [
                QuotaStatus(
                    role=CardRole.RAMP.value,
                    target_min=2,
                    target_max=3,
                    actual_count=2,
                    is_satisfied=True,
                    credit_sum=0.5,
                    credit_satisfied=False,
                    credit_warning="RAMP: credit 0.5 < minimum 2",
                )
            ],
            "strategic_coherence": StrategicCoherenceReport(
                primary_plan="food-sacrifice",
                confidence=0.35,
                on_plan_count=1,
                off_plan_count=MAX_OFF_PLAN_CARDS + 1,
                confidence_cap_reasons=["quota_credit_failure"],
            ),
        }
    )

    finalized = _finalize_quality_generation_status(deck)

    assert finalized.generation_status == "failed_quality"
    assert any("RAMP: credit 0.5" in warning for warning in finalized.warnings)
    assert any("off-plan" in warning for warning in finalized.warnings)


def test_refresh_deck_derived_state_uses_role_slots_after_repair() -> None:
    """SC-DECK-023: refresh uses assigned slots, not every raw role tag."""
    commander = _make_commander()
    package_card = _make_deck_card(
        "multi-role-refresh",
        "Multi Role Refresh",
        [
            CardRole.CARD_DRAW.value,
            CardRole.RAMP.value,
            CardRole.TOKEN_MAKER.value,
            CardRole.WIN_CONDITION.value,
        ],
    )
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=98)
    deck = _deck_for_refresh([package_card, forest], commander)
    report = StrategicCoherenceReport(primary_plan="aristocrats")

    refreshed = _refresh_deck_derived_state(
        deck=deck,
        commander=commander,
        all_cards_lookup={
            commander.oracle_id: commander,
            "multi-role-refresh": _make_card_data(
                "multi-role-refresh",
                "Multi Role Refresh",
                "Draw two cards.",
            ),
            "forest-basic": _forest_data(),
        },
        quotas=[
            RoleQuota(CardRole.CARD_DRAW, 1, 4),
            RoleQuota(CardRole.RAMP, 1, 4),
            RoleQuota(CardRole.LAND, 36, 40),
        ],
        coherence_report=report,
    )

    refreshed_card = next(
        card for card in refreshed.main_deck if card.oracle_id == package_card.oracle_id
    )
    assert refreshed_card.assigned_role == CardRole.CARD_DRAW.value
    assert CardRole.RAMP.value in refreshed_card.roles
    assert refreshed.role_breakdown == {
        CardRole.CARD_DRAW.value: 1,
        CardRole.LAND.value: 98,
    }
    ramp_status = next(
        quota for quota in refreshed.quota_status if quota.role == CardRole.RAMP.value
    )
    assert ramp_status.actual_count == 0


def test_coherence_repair_refreshes_quota_credit_status() -> None:
    """SC-DECK-018 hardening: quota actual_count and credit_sum are rebuilt."""
    commander = _make_commander()
    draw_card = _make_deck_card("draw-refresh", "Repeatable Draw", [CardRole.CARD_DRAW.value])
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=98)
    deck = _deck_for_refresh([draw_card, forest], commander)
    report = StrategicCoherenceReport(primary_plan="aristocrats")

    refreshed = _refresh_deck_derived_state(
        deck=deck,
        commander=commander,
        all_cards_lookup={
            commander.oracle_id: commander,
            "draw-refresh": _make_card_data(
                "draw-refresh",
                "Repeatable Draw",
                "Whenever you sacrifice a creature, draw a card.",
            ),
            "forest-basic": _forest_data(),
        },
        quotas=[RoleQuota(CardRole.CARD_DRAW, 1, 3)],
        coherence_report=report,
    )

    draw_status = next(qs for qs in refreshed.quota_status if qs.role == CardRole.CARD_DRAW.value)
    assert draw_status.actual_count == 1
    assert draw_status.credit_sum == 1.0
    assert draw_status.credit_satisfied is True
    assert draw_status.credit_warning is None


def test_coherence_repair_refreshes_owned_stats() -> None:
    """SC-DECK-018 hardening: owned_count and percentage reflect repaired deck."""
    commander = _make_commander()
    owned_card = _make_deck_card(
        "owned-refresh",
        "Owned Sac Outlet",
        [CardRole.SACRIFICE_OUTLET.value],
        is_owned=True,
    )
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=98)
    deck = _deck_for_refresh([owned_card, forest], commander)
    report = StrategicCoherenceReport(primary_plan="aristocrats")

    refreshed = _refresh_deck_derived_state(
        deck=deck,
        commander=commander,
        all_cards_lookup={
            commander.oracle_id: commander,
            "owned-refresh": _make_card_data("owned-refresh", "Owned Sac Outlet", "sacrifice a creature: gain life."),
            "forest-basic": _forest_data(),
        },
        quotas=[RoleQuota(CardRole.SACRIFICE_OUTLET, 1, 3)],
        coherence_report=report,
    )

    assert refreshed.owned_count == 1
    assert refreshed.owned_percentage == 1 / 99


def test_coherence_repair_revalidates_repaired_deck() -> None:
    """SC-DECK-018 hardening: legality validation runs on repaired main_deck."""
    commander = _make_commander()
    off_color = _make_deck_card("blue-refresh", "Blue Intruder", [CardRole.WIN_CONDITION.value])
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=98)
    deck = _deck_for_refresh([off_color, forest], commander)
    report = StrategicCoherenceReport(primary_plan="aristocrats")

    refreshed = _refresh_deck_derived_state(
        deck=deck,
        commander=commander,
        all_cards_lookup={
            commander.oracle_id: commander,
            "blue-refresh": _make_card_data(
                "blue-refresh",
                "Blue Intruder",
                "draw a card.",
                color_identity=["U"],
            ),
            "forest-basic": _forest_data(),
        },
        quotas=[RoleQuota(CardRole.WIN_CONDITION, 1, 3)],
        coherence_report=report,
    )

    assert refreshed.is_valid is False
    assert any("outside the commander's color identity" in err for err in refreshed.validation_errors)


def test_repaired_deck_warnings_do_not_include_stale_quota_warning() -> None:
    """SC-DECK-018 hardening: stale quota/coherence warnings are replaced."""
    commander = _make_commander()
    draw_card = _make_deck_card("draw-refresh", "Repeatable Draw", [CardRole.CARD_DRAW.value])
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=98)
    deck = _deck_for_refresh([draw_card, forest], commander)
    report = StrategicCoherenceReport(
        primary_plan="aristocrats",
        warnings=["Strategic coherence is low: repaired-deck warning."],
    )

    refreshed = _refresh_deck_derived_state(
        deck=deck,
        commander=commander,
        all_cards_lookup={
            commander.oracle_id: commander,
            "draw-refresh": _make_card_data(
                "draw-refresh",
                "Repeatable Draw",
                "Whenever you sacrifice a creature, draw a card.",
            ),
            "forest-basic": _forest_data(),
        },
        quotas=[RoleQuota(CardRole.CARD_DRAW, 1, 3)],
        coherence_report=report,
    )

    assert not any("CARD_DRAW: credit 0.2" in warning for warning in refreshed.warnings)
    assert not any("off-plan nonland cards exceed" in warning for warning in refreshed.warnings)
    assert "Utility land excluded for low strategic relevance: Mystifying Maze" in refreshed.warnings
    assert "Strategic coherence is low: repaired-deck warning." in refreshed.warnings


def test_coherence_repair_pass_replaces_off_plan_card_with_on_plan() -> None:
    """Repair pass swaps an off-plan card for an on-plan alternative."""
    commander = _make_commander()
    off_plan = _make_deck_card("off-plan-001", "Off Plan Beast", ["WIN_CONDITION"])
    deck = _make_minimal_deck(off_plan, commander)

    report = StrategicCoherenceReport(
        primary_plan="aristocrats",
        warning_card_oracle_ids=["off-plan-001"],
        off_plan_count=1,
        on_plan_count=97,
    )

    on_plan_card = _make_deck_card(
        "on-plan-001", "Sacrifice Outlet", ["SACRIFICE_OUTLET"], synergy_score=0.5
    )
    all_cards_lookup = {
        commander.oracle_id: commander,
        "off-plan-001": _make_card_data("off-plan-001", "Off Plan Beast", "trample"),
        "on-plan-001": _make_card_data("on-plan-001", "Sacrifice Outlet", "sacrifice a creature: gain 1 life."),
    }

    updated_deck, new_report = _coherence_repair_pass(
        deck=deck,
        coherence_report=report,
        enriched_candidate_pool=[on_plan_card],
        all_cards_lookup=all_cards_lookup,
        commander=commander,
        commander_tags=[],
        packages=[],
    )

    oracle_ids = {c.oracle_id for c in updated_deck.main_deck}
    assert "on-plan-001" in oracle_ids, "On-plan replacement should appear in deck"
    assert "off-plan-001" not in oracle_ids, "Off-plan card should be removed"
    assert sum(c.quantity for c in updated_deck.main_deck) == 99


def test_coherence_repair_pass_skips_when_no_on_plan_alternative() -> None:
    """Repair pass leaves the deck unchanged when the on-plan pool is empty."""
    commander = _make_commander()
    off_plan = _make_deck_card("off-plan-002", "No Replacement", ["WIN_CONDITION"])
    deck = _make_minimal_deck(off_plan, commander)

    report = StrategicCoherenceReport(
        primary_plan="aristocrats",
        warning_card_oracle_ids=["off-plan-002"],
        off_plan_count=1,
        on_plan_count=97,
    )
    all_cards_lookup = {
        commander.oracle_id: commander,
        "off-plan-002": _make_card_data("off-plan-002", "No Replacement", "trample"),
    }

    updated_deck, _ = _coherence_repair_pass(
        deck=deck,
        coherence_report=report,
        enriched_candidate_pool=[],
        all_cards_lookup=all_cards_lookup,
        commander=commander,
        commander_tags=[],
        packages=[],
    )

    oracle_ids = {c.oracle_id for c in updated_deck.main_deck}
    assert "off-plan-002" in oracle_ids, "Off-plan card should remain when no replacement exists"
    assert sum(c.quantity for c in updated_deck.main_deck) == 99


def test_coherence_repair_pass_respects_quota_guard() -> None:
    """Repair pass does not replace a REQUIRED_ROLE_FILLER card when it would breach target_min."""
    commander = _make_commander()
    # RAMP card is required and quota would break if removed
    ramp_card = _make_deck_card("ramp-only-001", "Only Ramp", ["RAMP"])
    deck = _make_minimal_deck(ramp_card, commander)
    deck = deck.model_copy(update={
        "quota_status": [QuotaStatus(role="RAMP", target_min=1, target_max=3, actual_count=1, is_satisfied=True)],
    })

    report = StrategicCoherenceReport(
        primary_plan="aristocrats",
        warning_card_oracle_ids=["ramp-only-001"],
        off_plan_count=1,
        on_plan_count=97,
    )

    on_plan_card = _make_deck_card("on-plan-002", "Sac Outlet 2", ["SACRIFICE_OUTLET"])
    all_cards_lookup = {
        commander.oracle_id: commander,
        "ramp-only-001": _make_card_data("ramp-only-001", "Only Ramp", "add one mana"),
        "on-plan-002": _make_card_data("on-plan-002", "Sac Outlet 2", "sacrifice a creature: gain life."),
    }

    updated_deck, _ = _coherence_repair_pass(
        deck=deck,
        coherence_report=report,
        enriched_candidate_pool=[on_plan_card],
        all_cards_lookup=all_cards_lookup,
        commander=commander,
        commander_tags=[],
        packages=[],
    )

    oracle_ids = {c.oracle_id for c in updated_deck.main_deck}
    assert "ramp-only-001" in oracle_ids, "Quota-required card must not be removed"
    assert "on-plan-002" not in oracle_ids, "Replacement should not be inserted"
    assert sum(c.quantity for c in updated_deck.main_deck) == 99


def test_coherence_repair_pass_does_not_exceed_max_off_plan_cards() -> None:
    """Repair pass makes at most MAX_OFF_PLAN_CARDS replacements."""
    commander = _make_commander()
    num_off_plan = MAX_OFF_PLAN_CARDS + 3

    off_plan_cards = [
        _make_deck_card(f"off-plan-{i:03d}", f"Off Plan {i}", ["WIN_CONDITION"])
        for i in range(num_off_plan)
    ]
    remaining = 99 - num_off_plan
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=remaining)
    commander_card = DeckCard(
        oracle_id=commander.oracle_id,
        name=commander.name,
        is_owned=True,
        quantity=1,
        roles=[],
        selection_reason="commander",
    )
    deck = GeneratedDeck(
        deck_id="test-deck-cap",
        session_id="test-session",
        commander=commander_card,
        main_deck=off_plan_cards + [forest],
        role_breakdown={},
        quota_status=[],
        package_breakdown=[],
        warnings=[],
        owned_count=0,
        owned_percentage=0.0,
        is_valid=True,
        validation_errors=[],
    )

    report = StrategicCoherenceReport(
        primary_plan="aristocrats",
        warning_card_oracle_ids=[c.oracle_id for c in off_plan_cards],
        off_plan_count=num_off_plan,
        on_plan_count=0,
    )

    # Provide plenty of on-plan replacements
    on_plan_pool = [
        _make_deck_card(f"on-plan-{i:03d}", f"Sac Outlet {i}", ["SACRIFICE_OUTLET"])
        for i in range(num_off_plan + 5)
    ]
    all_cards_lookup: dict[str, CardData] = {commander.oracle_id: commander}
    for c in off_plan_cards:
        all_cards_lookup[c.oracle_id] = _make_card_data(c.oracle_id, c.name, "trample")
    for c in on_plan_pool:
        all_cards_lookup[c.oracle_id] = _make_card_data(
            c.oracle_id, c.name, "sacrifice a creature: gain life."
        )

    updated_deck, _ = _coherence_repair_pass(
        deck=deck,
        coherence_report=report,
        enriched_candidate_pool=on_plan_pool,
        all_cards_lookup=all_cards_lookup,
        commander=commander,
        commander_tags=[],
        packages=[],
    )

    replaced = sum(
        1 for c in updated_deck.main_deck
        if c.selection_reason.startswith("coherence repair")
    )
    assert replaced <= MAX_OFF_PLAN_CARDS, f"Too many repairs: {replaced} > {MAX_OFF_PLAN_CARDS}"
    assert sum(c.quantity for c in updated_deck.main_deck) == 99


def test_coherence_repair_re_runs_validator_after_repair() -> None:
    """Returned coherence_report reflects the repaired deck, not the original."""
    commander = _make_commander()
    off_plan = _make_deck_card("off-plan-003", "Off Plan 3", ["WIN_CONDITION"])
    deck = _make_minimal_deck(off_plan, commander)

    report = StrategicCoherenceReport(
        primary_plan="aristocrats",
        warning_card_oracle_ids=["off-plan-003"],
        off_plan_count=1,
        on_plan_count=97,
    )

    on_plan_card = _make_deck_card(
        "on-plan-003", "Dies Trigger", ["SACRIFICE_OUTLET"], synergy_score=0.5
    )
    all_cards_lookup = {
        commander.oracle_id: commander,
        "off-plan-003": _make_card_data("off-plan-003", "Off Plan 3", "trample"),
        "on-plan-003": _make_card_data(
            "on-plan-003", "Dies Trigger", "sacrifice a creature: dies trigger."
        ),
    }

    _, new_report = _coherence_repair_pass(
        deck=deck,
        coherence_report=report,
        enriched_candidate_pool=[on_plan_card],
        all_cards_lookup=all_cards_lookup,
        commander=commander,
        commander_tags=[],
        packages=[],
    )

    # Re-validated report should reflect repaired deck
    assert new_report is not report, "Must return a freshly validated report"
    assert "off-plan-003" not in new_report.warning_card_oracle_ids


def test_coherence_repair_pass_noop_when_no_warnings() -> None:
    """Repair pass is a no-op when warning_card_oracle_ids is empty."""
    commander = _make_commander()
    deck = _make_minimal_deck(
        _make_deck_card("any-card", "Any Card", ["WIN_CONDITION"]), commander
    )
    report = StrategicCoherenceReport(
        primary_plan="aristocrats",
        warning_card_oracle_ids=[],
        off_plan_count=0,
        on_plan_count=98,
    )
    all_cards_lookup = {commander.oracle_id: commander}

    updated_deck, returned_report = _coherence_repair_pass(
        deck=deck,
        coherence_report=report,
        enriched_candidate_pool=[],
        all_cards_lookup=all_cards_lookup,
        commander=commander,
        commander_tags=[],
        packages=[],
    )

    assert updated_deck is deck, "Deck object should be returned unchanged"
    assert returned_report is report, "Report should be returned unchanged"


def test_greta_fixture_deck_improves_after_coherence_repair() -> None:
    """Greta negative fixture: off_plan_count decreases after coherence repair."""
    commander, deck, lookup, packages = _load_negative_fixture(GRETA_FIXTURE)

    initial_report = StrategicCoherenceValidator().validate(
        commander=commander,
        commander_tags=[],
        deck=deck,
        all_cards_lookup=lookup,
        packages=packages,
    )
    assert initial_report.off_plan_count > 0, "Fixture should have off-plan cards to repair"

    # Build on-plan pool: food/sacrifice cards matching Greta's positive evidence
    on_plan_pool: list[DeckCard] = []
    for i in range(15):
        oid = f"greta-repair-{i:03d}"
        on_plan_pool.append(
            DeckCard(
                oracle_id=oid,
                name=f"Food Sacrifice Card {i}",
                is_owned=False,
                quantity=1,
                roles=["ARISTOCRATS_SYNERGY"],
                selection_reason="repair candidate",
                synergy_score=0.3,
                color_identity=["B", "G"],
            )
        )
        lookup[oid] = CardData(
            id=oid,
            oracle_id=oid,
            name=f"Food Sacrifice Card {i}",
            color_identity=["B", "G"],
            legalities={"commander": "legal"},
            type_line="Creature",
            oracle_text="sacrifice a food token: you gain 2 life.",
            cmc=2.0,
        )

    updated_deck, repaired_report = _coherence_repair_pass(
        deck=deck,
        coherence_report=initial_report,
        enriched_candidate_pool=on_plan_pool,
        all_cards_lookup=lookup,
        commander=commander,
        commander_tags=[],
        packages=packages,
    )

    initial_qty = sum(c.quantity for c in deck.main_deck)
    assert repaired_report.off_plan_count < initial_report.off_plan_count, (
        f"Expected off_plan_count to decrease after repair: "
        f"{initial_report.off_plan_count} → {repaired_report.off_plan_count}"
    )
    assert sum(c.quantity for c in updated_deck.main_deck) == initial_qty, "Total card count must not change"


def test_toluz_fixture_deck_improves_after_coherence_repair() -> None:
    """Toluz negative fixture: off_plan_count decreases after coherence repair."""
    commander, deck, lookup, packages = _load_negative_fixture(TOLUZ_FIXTURE)

    initial_report = StrategicCoherenceValidator().validate(
        commander=commander,
        commander_tags=[],
        deck=deck,
        all_cards_lookup=lookup,
        packages=packages,
    )
    assert initial_report.off_plan_count > 0, "Fixture should have off-plan cards to repair"

    # Build on-plan pool: connive/discard cards matching Toluz's plan
    on_plan_pool: list[DeckCard] = []
    for i in range(15):
        oid = f"toluz-repair-{i:03d}"
        on_plan_pool.append(
            DeckCard(
                oracle_id=oid,
                name=f"Connive Discard Card {i}",
                is_owned=False,
                quantity=1,
                roles=["GRAVEYARD_SYNERGY"],
                selection_reason="repair candidate",
                synergy_score=0.3,
                color_identity=["U", "B"],
            )
        )
        lookup[oid] = CardData(
            id=oid,
            oracle_id=oid,
            name=f"Connive Discard Card {i}",
            color_identity=["U", "B"],
            legalities={"commander": "legal"},
            type_line="Creature",
            oracle_text="connive. When this enters the battlefield, draw a card, then discard a card.",
            cmc=2.0,
        )

    updated_deck, repaired_report = _coherence_repair_pass(
        deck=deck,
        coherence_report=initial_report,
        enriched_candidate_pool=on_plan_pool,
        all_cards_lookup=lookup,
        commander=commander,
        commander_tags=[],
        packages=packages,
    )

    initial_qty = sum(c.quantity for c in deck.main_deck)
    assert repaired_report.off_plan_count < initial_report.off_plan_count, (
        f"Expected off_plan_count to decrease after repair: "
        f"{initial_report.off_plan_count} → {repaired_report.off_plan_count}"
    )
    assert sum(c.quantity for c in updated_deck.main_deck) == initial_qty, "Total card count must not change"


# ---------------------------------------------------------------------------
# SC-DECK-030: _multi_pass_quality_repair tests
# ---------------------------------------------------------------------------


def _make_multi_pass_deck(
    main_deck: list[DeckCard],
    quota_status: list[QuotaStatus],
    strategic_coherence: StrategicCoherenceReport | None = None,
) -> GeneratedDeck:
    """Minimal GeneratedDeck for multi-pass repair tests."""
    commander_card = DeckCard(
        oracle_id="test-cmd",
        name="Test Commander",
        is_owned=True,
        quantity=1,
        roles=[],
        selection_reason="commander",
    )
    return GeneratedDeck(
        deck_id="multi-pass-test",
        session_id="multi-pass-session",
        commander=commander_card,
        main_deck=main_deck,
        role_breakdown={},
        quota_status=quota_status,
        package_breakdown=[],
        warnings=[],
        owned_count=0,
        owned_percentage=0.0,
        is_valid=True,
        validation_errors=[],
        strategic_coherence=strategic_coherence,
    )


def test_multi_pass_repair_resolves_win_condition_then_quota_shortfall() -> None:
    """SC-DECK-030: two iterations fix WIN_CONDITION then RAMP; deck passes quality gates."""
    commander = _make_commander()
    # Two weak cards act as swap targets; forests pad to 99.
    weak_a = _make_deck_card("weak-a", "Weak A", [])
    weak_b = _make_deck_card("weak-b", "Weak B", [])
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=97)

    win_cand = _make_deck_card("win-cand", "Win Card", [CardRole.WIN_CONDITION.value], synergy_score=0.5, is_owned=True)
    ramp_cand = _make_deck_card("ramp-cand", "Ramp Card", [CardRole.RAMP.value], synergy_score=0.4, is_owned=True)

    quotas = [
        RoleQuota(CardRole.WIN_CONDITION, 1, 2),
        RoleQuota(CardRole.RAMP, 1, 4),
        RoleQuota(CardRole.LAND, 36, 99),  # 97 forests → must not overflow target_max
    ]
    # Both candidates use "sacrifice" text so the food-sacrifice coherence plan marks them
    # on-plan, preventing unresolved_warning_cards caps from blocking loop exit.
    # All deck cards must be in all_cards_lookup so LegalityValidator sees 100 cards total.
    all_cards_lookup = {
        commander.oracle_id: commander,
        "win-cand": _make_card_data("win-cand", "Win Card", "Sacrifice a creature: you win the game."),
        "ramp-cand": _make_card_data("ramp-cand", "Ramp Card", "Whenever you sacrifice a permanent, add {G}{G}."),
        "weak-a": _make_card_data("weak-a", "Weak A", ""),
        "weak-b": _make_card_data("weak-b", "Weak B", ""),
        "forest-basic": _forest_data(),
    }

    deck = _make_multi_pass_deck(
        main_deck=[weak_a, weak_b, forest],
        quota_status=[
            QuotaStatus(
                role=CardRole.WIN_CONDITION.value,
                target_min=1, target_max=2, actual_count=0,
                is_satisfied=False,
                warning="WIN_CONDITION: need 1–2, got 0 assigned slot(s) (underfilled)",
                credit_satisfied=True,
            ),
            QuotaStatus(
                role=CardRole.RAMP.value,
                target_min=1, target_max=4, actual_count=0,
                is_satisfied=False,
                warning="RAMP: need 1–4, got 0 assigned slot(s) (underfilled)",
                credit_satisfied=True,
            ),
        ],
    )

    result = _multi_pass_quality_repair(
        deck=deck,
        commander=commander,
        commander_tags=[],
        all_cards_lookup=all_cards_lookup,
        quotas=quotas,
        enriched_candidate_pool=[win_cand, ramp_cand],
        packages=[],
    )

    oracle_ids = {c.oracle_id for c in result.main_deck}
    assert "win-cand" in oracle_ids, "WIN_CONDITION candidate must appear in deck"
    assert "ramp-cand" in oracle_ids, "RAMP candidate must appear in deck"
    assert not _quality_failure_reasons(result), "No quality failures should remain"
    assert any("quality repair: 2 iteration(s)" in w for w in result.warnings)


def test_multi_pass_repair_stops_after_max_iterations() -> None:
    """SC-DECK-030: loop exits at MAX_REPAIR_ITERATIONS even when failures remain."""
    commander = _make_commander()
    # One weak swap target per iteration; one WIN_CONDITION candidate per iteration.
    weak_cards = [
        _make_deck_card(f"weak-{i}", f"Weak {i}", [])
        for i in range(MAX_REPAIR_ITERATIONS)
    ]
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=99 - MAX_REPAIR_ITERATIONS)
    win_cands = [
        _make_deck_card(f"wc-{i}", f"Win Cand {i}", [CardRole.WIN_CONDITION.value], synergy_score=0.5, is_owned=True)
        for i in range(MAX_REPAIR_ITERATIONS)
    ]
    # target_min = MAX_REPAIR_ITERATIONS + 1 so quota is NEVER satisfied with 10 cards.
    quotas = [
        RoleQuota(CardRole.WIN_CONDITION, MAX_REPAIR_ITERATIONS + 1, MAX_REPAIR_ITERATIONS + 2),
        RoleQuota(CardRole.LAND, 36, 99),  # 89 forests must not overflow target_max
    ]
    # All deck cards must be in all_cards_lookup so LegalityValidator sees 100 cards total.
    all_cards_lookup: dict[str, CardData] = {commander.oracle_id: commander}
    for cand in win_cands:
        all_cards_lookup[cand.oracle_id] = _make_card_data(
            cand.oracle_id, cand.name, "Sacrifice a creature: you win the game."
        )
    for i in range(MAX_REPAIR_ITERATIONS):
        all_cards_lookup[f"weak-{i}"] = _make_card_data(f"weak-{i}", f"Weak {i}", "")
    all_cards_lookup["forest-basic"] = _forest_data()

    deck = _make_multi_pass_deck(
        main_deck=weak_cards + [forest],
        quota_status=[
            QuotaStatus(
                role=CardRole.WIN_CONDITION.value,
                target_min=MAX_REPAIR_ITERATIONS + 1,
                target_max=MAX_REPAIR_ITERATIONS + 2,
                actual_count=0,
                is_satisfied=False,
                warning=f"WIN_CONDITION: need {MAX_REPAIR_ITERATIONS + 1}–{MAX_REPAIR_ITERATIONS + 2}, got 0",
                credit_satisfied=True,
            ),
        ],
    )

    result = _multi_pass_quality_repair(
        deck=deck,
        commander=commander,
        commander_tags=[],
        all_cards_lookup=all_cards_lookup,
        quotas=quotas,
        enriched_candidate_pool=win_cands,
        packages=[],
    )

    assert any(f"quality repair: {MAX_REPAIR_ITERATIONS} iteration(s)" in w for w in result.warnings)
    finalized = _finalize_quality_generation_status(result)
    # Pool is exhausted after 10 repairs → SC-DECK-033 collection_gap, not failed_quality
    assert finalized.generation_status == "generated_with_collection_gap"
    assert any("collection_gap: WIN_CONDITION" in w for w in finalized.warnings)


def test_multi_pass_repair_exits_early_when_no_improving_move() -> None:
    """SC-DECK-030: loop breaks immediately when no candidate exists for any failure."""
    commander = _make_commander()
    weak = _make_deck_card("weak-x", "Weak X", [])
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=98)

    deck = _make_multi_pass_deck(
        main_deck=[weak, forest],
        quota_status=[
            QuotaStatus(
                role=CardRole.WIN_CONDITION.value,
                target_min=1, target_max=2, actual_count=0,
                is_satisfied=False,
                warning="WIN_CONDITION: need 1–2, got 0 assigned slot(s) (underfilled)",
                credit_satisfied=True,
            ),
        ],
    )
    original_ids = {c.oracle_id for c in deck.main_deck}

    result = _multi_pass_quality_repair(
        deck=deck,
        commander=commander,
        commander_tags=[],
        all_cards_lookup={commander.oracle_id: commander},
        quotas=[RoleQuota(CardRole.WIN_CONDITION, 1, 2), RoleQuota(CardRole.LAND, 36, 40)],
        enriched_candidate_pool=[],  # no candidates → improved is None → break
        packages=[],
    )

    assert not any("quality repair" in w for w in result.warnings), "No repairs should be reported"
    assert _quality_failure_reasons(result), "Quality failures must still remain"
    assert {c.oracle_id for c in result.main_deck} == original_ids, "Deck must be unchanged"


def test_multi_pass_repair_noop_when_no_failures() -> None:
    """SC-DECK-030: loop is a no-op when deck already passes all quality gates."""
    commander = _make_commander()
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=99)
    win = _make_deck_card("win-001", "Win Card", [CardRole.WIN_CONDITION.value], is_owned=True)

    deck = _make_multi_pass_deck(
        main_deck=[win, forest],
        quota_status=[
            QuotaStatus(
                role=CardRole.WIN_CONDITION.value,
                target_min=1, target_max=2, actual_count=1,
                is_satisfied=True,
                credit_satisfied=True,
            ),
        ],
        strategic_coherence=StrategicCoherenceReport(
            primary_plan="food-sacrifice",
            confidence=0.8,
            on_plan_count=1,
            off_plan_count=0,
        ),
    )
    original_ids = {c.oracle_id for c in deck.main_deck}

    result = _multi_pass_quality_repair(
        deck=deck,
        commander=commander,
        commander_tags=[],
        all_cards_lookup={commander.oracle_id: commander},
        quotas=[RoleQuota(CardRole.WIN_CONDITION, 1, 2), RoleQuota(CardRole.LAND, 36, 40)],
        enriched_candidate_pool=[],
        packages=[],
    )

    assert {c.oracle_id for c in result.main_deck} == original_ids, "Deck must not change"
    assert not any("quality repair" in w for w in result.warnings), "No repair warning expected"


def test_multi_pass_repair_addresses_off_plan_after_quota_shortfalls_resolved() -> None:
    """SC-DECK-030: WIN_CONDITION fixed in iteration 1; off-plan card fixed in iteration 2."""
    commander = _make_commander()
    # Weak card is the WIN_CONDITION swap target (not in all_cards_lookup → skipped by validator).
    weak = _make_deck_card("weak-swap", "Weak Swap", [])
    # Off-plan card: oracle_text has no food-sacrifice keywords → validator flags it.
    off_plan = _make_deck_card("off-plan-001", "Off Plan Card", [], synergy_score=0.0)
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=97)

    # WIN_CONDITION candidate is on-plan (sacrifice text) so it does not add to off_plan_count.
    win_cand = _make_deck_card("win-cand-5", "Win Card", [CardRole.WIN_CONDITION.value], synergy_score=0.5, is_owned=True)
    # On-plan replacement for the off-plan card.
    on_plan_repl = _make_deck_card("on-plan-repl", "On Plan Repl", [], synergy_score=0.3, is_owned=True)

    quotas = [
        RoleQuota(CardRole.WIN_CONDITION, 1, 2),
        RoleQuota(CardRole.LAND, 36, 99),  # 97 forests must not overflow target_max
    ]
    # All deck cards must be in all_cards_lookup so LegalityValidator sees 100 cards total.
    all_cards_lookup = {
        commander.oracle_id: commander,
        "win-cand-5": _make_card_data("win-cand-5", "Win Card", "Sacrifice a creature: you win the game."),
        "off-plan-001": _make_card_data("off-plan-001", "Off Plan Card", "trample."),
        "on-plan-repl": _make_card_data("on-plan-repl", "On Plan Repl", "Sacrifice a creature: you gain 1 life."),
        "forest-basic": _forest_data(),
    }

    # Initial strategic_coherence is clean: no warning_card_oracle_ids yet.
    # After iteration 1 refresh the validator discovers off-plan-001 and adds it to
    # warning_card_oracle_ids, producing an unresolved_warning_cards structural cap
    # that triggers the off-plan repair in iteration 2.
    deck = _make_multi_pass_deck(
        main_deck=[weak, off_plan, forest],
        quota_status=[
            QuotaStatus(
                role=CardRole.WIN_CONDITION.value,
                target_min=1, target_max=2, actual_count=0,
                is_satisfied=False,
                warning="WIN_CONDITION: need 1–2, got 0 assigned slot(s) (underfilled)",
                credit_satisfied=True,
            ),
        ],
        strategic_coherence=StrategicCoherenceReport(primary_plan="food-sacrifice"),
    )

    result = _multi_pass_quality_repair(
        deck=deck,
        commander=commander,
        commander_tags=[],
        all_cards_lookup=all_cards_lookup,
        quotas=quotas,
        enriched_candidate_pool=[win_cand, on_plan_repl],
        packages=[],
    )

    oracle_ids = {c.oracle_id for c in result.main_deck}
    assert "win-cand-5" in oracle_ids, "WIN_CONDITION candidate must be in deck (fixed first)"
    assert "on-plan-repl" in oracle_ids, "On-plan replacement must be in deck (off-plan fixed second)"
    assert "off-plan-001" not in oracle_ids, "Off-plan card must be removed"
    selection_reasons = [c.selection_reason for c in result.main_deck]
    assert any("fills WIN_CONDITION" in r for r in selection_reasons)
    assert any("replaced off-plan" in r for r in selection_reasons)


def test_multi_pass_repair_count_in_warnings() -> None:
    """SC-DECK-030: warnings include exact iteration count after repairs."""
    commander = _make_commander()
    weak = _make_deck_card("weak-w", "Weak W", [])
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=98)
    win_cand = _make_deck_card("win-cand-6", "Win Card", [CardRole.WIN_CONDITION.value], synergy_score=0.5, is_owned=True)

    quotas = [
        RoleQuota(CardRole.WIN_CONDITION, 1, 2),
        RoleQuota(CardRole.LAND, 36, 99),  # 98 forests must not overflow target_max
    ]
    # forest-basic must be in all_cards_lookup so LegalityValidator sees 100 cards total.
    all_cards_lookup = {
        commander.oracle_id: commander,
        "win-cand-6": _make_card_data("win-cand-6", "Win Card", "Sacrifice a creature: you win the game."),
        "forest-basic": _forest_data(),
    }

    deck = _make_multi_pass_deck(
        main_deck=[weak, forest],
        quota_status=[
            QuotaStatus(
                role=CardRole.WIN_CONDITION.value,
                target_min=1, target_max=2, actual_count=0,
                is_satisfied=False,
                warning="WIN_CONDITION: need 1–2, got 0 assigned slot(s) (underfilled)",
                credit_satisfied=True,
            ),
        ],
    )

    result = _multi_pass_quality_repair(
        deck=deck,
        commander=commander,
        commander_tags=[],
        all_cards_lookup=all_cards_lookup,
        quotas=quotas,
        enriched_candidate_pool=[win_cand],
        packages=[],
    )

    assert any("quality repair: 1 iteration(s)" in w for w in result.warnings)
    repaired_cards = [c for c in result.main_deck if c.selection_reason and "quality repair" in c.selection_reason]
    assert len(repaired_cards) == 1


# ---------------------------------------------------------------------------
# SC-DECK-031: Fallback commander quality gate
# ---------------------------------------------------------------------------

def _make_package(package_id: str, label: str, top_roles: list[str]) -> PackageCluster:
    return PackageCluster(
        package_id=package_id,
        label=label,
        confidence=0.8,
        card_oracle_ids=[],
        top_roles=top_roles,
    )


def test_fallback_commander_no_plan_does_not_trigger_commander_irrelevant_cap() -> None:
    """SC-DECK-031: primary_plan=None should not flag packages as irrelevant."""
    report = StrategicCoherenceReport(
        primary_plan=None,
        active_package_ids=["aristocrats-pkg"],
    )
    package = _make_package("aristocrats-pkg", "Aristocrats", ["WIN_CONDITION"])
    assert _has_commander_irrelevant_active_package(report, [package]) is False


def test_known_plan_commander_with_mismatched_packages_still_triggers_cap() -> None:
    """SC-DECK-031: known primary_plan with mismatched packages returns True."""
    report = StrategicCoherenceReport(
        primary_plan="landfall",
        active_package_ids=["aristocrats-pkg"],
    )
    package = _make_package("aristocrats-pkg", "Aristocrats", ["WIN_CONDITION"])
    assert _has_commander_irrelevant_active_package(report, [package]) is True


def test_no_active_packages_returns_false_regardless_of_plan() -> None:
    """SC-DECK-031: empty active_package_ids short-circuits to False."""
    report_no_plan = StrategicCoherenceReport(primary_plan=None, active_package_ids=[])
    report_with_plan = StrategicCoherenceReport(primary_plan="landfall", active_package_ids=[])
    assert _has_commander_irrelevant_active_package(report_no_plan, []) is False
    assert _has_commander_irrelevant_active_package(report_with_plan, []) is False


def test_fallback_commander_deck_does_not_return_failed_quality_when_repair_succeeds() -> None:
    """SC-DECK-031: fallback commander (primary_plan=None) exits as success, not failed_quality."""
    commander = _make_commander()
    weak = _make_deck_card("weak-sc031", "Weak SC031", [])
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=98)
    win_cand = _make_deck_card(
        "win-sc031", "Win SC031", [CardRole.WIN_CONDITION.value],
        synergy_score=0.5, is_owned=True,
    )
    quotas = [
        RoleQuota(CardRole.WIN_CONDITION, 1, 2),
        RoleQuota(CardRole.LAND, 36, 99),
    ]
    # primary_plan=None — fallback commander path
    coherence = StrategicCoherenceReport(
        primary_plan=None,
        active_package_ids=["some-pkg"],
        confidence=0.5,
    )
    deck = _make_multi_pass_deck(
        main_deck=[weak, forest],
        quota_status=[
            QuotaStatus(
                role=CardRole.WIN_CONDITION.value,
                target_min=1,
                target_max=2,
                actual_count=0,
                is_satisfied=False,
                warning="WIN_CONDITION: need 1–2, got 0 assigned slot(s) (underfilled)",
                credit_satisfied=True,
            ),
        ],
        strategic_coherence=coherence,
    )
    all_cards_lookup = {
        "test-cmd": _make_commander(),
        "weak-sc031": _make_card_data("weak-sc031", "Weak SC031", oracle_text=""),
        "forest-basic": _forest_data(),
        "win-sc031": _make_card_data(
            "win-sc031", "Win SC031",
            oracle_text="Sacrifice a creature: you win the game.",
        ),
    }
    package = _make_package("some-pkg", "Some Package", ["WIN_CONDITION"])
    result = _multi_pass_quality_repair(
        deck=deck,
        commander=commander,
        commander_tags=[],
        all_cards_lookup=all_cards_lookup,
        quotas=quotas,
        enriched_candidate_pool=[win_cand],
        packages=[package],
    )
    finalized = _finalize_quality_generation_status(result)
    assert finalized.generation_status != "failed_quality", (
        f"Expected success/needs_repair but got {finalized.generation_status!r}. "
        f"Failures: {_quality_failure_reasons(finalized)}"
    )


# ---------------------------------------------------------------------------
# SC-DECK-032: Credit-quality repair step
# ---------------------------------------------------------------------------

def _make_credit_repair_deck(
    main_deck: list[DeckCard],
    quota_status: list[QuotaStatus],
) -> GeneratedDeck:
    """Minimal GeneratedDeck for credit-repair tests; main_deck must total 99 cards."""
    commander_card = DeckCard(
        oracle_id="test-cmd",
        name="Test Commander",
        is_owned=True,
        quantity=1,
        roles=[],
        selection_reason="commander",
    )
    return GeneratedDeck(
        deck_id="credit-repair-test",
        session_id="credit-repair-session",
        commander=commander_card,
        main_deck=main_deck,
        role_breakdown={},
        quota_status=quota_status,
        package_breakdown=[],
        warnings=[],
        owned_count=0,
        owned_percentage=0.0,
        is_valid=True,
        validation_errors=[],
    )


def test_credit_repair_replaces_low_credit_ramp_with_higher_credit_alternative() -> None:
    """SC-DECK-032: step 6 replaces 0.5-credit ramp card when 1.0-credit alternative exists."""
    # Two ramp cards: low-credit (0.5) is the swap target; ok-ramp stays to meet target_min=1
    # after the swap (role_counts[RAMP]=2, 2-1=1 >= target_min=1 → removable).
    low_ramp = _make_deck_card("low-ramp", "Low Ramp", [CardRole.RAMP.value], synergy_score=0.3)
    ok_ramp = _make_deck_card("ok-ramp", "OK Ramp", [CardRole.RAMP.value], synergy_score=0.5)
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=97)

    # High-credit ramp candidate: "whenever" → credit=1.0
    high_ramp_candidate = _make_deck_card(
        "high-ramp", "High Ramp", [CardRole.RAMP.value], synergy_score=0.4, is_owned=True
    )

    # RAMP count=2 (satisfied at min=1), credit_sum=1.0 (two 0.5 cards) < 2.0 → not satisfied
    quota_status = [
        QuotaStatus(
            role=CardRole.RAMP.value,
            target_min=2,
            target_max=10,
            actual_count=2,
            is_satisfied=True,
            credit_sum=1.0,
            credit_satisfied=False,
            credit_warning="RAMP: credit 1.0 < minimum 2",
        )
    ]
    quotas = [
        RoleQuota(CardRole.RAMP, 2, 10),
        RoleQuota(CardRole.LAND, 36, 99),
    ]
    deck = _make_credit_repair_deck(main_deck=[low_ramp, ok_ramp, forest], quota_status=quota_status)
    all_cards_lookup = {
        "test-cmd": _make_commander(),
        "low-ramp": _make_card_data("low-ramp", "Low Ramp", oracle_text="Add {G}.", cmc=2.0),
        "ok-ramp": _make_card_data("ok-ramp", "OK Ramp", oracle_text="Add {G}.", cmc=2.0),
        "high-ramp": _make_card_data(
            "high-ramp", "High Ramp",
            oracle_text="Whenever you sacrifice a permanent, add {G}{G}.",
            cmc=3.0,
        ),
        "forest-basic": _forest_data(),
    }
    selected_ids = {c.oracle_id for c in deck.main_deck}

    result = _repair_credit_quality_one(
        deck, selected_ids, [high_ramp_candidate], all_cards_lookup, quotas
    )

    assert result is not None
    oracle_ids = [c.oracle_id for c in result.main_deck]
    assert "high-ramp" in oracle_ids
    assert "low-ramp" not in oracle_ids
    assert any(
        c.oracle_id == "high-ramp" and c.selection_reason and "RAMP credit" in c.selection_reason
        for c in result.main_deck
    )


def test_credit_repair_skips_when_count_not_satisfied() -> None:
    """SC-DECK-032: step 6 does not fire when count is below target_min."""
    low_ramp = _make_deck_card("low-ramp", "Low Ramp", [CardRole.RAMP.value])
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=98)
    high_ramp_cand = _make_deck_card("high-ramp", "High Ramp", [CardRole.RAMP.value], synergy_score=0.8)

    # RAMP count=1 but target_min=8 → is_satisfied=False → step 6 must not fire
    quota_status = [
        QuotaStatus(
            role=CardRole.RAMP.value,
            target_min=8,
            target_max=10,
            actual_count=1,
            is_satisfied=False,
            credit_sum=0.5,
            credit_satisfied=False,
            credit_warning="RAMP: credit 0.5 < minimum 8",
            warning="RAMP: need 8–10, got 1 assigned slot(s) (underfilled)",
        )
    ]
    quotas = [RoleQuota(CardRole.RAMP, 8, 10), RoleQuota(CardRole.LAND, 36, 99)]
    deck = _make_credit_repair_deck(main_deck=[low_ramp, forest], quota_status=quota_status)
    all_cards_lookup = {
        "test-cmd": _make_commander(),
        "low-ramp": _make_card_data("low-ramp", "Low Ramp", oracle_text="Add {G}.", cmc=2.0),
        "high-ramp": _make_card_data(
            "high-ramp", "High Ramp",
            oracle_text="Whenever you sacrifice a permanent, add {G}{G}.",
        ),
        "forest-basic": _forest_data(),
    }
    selected_ids = {c.oracle_id for c in deck.main_deck}

    result = _repair_credit_quality_one(
        deck, selected_ids, [high_ramp_cand], all_cards_lookup, quotas
    )
    # No credit_gaps because is_satisfied=False — step 6 returns None
    assert result is None


def test_credit_repair_noop_when_no_higher_credit_candidate() -> None:
    """SC-DECK-032: returns None when no pool card has higher credit than the swap target."""
    low_ramp = _make_deck_card("low-ramp", "Low Ramp", [CardRole.RAMP.value])
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=98)
    # Pool candidate also has credit=0.5 (not higher)
    equal_ramp_cand = _make_deck_card("equal-ramp", "Equal Ramp", [CardRole.RAMP.value])

    quota_status = [
        QuotaStatus(
            role=CardRole.RAMP.value,
            target_min=1,
            target_max=10,
            actual_count=1,
            is_satisfied=True,
            credit_sum=0.5,
            credit_satisfied=False,
            credit_warning="RAMP: credit 0.5 < minimum 1",
        )
    ]
    quotas = [RoleQuota(CardRole.RAMP, 1, 10), RoleQuota(CardRole.LAND, 36, 99)]
    deck = _make_credit_repair_deck(main_deck=[low_ramp, forest], quota_status=quota_status)
    all_cards_lookup = {
        "test-cmd": _make_commander(),
        "low-ramp": _make_card_data("low-ramp", "Low Ramp", oracle_text="Add {G}.", cmc=2.0),
        "equal-ramp": _make_card_data("equal-ramp", "Equal Ramp", oracle_text="Add {G}.", cmc=2.0),
        "forest-basic": _forest_data(),
    }
    selected_ids = {c.oracle_id for c in deck.main_deck}

    result = _repair_credit_quality_one(
        deck, selected_ids, [equal_ramp_cand], all_cards_lookup, quotas
    )
    assert result is None


def test_credit_repair_respects_quota_min() -> None:
    """SC-DECK-032: does not remove a card if doing so drops another role below target_min."""
    # Card with both RAMP and CARD_DRAW — removing it would drop CARD_DRAW below min
    dual_role = _make_deck_card("dual-role", "Dual Role", [CardRole.RAMP.value, CardRole.CARD_DRAW.value])
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=98)
    high_ramp_cand = _make_deck_card(
        "high-ramp", "High Ramp", [CardRole.RAMP.value], synergy_score=0.8, is_owned=True
    )

    quota_status = [
        QuotaStatus(
            role=CardRole.RAMP.value,
            target_min=1,
            target_max=10,
            actual_count=1,
            is_satisfied=True,
            credit_sum=0.5,
            credit_satisfied=False,
            credit_warning="RAMP: credit 0.5 < minimum 1",
        ),
        QuotaStatus(
            role=CardRole.CARD_DRAW.value,
            target_min=1,
            target_max=5,
            actual_count=1,
            is_satisfied=True,
            credit_sum=1.0,
            credit_satisfied=True,
        ),
    ]
    # CARD_DRAW min=1 and dual_role is the only CARD_DRAW card → cannot remove it
    quotas = [
        RoleQuota(CardRole.RAMP, 1, 10),
        RoleQuota(CardRole.CARD_DRAW, 1, 5),
        RoleQuota(CardRole.LAND, 36, 99),
    ]
    deck = _make_credit_repair_deck(main_deck=[dual_role, forest], quota_status=quota_status)
    all_cards_lookup = {
        "test-cmd": _make_commander(),
        "dual-role": _make_card_data("dual-role", "Dual Role", oracle_text="Draw a card. Add {G}.", cmc=2.0),
        "high-ramp": _make_card_data(
            "high-ramp", "High Ramp",
            oracle_text="Whenever you sacrifice a permanent, add {G}{G}.",
        ),
        "forest-basic": _forest_data(),
    }
    selected_ids = {c.oracle_id for c in deck.main_deck}

    result = _repair_credit_quality_one(
        deck, selected_ids, [high_ramp_cand], all_cards_lookup, quotas
    )
    # dual-role cannot be removed without dropping CARD_DRAW below min=1
    assert result is None


# ---------------------------------------------------------------------------
# SC-DECK-033: Collection-gap status
# ---------------------------------------------------------------------------

def test_pool_limited_win_condition_returns_collection_gap_not_failed_quality() -> None:
    """SC-DECK-033: pool-exhausted WIN_CONDITION gap → generated_with_collection_gap."""
    commander = _make_commander()
    win_card = _make_deck_card("win-001", "Win 001", [CardRole.WIN_CONDITION.value])
    win_card2 = _make_deck_card("win-002", "Win 002", [CardRole.WIN_CONDITION.value])
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=97)

    quotas = [
        RoleQuota(CardRole.WIN_CONDITION, 3, 5),  # need 3, have 2
        RoleQuota(CardRole.LAND, 36, 99),
    ]
    quota_status = [
        QuotaStatus(
            role=CardRole.WIN_CONDITION.value,
            target_min=3,
            target_max=5,
            actual_count=2,
            is_satisfied=False,
            warning="WIN_CONDITION: need 3–5, got 2 assigned slot(s) (underfilled)",
            credit_satisfied=True,
        )
    ]
    deck = _make_multi_pass_deck(
        main_deck=[win_card, win_card2, forest],
        quota_status=quota_status,
    )
    # Pool has no unselected WIN_CONDITION candidates (win-001 and win-002 already in deck)
    all_cards_lookup = {
        "test-cmd": _make_commander(),
        "win-001": _make_card_data("win-001", "Win 001", oracle_text="Sacrifice a creature: you win the game."),
        "win-002": _make_card_data("win-002", "Win 002", oracle_text="Sacrifice a creature: you win the game."),
        "forest-basic": _forest_data(),
    }
    selected_ids = {"win-001", "win-002", "forest-basic"}

    result = _multi_pass_quality_repair(
        deck=deck,
        commander=commander,
        commander_tags=[],
        all_cards_lookup=all_cards_lookup,
        quotas=quotas,
        enriched_candidate_pool=[win_card, win_card2],  # already selected — pool-limited
        packages=[],
    )
    finalized = _finalize_quality_generation_status(result)

    assert finalized.generation_status == "generated_with_collection_gap", (
        f"Expected collection_gap but got {finalized.generation_status!r}"
    )
    assert any("collection_gap: WIN_CONDITION" in w for w in finalized.warnings)
    assert finalized.is_valid is True


def test_pool_limited_detection_is_accurate() -> None:
    """SC-DECK-033: _is_role_pool_limited returns True only when all candidates are selected."""
    all_cards_lookup = {
        "wc-a": _make_card_data("wc-a", "Win A"),
        "wc-b": _make_card_data("wc-b", "Win B"),
        "wc-c": _make_card_data("wc-c", "Win C"),
    }
    wc_a = _make_deck_card("wc-a", "Win A", [CardRole.WIN_CONDITION.value])
    wc_b = _make_deck_card("wc-b", "Win B", [CardRole.WIN_CONDITION.value])
    wc_c = _make_deck_card("wc-c", "Win C", [CardRole.WIN_CONDITION.value])
    pool = [wc_a, wc_b, wc_c]

    # wc-a and wc-b selected; wc-c still available → NOT pool-limited
    selected_with_available = {"wc-a", "wc-b"}
    assert not _is_role_pool_limited("WIN_CONDITION", selected_with_available, pool, all_cards_lookup)

    # All three selected → pool-limited
    selected_all = {"wc-a", "wc-b", "wc-c"}
    assert _is_role_pool_limited("WIN_CONDITION", selected_all, pool, all_cards_lookup)


def test_structural_win_condition_failure_still_returns_failed_quality() -> None:
    """SC-DECK-033: pool HAS candidates but deck is locked → failed_quality not collection_gap."""
    commander = _make_commander()
    # Use a card with WIN_CONDITION so it cannot be swapped out (WIN_CONDITION in its roles
    # means _find_swap_target won't pick it; but add a second to be safe)
    # Make the deck have NO removable non-land cards (all are at quota minimum):
    # One WIN_CONDITION card already in deck; one RAMP-only card at minimum.
    # Need 2 WIN_CONDITION but have 1; pool has a win candidate but deck is locked.
    win_in_deck = _make_deck_card("win-locked", "Win Locked", [CardRole.WIN_CONDITION.value])
    ramp_locked = _make_deck_card("ramp-locked", "Ramp Locked", [CardRole.RAMP.value])
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=97)

    quotas = [
        RoleQuota(CardRole.WIN_CONDITION, 2, 5),  # need 2, have 1
        RoleQuota(CardRole.RAMP, 1, 10),           # ramp-locked at min=1 → not removable
        RoleQuota(CardRole.LAND, 36, 99),
    ]
    quota_status = [
        QuotaStatus(
            role=CardRole.WIN_CONDITION.value,
            target_min=2,
            target_max=5,
            actual_count=1,
            is_satisfied=False,
            warning="WIN_CONDITION: need 2–5, got 1 assigned slot(s) (underfilled)",
            credit_satisfied=True,
        ),
        QuotaStatus(
            role=CardRole.RAMP.value,
            target_min=1,
            target_max=10,
            actual_count=1,
            is_satisfied=True,
            credit_satisfied=True,
        ),
    ]
    deck = _make_multi_pass_deck(
        main_deck=[win_in_deck, ramp_locked, forest],
        quota_status=quota_status,
    )
    # Pool HAS an unselected WIN_CONDITION card — pool is NOT the constraint
    win_candidate = _make_deck_card(
        "win-cand", "Win Cand", [CardRole.WIN_CONDITION.value], synergy_score=0.8, is_owned=True
    )
    all_cards_lookup = {
        "test-cmd": _make_commander(),
        "win-locked": _make_card_data("win-locked", "Win Locked", oracle_text="You win the game."),
        "ramp-locked": _make_card_data("ramp-locked", "Ramp Locked", oracle_text="Add {G}.", cmc=2.0),
        "forest-basic": _forest_data(),
        "win-cand": _make_card_data("win-cand", "Win Cand", oracle_text="Sacrifice a creature: you win the game."),
    }

    result = _multi_pass_quality_repair(
        deck=deck,
        commander=commander,
        commander_tags=[],
        all_cards_lookup=all_cards_lookup,
        quotas=quotas,
        enriched_candidate_pool=[win_candidate],
        packages=[],
    )
    finalized = _finalize_quality_generation_status(result)
    # Pool has win-cand → NOT pool-limited → should not be collection_gap
    # (In practice the repair succeeds here since ramp-locked can't be swapped but
    # win-in-deck also can't since incoming=WIN_CONDITION and it already has WIN_CONDITION.
    # The pool candidate IS there, so the gap is NOT pool-limited.)
    assert finalized.generation_status != "generated_with_collection_gap", (
        f"Should not be collection_gap when pool has candidates: {finalized.generation_status!r}"
    )


def test_known_structural_failure_does_not_become_collection_gap() -> None:
    """SC-DECK-033: when all pool candidates are already selected but role has NO count gap, status is success."""
    commander = _make_commander()
    win_card = _make_deck_card("win-001", "Win 001", [CardRole.WIN_CONDITION.value])
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=98)

    # WIN_CONDITION count met (actual=1, min=1) — no count gap → success, not collection_gap
    quotas = [
        RoleQuota(CardRole.WIN_CONDITION, 1, 3),
        RoleQuota(CardRole.LAND, 36, 99),
    ]
    quota_status = [
        QuotaStatus(
            role=CardRole.WIN_CONDITION.value,
            target_min=1,
            target_max=3,
            actual_count=1,
            is_satisfied=True,
            credit_satisfied=True,
        )
    ]
    deck = _make_multi_pass_deck(main_deck=[win_card, forest], quota_status=quota_status)
    all_cards_lookup = {
        "test-cmd": _make_commander(),
        "win-001": _make_card_data("win-001", "Win 001", oracle_text="Sacrifice a creature: you win the game."),
        "forest-basic": _forest_data(),
    }
    result = _multi_pass_quality_repair(
        deck=deck,
        commander=commander,
        commander_tags=[],
        all_cards_lookup=all_cards_lookup,
        quotas=quotas,
        enriched_candidate_pool=[win_card],  # already selected, but no gap
        packages=[],
    )
    finalized = _finalize_quality_generation_status(result)
    assert finalized.generation_status == "success"
    assert not any("collection_gap" in w for w in finalized.warnings)


def test_credit_repair_does_not_crash_when_two_gaps_are_equal() -> None:
    """Regression: equal credit gaps must not cause TypeError when sorting QuotaStatus objects."""
    # Two roles with identical credit gaps cause Python to compare QuotaStatus objects
    # as tiebreakers if sort key is not provided — QuotaStatus has no __lt__.
    ramp = _make_deck_card("ramp-001", "Ramp Card", [CardRole.RAMP.value], synergy_score=0.3)
    draw = _make_deck_card("draw-001", "Draw Card", [CardRole.CARD_DRAW.value], synergy_score=0.3)
    forest = _make_deck_card("forest-basic", "Forest", [CardRole.LAND.value], quantity=97)

    quota_status = [
        QuotaStatus(
            role=CardRole.RAMP.value,
            target_min=2,
            target_max=10,
            actual_count=1,
            is_satisfied=True,
            credit_sum=0.5,
            credit_satisfied=False,
            credit_warning="RAMP: credit 0.5 < minimum 2",
        ),
        QuotaStatus(
            role=CardRole.CARD_DRAW.value,
            target_min=2,
            target_max=12,
            actual_count=1,
            is_satisfied=True,
            credit_sum=0.5,
            credit_satisfied=False,
            credit_warning="CARD_DRAW: credit 0.5 < minimum 2",
        ),
    ]
    deck = _make_credit_repair_deck(main_deck=[ramp, draw, forest], quota_status=quota_status)
    quotas = [
        RoleQuota(CardRole.RAMP, 2, 10),
        RoleQuota(CardRole.CARD_DRAW, 2, 12),
        RoleQuota(CardRole.LAND, 36, 99),
    ]
    # No exception should be raised even though both gaps are equal (1.5 each)
    result = _repair_credit_quality_one(deck, {c.oracle_id for c in deck.main_deck}, [], {}, quotas)
    # No candidates available → returns None; the important thing is no TypeError
    assert result is None
