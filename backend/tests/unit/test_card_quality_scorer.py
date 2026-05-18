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
    score = compute_quality_score(_card(edhrec_rank=500, rarity="rare"), "WIN_CONDITION")
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_format_staple_score_zero_for_no_edhrec_rank() -> None:
    assert format_staple_score(_card(edhrec_rank=None)) == 0.0


def test_format_staple_score_high_for_low_rank() -> None:
    # Log curve: rank=10 → ~0.76, still well above 0.70
    assert format_staple_score(_card(edhrec_rank=10)) > 0.70


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
    # With stub removed: commander_inclusion = format_staple_score = 0.0 when no edhrec_rank.
    # score = 0.40×0 + 0.25×0 + 0.20×efficiency + 0.10×flex + 0.05×rarity ≈ 0.10
    score = compute_quality_score(_card(edhrec_rank=None, rarity=None), "WIN_CONDITION")
    assert score < 0.20, f"Unknown card score {score} should be < 0.20 without edhrec data"


# ---------------------------------------------------------------------------
# SC-DECK-011 calibration: stub removed, format_staple fallback
# ---------------------------------------------------------------------------

def test_compute_quality_score_uses_format_staple_as_commander_inclusion_when_no_data() -> None:
    """commander_inclusion = format_staple_score(card) when no per-commander data."""
    import math
    # edhrec_rank=2500 → log-curve staple = 1 - log(2501)/log(25001)
    card = _card(edhrec_rank=2500, cmc=3.0, rarity=None)
    score = compute_quality_score(card, "WIN_CONDITION")
    staple = 1.0 - math.log(2501) / math.log(25001)
    # efficiency_score("WIN_CONDITION", cmc=3) = max(0, min(1, 0.5 - max(0, 3-4)×0.05)) = 0.5
    expected = 0.40 * staple + 0.25 * staple + 0.20 * 0.5
    assert abs(score - expected) < 1e-9, f"Expected {expected:.4f}, got {score:.4f}"


def test_unknown_common_with_no_edhrec_rank_scores_below_weakness_threshold() -> None:
    """Generic common without edhrec_rank scores below QUALITY_WEAKNESS_THRESHOLD (0.35)."""
    from app.recommendation.deck_generator import QUALITY_WEAKNESS_THRESHOLD

    card = _card(edhrec_rank=None, rarity="common", cmc=5.0)
    score = compute_quality_score(card, "WIN_CONDITION")
    assert score < QUALITY_WEAKNESS_THRESHOLD, (
        f"Unknown common score {score:.3f} should be < weakness threshold {QUALITY_WEAKNESS_THRESHOLD}"
    )


def test_known_staple_with_low_edhrec_rank_scores_above_weakness_threshold() -> None:
    """Popular staple (low edhrec_rank) scores above QUALITY_WEAKNESS_THRESHOLD (0.35)."""
    from app.recommendation.deck_generator import QUALITY_WEAKNESS_THRESHOLD

    card = _card(edhrec_rank=100, rarity="rare", cmc=2.0)
    score = compute_quality_score(card, "WIN_CONDITION")
    assert score > QUALITY_WEAKNESS_THRESHOLD, (
        f"Known staple score {score:.3f} should be > weakness threshold {QUALITY_WEAKNESS_THRESHOLD}"
    )


def test_quality_stub_removed_from_compute_quality_score() -> None:
    """Card with edhrec_rank scores higher than the same card without it."""
    card_no_rank = _card(oracle_id="no-rank", edhrec_rank=None, rarity=None, cmc=3.0)
    card_with_rank = _card(oracle_id="with-rank", edhrec_rank=500, rarity=None, cmc=3.0)
    score_no_rank = compute_quality_score(card_no_rank, "WIN_CONDITION")
    score_with_rank = compute_quality_score(card_with_rank, "WIN_CONDITION")
    assert score_with_rank > score_no_rank, (
        "Card with edhrec_rank should score higher than same card without it "
        f"(got {score_with_rank:.3f} vs {score_no_rank:.3f})"
    )


def test_weak_generic_common_is_replaced_in_deck() -> None:
    """SC-DECK-011 regression: weak generic common scores below threshold, enabling replacement."""
    from app.recommendation.deck_generator import QUALITY_WEAKNESS_THRESHOLD

    weak_common = _card(oracle_id="weak-common-001", edhrec_rank=None, rarity="common", cmc=6.0)
    score = compute_quality_score(weak_common, "WIN_CONDITION")
    assert score < QUALITY_WEAKNESS_THRESHOLD, (
        f"Weak generic common {score:.3f} must score below threshold {QUALITY_WEAKNESS_THRESHOLD} "
        "to be eligible for replacement in the deck"
    )


# ---------------------------------------------------------------------------
# SC-DECK-034: log-curve format_staple_score calibration
# ---------------------------------------------------------------------------

def test_format_staple_score_log_rank_2_near_one() -> None:
    """SC-DECK-034: rank-2 card (Sol Ring tier) scores >= 0.88 with log curve."""
    score = format_staple_score(_card(edhrec_rank=2))
    assert score >= 0.88, f"rank=2 expected >= 0.88, got {score:.4f}"


def test_format_staple_score_log_rank_3000_below_0_65() -> None:
    """SC-DECK-034: rank-3000 card scores < 0.65 with log curve (old linear was 0.88)."""
    score = format_staple_score(_card(edhrec_rank=3000))
    assert score < 0.65, f"rank=3000 expected < 0.65, got {score:.4f}"


def test_format_staple_score_log_rank_25000_near_zero() -> None:
    """SC-DECK-034: rank-25000 card scores < 0.01 (near boundary of tracking range)."""
    score = format_staple_score(_card(edhrec_rank=25000))
    assert score < 0.01, f"rank=25000 expected < 0.01, got {score:.4f}"


def test_format_staple_score_log_rank_none_returns_zero() -> None:
    """SC-DECK-034: no edhrec_rank → score is 0.0."""
    assert format_staple_score(_card(edhrec_rank=None)) == 0.0


def test_format_staple_score_log_monotone_decreasing() -> None:
    """SC-DECK-034: scores are strictly decreasing as rank increases."""
    ranks = [1, 100, 500, 2000, 5000, 15000, 24999]
    scores = [format_staple_score(_card(edhrec_rank=r)) for r in ranks]
    for i in range(len(scores) - 1):
        assert scores[i] > scores[i + 1], (
            f"Score not decreasing: rank={ranks[i]} → {scores[i]:.4f}, "
            f"rank={ranks[i+1]} → {scores[i+1]:.4f}"
        )
