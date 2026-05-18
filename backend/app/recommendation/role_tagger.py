"""Rule-based card role tagger.

Assigns functional role tags to cards based on oracle text, type line,
keywords, and mana cost. Cards may receive multiple role tags.
"""
from __future__ import annotations

import re

from app.models.card import CardData
from app.recommendation.mana_base_rules import is_primary_fixing_land
from app.recommendation.role_taxonomy import CardRole, RoleTag


# ---------------------------------------------------------------------------
# Regex helpers compiled once at import time
# ---------------------------------------------------------------------------

# Mana symbols in oracle text, e.g. {G}, {U}, {W}, {R}, {B}, {C}, {W/U}, etc.
_MANA_SYMBOL_RE = re.compile(r"\{[WUBRGC/0-9XYZP]+\}")

# "add {X}" patterns – indicates mana production
_ADD_MANA_RE = re.compile(r"\badd\b.{0,60}\{[WUBRGCX/0-9]+\}", re.IGNORECASE | re.DOTALL)

# Draw cards patterns
_DRAW_CARD_RE = re.compile(
    r"draw (a|an|one|two|three|four|five|x|\d+) cards?",
    re.IGNORECASE,
)

# Destroy/exile target patterns for spot removal
_DESTROY_TARGET_RE = re.compile(
    r"destroy target\b",
    re.IGNORECASE,
)
_EXILE_TARGET_RE = re.compile(
    r"exile target\b",
    re.IGNORECASE,
)

# Board wipe patterns – affects "all" or "each" creatures / permanents
_BOARD_WIPE_RE = re.compile(
    r"(destroy all|exile all|destroy each|exile each|"
    r"each creature.*(?:deals|gets|is destroyed)|"
    r"all creatures.*(?:get|are|deal))",
    re.IGNORECASE | re.DOTALL,
)

# Search library (tutor)
_TUTOR_RE = re.compile(r"search your library\b", re.IGNORECASE)

# Recursion from graveyard
_RECURSION_RE = re.compile(
    r"return (target |a |an )?(creature|permanent|card).{0,40}(from|in) (your )?graveyard",
    re.IGNORECASE | re.DOTALL,
)

# Sacrifice outlet: "sacrifice a creature" or "sacrifice another creature" as a COST
_SACK_COST_RE = re.compile(
    r"sacrifice (a|an|another|target) (creature|permanent)\b.*?:",
    re.IGNORECASE | re.DOTALL,
)
# Sacrifice outlet: sacrifice as an activated ability effect
_SACK_EFFECT_RE = re.compile(
    r"(as an additional cost|as part of its cost)[^.]*sacrifice",
    re.IGNORECASE,
)

# Token creation
_TOKEN_MAKER_RE = re.compile(
    r"create(s)? (a|an|one|two|three|four|five|\d+|x) .{0,40}token",
    re.IGNORECASE,
)

# Protection keywords in oracle text
_PROTECTION_ORACLE_RE = re.compile(
    r"\b(hexproof|indestructible|shroud)\b",
    re.IGNORECASE,
)
# Grants hexproof/shroud/indestructible to other permanents
_PROTECTION_GRANT_RE = re.compile(
    r"(gains?|have|has|get) (hexproof|indestructible|shroud)",
    re.IGNORECASE,
)

# Basic land type keywords in type line
_BASIC_LAND_TYPES = frozenset({"Plains", "Island", "Swamp", "Mountain", "Forest"})


class HybridTagger:
    """Combines RuleTagger with an optional ScryfallTaggerStore.

    Falls back to rule-based only when no store is provided or the store
    has no entry for the card's oracle_id.
    """

    def __init__(self, scryfall_store=None) -> None:
        self._rule_tagger = RuleTagger()
        self._store = scryfall_store  # ScryfallTaggerStore | None

    def tag(self, card: "CardData") -> "list[RoleTag]":
        rule_tags = self._rule_tagger.tag(card)
        if self._store is None:
            return rule_tags
        scryfall_tags = self._store.get_roles(card.oracle_id)
        if not scryfall_tags:
            return rule_tags
        merged = {t.role: t for t in rule_tags}
        for t in scryfall_tags:
            if t.role not in merged or t.confidence > merged[t.role].confidence:
                merged[t.role] = t
        return list(merged.values())


