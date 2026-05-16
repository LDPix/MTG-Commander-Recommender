"""Scryfall bulk data ingestion.

Provides functions to load and process Scryfall bulk card data into
the internal CardData representation used by the recommendation engine.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from app.models.card import CardData, CardFace


def _parse_card_face(face_data: dict[str, Any]) -> CardFace:
    """Parse a single card face dict into a CardFace model."""
    return CardFace(
        name=face_data["name"],
        type_line=face_data.get("type_line", ""),
        oracle_text=face_data.get("oracle_text"),
        mana_cost=face_data.get("mana_cost"),
        colors=face_data.get("colors", []),
        power=face_data.get("power"),
        toughness=face_data.get("toughness"),
        loyalty=face_data.get("loyalty"),
    )


def parse_scryfall_card(raw: dict[str, Any]) -> CardData | None:
    """Parse a single raw Scryfall card dict into a CardData model.

    Returns None if the card cannot be parsed (e.g., missing required fields).
    """
    try:
        card_faces_raw = raw.get("card_faces")
        card_faces = None
        if card_faces_raw:
            card_faces = [_parse_card_face(f) for f in card_faces_raw]

        return CardData(
            id=raw["id"],
            oracle_id=raw["oracle_id"],
            name=raw["name"],
            color_identity=raw.get("color_identity", []),
            legalities=raw.get("legalities", {}),
            type_line=raw.get("type_line", ""),
            oracle_text=raw.get("oracle_text"),
            mana_cost=raw.get("mana_cost"),
            cmc=raw.get("cmc", 0.0),
            keywords=raw.get("keywords", []),
            card_faces=card_faces,
            layout=raw.get("layout", "normal"),
            prints_search_uri=raw.get("prints_search_uri"),
            edhrec_rank=raw.get("edhrec_rank"),
            rarity=raw.get("rarity"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def load_scryfall_bulk_data(path: str | Path) -> list[CardData]:
    """Load Scryfall bulk data from a JSON file.

    Expects the file to contain a JSON array of card objects as produced
    by the Scryfall "Oracle Cards" or "Default Cards" bulk data export.

    Args:
        path: Path to the JSON file containing Scryfall bulk card data.

    Returns:
        A list of CardData objects parsed from the file.
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        raw_cards: list[dict[str, Any]] = json.load(fh)

    cards: list[CardData] = []
    for raw in raw_cards:
        card = parse_scryfall_card(raw)
        if card is not None:
            cards.append(card)
    return cards


def iter_scryfall_bulk_data(path: str | Path) -> Iterator[CardData]:
    """Iterate over Scryfall bulk data from a JSON file one card at a time.

    More memory-efficient than load_scryfall_bulk_data for very large files.
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        raw_cards: list[dict[str, Any]] = json.load(fh)

    for raw in raw_cards:
        card = parse_scryfall_card(raw)
        if card is not None:
            yield card


def filter_commander_legal(cards: list[CardData]) -> list[CardData]:
    """Return only cards that are legal in Commander."""
    return [c for c in cards if c.is_commander_legal]
