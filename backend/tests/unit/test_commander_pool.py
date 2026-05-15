import pytest

from app.data_pipeline.card_resolver import CardResolver
from app.models.card import CardData
from app.recommendation.commander_pool import CandidateCommander, CommanderPool


def make_card(
    oracle_id: str,
    name: str,
    colors: list[str],
    type_line: str = "Instant",
    legality: str = "legal",
    oracle_text: str | None = None,
) -> CardData:
    return CardData(
        id=f"id-{oracle_id}",
        oracle_id=oracle_id,
        name=name,
        color_identity=colors,
        legalities={"commander": legality},
        type_line=type_line,
        oracle_text=oracle_text,
    )


def make_legendary_creature(
    oracle_id: str, name: str, colors: list[str], legality: str = "legal"
) -> CardData:
    return make_card(oracle_id, name, colors, "Legendary Creature — Human", legality)


@pytest.fixture
def resolver():
    meren = make_legendary_creature("meren-001", "Meren of Clan Nel Toth", ["B", "G"])
    atraxa = make_legendary_creature(
        "atraxa-001", "Atraxa, Praetors' Voice", ["W", "U", "B", "G"]
    )
    sol_ring = make_card("sr-001", "Sol Ring", [])
    banned = make_legendary_creature("banned-001", "Banned Commander", ["B"], "banned")
    return CardResolver([meren, atraxa, sol_ring, banned])


# ── SC-CMD-001: Candidate Commander Pool ─────────────────────────────────────


class TestCommanderPool:
    def test_legal_commander_included(self, resolver):
        pool = CommanderPool(resolver)
        candidates = pool.build_candidate_pool(owned_oracle_ids=set())
        names = {c.name for c in candidates}
        assert "Meren of Clan Nel Toth" in names
        assert "Atraxa, Praetors' Voice" in names

    def test_illegal_commander_excluded(self, resolver):
        pool = CommanderPool(resolver)
        candidates = pool.build_candidate_pool(owned_oracle_ids=set())
        names = {c.name for c in candidates}
        assert "Banned Commander" not in names

    def test_owned_commander_detected(self, resolver):
        pool = CommanderPool(resolver)
        candidates = pool.build_candidate_pool(owned_oracle_ids={"meren-001"})
        meren = next(c for c in candidates if c.name == "Meren of Clan Nel Toth")
        atraxa = next(c for c in candidates if c.name == "Atraxa, Praetors' Voice")
        assert meren.is_owned is True
        assert atraxa.is_owned is False

    def test_unsupported_commander_excluded(self, resolver):
        pool = CommanderPool(resolver)
        candidates = pool.build_candidate_pool(
            owned_oracle_ids=set(), supported_oracle_ids={"meren-001"}
        )
        names = {c.name for c in candidates}
        assert "Meren of Clan Nel Toth" in names
        assert "Atraxa, Praetors' Voice" not in names

    def test_candidate_pool_is_deterministic(self, resolver):
        pool = CommanderPool(resolver)
        c1 = pool.build_candidate_pool(owned_oracle_ids=set())
        c2 = pool.build_candidate_pool(owned_oracle_ids=set())
        assert [c.oracle_id for c in c1] == [c.oracle_id for c in c2]

    def test_non_commander_card_excluded(self, resolver):
        pool = CommanderPool(resolver)
        candidates = pool.build_candidate_pool(owned_oracle_ids=set())
        names = {c.name for c in candidates}
        assert "Sol Ring" not in names

    def test_commander_eligible_mdfc_detected(self):
        mdfc = make_card(
            "valki-001",
            "Valki, God of Lies",
            ["B"],
            type_line="Legendary Creature — God // Legendary Planeswalker — Tibalt",
        )
        resolver = CardResolver([mdfc])
        pool = CommanderPool(resolver)
        assert pool.is_commander_eligible(resolver.get_all()[0])

    def test_can_be_your_commander_text_detected(self):
        card = make_card(
            "cust-001",
            "Custom Card",
            ["R"],
            type_line="Creature — Human",
            oracle_text="Custom Card can be your commander.",
        )
        resolver = CardResolver([card])
        pool = CommanderPool(resolver)
        assert pool.is_commander_eligible(resolver.get_all()[0])
