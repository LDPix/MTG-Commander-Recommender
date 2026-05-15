"""Tests for SC-DATA-001: Scryfall bulk data ingestion."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.data_pipeline.scryfall_ingest import load_scryfall_bulk_data
from app.models.card import CardData


def test_ingest_scryfall_bulk_data(sample_cards: list[CardData]) -> None:
    """Parsing a sample fixture returns a non-empty list of CardData objects."""
    assert len(sample_cards) > 0
    for card in sample_cards:
        assert isinstance(card, CardData)
        assert card.id
        assert card.oracle_id
        assert card.name


def test_card_metadata_contains_color_identity(cards_by_name: dict[str, CardData]) -> None:
    """Each parsed card exposes its color_identity as a list."""
    sol_ring = cards_by_name["Sol Ring"]
    assert sol_ring.color_identity == []

    swords = cards_by_name["Swords to Plowshares"]
    assert "W" in swords.color_identity

    cultivate = cards_by_name["Cultivate"]
    assert "G" in cultivate.color_identity


def test_card_metadata_contains_commander_legality(cards_by_name: dict[str, CardData]) -> None:
    """Cards expose their Commander legality via the legalities dict."""
    sol_ring = cards_by_name["Sol Ring"]
    assert sol_ring.legalities.get("commander") == "legal"
    assert sol_ring.is_commander_legal

    # All sample cards should be legal in Commander
    for card in cards_by_name.values():
        assert card.is_commander_legal, f"{card.name} should be Commander legal"


def test_mdfc_card_is_loaded_correctly(cards_by_name: dict[str, CardData]) -> None:
    """MDFC 'Valki, God of Lies // Tibalt, Cosmic Impostor' is parsed correctly."""
    valki = cards_by_name["Valki, God of Lies"]

    assert valki.layout == "modal_dfc"
    assert valki.is_mdfc

    assert valki.card_faces is not None
    assert len(valki.card_faces) == 2

    face_names = [f.name for f in valki.card_faces]
    assert "Valki, God of Lies" in face_names
    assert "Tibalt, Cosmic Impostor" in face_names

    # Each face has its own oracle text and mana cost
    front_face = next(f for f in valki.card_faces if f.name == "Valki, God of Lies")
    back_face = next(f for f in valki.card_faces if f.name == "Tibalt, Cosmic Impostor")

    assert front_face.mana_cost == "{1}{B}"
    assert back_face.mana_cost == "{5}{B}{R}"
    assert front_face.oracle_text is not None
    assert back_face.oracle_text is not None

    # Combined oracle text includes both faces
    combined = valki.get_all_oracle_text()
    assert "Valki" in combined or "exile" in combined.lower()
    assert "Tibalt" in combined or "planeswalker" in combined.lower() or "+2" in combined


def test_basic_land_is_loaded_correctly(cards_by_name: dict[str, CardData]) -> None:
    """Basic lands are loaded with correct type_line and properties."""
    forest = cards_by_name["Forest"]

    assert forest.is_land
    assert forest.is_basic_land
    assert "Basic Land" in forest.type_line
    assert forest.cmc == 0.0
    assert forest.mana_cost is None
    assert forest.is_commander_legal
