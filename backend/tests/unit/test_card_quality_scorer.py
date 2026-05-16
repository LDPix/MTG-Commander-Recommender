"""Tests for SC-DECK-011 card quality scoring."""
from __future__ import annotations

from app.models.card import CardData, CardFace
from app.recommendation.card_quality_scorer import (
    compute_quality_score,
    efficiency_score,
    flexibility_score,
    format_staple_score,
    rarity_hint,
)


def _card(**updates: object) -> CardData:
    base = {
        "id": "quality-test",
        "oracle_id": "quality-test",
        "name": "Quality Test",
        "color_identity": ["G"],
        "legalities": {"commander": "legal"},
        "type_line": "Sorcery",
        "oracle_text": "",
        "mana_cost": "{2}{G}",
        "cmc": 3.0,
    }
    base.update(updates)
    return CardData(**base)


def test_compute_quality_score_uses_override_when_present() -> None:
    sol_ring = _card(
        oracle_id="a2e91c27-6f81-4512-bf20-7a01cb7b6a8e",
        name="Sol Ring",
        type_line="Artifact",
    )
    assert compute_quality_score(sol_ring, "RAMP") == 1.0


def test_compute_quality_score_returns_float_in_0_to_1() -> None:
    score = compute_quality_score(_card(edhrec_rank=500, rarity="rare"), "PAYOFF")
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_format_staple_score_zero_for_no_edhrec_rank() -> None:
    assert format_staple_score(_card(edhrec_rank=None)) == 0.0


def test_format_staple_score_high_for_low_rank() -> None:
    assert format_staple_score(_card(edhrec_rank=10)) > 0.99


def test_format_staple_score_low_for_high_rank() -> None:
    assert format_staple_score(_card(edhrec_rank=24_000)) < 0.05


def test_efficiency_score_spot_removal_cheap_instant_scores_high() -> None:
    swords = _card(
        type_line="Instant",
        oracle_text="Exile target creature.",
        mana_cost="{W}",
        cmc=1.0,
    )
    assert efficiency_score(swords, "SPOT_REMOVAL") >= 0.9


def test_efficiency_score_ramp_cheap_scores_high() -> None:
    ramp = _card(type_line="Artifact", oracle_text="{T}: Add one mana.", cmc=2.0)
    assert efficiency_score(ramp, "RAMP") > 0.7


def test_efficiency_score_ramp_4_plus_cmc_penalized() -> None:
    ramp = _card(type_line="Artifact", oracle_text="{T}: Add three mana.", cmc=4.0)
    assert efficiency_score(ramp, "RAMP") < 0.5


def test_flexibility_score_instant_speed_contributes() -> None:
    assert flexibility_score(_card(type_line="Instant")) >= 0.3


def test_flexibility_score_instant_face_contributes() -> None:
    modal = _card(
        card_faces=[
            CardFace(name="Front", type_line="Creature", oracle_text=""),
            CardFace(name="Back", type_line="Instant", oracle_text="Draw a card."),
        ]
    )
    assert flexibility_score(modal) >= 0.3


def test_flexibility_score_cycling_keyword_contributes() -> None:
    assert flexibility_score(_card(keywords=["Cycling"])) >= 0.3


def test_rarity_hint_mythic_returns_max() -> None:
    assert rarity_hint(_card(rarity="mythic")) == 0.05


def test_rarity_hint_common_returns_zero() -> None:
    assert rarity_hint(_card(rarity="common")) == 0.0


def test_compute_quality_score_without_edhrec_uses_defaults() -> None:
    score = compute_quality_score(_card(edhrec_rank=None, rarity=None), "PAYOFF")
    assert 0.25 <= score <= 0.35
