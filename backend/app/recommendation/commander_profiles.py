"""Commander support tier profiles for SC-CMD-005.

Tier definitions:
  curated   — manual profile assumptions + golden regression coverage.
  profiled  — manual profile assumptions, no golden coverage yet.
  fallback  — any legal resolved commander not listed above.

Adding an entry here does not automatically add golden coverage.
Curated requires both a profile entry AND golden test coverage.
"""
from __future__ import annotations

from typing import Literal

SupportTier = Literal["curated", "profiled", "fallback"]

# Keyed by Scryfall oracle_id.
# Must be kept in sync with golden_expectations.json for curated entries.
COMMANDER_SUPPORT_TIERS: dict[str, SupportTier] = {
    # --- Curated (profile + golden regression) ---
    "4b2521bc-8f94-1a0b-c3d4-5e6f7a8b9c0d": "curated",   # Meren of Clan Nel Toth
    "aa000082-0000-4000-0000-000000000082": "curated",     # Atraxa, Praetors' Voice

    # --- Profiled (profile exists, golden pending) ---
    "aa000083-0000-4000-0000-000000000083": "profiled",    # Prossh, Skyraider of Kher
}


def get_support_tier(oracle_id: str) -> SupportTier:
    """Return the support tier for a commander. Defaults to 'fallback'."""
    return COMMANDER_SUPPORT_TIERS.get(oracle_id, "fallback")
