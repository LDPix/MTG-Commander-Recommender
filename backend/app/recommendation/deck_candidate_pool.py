"""SC-DECK-001: Build the legal candidate card pool for deck generation."""
from __future__ import annotations

from app.models.card import CardData
from app.models.deck import DeckCard
from app.recommendation.colorless_rules import (
    C_REQUIREMENT_MIN_SOURCES,
    has_c_mana_requirement,
    is_dedicated_colorless_source,
)
from app.recommendation.mana_base_rules import (
    commander_is_colorless,
    is_c_only_land,
    is_fixing_land,
    is_mono_color,
)
from app.recommendation.role_taxonomy import RoleTag


COLOR_TO_BASIC_LAND: dict[str, str] = {
    "W": "Plains",
    "U": "Island",
    "B": "Swamp",
    "R": "Mountain",
    "G": "Forest",
}


def _land_is_eligible(
    card: CardData,
    commander_color_identity: list[str],
) -> bool:
    """Return False for lands excluded by mana base discipline rules."""
    if "Land" not in card.type_line:
        return True

    # SC-MANA-002: Exclude fixing lands from mono-color decks
    if is_mono_color(commander_color_identity):
        if is_fixing_land(card.name, card.oracle_text, commander_color_identity):
            return False

    # SC-MANA-004: Exclude {C}-only lands from non-colorless decks
    if not commander_is_colorless(commander_color_identity):
        if is_c_only_land(card.name, card.oracle_text):
            return False

    return True


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
        - SC-MANA-002: Exclude fixing lands from mono-color decks
        - SC-MANA-004: Exclude {C}-only lands from non-colorless decks
        - SC-DECK-010: Exclude {C}-requirement cards when colorless sources < threshold
        - Mark is_owned correctly
        - Populate color_identity from card data
        - Deduplicate by oracle_id (singleton)
        - Prefer owned cards (they appear first)
        - Cap at max_pool_size
        """
        commander_colors = set(commander.color_identity)

        # SC-DECK-010: Count dedicated colorless sources in owned cards
        colorless_source_count = sum(
            1 for card in owned_cards
            if is_dedicated_colorless_source(card.oracle_text, card.type_line)
        )
        allow_c_requirement_cards = colorless_source_count >= C_REQUIREMENT_MIN_SOURCES

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

            # SC-MANA-002 / SC-MANA-004: Exclude ineligible lands
            if not _land_is_eligible(card, commander.color_identity):
                continue

            # SC-DECK-010: Exclude {C}-requirement cards without enough colorless sources
            if not allow_c_requirement_cards and has_c_mana_requirement(
                card.mana_cost,
                card.oracle_text,
            ):
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
                color_identity=list(card.color_identity),
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
        capped = combined[:max_pool_size]
        return capped + _free_basic_lands_for_missing_colors(
            commander_color_identity=commander.color_identity,
            current_pool=capped,
            all_cards=all_cards,
            role_tags=role_tags,
        )


def _free_basic_lands_for_missing_colors(
    commander_color_identity: list[str],
    current_pool: list[DeckCard],
    all_cards: list[CardData],
    role_tags: dict[str, list[RoleTag]],
) -> list[DeckCard]:
    """Inject unowned regular basic land candidates for commander colors."""
    basic_names_in_pool = {card.name for card in current_pool}
    free_basics: list[DeckCard] = []

    for color in commander_color_identity:
        basic_name = COLOR_TO_BASIC_LAND.get(color)
        if basic_name is None or basic_name in basic_names_in_pool:
            continue

        basic_card = next(
            (
                card for card in all_cards
                if card.name == basic_name and card.is_basic_land
            ),
            None,
        )
        if basic_card is None:
            continue

        free_basics.append(
            DeckCard(
                oracle_id=basic_card.oracle_id,
                name=basic_card.name,
                is_owned=False,
                quantity=1,
                roles=[tag.role.value for tag in role_tags.get(basic_card.oracle_id, [])],
                color_identity=list(basic_card.color_identity),
                selection_reason="candidate",
            )
        )
        basic_names_in_pool.add(basic_name)

    return free_basics
