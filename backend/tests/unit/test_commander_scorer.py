import math

import pytest

from app.models.card import CardData
from app.recommendation.commander_scorer import CommanderFitScore, CommanderScorer
from app.recommendation.role_taxonomy import CardRole, RoleTag
from app.recommendation.role_tagger import RuleTagger


class StaticTagger:
    def __init__(self, roles_by_id: dict[str, list[CardRole]]) -> None:
        self.roles_by_id = roles_by_id

    def tag(self, card: CardData) -> list[RoleTag]:
        return [
            RoleTag(role=role, confidence=1.0, source="manual")
            for role in self.roles_by_id.get(card.oracle_id, [])
        ]


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


def make_cards(
    count: int,
    prefix: str,
    colors: list[str] | None = None,
    type_line: str = "Creature",
) -> list[CardData]:
    return [
        make_card(f"{prefix}-{idx:03d}", f"{prefix.title()} {idx:03d}", colors or ["G"], type_line)
        for idx in range(count)
    ]


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

    def test_large_collection_does_not_saturate_owned_ratio(self, meren):
        scorer = CommanderScorer(StaticTagger({}))  # type: ignore[arg-type]

        score_200 = scorer.compute_fit_score(meren, make_cards(200, "owned-a"))
        score_100 = scorer.compute_fit_score(meren, make_cards(100, "owned-b"))

        assert score_200.total_score > score_100.total_score
        assert score_200.owned_percentage < 1.0

    def test_owned_ratio_is_asymptotic_for_large_collections(self, meren):
        scorer = CommanderScorer(StaticTagger({}))  # type: ignore[arg-type]

        score_300 = scorer.compute_fit_score(meren, make_cards(300, "owned-soft"))
        score_600 = scorer.compute_fit_score(meren, make_cards(600, "owned-large"))

        assert score_600.owned_percentage > score_300.owned_percentage
        assert score_600.owned_percentage < 1.0
        assert score_600.score_breakdown["owned_ratio"] < 1.0

    def test_owned_ratio_at_99_is_not_saturated(self, meren):
        scorer = CommanderScorer(StaticTagger({}))  # type: ignore[arg-type]

        result = scorer.compute_fit_score(meren, make_cards(99, "owned-99"))

        assert result.owned_percentage == round(1.0 - math.exp(-99 / 1200), 6)
        assert result.owned_percentage < 1.0

    def test_role_score_reflects_depth_not_just_presence(self, meren):
        shallow_cards = make_cards(5, "shallow")
        deep_cards: list[CardData] = []
        shallow_roles = {
            card.oracle_id: [role]
            for card, role in zip(
                shallow_cards,
                [
                    CardRole.RAMP,
                    CardRole.CARD_DRAW,
                    CardRole.SPOT_REMOVAL,
                    CardRole.BOARD_WIPE,
                    CardRole.LAND,
                ],
            )
        }
        deep_roles: dict[str, list[CardRole]] = {}
        for role in [
            CardRole.RAMP,
            CardRole.CARD_DRAW,
            CardRole.SPOT_REMOVAL,
            CardRole.BOARD_WIPE,
            CardRole.LAND,
        ]:
            cards = make_cards(5, f"deep-{role.value.lower()}", type_line="Basic Land" if role == CardRole.LAND else "Creature")
            deep_cards.extend(cards)
            deep_roles.update({card.oracle_id: [role] for card in cards})

        shallow_score = CommanderScorer(StaticTagger(shallow_roles)).compute_fit_score(
            meren, shallow_cards
        )
        deep_score = CommanderScorer(StaticTagger(deep_roles)).compute_fit_score(
            meren, deep_cards
        )

        assert shallow_score.score_breakdown["role_score"] == pytest.approx(0.2)
        assert shallow_score.total_score < 0.5
        assert deep_score.total_score > shallow_score.total_score

    def test_role_score_caps_at_depth_cap_per_role(self, meren):
        ramp_cards = make_cards(10, "ramp-depth")
        roles = {card.oracle_id: [CardRole.RAMP] for card in ramp_cards}
        scorer = CommanderScorer(StaticTagger(roles))  # type: ignore[arg-type]

        result = scorer.compute_fit_score(meren, ramp_cards)

        assert result.score_breakdown["role_score"] == pytest.approx(0.2)

    def test_commanders_with_different_owned_counts_rank_correctly(self, meren):
        scorer = CommanderScorer(StaticTagger({}))  # type: ignore[arg-type]

        many = scorer.compute_fit_score(meren, make_cards(150, "many"))
        few = scorer.compute_fit_score(meren, make_cards(25, "few"))

        assert many.total_score > few.total_score
