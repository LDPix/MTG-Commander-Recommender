"""Golden regression tests for recommendation and deck quality."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

GOLDEN_DIR = Path(__file__).parents[1] / "fixtures" / "golden"
EXPECTATIONS = json.loads((GOLDEN_DIR / "golden_expectations.json").read_text())
SCENARIOS = EXPECTATIONS["scenarios"]


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

    assert recommendations[0]["name"] == "Meren of Clan Nel Toth"


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
