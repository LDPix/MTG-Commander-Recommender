"""Tests for SC-DATA-003: Role tag taxonomy."""
from __future__ import annotations

import pytest

from app.recommendation.package_density import COMPOSITION_OUTCOME_ROLES
from app.recommendation.role_taxonomy import (
    ROLE_DEFINITIONS,
    ROLE_EXAMPLES,
    CardRole,
    RoleTag,
)

# Roles that MUST exist per requirements
REQUIRED_ROLES = {
    CardRole.LAND,
    CardRole.RAMP,
    CardRole.CARD_DRAW,
    CardRole.SPOT_REMOVAL,
    CardRole.BOARD_WIPE,
    CardRole.PROTECTION,
    CardRole.TUTOR,
    CardRole.RECURSION,
    CardRole.SACRIFICE_OUTLET,
    CardRole.TOKEN_MAKER,
    CardRole.WIN_CONDITION,
}


def test_role_taxonomy_loads() -> None:
    """The CardRole enum loads with at least the required roles."""
    roles = set(CardRole)
    assert len(roles) > 0


def test_required_roles_exist() -> None:
    """All required roles are present in the CardRole enum."""
    actual_roles = {role for role in CardRole}
    for role in REQUIRED_ROLES:
        assert role in actual_roles, f"Required role {role!r} is missing from CardRole"


def test_role_has_description() -> None:
    """Every CardRole has a non-empty description in ROLE_DEFINITIONS."""
    for role in CardRole:
        assert role in ROLE_DEFINITIONS, f"Role {role!r} has no entry in ROLE_DEFINITIONS"
        description = ROLE_DEFINITIONS[role]
        assert isinstance(description, str)
        assert len(description.strip()) > 0, f"Role {role!r} has an empty description"


def test_role_has_examples() -> None:
    """Every CardRole has at least one example card in ROLE_EXAMPLES."""
    for role in CardRole:
        assert role in ROLE_EXAMPLES, f"Role {role!r} has no entry in ROLE_EXAMPLES"
        examples = ROLE_EXAMPLES[role]
        assert isinstance(examples, list)
        assert len(examples) > 0, f"Role {role!r} has no example cards"


def test_unknown_role_rejected() -> None:
    """Constructing a CardRole from an invalid string raises a ValueError."""
    with pytest.raises(ValueError):
        CardRole("NOT_A_REAL_ROLE")


# ---------------------------------------------------------------------------
# RoleTag dataclass validation
# ---------------------------------------------------------------------------

def test_role_tag_valid_construction() -> None:
    """A RoleTag with valid fields constructs without error."""
    tag = RoleTag(role=CardRole.RAMP, confidence=0.9, source="rule_based")
    assert tag.role == CardRole.RAMP
    assert tag.confidence == 0.9
    assert tag.source == "rule_based"


def test_role_tag_confidence_must_be_0_to_1() -> None:
    """RoleTag raises ValueError for confidence outside [0.0, 1.0]."""
    with pytest.raises(ValueError):
        RoleTag(role=CardRole.RAMP, confidence=1.5, source="rule_based")

    with pytest.raises(ValueError):
        RoleTag(role=CardRole.RAMP, confidence=-0.1, source="rule_based")


def test_role_tag_source_must_be_valid() -> None:
    """RoleTag raises ValueError for an unrecognised source string."""
    with pytest.raises(ValueError):
        RoleTag(role=CardRole.RAMP, confidence=0.9, source="unknown_source")  # type: ignore[arg-type]


def test_role_tag_all_valid_sources() -> None:
    """All three valid sources construct without error."""
    for source in ("rule_based", "manual", "external"):
        tag = RoleTag(role=CardRole.LAND, confidence=1.0, source=source)  # type: ignore[arg-type]
        assert tag.source == source


# ---------------------------------------------------------------------------
# SC-TAG-003: PAYOFF role removal
# ---------------------------------------------------------------------------

def test_payoff_role_does_not_exist_in_enum() -> None:
    """SC-TAG-003: CardRole.PAYOFF must not exist after cleanup."""
    assert not hasattr(CardRole, "PAYOFF")
    assert "PAYOFF" not in [r.value for r in CardRole]


def test_blood_artist_example_cards_present_under_aristocrats_synergy() -> None:
    """SC-TAG-003: example cards formerly under PAYOFF appear under ARISTOCRATS_SYNERGY."""
    examples = ROLE_EXAMPLES[CardRole.ARISTOCRATS_SYNERGY]
    assert "Blood Artist" in examples
    assert "Zulaport Cutthroat" in examples


def test_composition_outcome_roles_contains_no_payoff_string() -> None:
    """SC-TAG-003: COMPOSITION_OUTCOME_ROLES (formerly COMPOSITION_PAYOFF_ROLES) has no PAYOFF."""
    assert "PAYOFF" not in COMPOSITION_OUTCOME_ROLES
    assert all(r in [role.value for role in CardRole] for r in COMPOSITION_OUTCOME_ROLES)