class RuleTagger:
    """Assigns role tags to cards using rule-based heuristics.

    Rules are applied to oracle_text, type_line, keywords, and cmc.
    Cards may receive multiple tags. For MDFCs, both faces are considered.
    """

    def tag(self, card: CardData) -> list[RoleTag]:
        """Assign role tags to a card.

        Args:
            card: CardData instance to tag.

        Returns:
            List of RoleTag objects. May be empty if no rules match.
        """
        tags: list[RoleTag] = []

        # Collect text and type info across all faces
        combined_oracle = card.get_all_oracle_text().strip()
        all_type_lines = card.get_all_type_lines()
        primary_type_line = card.type_line

        # ----------------------------------------------------------------
        # LAND
        # ----------------------------------------------------------------
        if any("Land" in tl for tl in all_type_lines):
            tags.append(RoleTag(role=CardRole.LAND, confidence=1.0, source="rule_based"))

            # MANA_FIXING: non-basic lands that add multiple colors
            # or specifically note "commander's color identity"
            if not card.is_basic_land:
                if (
                    is_primary_fixing_land(card.name, combined_oracle, primary_type_line)
                    or "commander's color identity" in combined_oracle.lower()
                    or "any color" in combined_oracle.lower()
                    or "mana of any" in combined_oracle.lower()
                    or "color of your choice" in combined_oracle.lower()
                ):
                    tags.append(
                        RoleTag(role=CardRole.MANA_FIXING, confidence=0.95, source="rule_based")
                    )

        # ----------------------------------------------------------------
        # RAMP – non-land cards that produce extra mana or fetch lands
        # ----------------------------------------------------------------
        is_land = any("Land" in tl for tl in all_type_lines)

        if not is_land:
            # Mana rocks / dorks: oracle text has "add {" mana symbol
            if _ADD_MANA_RE.search(combined_oracle):
                # Avoid tagging things that only add mana as a land would
                tags.append(
                    RoleTag(role=CardRole.RAMP, confidence=0.85, source="rule_based")
                )

            # Land-search spells: "search your library for...land"
            if _TUTOR_RE.search(combined_oracle):
                if re.search(r"search your library.{0,80}land", combined_oracle, re.IGNORECASE | re.DOTALL):
                    tags.append(
                        RoleTag(role=CardRole.RAMP, confidence=0.9, source="rule_based")
                    )

        # ----------------------------------------------------------------
        # CARD_DRAW
        # ----------------------------------------------------------------
        if _DRAW_CARD_RE.search(combined_oracle):
            tags.append(
                RoleTag(role=CardRole.CARD_DRAW, confidence=0.9, source="rule_based")
            )

        # ----------------------------------------------------------------
        # SPOT_REMOVAL
        # ----------------------------------------------------------------
        # Must target a specific permanent (creature, artifact, enchantment, etc.)
        # and destroy or exile it
        _removal_types = re.compile(
            r"target (creature|artifact|enchantment|permanent|planeswalker|"
            r"nonland permanent|nonbasic land)",
            re.IGNORECASE,
        )
        if (_DESTROY_TARGET_RE.search(combined_oracle) or _EXILE_TARGET_RE.search(combined_oracle)):
            if _removal_types.search(combined_oracle):
                # Don't double-tag as removal if it's clearly a board wipe
                if not _BOARD_WIPE_RE.search(combined_oracle):
                    tags.append(
                        RoleTag(role=CardRole.SPOT_REMOVAL, confidence=0.9, source="rule_based")
                    )

        # ----------------------------------------------------------------
        # BOARD_WIPE
        # ----------------------------------------------------------------
        if _BOARD_WIPE_RE.search(combined_oracle):
            tags.append(
                RoleTag(role=CardRole.BOARD_WIPE, confidence=0.85, source="rule_based")
            )

        # ----------------------------------------------------------------
        # TUTOR (non-land search)
        # ----------------------------------------------------------------
        if _TUTOR_RE.search(combined_oracle):
            # If it fetches non-land cards, it's a tutor
            # If it only fetches lands and is non-land, we already tagged RAMP
            if not re.search(
                r"search your library.{0,80}basic land", combined_oracle, re.IGNORECASE | re.DOTALL
            ):
                tags.append(
                    RoleTag(role=CardRole.TUTOR, confidence=0.85, source="rule_based")
                )

        # ----------------------------------------------------------------
        # RECURSION
        # ----------------------------------------------------------------
        if _RECURSION_RE.search(combined_oracle):
            tags.append(
                RoleTag(role=CardRole.RECURSION, confidence=0.85, source="rule_based")
            )

        # ----------------------------------------------------------------
        # SACRIFICE_OUTLET
        # ----------------------------------------------------------------
        if _SACK_COST_RE.search(combined_oracle) or _SACK_EFFECT_RE.search(combined_oracle):
            tags.append(
                RoleTag(role=CardRole.SACRIFICE_OUTLET, confidence=0.8, source="rule_based")
            )

        # ----------------------------------------------------------------
        # TOKEN_MAKER
        # ----------------------------------------------------------------
        if _TOKEN_MAKER_RE.search(combined_oracle):
            tags.append(
                RoleTag(role=CardRole.TOKEN_MAKER, confidence=0.85, source="rule_based")
            )

        # ----------------------------------------------------------------
        # PROTECTION – equipment or permanent that grants hexproof/indestructible/shroud
        # ----------------------------------------------------------------
        if _PROTECTION_GRANT_RE.search(combined_oracle) or (
            "Artifact — Equipment" in primary_type_line
            and _PROTECTION_ORACLE_RE.search(combined_oracle)
        ):
            tags.append(
                RoleTag(role=CardRole.PROTECTION, confidence=0.85, source="rule_based")
            )

        # Deduplicate by role (keep highest confidence)
        tags = _deduplicate_tags(tags)

        return tags


def _deduplicate_tags(tags: list[RoleTag]) -> list[RoleTag]:
    """Keep the highest-confidence tag per role."""
    best: dict[CardRole, RoleTag] = {}
    for tag in tags:
        existing = best.get(tag.role)
        if existing is None or tag.confidence > existing.confidence:
            best[tag.role] = tag
    return list(best.values())
