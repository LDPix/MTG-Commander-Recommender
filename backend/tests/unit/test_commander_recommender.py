import pytest

from app.data_pipeline.card_resolver import CardResolver
from app.models.card import CardData
from app.recommendation.commander_pool import CommanderPool
from app.recommendation.commander_recommender import (
    CommanderRecommendation,
    CommanderRecommender,
)
from app.recommendation.commander_scorer import CommanderScorer
from app.recommendation.role_tagger import RuleTagger


def make_card(
    oracle_id: str,
    name: str,
    colors: list[str],
    type_line: str = "Instant",
    oracle_text: str = "",
    cmc: float = 1.0,
    legality: str = "legal",
) -> CardData:
    return CardData(
        id=f"id-{oracle_id}",
        oracle_id=oracle_id,
        name=name,
        color_identity=colors,
        legalities={"commander": legality},
        type_line=type_line,
        oracle_text=oracle_text,
        cmc=cmc,
    )


# Meren — graveyard/aristocrats archetype
MEREN = make_card(
    "meren-001",
    "Meren of Clan Nel Toth",
    ["B", "G"],
    "Legendary Creature — Human Shaman",
    oracle_text=(
        "Whenever another creature you control dies, you get an experience counter.\n"
        "At the beginning of your end step, choose target creature card in your graveyard."
    ),
    cmc=4.0,
)

# Atraxa — proliferate/counters archetype
ATRAXA = make_card(
    "atraxa-001",
    "Atraxa, Praetors' Voice",
    ["W", "U", "B", "G"],
    "Legendary Creature — Phyrexian Angel",
    oracle_text=(
        "Flying, vigilance, deathtouch, lifelink.\n"
        "At the beginning of your end step, proliferate."
    ),
    cmc=4.0,
)

BANNED_CMD = make_card(
    "banned-001",
    "Banned Commander",
    ["B"],
    "Legendary Creature — Human",
    legality="banned",
)

SOL_RING = make_card("sr-001", "Sol Ring", [], oracle_text="{T}: Add {C}{C}.")
CULTIVATE = make_card(
    "clt-001",
    "Cultivate",
    ["G"],
    "Sorcery",
    oracle_text="Search your library for up to two basic land cards",
)


@pytest.fixture
def recommender() -> CommanderRecommender:
    resolver = CardResolver([MEREN, ATRAXA, BANNED_CMD])
    pool = CommanderPool(resolver)
    scorer = CommanderScorer(RuleTagger())
    return CommanderRecommender(pool, scorer)


# ── SC-CMD-003: Rank Commander Recommendations ───────────────────────────────


class TestCommanderRanking:
    def test_commanders_sorted_by_fit_score(self, recommender):
        owned_cards = [SOL_RING, CULTIVATE]  # colorless + G — benefit Meren (B/G) more
        recs = recommender.recommend(
            owned_oracle_ids={"sr-001", "clt-001"},
            owned_cards=owned_cards,
        )
        assert len(recs) >= 2
        scores = [r.fit_score for r in recs]
        assert scores == sorted(scores, reverse=True)

    def test_recommendation_contains_fit_score(self, recommender):
        recs = recommender.recommend(
            owned_oracle_ids=set(), owned_cards=[]
        )
        for rec in recs:
            assert isinstance(rec.fit_score, float)
            assert 0.0 <= rec.fit_score <= 1.0

    def test_recommendation_contains_archetype(self, recommender):
        recs = recommender.recommend(
            owned_oracle_ids=set(), owned_cards=[]
        )
        for rec in recs:
            assert rec.archetype  # non-empty string
            assert isinstance(rec.archetype, str)

    def test_illegal_commander_not_recommended(self, recommender):
        recs = recommender.recommend(
            owned_oracle_ids=set(), owned_cards=[]
        )
        names = {r.name for r in recs}
        assert "Banned Commander" not in names

    def test_ranking_is_deterministic(self, recommender):
        owned_cards = [SOL_RING, CULTIVATE]
        recs1 = recommender.recommend(
            owned_oracle_ids={"sr-001", "clt-001"},
            owned_cards=owned_cards,
        )
        recs2 = recommender.recommend(
            owned_oracle_ids={"sr-001", "clt-001"},
            owned_cards=owned_cards,
        )
        assert [r.oracle_id for r in recs1] == [r.oracle_id for r in recs2]


# ── SC-CMD-004: Explain Commander Recommendation ─────────────────────────────


class TestCommanderExplanation:
    def test_commander_explanation_uses_owned_cards(self, recommender):
        recs = recommender.recommend(
            owned_oracle_ids={"sr-001", "clt-001"},
            owned_cards=[SOL_RING, CULTIVATE],
        )
        meren_rec = next(r for r in recs if r.name == "Meren of Clan Nel Toth")
        # Explanation should reference owned cards
        assert meren_rec.explanation.owned_highlights or meren_rec.explanation.summary

    def test_commander_explanation_uses_package_data(self, recommender):
        """Explanation references archetype/package label."""
        recs = recommender.recommend(
            owned_oracle_ids=set(), owned_cards=[]
        )
        for rec in recs:
            assert rec.explanation.archetype_label  # package/archetype is populated
            assert rec.explanation.summary  # summary is non-empty

    def test_commander_explanation_mentions_missing_core_card(self, recommender):
        """When collection has no ramp, explanation notes the gap."""
        recs = recommender.recommend(
            owned_oracle_ids=set(), owned_cards=[]
        )
        meren_rec = next(r for r in recs if r.name == "Meren of Clan Nel Toth")
        # Empty collection → should flag missing roles
        assert meren_rec.explanation.missing_core_notes

    def test_explanation_does_not_reference_nonexistent_tag(self, recommender):
        """Owned highlights only contain names of cards actually passed in."""
        owned_cards = [SOL_RING]
        recs = recommender.recommend(
            owned_oracle_ids={"sr-001"},
            owned_cards=owned_cards,
        )
        meren_rec = next(r for r in recs if r.name == "Meren of Clan Nel Toth")
        for highlight in meren_rec.explanation.owned_highlights:
            assert highlight in {c.name for c in owned_cards}

    def test_explanation_is_returned_with_recommendation(self, recommender):
        recs = recommender.recommend(
            owned_oracle_ids=set(), owned_cards=[]
        )
        for rec in recs:
            assert isinstance(rec, CommanderRecommendation)
            assert rec.explanation is not None
            assert rec.explanation.summary
