"""Tests for SC-DATA-002: Canonical card identity resolver."""
from __future__ import annotations

import pytest

from app.data_pipeline.card_resolver import CardNotFoundError, CardResolver
from app.models.card import CanonicalCard, CardData


@pytest.fixture
def resolver(sample_cards: list[CardData]) -> CardResolver:
    """Build a CardResolver from the sample fixture cards."""
    return CardResolver(sample_cards)


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
