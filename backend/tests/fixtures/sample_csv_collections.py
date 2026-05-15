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
