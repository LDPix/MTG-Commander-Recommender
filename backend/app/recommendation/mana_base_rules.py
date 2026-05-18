"""SC-MANA-001/002/004: Mana base classification rules."""
from __future__ import annotations

from app.models.card import is_basic_land_type_line

# Minimum basic lands for a mono-color deck (configurable)
MONO_COLOR_BASIC_LAND_MIN: int = 20

# Minimum synergy required for a utility land without active package relevance.
UTILITY_LAND_MIN_SYNERGY_SCORE: float = 0.35

# Lands whose primary purpose is color diversification.
# Excluded from mono-color decks because they provide no functional value there.
KNOWN_FIXING_LAND_NAMES: frozenset[str] = frozenset({
    "Adarkar Wastes",
    "Battlefield Forge",
    "Brushland",
    "Caves of Koilos",
    "Llanowar Wastes",
    "Shivan Reef",
    "Sulfurous Springs",
    "Karplusan Forest",
    "Underground River",
    "Yavimaya Coast",
    "Command Tower",
    "Gemstone Mine",
    "Exotic Orchard",
    "Shimmerdrift Vale",
    "Temple of the Dragon Queen",
    "Riveteers Overlook",
    "Capital City",
    "Unclaimed Territory",
    "Spectator Seating",
    "Path of Ancestry",
    "Murmuring Bosk",
})

# Lands that produce ONLY {C} mana — useless in non-colorless decks.
C_ONLY_LAND_NAMES: frozenset[str] = frozenset({
    "Wastes",
    "Snow-Covered Wastes",
})

KNOWN_UTILITY_LAND_NAMES: frozenset[str] = frozenset({
    "White Lotus Hideout",
    "The Seedcore",
    "Eclipsed Realms",
    "Scavenger Grounds",
    "Mystifying Maze",
    "Reliquary Tower",
})

_COLOR_SYMBOLS: dict[str, str] = {
    "{W}": "W",
    "{U}": "U",
    "{B}": "B",
    "{R}": "R",
    "{G}": "G",
}


def is_mono_color(commander_color_identity: list[str]) -> bool:
    """Return True if the commander has exactly one color."""
    return len(commander_color_identity) == 1


def land_produces_off_color_mana(
    oracle_text: str | None,
    commander_color_identity: list[str],
) -> bool:
    """Return True when oracle text explicitly produces off-identity mana."""
    if not oracle_text:
        return False

    commander_colors = set(commander_color_identity)
    for symbol, color in _COLOR_SYMBOLS.items():
        if color not in commander_colors and symbol in oracle_text:
            return True
    return False


def is_fixing_land(
    card_name: str,
    oracle_text: str | None,
    commander_color_identity: list[str] | None = None,
) -> bool:
    """Return True if this land's primary purpose is color diversification.

    Used to exclude these from mono-color candidate pools.
    """
    if card_name in KNOWN_FIXING_LAND_NAMES:
        return True
    text = (oracle_text or "").lower()
    if "add one mana of any color" in text:
        return True
    if "add mana of any color" in text:
        return True
    if commander_color_identity is not None:
        if land_produces_off_color_mana(oracle_text, commander_color_identity):
            return True
    return False


def is_primary_fixing_land(
    card_name: str,
    oracle_text: str | None,
    type_line: str,
    commander_color_identity: list[str] | None = None,
) -> bool:
    """Return True for lands whose main deckbuilding job is color fixing."""
    if "Land" not in type_line or is_basic_land_type_line(type_line):
        return False
    if card_name in KNOWN_UTILITY_LAND_NAMES:
        return False
    if card_name in KNOWN_FIXING_LAND_NAMES:
        return True

    text = (oracle_text or "").lower()
    if not text:
        return False

    fixing_markers = (
        "commander's color identity",
        "add one mana of any color",
        "add mana of any color",
        "add one mana of any type",
        "mana of any one color",
        "mana of any color",
        "color of your choice",
        "chosen color",
        "chosen type",
    )
    if any(marker in text for marker in fixing_markers):
        return True

    # Fetch-style lands: the search text is mana-base fixing, not utility text.
    if "search your library" in text and "land card" in text:
        return True
    if "search your library" in text and any(
        land_type.lower() in text for land_type in ("Plains", "Island", "Swamp", "Mountain", "Forest")
    ):
        return True

    # Pain/check/filter/dual-style lands often spell out two or more colored symbols.
    produced_colors = {
        color for symbol, color in _COLOR_SYMBOLS.items() if symbol.lower() in text
    }
    if len(produced_colors) >= 2:
        return True

    if commander_color_identity is not None and len(commander_color_identity) > 1:
        commander_colors = set(commander_color_identity)
        on_identity_colors = produced_colors.intersection(commander_colors)
        if len(on_identity_colors) >= 2:
            return True

    return False


def is_c_only_land(card_name: str, oracle_text: str | None) -> bool:
    """Return True if this land produces only {C} (colorless) mana.

    These are excluded from non-colorless (colored) decks.
    """
    if card_name in C_ONLY_LAND_NAMES:
        return True
    return False


def commander_is_colorless(commander_color_identity: list[str]) -> bool:
    """Return True if the commander has no colors (colorless identity)."""
    return len(commander_color_identity) == 0


def is_utility_land(
    card_name: str,
    oracle_text: str | None,
    type_line: str,
) -> bool:
    """Return True for non-basic lands with non-mana strategic text."""
    if "Land" not in type_line or is_basic_land_type_line(type_line):
        return False

    if is_primary_fixing_land(card_name, oracle_text, type_line):
        return False

    if card_name in KNOWN_UTILITY_LAND_NAMES:
        return True

    text = (oracle_text or "").lower()
    if not text:
        return False

    utility_markers = (
        "you have no maximum hand size",
        "target",
        "exile",
        "destroy",
        "deals damage",
        "damage to",
        "draw",
        "create",
        "token",
        "counter",
        "graveyard",
        "gains",
        "gets +",
        "activate only",
        "spend this mana only",
        "choose a",
        "chosen type",
        "lifegain",
        "life",
        "daybound",
        "nightbound",
        "enchantment",
        "phyrexian",
        "compleated",
    )
    return any(marker in text for marker in utility_markers)


def utility_land_has_relevance(
    card_name: str,
    oracle_text: str | None,
    type_line: str,
    synergy_score: float,
    package_ids: list[str],
    active_package_ids: set[str],
) -> bool:
    """Return True when a utility land has enough deck relevance to keep."""
    if is_primary_fixing_land(card_name, oracle_text, type_line):
        return True

    if not is_utility_land(card_name, oracle_text, type_line):
        return True

    if synergy_score >= UTILITY_LAND_MIN_SYNERGY_SCORE:
        return True

    if set(package_ids).intersection(active_package_ids):
        return True

    return False
