"""End-to-end regressions for the strategic coherence gate."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.data_pipeline.card_resolver import CardResolver
from app.models.card import CardData
from app.models.deck import (
    DeckCard,
    GeneratedDeck,
    PackageCluster,
    QuotaStatus,
    StrategicCoherenceReport,
)
from app.recommendation.quota_config import BASELINE_QUOTAS
from app.recommendation.role_taxonomy import CardRole
from app.recommendation.strategic_coherence import (
    MAX_OFF_PLAN_CARDS,
    REQUIRED_ROLE_FILLERS,
    StrategicCoherenceValidator,
)
from app.services import deck_generation_service as service_module
from app.services.deck_generation_service import DeckGenerationService
from tests.conftest import MEREN_ORACLE_ID


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "negative"
GRETA_FIXTURE = FIXTURE_DIR / "greta_incoherent_generic_pile.json"
TOLUZ_FIXTURE = FIXTURE_DIR / "toluz_incoherent_generic_pile.json"
GENERATE_ENDPOINT = "/api/v1/decks/generate"


class _FakeCollectionRepo:
    def __init__(self, oracle_ids: list[str]) -> None:
        self._items = [SimpleNamespace(oracle_id=oracle_id) for oracle_id in oracle_ids]

    def get_collection_by_session(self, session_id: str):
        return SimpleNamespace(id=1, session_id=session_id)

    def get_items(self, collection_id: int):
        return self._items


def _load_negative_fixture(
    path: Path,
) -> tuple[CardData, GeneratedDeck, dict[str, CardData], list[PackageCluster]]:
    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    commander = CardData(**raw["commander"])
    lookup: dict[str, CardData] = {commander.oracle_id: commander}
    package = PackageCluster(**raw["unsupported_package"])
    package_ids = set(package.card_oracle_ids)
    cards: list[DeckCard] = []

    for item in raw["cards"]:
        card = CardData(
            id=item["oracle_id"],
            oracle_id=item["oracle_id"],
            name=item["name"],
            color_identity=commander.color_identity,
            legalities={"commander": "legal"},
            type_line=item["type_line"],
            oracle_text=item["oracle_text"],
            cmc=item["cmc"],
        )
        lookup[card.oracle_id] = card
        cards.append(
            DeckCard(
                oracle_id=card.oracle_id,
                name=card.name,
                is_owned=True,
                quantity=1,
                roles=item["roles"],
                color_identity=card.color_identity,
                package_ids=[package.package_id] if card.oracle_id in package_ids else [],
                selection_reason="fixture selection",
                synergy_score=0.0,
            )
        )

    basic_land = _basic_land_for(commander)
    lookup[basic_land.oracle_id] = basic_land
    cards.append(
        DeckCard(
            oracle_id=basic_land.oracle_id,
            name=basic_land.name,
            is_owned=True,
            quantity=99 - len(cards),
            roles=[CardRole.LAND.value],
            color_identity=basic_land.color_identity,
            selection_reason="fixture basic lands",
        )
    )

    deck = GeneratedDeck(
        deck_id=f"negative-fixture-{raw['fixture_id']}",
        session_id=f"negative-fixture-{raw['fixture_id']}",
        commander=DeckCard(
            oracle_id=commander.oracle_id,
            name=commander.name,
            is_owned=True,
            quantity=1,
            roles=[],
            color_identity=commander.color_identity,
            selection_reason="commander",
        ),
        main_deck=cards,
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


def _basic_land_for(commander: CardData) -> CardData:
    name = "Island" if "U" in commander.color_identity else "Forest"
    return CardData(
        id=f"{name.lower()}-basic",
        oracle_id=f"{name.lower()}-basic",
        name=name,
        color_identity=[commander.color_identity[0]],
        legalities={"commander": "legal"},
        type_line=f"Basic Land - {name}",
        oracle_text="",
        cmc=0.0,
    )


def _repair_candidates(commander: CardData, lookup: dict[str, CardData]) -> list[DeckCard]:
    if commander.oracle_id.startswith("greta"):
        role = CardRole.SACRIFICE_OUTLET.value
        text = "Sacrifice a Food: you gain 2 life. When a creature dies, draw a card."
        name_prefix = "Food Sacrifice"
        colors = ["B", "G"]
    else:
        role = CardRole.GRAVEYARD_SYNERGY.value
        text = "Connive. When this enters, draw a card, then discard a card."
        name_prefix = "Connive Discard"
        colors = ["U", "B"]

    candidates: list[DeckCard] = []
    for idx in range(8):
        oracle_id = f"{commander.oracle_id}-repair-{idx:02d}"
        lookup[oracle_id] = CardData(
            id=oracle_id,
            oracle_id=oracle_id,
            name=f"{name_prefix} {idx}",
            color_identity=colors,
            legalities={"commander": "legal"},
            type_line="Creature",
            oracle_text=text,
            cmc=2.0,
        )
        candidates.append(
            DeckCard(
                oracle_id=oracle_id,
                name=f"{name_prefix} {idx}",
                is_owned=False,
                quantity=1,
                roles=[role],
                color_identity=colors,
                selection_reason="repair candidate",
                synergy_score=0.5,
            )
        )
    return candidates


def _service_for_fixture(
    monkeypatch: pytest.MonkeyPatch,
    fixture_path: Path,
) -> tuple[DeckGenerationService, StrategicCoherenceReport, CardData, dict[str, CardData], list[PackageCluster]]:
    commander, initial_deck, lookup, packages = _load_negative_fixture(fixture_path)
    repair_pool = _repair_candidates(commander, lookup)
    initial_report = StrategicCoherenceValidator().validate(
        commander=commander,
        commander_tags=[],
        deck=initial_deck,
        all_cards_lookup=lookup,
        packages=packages,
    )

    def fake_build(*args, **kwargs):
        return list(repair_pool)

    def fake_detect(*args, **kwargs):
        return packages

    def fake_label(self, package):
        return package

    def fake_generate(*args, **kwargs):
        return initial_deck.model_copy(deep=True)

    monkeypatch.setattr(service_module.DeckCandidatePool, "build", fake_build)
    monkeypatch.setattr(service_module.PackageDetector, "detect", fake_detect)
    monkeypatch.setattr(service_module.PackageLabeler, "label", fake_label)
    monkeypatch.setattr(service_module.DeckGenerator, "generate", fake_generate)

    resolver = CardResolver(list(lookup.values()))
    service = DeckGenerationService(
        _FakeCollectionRepo([card.oracle_id for card in lookup.values()]),
        resolver,
    )
    return service, initial_report, commander, lookup, packages


def _assert_returned_coherence_state(
    deck: GeneratedDeck,
    initial_report: StrategicCoherenceReport,
    commander: CardData,
    lookup: dict[str, CardData],
    packages: list[PackageCluster],
) -> None:
    assert deck.strategic_coherence is not None
    report = deck.strategic_coherence
    recomputed = StrategicCoherenceValidator().validate(
        commander=commander,
        commander_tags=[],
        deck=deck,
        all_cards_lookup=lookup,
        packages=packages,
    )
    expected_deck = service_module._finalize_coherence_fail_closed(
        deck=deck.model_copy(update={"strategic_coherence": recomputed}),
        packages=packages,
    )
    assert expected_deck.strategic_coherence is not None
    assert report.model_dump() == expected_deck.strategic_coherence.model_dump()
    assert report.off_plan_count < initial_report.off_plan_count or (
        report.off_plan_count <= MAX_OFF_PLAN_CARDS
    )

    repaired_cards = [
        card
        for card in deck.main_deck
        if card.selection_reason.startswith("coherence repair:")
    ]
    if report.off_plan_count < initial_report.off_plan_count:
        assert repaired_cards

    final_ids = {card.oracle_id for card in deck.main_deck}
    unrepaired_warning_ids = set(initial_report.warning_card_oracle_ids).intersection(
        final_ids,
        report.warning_card_oracle_ids,
    )
    cards_by_id = {card.oracle_id: card for card in deck.main_deck}
    unrepaired_unprotected_ids = {
        oracle_id
        for oracle_id in unrepaired_warning_ids
        if not REQUIRED_ROLE_FILLERS.intersection(cards_by_id[oracle_id].roles)
    }
    assert not unrepaired_unprotected_ids, (
        "Coherence warnings still point at unrepaired initial off-plan cards: "
        f"{sorted(unrepaired_unprotected_ids)}"
    )

    expected_breakdown: dict[str, int] = {}
    for card in deck.main_deck:
        if card.assigned_role is not None:
            expected_breakdown[card.assigned_role] = (
                expected_breakdown.get(card.assigned_role, 0) + card.quantity
            )
    assert deck.role_breakdown == expected_breakdown
    for quota in deck.quota_status:
        assert quota.actual_count == expected_breakdown.get(quota.role, 0)

    assert deck.owned_count == sum(card.quantity for card in deck.main_deck if card.is_owned)
    assert deck.owned_percentage == deck.owned_count / 99
    assert sum(card.quantity for card in deck.main_deck) == 99
    assert deck.is_valid is True
    assert deck.validation_errors == []
    assert all(warning.strip() for warning in deck.warnings)


def test_generate_deck_returns_repaired_greta_coherence_state(monkeypatch) -> None:
    service, initial_report, commander, lookup, packages = _service_for_fixture(
        monkeypatch,
        GRETA_FIXTURE,
    )

    deck = service.generate_deck("greta-e2e-session", commander.oracle_id)

    assert deck is not None
    _assert_returned_coherence_state(deck, initial_report, commander, lookup, packages)


def test_generate_deck_returns_repaired_toluz_coherence_state(monkeypatch) -> None:
    service, initial_report, commander, lookup, packages = _service_for_fixture(
        monkeypatch,
        TOLUZ_FIXTURE,
    )

    deck = service.generate_deck("toluz-e2e-session", commander.oracle_id)

    assert deck is not None
    _assert_returned_coherence_state(deck, initial_report, commander, lookup, packages)


def test_api_response_coherence_report_matches_returned_main_deck(
    api_client,
    seeded_collection,
    sample_card_resolver,
) -> None:
    response = api_client.post(
        GENERATE_ENDPOINT,
        json={"session_id": seeded_collection, "commander_oracle_id": MEREN_ORACLE_ID},
    )
    assert response.status_code == 200
    payload = response.json()

    commander = service_module._canonical_to_card_data(
        sample_card_resolver.resolve_by_oracle_id(MEREN_ORACLE_ID)
    )
    lookup = {
        card.oracle_id: service_module._canonical_to_card_data(card)
        for card in sample_card_resolver.get_all()
    }
    deck = GeneratedDeck(
        deck_id=payload["deck_id"],
        session_id=payload["session_id"],
        commander=DeckCard(**payload["commander"]),
        main_deck=[DeckCard(**card) for card in payload["main_deck"]],
        role_breakdown=payload["role_breakdown"],
        quota_status=[QuotaStatus(**quota) for quota in payload["quota_status"]],
        package_breakdown=[
            PackageCluster(**package) for package in payload["package_breakdown"]
        ],
        warnings=payload["warnings"],
        owned_count=payload["owned_count"],
        owned_percentage=payload["owned_percentage"],
        is_valid=payload["is_valid"],
        validation_errors=payload["validation_errors"],
    )
    report = StrategicCoherenceValidator().validate(
        commander=commander,
        commander_tags=[],
        deck=deck,
        all_cards_lookup=lookup,
        packages=deck.package_breakdown,
    )

    expected_deck = service_module._finalize_coherence_fail_closed(
        deck=deck.model_copy(update={"strategic_coherence": report}),
        packages=deck.package_breakdown,
    )
    assert expected_deck.strategic_coherence is not None
    assert payload["strategic_coherence"] == expected_deck.strategic_coherence.model_dump()
    assert set(report.warning_card_oracle_ids).issubset(
        {card["oracle_id"] for card in payload["main_deck"]}
    )


def test_warning_only_unrepaired_incoherent_deck_fails_regression() -> None:
    commander, deck, lookup, packages = _load_negative_fixture(GRETA_FIXTURE)
    initial_report = StrategicCoherenceValidator().validate(
        commander=commander,
        commander_tags=[],
        deck=deck,
        all_cards_lookup=lookup,
        packages=packages,
    )
    deck = service_module._refresh_deck_derived_state(
        deck=deck,
        commander=commander,
        all_cards_lookup=lookup,
        quotas=list(BASELINE_QUOTAS),
        coherence_report=initial_report,
    )
    deck = service_module._finalize_coherence_fail_closed(deck, packages)

    with pytest.raises(AssertionError, match="unrepaired initial off-plan cards"):
        _assert_returned_coherence_state(
            deck,
            initial_report,
            commander,
            lookup,
            packages,
        )
