"""Tests for SC-DECK-013 role quality credit."""
from __future__ import annotations

from app.models.card import CardData
from app.recommendation.role_credit import role_quality_credit


def _card(
    type_line: str = "Sorcery",
    oracle_text: str = "",
    cmc: float = 3.0,
) -> CardData:
    return CardData(
        id="credit-test",
        oracle_id="credit-test",
        name="Credit Test",
        color_identity=["G"],
        legalities={"commander": "legal"},
        type_line=type_line,
        oracle_text=oracle_text,
        cmc=cmc,
    )


# ---------------------------------------------------------------------------
# RAMP
# ---------------------------------------------------------------------------

def test_ramp_credit_repeatable_engine_is_1_0() -> None:
    card = _card(oracle_text="Whenever you cast a spell, add {G}.", cmc=3.0)
    assert role_quality_credit(card, "RAMP") == 1.0


def test_ramp_credit_cultivate_style_is_0_75() -> None:
    card = _card(oracle_text="Search your library for two basic land cards, put one into play and one into your hand.", cmc=3.0)
    assert role_quality_credit(card, "RAMP") == 0.75


def test_ramp_credit_signet_is_0_5() -> None:
    card = _card(type_line="Artifact", oracle_text="{T}: Add {G}{W}.", cmc=2.0)
    assert role_quality_credit(card, "RAMP") == 0.5


def test_ramp_credit_high_cmc_ramp_is_0_25() -> None:
    card = _card(oracle_text="Search your library for a basic land card and put it into play.", cmc=5.0)
    assert role_quality_credit(card, "RAMP") == 0.25


# ---------------------------------------------------------------------------
# CARD_DRAW
# ---------------------------------------------------------------------------

def test_draw_credit_repeatable_trigger_is_1_0() -> None:
    card = _card(oracle_text="Whenever a creature enters under your control, draw a card.")
    assert role_quality_credit(card, "CARD_DRAW") == 1.0


def test_draw_credit_draw_two_is_0_5() -> None:
    card = _card(oracle_text="Draw 2 cards.")
    assert role_quality_credit(card, "CARD_DRAW") == 0.5


def test_draw_credit_cantrip_is_0_25() -> None:
    card = _card(oracle_text="Destroy target creature. Draw a card.")
    assert role_quality_credit(card, "CARD_DRAW") == 0.25


# ---------------------------------------------------------------------------
# SPOT_REMOVAL
# ---------------------------------------------------------------------------

def test_removal_credit_instant_exile_is_1_0() -> None:
    card = _card(type_line="Instant", oracle_text="Exile target creature or planeswalker.")
    assert role_quality_credit(card, "SPOT_REMOVAL") == 1.0


def test_removal_credit_sorcery_destroy_is_0_75() -> None:
    card = _card(type_line="Sorcery", oracle_text="Destroy target nonland permanent.")
    assert role_quality_credit(card, "SPOT_REMOVAL") == 0.75


def test_removal_credit_bounce_is_0_5() -> None:
    card = _card(type_line="Instant", oracle_text="Return target creature to its owner's hand.")
    assert role_quality_credit(card, "SPOT_REMOVAL") == 0.5


# ---------------------------------------------------------------------------
# BOARD_WIPE
# ---------------------------------------------------------------------------

def test_wipe_credit_all_creatures_is_1_0() -> None:
    card = _card(oracle_text="Destroy all creatures.")
    assert role_quality_credit(card, "BOARD_WIPE") == 1.0


def test_wipe_credit_selective_is_0_5() -> None:
    # "Each player sacrifices" — mass removal without "all creatures/permanents/nonland"
    card = _card(oracle_text="Each player sacrifices two creatures.")
    assert role_quality_credit(card, "BOARD_WIPE") == 0.5


# ---------------------------------------------------------------------------
# Unrecognized roles
# ---------------------------------------------------------------------------

def test_unknown_role_returns_1_0() -> None:
    card = _card(oracle_text="Search your library for a card and put it into your hand.")
    assert role_quality_credit(card, "TUTOR") == 1.0


def test_payoff_role_returns_1_0() -> None:
    card = _card(oracle_text="When this enters, create three 1/1 tokens.")
    assert role_quality_credit(card, "WIN_CONDITION") == 1.0
