"""Tests for SC-DATA-002: Canonical card identity resolver."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.data_pipeline.basic_land_catalog import (
    BASIC_LAND_TYPE_LINES,
    audit_basic_land_records,
)
from app.data_pipeline.card_resolver import CardNotFoundError, CardResolver
from app.data_pipeline.scryfall_ingest import load_scryfall_bulk_data
from app.models.card import CanonicalCard, CardData, is_basic_land_type_line
from app.recommendation.legality_validator import LegalityValidator


REAL_CATALOG_PATH = Path(__file__).parents[2] / "data" / "oracle-cards.json"


@pytest.fixture
def resolver(sample_cards: list[CardData]) -> CardResolver:
    """Build a CardResolver from the sample fixture cards."""
    return CardResolver(sample_cards)


@pytest.fixture(scope="session")
def live_catalog_resolver() -> CardResolver:
    """Build a resolver from the checked-in Scryfall catalog snapshot."""
    return CardResolver(load_scryfall_bulk_data(REAL_CATALOG_PATH))


def _card(
    oracle_id: str,
    name: str,
    type_line: str,
    color_identity: list[str] | None = None,
) -> CardData:
    return CardData(
        id=f"id-{oracle_id}",
        oracle_id=oracle_id,
        name=name,
        color_identity=color_identity or [],
        legalities={"commander": "legal"},
        type_line=type_line,
    )


def _card_from_canonical(card: CanonicalCard) -> CardData:
    return _card(
        oracle_id=card.oracle_id,
        name=card.name,
        type_line=card.type_line,
        color_identity=card.color_identity,
    )


# ---------------------------------------------------------------------------
# Exact name resolution
# ---------------------------------------------------------------------------

def test_exact_card_name_resolves(resolver: CardResolver) -> None:
    """An exact card name resolves to a CanonicalCard."""
    card = resolver.resolve("Sol Ring")

    assert isinstance(card, CanonicalCard)
    assert card.name == "Sol Ring"
    assert card.oracle_id


def test_exact_name_is_case_insensitive(resolver: CardResolver) -> None:
    """Name lookup is case-insensitive."""
    lower = resolver.resolve("sol ring")
    upper = resolver.resolve("SOL RING")
    mixed = resolver.resolve("Sol Ring")

    assert lower.oracle_id == upper.oracle_id == mixed.oracle_id


# ---------------------------------------------------------------------------
# Reprint identity
# ---------------------------------------------------------------------------

def test_reprint_maps_to_same_identity(sample_cards: list[CardData]) -> None:
    """Two CardData objects with the same oracle_id resolve to the same canonical identity."""
    base_card = next(c for c in sample_cards if c.name == "Sol Ring")

    # Simulate a reprint: same oracle_id, different printing id and name variant
    reprint = CardData(
        id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        oracle_id=base_card.oracle_id,  # Same oracle_id
        name="Sol Ring",
        color_identity=[],
        legalities={"commander": "legal"},
        type_line="Artifact",
        oracle_text="{T}: Add {C}{C}.",
        mana_cost="{1}",
        cmc=1.0,
        keywords=[],
    )

    resolver = CardResolver([base_card, reprint])

    original = resolver.resolve("Sol Ring")
    by_id = resolver.resolve_by_oracle_id(base_card.oracle_id)

    assert original.oracle_id == by_id.oracle_id == base_card.oracle_id


# ---------------------------------------------------------------------------
# Alternate name resolution
# ---------------------------------------------------------------------------

def test_alternate_name_resolves(resolver: CardResolver) -> None:
    """Cards present under different printings in the fixture all resolve."""
    # Wrath of God has appeared in many sets; our fixture has it once
    wrath = resolver.resolve("Wrath of God")
    assert wrath.name == "Wrath of God"


# ---------------------------------------------------------------------------
# Unknown card
# ---------------------------------------------------------------------------

def test_unknown_card_returns_error(resolver: CardResolver) -> None:
    """Looking up an unknown card name raises CardNotFoundError."""
    with pytest.raises(CardNotFoundError) as exc_info:
        resolver.resolve("Definitely Not A Real Card XYZ")

    err = exc_info.value
    assert "Definitely Not A Real Card XYZ" in str(err)
    assert err.identifier == "Definitely Not A Real Card XYZ"
    assert err.identifier_type == "name"


def test_unknown_oracle_id_returns_error(resolver: CardResolver) -> None:
    """Looking up an unknown oracle_id raises CardNotFoundError."""
    with pytest.raises(CardNotFoundError) as exc_info:
        resolver.resolve_by_oracle_id("00000000-0000-0000-0000-000000000000")

    err = exc_info.value
    assert err.identifier_type == "oracle_id"


# ---------------------------------------------------------------------------
# Basic land identity
# ---------------------------------------------------------------------------

def test_basic_land_identity_resolution(resolver: CardResolver) -> None:
    """Basic lands resolve to a CanonicalCard and are flagged as basic lands."""
    forest = resolver.resolve("Forest")

    assert isinstance(forest, CanonicalCard)
    assert forest.is_basic_land
    assert "Basic Land" in forest.type_line


def test_live_catalog_snow_covered_forest_is_basic_land(
    live_catalog_resolver: CardResolver,
) -> None:
    """Live catalog snow basics use Basic Snow Land and still count as basics."""
    forest = live_catalog_resolver.resolve("Snow-Covered Forest")

    assert isinstance(forest, CanonicalCard)
    assert forest.type_line == "Basic Snow Land — Forest"
    assert forest.is_basic_land
    assert is_basic_land_type_line(forest.type_line)


def test_live_catalog_exact_basic_names_prefer_basic_cards_over_art_faces(
    live_catalog_resolver: CardResolver,
) -> None:
    """Exact basic land names must not resolve to art-series face aliases."""
    for name in ["Plains", "Island", "Swamp", "Forest"]:
        basic = live_catalog_resolver.resolve(name)
        assert basic.name == name
        assert basic.is_basic_land
        assert is_basic_land_type_line(basic.type_line)


def test_basic_land_backfill_updates_existing_catalog_rows() -> None:
    """Known basic names are canonicalized when local catalog rows are stale."""
    stale_snow_forest = _card(
        "snow-forest-oracle",
        "Snow-Covered Forest",
        "Snow Land",
        ["G"],
    )
    resolver = CardResolver([stale_snow_forest])

    forest = resolver.resolve("Snow-Covered Forest")

    assert forest.type_line == BASIC_LAND_TYPE_LINES["Snow-Covered Forest"]
    assert forest.is_basic_land


def test_resolver_and_validator_agree_on_basic_land_status(
    live_catalog_resolver: CardResolver,
) -> None:
    """Resolver output feeds validator with the same basic-land classification."""
    snow_forest = _card_from_canonical(
        live_catalog_resolver.resolve("Snow-Covered Forest")
    )
    commander = _card("commander-oracle", "Green Commander", "Legendary Creature", ["G"])
    fillers = [
        (_card(f"filler-{i}", f"Filler {i}", "Artifact"), 1)
        for i in range(79)
    ]

    result = LegalityValidator().validate_deck(
        commander,
        [*fillers, (snow_forest, 20)],
    )

    assert result.valid
    assert result.errors == []


def test_snow_covered_basic_duplicates_allowed_in_generated_deck(
    live_catalog_resolver: CardResolver,
) -> None:
    """Canonical snow basics can appear as legal multi-copy deck entries."""
    snow_forest = live_catalog_resolver.resolve("Snow-Covered Forest")
    entries = [
        _card_from_canonical(snow_forest),
        _card_from_canonical(snow_forest),
        _card_from_canonical(snow_forest),
    ]

    assert all(card.is_basic_land for card in entries)
    assert {card.oracle_id for card in entries} == {snow_forest.oracle_id}


def test_nonbasic_snow_land_duplicate_still_fails() -> None:
    """Snow-only nonbasic lands do not receive basic-land singleton relief."""
    commander = _card("commander-oracle", "Test Commander", "Legendary Creature")
    fillers = [
        (_card(f"filler-{i}", f"Filler {i}", "Artifact"), 1)
        for i in range(97)
    ]
    nonbasic_snow_land = _card(
        "snow-hideout-oracle",
        "Snow-Covered Hideout",
        "Snow Land",
    )

    result = LegalityValidator().validate_deck(
        commander,
        [*fillers, (nonbasic_snow_land, 2)],
    )

    assert not result.valid
    assert any(error.error_type == "duplicate" for error in result.errors)


def test_basic_land_audit_has_no_live_catalog_issues(
    live_catalog_resolver: CardResolver,
) -> None:
    """The checked-in catalog snapshot exposes every required basic as basic."""
    assert audit_basic_land_records(live_catalog_resolver.get_all()) == []


def test_basic_land_audit_reports_stale_metadata() -> None:
    stale_snow_forest = _card(
        "snow-forest-oracle",
        "Snow-Covered Forest",
        "Snow Land",
        ["G"],
    )

    issues = audit_basic_land_records([stale_snow_forest])

    assert any(
        issue.name == "Snow-Covered Forest"
        and issue.reason == "record is not flagged as a basic land"
        for issue in issues
    )


# ---------------------------------------------------------------------------
# MDFC face name resolution
# ---------------------------------------------------------------------------

def test_mdfc_front_face_resolves(resolver: CardResolver) -> None:
    """The front face name of an MDFC resolves to the card's canonical identity."""
    valki = resolver.resolve("Valki, God of Lies")
    assert valki is not None
    assert valki.layout == "modal_dfc"


def test_mdfc_back_face_resolves(resolver: CardResolver) -> None:
    """The back face name of an MDFC also resolves to the same canonical identity."""
    tibalt = resolver.resolve("Tibalt, Cosmic Impostor")
    valki = resolver.resolve("Valki, God of Lies")
    assert tibalt.oracle_id == valki.oracle_id
