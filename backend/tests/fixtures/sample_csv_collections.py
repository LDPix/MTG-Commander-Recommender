"""CSV fixture strings for collection import tests."""
from __future__ import annotations

# B/G collection supporting Meren of Clan Nel Toth as commander.
# Includes lands, ramp, card draw, and spot removal.
DECK_TEST_COLLECTION_CSV = """name,quantity
Sol Ring,1
Command Tower,1
Arcane Signet,1
Golgari Signet,1
Cultivate,1
Kodama's Reach,1
Rampant Growth,1
Nature's Lore,1
Farseek,1
Three Visits,1
Llanowar Elves,1
Elvish Mystic,1
Fyndhorn Elves,1
Mind Stone,1
Solemn Simulacrum,1
Phyrexian Arena,1
Night's Whisper,1
Read the Bones,1
Skullclamp,1
Forest,10
Swamp,10
Golgari Rot Farm,1
Overgrown Tomb,1
Woodland Cemetery,1
Llanowar Wastes,1
Bojuka Bog,1
Myriad Landscape,1
"""

VALID_COLLECTION_CSV = """name,quantity
Sol Ring,1
Command Tower,1
Swords to Plowshares,2
"""

MALFORMED_COLLECTION_CSV = """name,quantity
Sol Ring,1
,2
BadCard,abc
Cultivate,3
"""

VARIANT_HEADERS_CSV = """card_name,Count
Sol Ring,1
Command Tower,2
"""

ALT_QTY_HEADER_CSV = """Card Name,qty
Sol Ring,1
Command Tower,1
"""

WITH_OPTIONAL_COLS_CSV = """name,quantity,set_code,collector_number
Sol Ring,1,C21,175
Command Tower,1,C21,350
"""

EXTRA_COLUMNS_CSV = """name,quantity,foil,condition,price
Sol Ring,1,yes,NM,5.00
Command Tower,2,no,LP,0.50
"""

NEGATIVE_QUANTITY_CSV = """name,quantity
Sol Ring,-1
Command Tower,0
Cultivate,3
"""

# B/G collection supporting Greta, Sweettooth Scourge as commander (food-sacrifice plan).
GRETA_COLLECTION_CSV = """name,quantity
Sol Ring,1
Command Tower,1
Arcane Signet,1
Golgari Signet,1
Cultivate,1
Kodama's Reach,1
Rampant Growth,1
Nature's Lore,1
Farseek,1
Three Visits,1
Llanowar Elves,1
Elvish Mystic,1
Fyndhorn Elves,1
Mind Stone,1
Solemn Simulacrum,1
Phyrexian Arena,1
Night's Whisper,1
Read the Bones,1
Skullclamp,1
Blood Artist,1
Zulaport Cutthroat,1
Dictate of Erebos,1
Grave Pact,1
Bastion of Remembrance,1
Poison-Tip Archer,1
Skyclave Shadowcat,1
Vengeful Bloodwitch,1
Vindictive Vampire,1
Ashnod's Altar,1
Carrion Feeder,1
Viscera Seer,1
Altar of Dementia,1
Abrupt Decay,1
Assassin's Trophy,1
Beast Within,1
Doom Blade,1
Go for the Throat,1
Damnation,1
In Garruk's Wake,1
Heroic Intervention,1
Lightning Greaves,1
Swiftfoot Boots,1
Forest,10
Swamp,10
Golgari Rot Farm,1
Overgrown Tomb,1
Woodland Cemetery,1
Llanowar Wastes,1
Bojuka Bog,1
Myriad Landscape,1
"""
