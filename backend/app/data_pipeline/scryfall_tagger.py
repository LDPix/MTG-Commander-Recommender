"""Scryfall Tagger integration.

Loads the oracle_id → [tag_names] JSON produced by
scripts/fetch_scryfall_tags.py and converts ORACLE_CARD_TAG values
into internal RoleTag objects to supplement the rule-based tagger.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.recommendation.role_taxonomy import CardRole, RoleTag

# ---------------------------------------------------------------------------
# Tag → (CardRole, confidence) mapping
# Only ORACLE_CARD_TAG values with a clear role mapping are listed.
# ---------------------------------------------------------------------------
_TAG_TO_ROLES: dict[str, list[tuple[CardRole, float]]] = {
    # RAMP
    "mana rock": [(CardRole.RAMP, 0.95)],
    "mana dork": [(CardRole.RAMP, 0.9)],
    "fast mana": [(CardRole.RAMP, 0.95)],
    "land ramp": [(CardRole.RAMP, 0.9)],
    "adds multiple mana": [(CardRole.RAMP, 0.85)],
    "ritual": [(CardRole.RAMP, 0.75)],
    "treasure maker": [(CardRole.RAMP, 0.7)],
    "tutor-land-to-battlefield": [(CardRole.RAMP, 0.9)],
    "tutor-land-basic": [(CardRole.RAMP, 0.85)],
    "mana battery": [(CardRole.RAMP, 0.8)],
    "ramp": [(CardRole.RAMP, 0.8)],
    "repeatable treasures": [(CardRole.RAMP, 0.8)],
    "multi land ramp": [(CardRole.RAMP, 0.9)],
    # CARD_DRAW
    "draw engine": [(CardRole.CARD_DRAW, 0.95)],
    "repeatable pure draw": [(CardRole.CARD_DRAW, 0.95)],
    "wheel": [(CardRole.CARD_DRAW, 0.85)],
    "cantrip": [(CardRole.CARD_DRAW, 0.75)],
    "impulse draw": [(CardRole.CARD_DRAW, 0.8)],
    "card advantage": [(CardRole.CARD_DRAW, 0.75)],
    "draw spell": [(CardRole.CARD_DRAW, 0.85)],
    "pure draw": [(CardRole.CARD_DRAW, 0.9)],
    "burst draw": [(CardRole.CARD_DRAW, 0.85)],
    "repeatable impulsive draw": [(CardRole.CARD_DRAW, 0.85)],
    "life for cards": [(CardRole.CARD_DRAW, 0.8)],
    "curiosity": [(CardRole.CARD_DRAW, 0.8)],
    # CARD_SELECTION
    "top-deck manipulation": [(CardRole.CARD_SELECTION, 0.8)],
    "looting": [(CardRole.CARD_SELECTION, 0.75)],
    "rummaging": [(CardRole.CARD_SELECTION, 0.75)],
    "loot": [(CardRole.CARD_SELECTION, 0.8)],
    "repeatable loot": [(CardRole.CARD_SELECTION, 0.85)],
    "rummage": [(CardRole.CARD_SELECTION, 0.75)],
    "repeatable rummage": [(CardRole.CARD_SELECTION, 0.8)],
    "scry": [(CardRole.CARD_SELECTION, 0.75)],
    "surveil": [(CardRole.CARD_SELECTION, 0.8)],
    # SPOT_REMOVAL
    "spot removal": [(CardRole.SPOT_REMOVAL, 0.95)],
    "unconditional removal": [(CardRole.SPOT_REMOVAL, 0.95)],
    "exile removal": [(CardRole.SPOT_REMOVAL, 0.9)],
    "kill spell": [(CardRole.SPOT_REMOVAL, 0.9)],
    "removal": [(CardRole.SPOT_REMOVAL, 0.8)],
    "bounce": [(CardRole.SPOT_REMOVAL, 0.65)],
    "removal-creature": [(CardRole.SPOT_REMOVAL, 0.9)],
    "removal-exile": [(CardRole.SPOT_REMOVAL, 0.9)],
    "removal-destroy": [(CardRole.SPOT_REMOVAL, 0.85)],
    "removal-toughness": [(CardRole.SPOT_REMOVAL, 0.8)],
    "removal-nonland": [(CardRole.SPOT_REMOVAL, 0.85)],
    "removal-artifact": [(CardRole.SPOT_REMOVAL, 0.9)],
    "removal-enchantment": [(CardRole.SPOT_REMOVAL, 0.9)],
    "removal-land": [(CardRole.SPOT_REMOVAL, 0.85)],
    "removal-planeswalker": [(CardRole.SPOT_REMOVAL, 0.9)],
    "removal-sacrifice": [(CardRole.SPOT_REMOVAL, 0.85)],
    "removal-bounce": [(CardRole.SPOT_REMOVAL, 0.75)],
    "removal-fight": [(CardRole.SPOT_REMOVAL, 0.75)],
    "repeatable removal": [(CardRole.SPOT_REMOVAL, 0.95)],
    "multi removal": [(CardRole.SPOT_REMOVAL, 0.85)],
    "one-sided fight": [(CardRole.SPOT_REMOVAL, 0.75)],
    "disenchant/naturalize": [(CardRole.SPOT_REMOVAL, 0.9)],
    # BOARD_WIPE
    "board wipe": [(CardRole.BOARD_WIPE, 0.95)],
    "wrath": [(CardRole.BOARD_WIPE, 0.95)],
    "mass removal": [(CardRole.BOARD_WIPE, 0.95)],
    "asymmetric wrath": [(CardRole.BOARD_WIPE, 0.9)],
    "semi-wrath": [(CardRole.BOARD_WIPE, 0.8)],
    "sweeper": [(CardRole.BOARD_WIPE, 0.9)],
    "sweeper-one-sided": [(CardRole.BOARD_WIPE, 0.95)],
    # TUTOR
    "tutor": [(CardRole.TUTOR, 0.9)],
    "tutor-to-hand": [(CardRole.TUTOR, 0.9)],
    "tutor-to-battlefield": [(CardRole.TUTOR, 0.85)],
    "tutor-top-of-library": [(CardRole.TUTOR, 0.8)],
    "tutor-card": [(CardRole.TUTOR, 0.85)],
    "tutor-creature": [(CardRole.TUTOR, 0.85)],
    # RECURSION
    "reanimation": [(CardRole.RECURSION, 0.95)],
    "recursion": [(CardRole.RECURSION, 0.9)],
    "mass reanimation": [(CardRole.RECURSION, 0.9)],
    "regrowth": [(CardRole.RECURSION, 0.85)],
    "graveyard recursion": [(CardRole.RECURSION, 0.9)],
    "reanimate-creature": [(CardRole.RECURSION, 0.95)],
    "reanimate-self": [(CardRole.RECURSION, 0.85)],
    "reanimate-cast": [(CardRole.RECURSION, 0.9)],
    "reanimate-permanent": [(CardRole.RECURSION, 0.9)],
    "reanimate-from-any": [(CardRole.RECURSION, 0.95)],
    "reanimate-artifact": [(CardRole.RECURSION, 0.85)],
    "reanimate-land": [(CardRole.RECURSION, 0.8)],
    "regrowth-creature": [(CardRole.RECURSION, 0.9)],
    "regrowth-self": [(CardRole.RECURSION, 0.85)],
    # SACRIFICE_OUTLET
    "sacrifice outlet": [(CardRole.SACRIFICE_OUTLET, 0.95)],
    "free sacrifice outlet": [(CardRole.SACRIFICE_OUTLET, 1.0)],
    "paid sacrifice outlet": [(CardRole.SACRIFICE_OUTLET, 0.85)],
    "sacrifice outlet-creature": [(CardRole.SACRIFICE_OUTLET, 0.9)],
    "sacrifice outlet-artifact": [(CardRole.SACRIFICE_OUTLET, 0.85)],
    "sacrifice outlet-land": [(CardRole.SACRIFICE_OUTLET, 0.8)],
    "repeatable sacrifice outlet": [(CardRole.SACRIFICE_OUTLET, 0.95)],
    # TOKEN_MAKER
    "token maker": [(CardRole.TOKEN_MAKER, 0.9)],
    "token generator": [(CardRole.TOKEN_MAKER, 0.9)],
    "goes wide": [(CardRole.TOKEN_MAKER, 0.8)],
    "repeatable creature tokens": [(CardRole.TOKEN_MAKER, 0.95)],
    "repeatable artifact tokens": [(CardRole.TOKEN_MAKER, 0.85)],
    "create token": [(CardRole.TOKEN_MAKER, 0.8)],
    # PROTECTION
    "counterspell": [(CardRole.PROTECTION, 0.9)],
    "free counterspell": [(CardRole.PROTECTION, 0.95)],
    "hard counter": [(CardRole.PROTECTION, 0.9)],
    "stifle": [(CardRole.PROTECTION, 0.7)],
    "counterspell-soft": [(CardRole.PROTECTION, 0.75)],
    "gives hexproof": [(CardRole.PROTECTION, 0.85)],
    "gives indestructible": [(CardRole.PROTECTION, 0.85)],
    # COMBO_PIECE / WIN_CONDITION
    "combo piece": [(CardRole.COMBO_PIECE, 0.9)],
    "infinite combo piece": [(CardRole.COMBO_PIECE, 0.95)],
    "win condition": [(CardRole.WIN_CONDITION, 0.9)],
    "wincon": [(CardRole.WIN_CONDITION, 0.9)],
    "alternate win condition": [(CardRole.WIN_CONDITION, 0.95)],
    # MANA_FIXING
    "mana fixing": [(CardRole.MANA_FIXING, 0.9)],
    "color fixing": [(CardRole.MANA_FIXING, 0.9)],
    "fetch land": [(CardRole.MANA_FIXING, 0.95)],
    "rainbow land": [(CardRole.MANA_FIXING, 0.9)],
    "utility mana rock": [(CardRole.MANA_FIXING, 0.8)],
    # ARISTOCRATS_SYNERGY
    "aristocrats payoff": [(CardRole.ARISTOCRATS_SYNERGY, 0.9)],
    "blood artist ability": [(CardRole.ARISTOCRATS_SYNERGY, 0.9)],
    "death trigger": [(CardRole.ARISTOCRATS_SYNERGY, 0.8)],
    "on-death trigger": [(CardRole.ARISTOCRATS_SYNERGY, 0.85)],
    "death payoff": [(CardRole.ARISTOCRATS_SYNERGY, 0.8)],
    "enters-the-battlefield trigger-other": [(CardRole.ARISTOCRATS_SYNERGY, 0.7)],
    # LANDFALL_SYNERGY
    "landfall": [(CardRole.LANDFALL_SYNERGY, 0.9)],
    "land payoff": [(CardRole.LANDFALL_SYNERGY, 0.8)],
    # BLINK_SYNERGY
    "flicker": [(CardRole.BLINK_SYNERGY, 0.9)],
    "blink": [(CardRole.BLINK_SYNERGY, 0.9)],
    "etb abuse": [(CardRole.BLINK_SYNERGY, 0.8)],
    "flicker-creature": [(CardRole.BLINK_SYNERGY, 0.9)],
    "flicker-slow": [(CardRole.BLINK_SYNERGY, 0.8)],
    "flicker-self": [(CardRole.BLINK_SYNERGY, 0.75)],
    "flicker-permanent": [(CardRole.BLINK_SYNERGY, 0.85)],
    "flicker-artifact": [(CardRole.BLINK_SYNERGY, 0.8)],
    "flicker-nonland": [(CardRole.BLINK_SYNERGY, 0.85)],
    # SPELLSLINGER_SYNERGY
    "spellslinger": [(CardRole.SPELLSLINGER_SYNERGY, 0.9)],
    "storm": [(CardRole.SPELLSLINGER_SYNERGY, 0.8)],
    "prowess payoff": [(CardRole.SPELLSLINGER_SYNERGY, 0.75)],
    # TRIBAL
    "lord": [(CardRole.TRIBAL_LORD, 0.9)],
    "tribal lord": [(CardRole.TRIBAL_LORD, 0.95)],
    "tribal support": [(CardRole.TRIBAL_SUPPORT, 0.9)],
    # LIFEGAIN
    "lifegain": [(CardRole.LIFEGAIN, 0.9)],
    "life gain": [(CardRole.LIFEGAIN, 0.85)],
    "life drain": [(CardRole.LIFEGAIN, 0.85)],
    "drain": [(CardRole.LIFEGAIN, 0.8)],
    "lifegain payoff": [(CardRole.LIFEGAIN, 0.9)],
    "lifegain trigger": [(CardRole.LIFEGAIN, 0.85)],
    "lifelink": [(CardRole.LIFEGAIN, 0.7)],
    # STAX
    "stax": [(CardRole.STAX, 0.95)],
    "tax": [(CardRole.STAX, 0.85)],
    "hatebear": [(CardRole.STAX, 0.9)],
    "resource denial": [(CardRole.STAX, 0.9)],
    "group slug": [(CardRole.STAX, 0.8)],
    "symmetrical damage": [(CardRole.STAX, 0.75)],
    "symmetrical discard": [(CardRole.STAX, 0.75)],
    # COST_REDUCTION
    "cost reduction": [(CardRole.COST_REDUCTION, 0.9)],
    "cost reducer": [(CardRole.COST_REDUCTION, 0.9)],
    "affinity": [(CardRole.COST_REDUCTION, 0.85)],
    "alternate cost": [(CardRole.COST_REDUCTION, 0.8)],
    "free spells": [(CardRole.COST_REDUCTION, 0.85)],
    # COPY_EFFECT
    "copy spell": [(CardRole.COPY_EFFECT, 0.9)],
    "fork": [(CardRole.COPY_EFFECT, 0.9)],
    "copy permanent": [(CardRole.COPY_EFFECT, 0.85)],
    "clone": [(CardRole.COPY_EFFECT, 0.85)],
    "copy creature": [(CardRole.COPY_EFFECT, 0.85)],
    "doubling": [(CardRole.COPY_EFFECT, 0.8)],
    # GRAVEYARD_SYNERGY
    "graveyard matters": [(CardRole.GRAVEYARD_SYNERGY, 0.9)],
    "graveyard payoff": [(CardRole.GRAVEYARD_SYNERGY, 0.9)],
    "self-mill": [(CardRole.GRAVEYARD_SYNERGY, 0.85)],
    "mill-self": [(CardRole.GRAVEYARD_SYNERGY, 0.85)],
    "discard outlet": [(CardRole.GRAVEYARD_SYNERGY, 0.75)],
    "delve": [(CardRole.GRAVEYARD_SYNERGY, 0.8)],
    "flashback": [(CardRole.GRAVEYARD_SYNERGY, 0.75)],
    "threshold": [(CardRole.GRAVEYARD_SYNERGY, 0.75)],
    "escape": [(CardRole.GRAVEYARD_SYNERGY, 0.75)],
}


_scryfall_tagger_store: "ScryfallTaggerStore | None" = None


def get_scryfall_tagger_store() -> "ScryfallTaggerStore | None":
    return _scryfall_tagger_store


def set_scryfall_tagger_store(store: "ScryfallTaggerStore") -> None:
    global _scryfall_tagger_store
    _scryfall_tagger_store = store


class ScryfallTaggerStore:
    """In-memory store of Scryfall Tagger ORACLE_CARD_TAG data.

    Provides get_roles(oracle_id) which maps community tags to RoleTag objects
    with source="scryfall_tagger".
    """

    def __init__(self, data: dict[str, list[str]]) -> None:
        self._data = data

    @classmethod
    def from_file(cls, path: str | Path) -> "ScryfallTaggerStore":
        path = Path(path)
        with path.open() as f:
            data: dict[str, list[str]] = json.load(f)
        return cls(data)

    def get_roles(self, oracle_id: str) -> list[RoleTag]:
        """Return role tags derived from community tags for an oracle_id."""
        raw_tags = self._data.get(oracle_id, [])
        role_tags: list[RoleTag] = []
        for tag_name in raw_tags:
            for role, confidence in _TAG_TO_ROLES.get(tag_name, []):
                role_tags.append(RoleTag(role=role, confidence=confidence, source="scryfall_tagger"))
        return role_tags

    def __len__(self) -> int:
        return len(self._data)
