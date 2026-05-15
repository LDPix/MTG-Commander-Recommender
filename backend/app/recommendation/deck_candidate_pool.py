"""SC-DECK-001: Build the legal candidate card pool for deck generation."""
from __future__ import annotations

from app.models.card import CardData
from app.models.deck import DeckCard
from app.recommendation.role_taxonomy import RoleTag


class DeckCandidatePool:
    def build(
        self,
        commander: CardData,
        owned_cards: list[CardData],
        all_cards: list[CardData],
        role_tags: dict[str, list[RoleTag]],
        owned_oracle_ids: set[str],
        max_pool_size: int = 600,
    ) -> list[DeckCard]:
        """Build sorted candidate pool of DeckCard objects.

        Rules:
        - Exclude commander-illegal cards
        - Exclude cards outside commander color identity
        - Exclude the commander itself
        - Mark is_owned correctly
        - Deduplicate by oracle_id (singleton)
        - Prefer owned cards (they appear first)
        - Cap at max_pool_size
        """
        commander_colors = set(commander.color_identity)

        seen: set[str] = set()
        owned_pool: list[DeckCard] = []
        unowned_pool: list[DeckCard] = []

        for card in all_cards:
            # Skip commander itself
            if card.oracle_id == commander.oracle_id:
                continue

            # Skip illegal cards
            if card.legalities.get("commander") != "legal":
                continue

            # Skip off-color cards
            if not set(card.color_identity).issubset(commander_colors):
                continue

            # Skip duplicates
            if card.oracle_id in seen:
                continue
            seen.add(card.oracle_id)

            is_owned = card.oracle_id in owned_oracle_ids
            roles = [tag.role.value for tag in role_tags.get(card.oracle_id, [])]

            deck_card = DeckCard(
                oracle_id=card.oracle_id,
                name=card.name,
                is_owned=is_owned,
                quantity=1,
                roles=roles,
                selection_reason="candidate",
            )

            if is_owned:
                owned_pool.append(deck_card)
            else:
                unowned_pool.append(deck_card)

        # Sort deterministically within each group
        owned_pool.sort(key=lambda c: c.oracle_id)
        unowned_pool.sort(key=lambda c: c.oracle_id)

        combined = owned_pool + unowned_pool
        return combined[:max_pool_size]
