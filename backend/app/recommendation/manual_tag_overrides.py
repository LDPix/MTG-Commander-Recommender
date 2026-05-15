"""Manual tag override system.

Allows human curators to add, remove, or adjust confidence of role tags
on specific cards. Overrides are stored as JSON and take precedence over
rule-based tags.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.recommendation.role_taxonomy import CardRole, RoleTag


class ManualTagOverride:
    """A set of manual tag overrides for a specific card."""

    def __init__(
        self,
        card_name: str,
        add: list[str],
        remove: list[str],
        confidence_overrides: dict[str, float],
        source: str = "manual",
    ) -> None:
        self.card_name = card_name
        self.add: list[CardRole] = [CardRole(r) for r in add]
        self.remove: list[CardRole] = [CardRole(r) for r in remove]
        self.confidence_overrides: dict[CardRole, float] = {
            CardRole(k): v for k, v in confidence_overrides.items()
        }
        self.source = source

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ManualTagOverride":
        """Parse a ManualTagOverride from a dict (e.g. from JSON)."""
        return cls(
            card_name=data["card_name"],
            add=data.get("add", []),
            remove=data.get("remove", []),
            confidence_overrides=data.get("confidence_overrides", {}),
            source=data.get("source", "manual"),
        )


class ManualTagStore:
    """Loads and stores manual tag overrides from a JSON file.

    Override JSON format::

        [
          {
            "card_name": "Sol Ring",
            "add": ["RAMP"],
            "remove": [],
            "confidence_overrides": {"RAMP": 0.99},
            "source": "manual"
          }
        ]
    """

    def __init__(self, overrides: list[ManualTagOverride] | None = None) -> None:
        self._overrides: dict[str, ManualTagOverride] = {}
        if overrides:
            for override in overrides:
                self._overrides[override.card_name.lower()] = override

    @classmethod
    def from_file(cls, path: str | Path) -> "ManualTagStore":
        """Load manual overrides from a JSON file."""
        path = Path(path)
        with path.open("r", encoding="utf-8") as fh:
            raw: list[dict[str, Any]] = json.load(fh)
        overrides = [ManualTagOverride.from_dict(entry) for entry in raw]
        return cls(overrides)

    def get_override(self, card_name: str) -> ManualTagOverride | None:
        """Return the override for a card name, or None if none exists."""
        return self._overrides.get(card_name.lower())

    def has_override(self, card_name: str) -> bool:
        """Return True if a manual override exists for the given card name."""
        return card_name.lower() in self._overrides


def apply_overrides(
    tags: list[RoleTag],
    override: ManualTagOverride,
) -> list[RoleTag]:
    """Apply a ManualTagOverride to an existing list of role tags.

    The process:
    1. Remove roles listed in override.remove.
    2. Add roles listed in override.add (if not already present).
    3. Apply confidence overrides from override.confidence_overrides.

    The source of added/modified tags is set to "manual".
    Rule-based tags that are not modified retain their original source.

    Args:
        tags: Existing list of RoleTag objects (e.g. from RuleTagger).
        override: ManualTagOverride to apply.

    Returns:
        New list of RoleTag objects with overrides applied.
    """
    # Start from a mutable copy indexed by role
    result: dict[CardRole, RoleTag] = {t.role: t for t in tags}

    # Step 1 – remove
    for role in override.remove:
        result.pop(role, None)

    # Step 2 – add missing roles
    for role in override.add:
        if role not in result:
            confidence = override.confidence_overrides.get(role, 0.9)
            result[role] = RoleTag(role=role, confidence=confidence, source="manual")

    # Step 3 – apply confidence overrides (also sets source to "manual")
    for role, confidence in override.confidence_overrides.items():
        if role in result:
            result[role] = RoleTag(role=role, confidence=confidence, source="manual")

    return list(result.values())
