"""Golden regression tests for recommendation and deck quality."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from app.data_pipeline.card_resolver import CardResolver
from app.data_pipeline.collection_normalizer import CollectionNormalizer
from app.data_pipeline.csv_importer import CSVImporter
from app.data_pipeline.scryfall_ingest import load_scryfall_bulk_data
from app.data_pipeline.scryfall_tagger import (
    ScryfallTaggerStore,
    get_scryfall_tagger_store,
    set_scryfall_tagger_store,
)
from app.models.card import CardData
from app.repositories.collection_repo import CollectionRepository
from app.recommendation.legality_validator import LegalityValidator
from app.recommendation.role_tagger import HybridTagger
from app.recommendation.role_taxonomy import CardRole
from app.services.collection_service import CollectionService
from app.services.deck_generation_service import DeckGenerationService
from app.services.recommendation_service import RecommendationService

GOLDEN_DIR = Path(__file__).parents[1] / "fixtures" / "golden"
EXPECTATIONS = json.loads((GOLDEN_DIR / "golden_expectations.json").read_text())
SCENARIOS = EXPECTATIONS["scenarios"]
REAL_CATALOG_PATH = Path(__file__).parents[2] / "data" / "oracle-cards.json"
SCRYFALL_TAGS_PATH = Path(__file__).parents[2] / "data" / "scryfall-tagger-tags.json"
LARGE_COLLECTION_SESSION = "moxfield-large-quality-regression"
REPRESENTATIVE_COMMANDERS = [
    "Nissa, Worldsoul Speaker",
    "Greta, Sweettooth Scourge",
    "Toluz, Clever Conductor",
]
_LARGE_FIXTURE_ROLES = [
    CardRole.RAMP,
    CardRole.CARD_DRAW,
    CardRole.SPOT_REMOVAL,
    CardRole.BOARD_WIPE,
    CardRole.PROTECTION,
    CardRole.WIN_CONDITION,
    CardRole.LANDFALL_SYNERGY,
    CardRole.ARISTOCRATS_SYNERGY,
    CardRole.SACRIFICE_OUTLET,
    CardRole.TOKEN_MAKER,
    CardRole.GRAVEYARD_SYNERGY,
]
_MOXFIELD_HEADER = (
    '"Count","Tradelist Count","Name","Edition","Condition","Language","Foil",'
    '"Tags","Last Modified","Collector Number","Alter","Proxy","Purchase Price"'
)


def _import_golden(api_client, scenario: dict) -> str:
    session_id = f"golden-{scenario['name']}"
    content = (GOLDEN_DIR / scenario["collection_filename"]).read_bytes()
    resp = api_client.post(
        "/api/v1/collections/import",
        files={"file": (scenario["collection_filename"], io.BytesIO(content), "text/csv")},
        headers={"X-Session-Id": session_id},
    )
    assert resp.status_code == 200, resp.text
    return session_id


def _recommend(api_client, session_id: str) -> list[dict]:
    resp = api_client.get(f"/api/v1/recommendations/{session_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()["recommendations"]


def _commander_id(sample_card_resolver, name: str) -> str:
    return sample_card_resolver.resolve(name).oracle_id


def _generate_deck(api_client, sample_card_resolver, scenario: dict) -> dict:
    session_id = _import_golden(api_client, scenario)
    commander_id = _commander_id(sample_card_resolver, scenario["deck_commander_name"])
    resp = api_client.post(
        "/api/v1/decks/generate",
        json={"session_id": session_id, "commander_oracle_id": commander_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture(scope="session")
def real_catalog_cards() -> list[CardData]:
    return load_scryfall_bulk_data(REAL_CATALOG_PATH)


@pytest.fixture(scope="session")
def real_catalog_resolver(real_catalog_cards: list[CardData]) -> CardResolver:
    return CardResolver(real_catalog_cards)


@pytest.fixture
def scryfall_tagger_store():
    previous = get_scryfall_tagger_store()
    store = ScryfallTaggerStore.from_file(SCRYFALL_TAGS_PATH)
    set_scryfall_tagger_store(store)
    try:
        yield store
    finally:
        if previous is not None:
            set_scryfall_tagger_store(previous)


@pytest.fixture
def large_moxfield_collection(
    db_session,
    real_catalog_cards,
    real_catalog_resolver,
    scryfall_tagger_store,
):
    repo = CollectionRepository(db_session)
    response = CollectionService(
        importer=CSVImporter(),
        normalizer=CollectionNormalizer(real_catalog_resolver),
        repo=repo,
    ).import_collection(
        session_id=LARGE_COLLECTION_SESSION,
        file_content=_large_moxfield_csv(real_catalog_cards).encode(),
        filename="moxfield-large-quality-regression.csv",
    )
    assert response.success is True
    return repo, response


def _large_moxfield_csv(cards: list[CardData]) -> str:
    rows = [_MOXFIELD_HEADER]
    for name in _large_collection_names(cards):
        quantity = 40 if name in {"Forest", "Swamp", "Island", "Plains"} else 1
        if name.startswith("Snow-Covered "):
            quantity = 12
        rows.append(
            f'"{quantity}","0","{name}","","Near Mint","English","","","","",'
            '"False","False",""'
        )
    return "\n".join(rows)


def _large_collection_names(cards: list[CardData]) -> list[str]:
    by_name = {card.name: card for card in cards}
    tagger = HybridTagger(get_scryfall_tagger_store())
    validator = LegalityValidator()
    selected = [
        *REPRESENTATIVE_COMMANDERS,
        "Sol Ring",
        "Arcane Signet",
        "Command Tower",
        "Forest",
        "Swamp",
        "Island",
        "Plains",
        "Snow-Covered Forest",
        "Snow-Covered Swamp",
        "Snow-Covered Island",
        "Snow-Covered Plains",
    ]

    for commander_name in REPRESENTATIVE_COMMANDERS:
        commander = by_name[commander_name]
        legal_cards = validator.filter_color_identity(
            commander,
            validator.filter_legal_cards(cards),
        )
        legal_cards = [
            card for card in legal_cards
            if card.name not in selected
            and card.name != commander_name
            and card.layout != "art_series"
        ]
        legal_cards.sort(key=lambda card: (card.edhrec_rank or 999999, card.name))
        for role in _LARGE_FIXTURE_ROLES:
            matches: list[str] = []
            for card in legal_cards:
                if any(tag.role == role for tag in tagger.tag(card)):
                    matches.append(card.name)
                if len(matches) >= 18:
                    break
            selected.extend(matches)

    deduped: list[str] = []
    for name in selected:
        if name not in deduped:
            deduped.append(name)
    return deduped


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["name"] for s in SCENARIOS])
def test_golden_collections_recommend_expected_commander(api_client, scenario):
    session_id = _import_golden(api_client, scenario)
    recommendations = _recommend(api_client, session_id)
    top_names = [
        recommendation["name"]
        for recommendation in recommendations[: scenario["acceptable_rank_max"]]
    ]

    assert any(
        expected in top_names for expected in scenario["expected_commander_names"]
    ), scenario["notes"]


def test_golden_aristocrats_collection_recommends_expected_commander(api_client):
    scenario = next(s for s in SCENARIOS if s["name"] == "aristocrats")
    session_id = _import_golden(api_client, scenario)
    recommendations = _recommend(api_client, session_id)
    # Meren and Greta are both strong B/G aristocrats commanders; either may rank first
    top_names = {r["name"] for r in recommendations[:2]}
    assert "Meren of Clan Nel Toth" in top_names or "Greta, Sweettooth Scourge" in top_names


def test_golden_landfall_collection_recommends_expected_commander(api_client):
    scenario = next(s for s in SCENARIOS if s["name"] == "landfall")
    session_id = _import_golden(api_client, scenario)
    recommendations = _recommend(api_client, session_id)
    top_names = [r["name"] for r in recommendations[: scenario["acceptable_rank_max"]]]

    assert "Meren of Clan Nel Toth" in top_names


def test_golden_spellslinger_collection_recommends_expected_commander(api_client):
    scenario = next(s for s in SCENARIOS if s["name"] == "spellslinger")
    session_id = _import_golden(api_client, scenario)
    recommendations = _recommend(api_client, session_id)
    top_names = [r["name"] for r in recommendations[: scenario["acceptable_rank_max"]]]

    assert "Atraxa, Praetors' Voice" in top_names


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["name"] for s in SCENARIOS])
def test_golden_decks_pass_legality(api_client, sample_card_resolver, scenario):
    deck = _generate_deck(api_client, sample_card_resolver, scenario)

    assert deck["is_valid"] is True, deck["validation_errors"]
    assert sum(card["quantity"] for card in deck["main_deck"]) == 99


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["name"] for s in SCENARIOS])
def test_golden_decks_meet_minimum_role_quality(
    api_client,
    sample_card_resolver,
    scenario,
):
    deck = _generate_deck(api_client, sample_card_resolver, scenario)

    for role, minimum in scenario["minimum_role_counts"].items():
        assert deck["role_breakdown"].get(role, 0) >= minimum
    assert deck["owned_percentage"] >= scenario["minimum_owned_percentage"]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["name"] for s in SCENARIOS])
def test_golden_decks_include_package_or_explanation_data(
    api_client,
    sample_card_resolver,
    scenario,
):
    deck = _generate_deck(api_client, sample_card_resolver, scenario)
    role_hints = set(deck["role_breakdown"])
    package_roles = {
        role
        for package in deck["package_breakdown"]
        for role in package["top_roles"]
    }
    explanation_count = len(deck["card_explanations"])

    assert explanation_count >= len(deck["main_deck"])
    assert deck["package_breakdown"] or deck["card_explanations"]
    assert role_hints | package_roles
    assert any(
        hint in role_hints or hint in package_roles
        for hint in scenario["expected_package_or_role_hints"]
    )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["name"] for s in SCENARIOS])
def test_golden_deck_has_minimum_package_membership_when_packages_available(
    api_client,
    sample_card_resolver,
    scenario,
):
    deck = _generate_deck(api_client, sample_card_resolver, scenario)
    if not deck["package_breakdown"]:
        pytest.skip("No detected packages available for this fixture.")

    packaged_cards = [card for card in deck["main_deck"] if card["package_ids"]]

    assert len(packaged_cards) >= 3


def test_package_breakdown_labels_are_conservative_when_confidence_low(
    api_client,
    sample_card_resolver,
):
    scenario = next(s for s in SCENARIOS if s["name"] == "aristocrats")
    deck = _generate_deck(api_client, sample_card_resolver, scenario)
    fallback_labels = {
        "black value package",
        "green value package",
        "utility package",
        "spells package",
        "tribal package",
        "graveyard package",
        "token package",
    }
    specific_labels = {
        "sacrifice/aristocrats package",
        "landfall package",
        "blink/ETB package",
        "spellslinger package",
        "tribal support package",
        "graveyard recursion package",
        "sacrifice outlet package",
        "token creation package",
    }

    assert deck["package_breakdown"]
    for package in deck["package_breakdown"]:
        if package["confidence"] < 0.5:
            assert package["label"] in fallback_labels
        else:
            assert package["label"] in specific_labels


def test_large_moxfield_fixture_imports_without_catalog_or_csv_noise(
    large_moxfield_collection,
):
    repo, response = large_moxfield_collection
    collection = repo.get_collection_by_session(LARGE_COLLECTION_SESSION)
    assert collection is not None
    items = repo.get_items(collection.id)
    basics = {item.canonical_name: item for item in items if item.is_basic_land}

    assert response.imported_count >= 500
    assert response.unknown_cards == []
    assert response.warnings == []
    assert sum(item.quantity for item in items) > response.imported_count
    assert {"Forest", "Swamp", "Island", "Plains", "Snow-Covered Forest"}.issubset(
        basics
    )


def test_large_collection_recommendations_do_not_saturate_to_one(
    large_moxfield_collection,
    real_catalog_resolver,
):
    repo, _ = large_moxfield_collection

    recommendations = RecommendationService(repo, real_catalog_resolver).get_recommendations(
        LARGE_COLLECTION_SESSION,
        top_k=10,
    )

    assert recommendations is not None
    top_scores = [recommendation.fit_score for recommendation in recommendations[:10]]
    assert top_scores
    assert all(score < 1.0 for score in top_scores), top_scores


@pytest.mark.parametrize("commander_name", REPRESENTATIVE_COMMANDERS)
def test_large_collection_representative_decks_separate_legality_from_quality(
    large_moxfield_collection,
    real_catalog_resolver,
    commander_name,
):
    repo, _ = large_moxfield_collection
    commander = real_catalog_resolver.resolve(commander_name)

    deck = DeckGenerationService(repo, real_catalog_resolver).generate_deck(
        LARGE_COLLECTION_SESSION,
        commander.oracle_id,
    )

    assert deck is not None
    assert deck.is_valid is True, deck.validation_errors
    assert deck.generation_status != "failed_validation", _quality_diagnostics(deck)
    assert sum(card.quantity for card in deck.main_deck) == 99
    if deck.generation_status == "failed_quality":
        diagnostics = _quality_diagnostics(deck)
        assert diagnostics["validation_errors"] == []
        assert any("Deck quality failure:" in warning for warning in deck.warnings)
    else:
        assert all(
            quota.target_min <= quota.actual_count <= quota.target_max
            and quota.credit_satisfied
            for quota in deck.quota_status
        ), _quality_diagnostics(deck)
    assert not any(
        package.label == "green value package"
        and package.activation_status == "rejected_loose"
        for package in deck.package_breakdown
    )
    assert all(
        card.is_owned
        for card in deck.main_deck
        if card.name in {"Forest", "Swamp", "Island", "Plains"}
    )


def _quality_diagnostics(deck) -> dict:
    return {
        "generation_status": deck.generation_status,
        "is_valid": deck.is_valid,
        "validation_errors": deck.validation_errors,
        "quota_status": [
            {
                "role": quota.role,
                "actual_count": quota.actual_count,
                "target_min": quota.target_min,
                "target_max": quota.target_max,
                "credit_sum": quota.credit_sum,
                "credit_satisfied": quota.credit_satisfied,
                "warning": quota.warning,
                "credit_warning": quota.credit_warning,
            }
            for quota in deck.quota_status
        ],
        "packages": [
            {
                "label": package.label,
                "activation_status": package.activation_status,
                "selected_count": package.selected_count,
            }
            for package in deck.package_breakdown
        ],
        "coherence": (
            deck.strategic_coherence.model_dump()
            if deck.strategic_coherence is not None
            else None
        ),
        "warnings": deck.warnings,
    }
