"""Card identity resolver.

Resolves card names and oracle IDs to canonical card identities,
handling reprints, alternate names, and basic lands.
"""
from __future__ import annotations


from app.data_pipeline.basic_land_catalog import normalize_basic_land_card
from app.models.card import CanonicalCard, CardData


class CardNotFoundError(Exception):
    """Raised when a card name or oracle_id cannot be resolved."""

    def __init__(self, identifier: str, identifier_type: str = "name") -> None:
        self.identifier = identifier
        self.identifier_type = identifier_type
        super().__init__(
            f"Card not found by {identifier_type}: {identifier!r}"
        )


class CardResolver:
    """Resolves card names and oracle IDs to canonical card identities.

    Different printings of the same game card share a canonical identity
    via their oracle_id. Basic lands are handled specially: multiple copies
    are legal in Commander decks.

    Usage::

        resolver = CardResolver(cards)
        canonical = resolver.resolve("Sol Ring")
        canonical_by_id = resolver.resolve_by_oracle_id("a2e91c27-...")
    """

    def __init__(self, cards: list[CardData]) -> None:
        # oracle_id -> CanonicalCard (one entry per oracle identity)
        self._by_oracle_id: dict[str, CanonicalCard] = {}
        # lowercase name -> oracle_id  (exact name, case-insensitive)
        self._name_to_oracle_id: dict[str, str] = {}
        normalized_cards = [normalize_basic_land_card(card) for card in cards]
        exact_names = {card.name.lower() for card in normalized_cards}

        for card in normalized_cards:
            # Build oracle-id index (first occurrence wins)
            if card.oracle_id not in self._by_oracle_id:
                self._by_oracle_id[card.oracle_id] = CanonicalCard.from_card_data(card)

            # Build name index (case-insensitive)
            lower_name = card.name.lower()
            if lower_name not in self._name_to_oracle_id:
                self._name_to_oracle_id[lower_name] = card.oracle_id

            # For MDFCs, also index each face name independently
            if card.card_faces:
                for face in card.card_faces:
                    face_lower = face.name.lower()
                    if (
                        face_lower not in exact_names
                        and face_lower not in self._name_to_oracle_id
                    ):
                        self._name_to_oracle_id[face_lower] = card.oracle_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, name: str) -> CanonicalCard:
        """Resolve a card name to its canonical identity.

        Args:
            name: Exact card name (case-insensitive).

        Returns:
            CanonicalCard for the given name.

        Raises:
            CardNotFoundError: If no card with that name exists.
        """
        oracle_id = self._name_to_oracle_id.get(name.lower())
        if oracle_id is None:
            raise CardNotFoundError(name, identifier_type="name")
        return self._by_oracle_id[oracle_id]

    def resolve_by_oracle_id(self, oracle_id: str) -> CanonicalCard:
        """Resolve an oracle_id to its canonical identity.

        Args:
            oracle_id: Scryfall oracle_id UUID string.

        Returns:
            CanonicalCard for the given oracle_id.

        Raises:
            CardNotFoundError: If no card with that oracle_id exists.
        """
        canonical = self._by_oracle_id.get(oracle_id)
        if canonical is None:
            raise CardNotFoundError(oracle_id, identifier_type="oracle_id")
        return canonical

    def get_all(self) -> list[CanonicalCard]:
        """Return all known canonical cards."""
        return list(self._by_oracle_id.values())
