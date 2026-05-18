"""Pydantic models for in-memory card representation.

These are NOT SQLAlchemy ORM models. They represent card data
used by the data pipeline and recommendation layers.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


def is_basic_land_type_line(type_line: str) -> bool:
    """Return True when a type line has both the Basic supertype and Land type."""
    parts = type_line.replace("—", " ").replace(" - ", " ").split()
    return "Basic" in parts and "Land" in parts


class CardFace(BaseModel):
    """Represents one face of a modal double-faced card (MDFC) or transform card."""

    name: str
    type_line: str
    oracle_text: str | None = None
    mana_cost: str | None = None
    colors: list[str] = Field(default_factory=list)
    power: str | None = None
    toughness: str | None = None
    loyalty: str | None = None


class CardData(BaseModel):
    """Canonical in-memory representation of a Magic: The Gathering card.

    Sourced from Scryfall bulk data. Used throughout data pipeline and
    recommendation services.
    """

    id: str  # Scryfall UUID (printing-specific)
    oracle_id: str
    name: str
    color_identity: list[str] = Field(default_factory=list)
    legalities: dict[str, str] = Field(default_factory=dict)
    type_line: str
    oracle_text: str | None = None
    mana_cost: str | None = None
    cmc: float = 0.0
    keywords: list[str] = Field(default_factory=list)
    card_faces: list[CardFace] | None = None
    layout: str = "normal"
    prints_search_uri: str | None = None
    edhrec_rank: int | None = None
    rarity: str | None = None

    @property
    def is_basic_land(self) -> bool:
        """Return True if this card is a basic land."""
        return is_basic_land_type_line(self.type_line)

    @property
    def is_land(self) -> bool:
        """Return True if this card is a land of any kind."""
        return "Land" in self.type_line

    @property
    def is_mdfc(self) -> bool:
        """Return True if this card is a Modal Double-Faced Card."""
        return self.layout == "modal_dfc"

    @property
    def is_commander_legal(self) -> bool:
        """Return True if this card is legal in Commander."""
        return self.legalities.get("commander") == "legal"

    def get_all_oracle_text(self) -> str:
        """Return combined oracle text from all faces, or the card's own oracle text."""
        if self.card_faces:
            parts = [
                face.oracle_text for face in self.card_faces if face.oracle_text
            ]
            return "\n".join(parts)
        return self.oracle_text or ""

    def get_all_type_lines(self) -> list[str]:
        """Return type lines from all faces."""
        if self.card_faces:
            return [face.type_line for face in self.card_faces]
        return [self.type_line]


class CanonicalCard(BaseModel):
    """A canonical card identity, independent of printing.

    Multiple printings of the same game card share the same oracle_id and
    canonical identity. Used by the CardResolver.
    """

    oracle_id: str
    name: str
    color_identity: list[str] = Field(default_factory=list)
    legalities: dict[str, str] = Field(default_factory=dict)
    type_line: str
    oracle_text: str | None = None
    mana_cost: str | None = None
    cmc: float = 0.0
    keywords: list[str] = Field(default_factory=list)
    card_faces: list[CardFace] | None = None
    layout: str = "normal"
    is_basic_land: bool = False
    edhrec_rank: int | None = None
    rarity: str | None = None

    @classmethod
    def from_card_data(cls, card: CardData) -> "CanonicalCard":
        """Create a CanonicalCard from a CardData instance."""
        return cls(
            oracle_id=card.oracle_id,
            name=card.name,
            color_identity=card.color_identity,
            legalities=card.legalities,
            type_line=card.type_line,
            oracle_text=card.oracle_text,
            mana_cost=card.mana_cost,
            cmc=card.cmc,
            keywords=card.keywords,
            card_faces=card.card_faces,
            layout=card.layout,
            is_basic_land=card.is_basic_land,
            edhrec_rank=card.edhrec_rank,
            rarity=card.rarity,
        )
