"""Card role taxonomy for the MTG Commander Recommender.

Defines the CardRole enum, role descriptions, and example cards for each role.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class CardRole(str, Enum):
    """Functional roles a card can fulfil in a Commander deck."""

    LAND = "LAND"
    RAMP = "RAMP"
    MANA_FIXING = "MANA_FIXING"
    CARD_DRAW = "CARD_DRAW"
    CARD_SELECTION = "CARD_SELECTION"
    SPOT_REMOVAL = "SPOT_REMOVAL"
    BOARD_WIPE = "BOARD_WIPE"
    PROTECTION = "PROTECTION"
    TUTOR = "TUTOR"
    RECURSION = "RECURSION"
    SACRIFICE_OUTLET = "SACRIFICE_OUTLET"
    TOKEN_MAKER = "TOKEN_MAKER"
    PAYOFF = "PAYOFF"
    COMBO_PIECE = "COMBO_PIECE"
    TRIBAL_SUPPORT = "TRIBAL_SUPPORT"
    BLINK_SYNERGY = "BLINK_SYNERGY"
    LANDFALL_SYNERGY = "LANDFALL_SYNERGY"
    ARISTOCRATS_SYNERGY = "ARISTOCRATS_SYNERGY"
    SPELLSLINGER_SYNERGY = "SPELLSLINGER_SYNERGY"
    ENABLER = "ENABLER"
    TRIBAL_LORD = "TRIBAL_LORD"
    WIN_CONDITION = "WIN_CONDITION"
    LIFEGAIN = "LIFEGAIN"
    STAX = "STAX"
    COST_REDUCTION = "COST_REDUCTION"
    COPY_EFFECT = "COPY_EFFECT"
    GRAVEYARD_SYNERGY = "GRAVEYARD_SYNERGY"


ROLE_DEFINITIONS: dict[CardRole, str] = {
    CardRole.LAND: (
        "A land card. Provides the mana base for the deck. "
        "Basic lands may appear in multiple copies."
    ),
    CardRole.RAMP: (
        "Accelerates mana development. Includes mana rocks (Sol Ring, Signets), "
        "land-search spells (Cultivate, Kodama's Reach), and creatures that "
        "produce extra mana (Selvala, Heart of the Wilds)."
    ),
    CardRole.MANA_FIXING: (
        "Helps produce mana of colors needed by the deck. Includes dual lands, "
        "fetch lands, tri-color utility lands (Command Tower), and color-fixing "
        "artifacts or enchantments."
    ),
    CardRole.CARD_DRAW: (
        "Draws cards or generates card advantage. Includes cantrips, "
        "draw spells, wheels, and permanents with continuous draw triggers."
    ),
    CardRole.CARD_SELECTION: (
        "Filters the top of the library or improves draw quality without "
        "necessarily generating raw card advantage. Includes Scry, Surveil, "
        "and similar effects."
    ),
    CardRole.SPOT_REMOVAL: (
        "Removes a single threat: creature, artifact, enchantment, or "
        "planeswalker. Includes exile, destruction, bounce, and tuck effects."
    ),
    CardRole.BOARD_WIPE: (
        "Removes multiple threats simultaneously. Includes mass destruction, "
        "exile-all, and bounce-all effects that affect three or more permanents."
    ),
    CardRole.PROTECTION: (
        "Protects key permanents or the player from interaction. Includes "
        "hexproof, indestructible, shroud, counterspells, and equipment that "
        "grants protection."
    ),
    CardRole.TUTOR: (
        "Searches the library for one or more specific cards. Includes "
        "Demonic Tutor, Enlightened Tutor, Worldly Tutor, and similar effects."
    ),
    CardRole.RECURSION: (
        "Returns cards from the graveyard to the hand, battlefield, or library. "
        "Key for value engines and resilience."
    ),
    CardRole.SACRIFICE_OUTLET: (
        "Allows sacrificing creatures (or other permanents) as a cost or "
        "triggered ability. Essential for aristocrats and graveyard strategies."
    ),
    CardRole.TOKEN_MAKER: (
        "Creates one or more creature or artifact tokens. Fuels aristocrats, "
        "go-wide, and tribal strategies."
    ),
    CardRole.PAYOFF: (
        "A card that rewards executing the deck's strategy. Typically scores "
        "points, drains life, creates card advantage, or wins the game when "
        "the engine is running."
    ),
    CardRole.COMBO_PIECE: (
        "A card that is part of a two- or three-card combo that can win or "
        "generate overwhelming advantage when assembled."
    ),
    CardRole.TRIBAL_SUPPORT: (
        "Supports or benefits a specific creature tribe. Includes lords, "
        "tribal anthems, and cards that care about a creature type."
    ),
    CardRole.BLINK_SYNERGY: (
        "Benefits from being blinked (exiled and returned) or triggers "
        "strong enter-the-battlefield effects. Works well with Ephemerate, "
        "Conjurer's Closet, etc."
    ),
    CardRole.LANDFALL_SYNERGY: (
        "Triggers or benefits when a land enters the battlefield. "
        "Core to landfall and ramp-heavy strategies."
    ),
    CardRole.ARISTOCRATS_SYNERGY: (
        "Generates value when creatures die. Includes death triggers, "
        "drain effects, and cards that scale with creatures entering or "
        "leaving the battlefield."
    ),
    CardRole.SPELLSLINGER_SYNERGY: (
        "Triggers or benefits when instant or sorcery spells are cast. "
        "Core to spellslinger and izzet-style strategies."
    ),
    CardRole.ENABLER: (
        "A utility card that enables the deck's strategy without being a "
        "payoff itself. Includes discard outlets, looters, and self-mill effects."
    ),
    CardRole.TRIBAL_LORD: (
        "Grants a static buff (+1/+1 or similar) or ability to all creatures "
        "of a specific tribe. The marquee tribal support card."
    ),
    CardRole.WIN_CONDITION: (
        "A card whose presence on the battlefield or resolution can end the "
        "game if left unanswered. Includes combo finishers, large threats, "
        "and alt-win conditions."
    ),
    CardRole.LIFEGAIN: (
        "Gains life or rewards gaining life. Includes drain effects, "
        "lifegain payoffs, and cards that scale with life totals."
    ),
    CardRole.STAX: (
        "Restricts opponents' resources or actions. Includes tax effects, "
        "hatebears, symmetrical punishers, and resource-denial permanents."
    ),
    CardRole.COST_REDUCTION: (
        "Reduces the mana cost of spells or abilities. Includes cost reducers, "
        "affinity enablers, and cards that grant free casts."
    ),
    CardRole.COPY_EFFECT: (
        "Copies spells, abilities, or permanents. Includes forks, clones, "
        "and doubling effects."
    ),
    CardRole.GRAVEYARD_SYNERGY: (
        "Cares about or enables the graveyard. Includes self-mill, "
        "discard outlets, flashback payoffs, and cards that reward a "
        "stocked graveyard."
    ),
}

ROLE_EXAMPLES: dict[CardRole, list[str]] = {
    CardRole.LAND: [
        "Forest",
        "Island",
        "Command Tower",
        "Breeding Pool",
        "Stomping Ground",
    ],
    CardRole.RAMP: [
        "Sol Ring",
        "Arcane Signet",
        "Cultivate",
        "Kodama's Reach",
        "Rampant Growth",
        "Selvala, Heart of the Wilds",
    ],
    CardRole.MANA_FIXING: [
        "Command Tower",
        "Arcane Signet",
        "Chromatic Lantern",
        "Talisman of Dominance",
        "City of Brass",
    ],
    CardRole.CARD_DRAW: [
        "Skullclamp",
        "Rhystic Study",
        "Necropotence",
        "Phyrexian Arena",
        "Consecrated Sphinx",
        "Brainstorm",
    ],
    CardRole.CARD_SELECTION: [
        "Ponder",
        "Preordain",
        "Sensei's Divining Top",
        "Sylvan Library",
    ],
    CardRole.SPOT_REMOVAL: [
        "Swords to Plowshares",
        "Path to Exile",
        "Chaos Warp",
        "Abrupt Decay",
        "Reality Shift",
    ],
    CardRole.BOARD_WIPE: [
        "Wrath of God",
        "Damnation",
        "Cyclonic Rift",
        "Toxic Deluge",
        "Blasphemous Act",
    ],
    CardRole.PROTECTION: [
        "Lightning Greaves",
        "Swiftfoot Boots",
        "Counterspell",
        "Heroic Intervention",
        "Teferi's Protection",
    ],
    CardRole.TUTOR: [
        "Demonic Tutor",
        "Vampiric Tutor",
        "Enlightened Tutor",
        "Worldly Tutor",
        "Diabolic Intent",
    ],
    CardRole.RECURSION: [
        "Meren of Clan Nel Toth",
        "Eternal Witness",
        "Reanimate",
        "Animate Dead",
        "Living Death",
    ],
    CardRole.SACRIFICE_OUTLET: [
        "Ashnod's Altar",
        "Altar of Dementia",
        "Viscera Seer",
        "Cartel Aristocrat",
        "Goblin Bombardment",
    ],
    CardRole.TOKEN_MAKER: [
        "Avenger of Zendikar",
        "Tendershoot Dryad",
        "Rabble Rousing",
        "Young Pyromancer",
        "Mycoloth",
    ],
    CardRole.PAYOFF: [
        "Blood Artist",
        "Zulaport Cutthroat",
        "Dictate of Erebos",
        "Parallel Lives",
        "Purphoros, God of the Forge",
    ],
    CardRole.COMBO_PIECE: [
        "Dramatic Reversal",
        "Isochron Scepter",
        "Thassa's Oracle",
        "Demonic Consultation",
    ],
    CardRole.TRIBAL_SUPPORT: [
        "Kindred Discovery",
        "Coat of Arms",
        "Door of Destinies",
        "Shared Animosity",
    ],
    CardRole.BLINK_SYNERGY: [
        "Eternal Witness",
        "Reclamation Sage",
        "Solemn Simulacrum",
        "Acidic Slime",
        "Mulldrifter",
    ],
    CardRole.LANDFALL_SYNERGY: [
        "Avenger of Zendikar",
        "Lotus Cobra",
        "Rampaging Baloths",
        "Roil Elemental",
        "Tireless Tracker",
    ],
    CardRole.ARISTOCRATS_SYNERGY: [
        "Blood Artist",
        "Zulaport Cutthroat",
        "Yawgmoth, Thran Physician",
        "Bastion of Remembrance",
    ],
    CardRole.SPELLSLINGER_SYNERGY: [
        "Young Pyromancer",
        "Guttersnipe",
        "Talrand, Sky Summoner",
        "Murmuring Mystic",
    ],
    CardRole.ENABLER: [
        "Fauna Shaman",
        "Frantic Search",
        "Faithless Looting",
        "Entomb",
        "Buried Alive",
    ],
    CardRole.TRIBAL_LORD: [
        "Lord of the Undead",
        "Merfolk Mistbinder",
        "Elvish Archdruid",
        "Vampire Nocturnus",
        "Goblin King",
    ],
    CardRole.WIN_CONDITION: [
        "Craterhoof Behemoth",
        "Thassa's Oracle",
        "Exsanguinate",
        "Torment of Hailfire",
        "Aetherflux Reservoir",
    ],
    CardRole.LIFEGAIN: [
        "Aetherflux Reservoir",
        "Sanguine Bond",
        "Vito, Thorn of the Dusk Rose",
        "Oloro, Ageless Ascetic",
        "Soul Warden",
    ],
    CardRole.STAX: [
        "Rhystic Study",
        "Smothering Tithe",
        "Aura of Silence",
        "Thalia, Guardian of Thraben",
        "Archon of Emeria",
    ],
    CardRole.COST_REDUCTION: [
        "Urza, Lord High Artificer",
        "Goblin Electromancer",
        "Baral, Chief of Compliance",
        "Semblance Anvil",
        "Cloud Key",
    ],
    CardRole.COPY_EFFECT: [
        "Strionic Resonator",
        "Lithoform Engine",
        "Mirari",
        "Irenicus's Vile Duplication",
        "Phantasmal Image",
    ],
    CardRole.GRAVEYARD_SYNERGY: [
        "Faithless Looting",
        "Entomb",
        "Buried Alive",
        "Dredge",
        "Underrealm Lich",
    ],
}


@dataclass
class RoleTag:
    """A role tag assigned to a card with confidence and source information."""

    role: CardRole
    confidence: float  # 0.0 – 1.0
    source: Literal["rule_based", "manual", "external", "scryfall_tagger"]

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {self.confidence}"
            )
        if self.source not in ("rule_based", "manual", "external", "scryfall_tagger"):
            raise ValueError(
                f"source must be one of 'rule_based', 'manual', 'external', 'scryfall_tagger', got {self.source!r}"
            )
