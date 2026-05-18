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

GRETA_REAL_ORACLE_ID = "00173df7-a584-410c-af1d-ada9c791056a"
TOLUZ_REAL_ORACLE_ID = "005c181a-05db-4c15-9893-65103cca338e"
GRETA_FIXTURE_ORACLE_ID = "greta-sweettooth-001"
TOLUZ_FIXTURE_ORACLE_ID = "toluz-clever-conductor-001"

_GRETA_PROFILE_IDS = (GRETA_REAL_ORACLE_ID, GRETA_FIXTURE_ORACLE_ID)
_TOLUZ_PROFILE_IDS = (TOLUZ_REAL_ORACLE_ID, TOLUZ_FIXTURE_ORACLE_ID)

_GRETA_POSITIVE_EVIDENCE = (
    "food", "sacrifice", "you gain", "life", "dies", "graveyard",
)
_TOLUZ_POSITIVE_EVIDENCE = (
    "connive", "discard", "draw a card, then discard", "graveyard",
)
_GRETA_NEGATIVE_EVIDENCE = (
    "treasure",  # Treasure producers are off-plan for food-sacrifice Greta
)
_TOLUZ_NEGATIVE_EVIDENCE = (
    "landfall",  # Landfall cards don't support connive
)

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


# Per-commander plan overrides: force a specific plan regardless of oracle-text inference.
# Use these for fallback commanders where generic inference misfires.
COMMANDER_PLAN_OVERRIDES: dict[str, str] = {
    **{oracle_id: "food-sacrifice" for oracle_id in _GRETA_PROFILE_IDS},
    **{oracle_id: "connive" for oracle_id in _TOLUZ_PROFILE_IDS},
}

# Positive text signals per commander oracle_id.
# Any card whose oracle text matches ANY signal is counted as on-plan.
COMMANDER_PLAN_POSITIVE_EVIDENCE: dict[str, tuple[str, ...]] = {
    **{oracle_id: _GRETA_POSITIVE_EVIDENCE for oracle_id in _GRETA_PROFILE_IDS},
    **{oracle_id: _TOLUZ_POSITIVE_EVIDENCE for oracle_id in _TOLUZ_PROFILE_IDS},
}

# Negative text signals per commander oracle_id.
# Any card whose oracle text matches ANY signal is flagged as off-plan.
# Applied BEFORE positive evidence check.
COMMANDER_PLAN_NEGATIVE_EVIDENCE: dict[str, tuple[str, ...]] = {
    **{oracle_id: _GRETA_NEGATIVE_EVIDENCE for oracle_id in _GRETA_PROFILE_IDS},
    **{oracle_id: _TOLUZ_NEGATIVE_EVIDENCE for oracle_id in _TOLUZ_PROFILE_IDS},
}

COMMANDER_NAME_PLAN_FALLBACKS: dict[str, str] = {
    "greta, sweettooth scourge": "food-sacrifice",
    "toluz, clever conductor": "connive",
}


def get_commander_plan_override(
    oracle_id: str,
    commander_name: str | None = None,
) -> str | None:
    """Return a forced plan name for this commander, or None to use inference."""
    override = COMMANDER_PLAN_OVERRIDES.get(oracle_id)
    if override is not None:
        return override
    if commander_name is None:
        return None
    return COMMANDER_NAME_PLAN_FALLBACKS.get(_normalize_name(commander_name))


def get_commander_profile_source(
    oracle_id: str,
    commander_name: str | None = None,
) -> str:
    """Return how commander profile data was resolved for diagnostics."""
    if oracle_id in COMMANDER_PLAN_OVERRIDES:
        return "oracle_id"
    if (
        commander_name is not None
        and _normalize_name(commander_name) in COMMANDER_NAME_PLAN_FALLBACKS
    ):
        return "name_fallback"
    return "none"


def get_commander_positive_evidence(oracle_id: str) -> tuple[str, ...]:
    """Return text signals that indicate a card is on-plan for this commander."""
    return COMMANDER_PLAN_POSITIVE_EVIDENCE.get(oracle_id, ())


def get_commander_negative_evidence(oracle_id: str) -> tuple[str, ...]:
    """Return text signals that indicate a card is off-plan for this commander."""
    return COMMANDER_PLAN_NEGATIVE_EVIDENCE.get(oracle_id, ())


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())
