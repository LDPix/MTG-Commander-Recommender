import pytest

from app.models.card import CardData
from app.recommendation.commander_scorer import CommanderFitScore, CommanderScorer
from app.recommendation.role_tagger import RuleTagger


def make_card(
    oracle_id: str,
    name: str,
    colors: list[str],
    type_line: str = "Instant",
    oracle_text: str = "",
    cmc: float = 1.0,
) -> CardData:
    return CardData(
        id=f"id-{oracle_id}",
        oracle_id=oracle_id,
        name=name,
        color_identity=colors,
        legalities={"commander": "legal"},
        type_line=type_line,
        oracle_text=oracle_text,
        cmc=cmc,
    )


@pytest.fixture
def meren() -> CardData:
    return make_card(
        "meren-001",
        "Meren of Clan Nel Toth",
        ["B", "G"],
        type_line="Legendary Creature — Human Shaman",
        oracle_text=(
            "Whenever another creature you control dies, you get an experience counter.\n"
            "At the beginning of your end step, choose target creature card in your graveyard."
        ),
        cmc=4.0,
    )


@pytest.fixture
def sol_ring() -> CardData:
    return make_card("sr-001", "Sol Ring", [], oracle_text="{T}: Add {C}{C}.")


@pytest.fixture
def cultivate() -> CardData:
    return make_card(
        "clt-001",
        "Cultivate",
        ["G"],
        type_line="Sorcery",
        oracle_text="Search your library for up to two basic land cards, reveal those cards, put one onto the battlefield tapped and the other into your hand, then shuffle.",
    )


@pytest.fixture
def swords() -> CardData:
    return make_card(
        "stp-001",
        "Swords to Plowshares",
        ["W"],
        oracle_text="Exile target creature. Its controller gains life equal to its power.",
    )


# ── SC-CMD-002: Commander Collection Fit Score ───────────────────────────────


class TestCommanderScorer:
    def test_owned_synergy_cards_increase_fit_score(self, meren, sol_ring, cultivate):
        scorer = CommanderScorer(RuleTagger())
        score_with = scorer.compute_fit_score(meren, owned_cards=[sol_ring, cultivate])
        score_without = scorer.compute_fit_score(meren, owned_cards=[])
        assert score_with.total_score > score_without.total_score

    def test_missing_core_cards_decrease_fit_score(self, meren, sol_ring, cultivate):
        scorer = CommanderScorer(RuleTagger())
        score_many = scorer.compute_fit_score(meren, owned_cards=[sol_ring, cultivate])
        score_few = scorer.compute_fit_score(meren, owned_cards=[sol_ring])
        assert score_many.total_score >= score_few.total_score

    def test_role_coverage_affects_fit_score(self, meren, sol_ring, cultivate):
        scorer = CommanderScorer(RuleTagger())
        score_diverse = scorer.compute_fit_score(meren, owned_cards=[sol_ring, cultivate])
        score_ramp_only = scorer.compute_fit_score(meren, owned_cards=[sol_ring])
        assert score_diverse.total_score >= score_ramp_only.total_score

    def test_off_color_cards_do_not_increase_score(self, meren, sol_ring, swords):
        scorer = CommanderScorer(RuleTagger())
        # meren is B/G — swords (W) is off-color and should be ignored
        score_without = scorer.compute_fit_score(meren, owned_cards=[sol_ring])
        score_with_offcolor = scorer.compute_fit_score(
            meren, owned_cards=[sol_ring, swords]
        )
        assert score_with_offcolor.total_score <= score_without.total_score

    def test_commander_fit_score_is_deterministic(self, meren, sol_ring, cultivate):
        scorer = CommanderScorer(RuleTagger())
        owned = [sol_ring, cultivate]
        s1 = scorer.compute_fit_score(meren, owned_cards=owned)
        s2 = scorer.compute_fit_score(meren, owned_cards=owned)
        assert s1.total_score == s2.total_score

    def test_fit_score_result_has_required_fields(self, meren, sol_ring):
        scorer = CommanderScorer(RuleTagger())
        result = scorer.compute_fit_score(meren, owned_cards=[sol_ring])
        assert isinstance(result, CommanderFitScore)
        assert 0.0 <= result.total_score <= 1.0
        assert result.owned_count == 1
        assert result.oracle_id == "meren-001"
        assert result.score_breakdown

    def test_empty_collection_score_is_zero_or_near_zero(self, meren):
        scorer = CommanderScorer(RuleTagger())
        result = scorer.compute_fit_score(meren, owned_cards=[])
        assert result.total_score == 0.0
        assert result.owned_count == 0
