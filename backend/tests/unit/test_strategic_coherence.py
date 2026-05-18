"""Tests for SC-DECK-012 strategic coherence gate."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.card import CardData
from app.models.deck import DeckCard, GeneratedDeck, PackageCluster
from app.recommendation.role_taxonomy import CardRole, RoleTag
from app.recommendation.strategic_coherence import (
    StrategicCoherenceValidator,
    active_packages,
    infer_primary_plan,
    is_card_justified,
)
from app.services.deck_generation_service import _build_deck_score_logs, _merge_warnings


NEGATIVE_FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "negative"
    / "nissa_incoherent_value_pile.json"
)


def _card_data(
    oracle_id: str,
    name: str,
    roles: list[str] | None = None,
    type_line: str = "Creature",
    oracle_text: str = "",
    cmc: float = 3.0,
) -> CardData:
    return CardData(
        id=oracle_id,
        oracle_id=oracle_id,
        name=name,
        color_identity=["G"],
        legalities={"commander": "legal"},
        type_line=type_line,
        oracle_text=oracle_text,
        cmc=cmc,
    )


def _deck_card(
    card: CardData,
    roles: list[str],
    package_ids: list[str] | None = None,
) -> DeckCard:
    return DeckCard(
        oracle_id=card.oracle_id,
        name=card.name,
        is_owned=False,
        quantity=1,
        roles=roles,
        package_ids=package_ids or [],
        selection_reason="test selection",
        synergy_score=0.0,
        color_identity=card.color_identity,
    )


def _commander(
    oracle_text: str = "Landfall - Whenever a land enters under your control, you get {E}{E}.",
) -> CardData:
    return CardData(
        id="nissa",
        oracle_id="00037840-6089-42ec-8c5c-281f9f474504",
        name="Nissa, Worldsoul Speaker",
        color_identity=["G"],
        legalities={"commander": "legal"},
        type_line="Legendary Creature - Elf Druid",
        oracle_text=oracle_text,
        mana_cost="{3}{G}",
        cmc=4.0,
        keywords=["Landfall"] if "Landfall" in oracle_text else [],
    )


def _generated_deck(cards: list[DeckCard], packages: list[PackageCluster] | None = None) -> GeneratedDeck:
    commander_card = DeckCard(
        oracle_id="00037840-6089-42ec-8c5c-281f9f474504",
        name="Nissa, Worldsoul Speaker",
        is_owned=True,
        quantity=1,
        roles=[CardRole.LANDFALL_SYNERGY.value],
        selection_reason="commander",
    )
    return GeneratedDeck(
        deck_id="coherence-test-deck",
        session_id="coherence-session",
        commander=commander_card,
        main_deck=cards,
        role_breakdown={},
        quota_status=[],
        package_breakdown=packages or [],
        warnings=[],
        owned_count=0,
        owned_percentage=0.0,
        is_valid=True,
        validation_errors=[],
    )


def _fixture() -> dict:
    with NEGATIVE_FIXTURE.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _deck_from_fixture() -> tuple[CardData, GeneratedDeck, dict[str, CardData], list[PackageCluster]]:
    raw = _fixture()
    commander = CardData(**raw["commander"])
    lookup = {commander.oracle_id: commander}
    deck_cards: list[DeckCard] = []
    package_id = raw["unsupported_package"]["package_id"]
    package_card_ids = set(raw["unsupported_package"]["card_oracle_ids"])

    for item in raw["cards"]:
        roles = item["roles"]
        card = _card_data(
            oracle_id=item["oracle_id"],
            name=item["name"],
            roles=roles,
            type_line=item["type_line"],
            oracle_text=item["oracle_text"],
            cmc=item["cmc"],
        )
        lookup[card.oracle_id] = card
        deck_cards.append(
            _deck_card(
                card,
                roles,
                package_ids=[package_id] if card.oracle_id in package_card_ids else [],
            )
        )

    package = PackageCluster(**raw["unsupported_package"])
    return commander, _generated_deck(deck_cards, [package]), lookup, [package]


def test_generated_deck_has_primary_plan_or_warning() -> None:
    commander = _commander()
    landfall = _card_data(
        "landfall-payoff",
        "Landfall Payoff",
        type_line="Creature",
        oracle_text="Landfall - Whenever a land enters, draw a card.",
    )
    deck = _generated_deck([
        _deck_card(landfall, [CardRole.LANDFALL_SYNERGY.value])
    ])
    report = StrategicCoherenceValidator().validate(
        commander=commander,
        commander_tags=[],
        deck=deck,
        all_cards_lookup={landfall.oracle_id: landfall},
        packages=[],
    )

    assert report.primary_plan == "landfall"
    assert report.warnings == []


def test_loose_treasure_clue_food_cards_do_not_form_package_without_support() -> None:
    commander, deck, _, packages = _deck_from_fixture()
    active, loose_rejected = active_packages(deck, packages, "landfall", commander)

    assert active == set()
    assert "loose-artifact-value" in loose_rejected


def test_off_plan_cards_limited_after_role_quotas() -> None:
    commander, deck, lookup, packages = _deck_from_fixture()
    report = StrategicCoherenceValidator().validate(
        commander=commander,
        commander_tags=[],
        deck=deck,
        all_cards_lookup=lookup,
        packages=packages,
    )

    assert report.off_plan_count > report.on_plan_count
    assert any("off-plan" in warning for warning in report.warnings)


def test_coherence_warning_returned_for_fallback_commander_without_plan() -> None:
    commander = _commander(oracle_text="Flying.")
    filler = _card_data("generic-payoff", "Generic Payoff", oracle_text="Trample.")
    deck = _generated_deck([_deck_card(filler, [CardRole.WIN_CONDITION.value])])
    report = StrategicCoherenceValidator().validate(
        commander=commander,
        commander_tags=[],
        deck=deck,
        all_cards_lookup={filler.oracle_id: filler},
        packages=[],
    )

    assert report.primary_plan is None
    assert any("no clear primary commander plan" in warning for warning in report.warnings)


def test_score_logs_include_primary_plan_and_warning_candidates() -> None:
    commander, deck, lookup, packages = _deck_from_fixture()
    report = StrategicCoherenceValidator().validate(
        commander=commander,
        commander_tags=[],
        deck=deck,
        all_cards_lookup=lookup,
        packages=packages,
    )
    deck.strategic_coherence = report

    analysis_log = next(
        log for log in _build_deck_score_logs("coherence-session", deck)
        if log.scope == "deck_analysis"
    )
    assert "primary_plan:landfall" in analysis_log.selected_reasons
    assert analysis_log.score_components["warning_candidate_count"] > 0
    assert any(warning.startswith("warning_card:") for warning in analysis_log.warnings)


def test_nissa_incoherent_deck_fixture_loaded() -> None:
    raw = _fixture()

    assert raw["commander"]["name"] == "Nissa, Worldsoul Speaker"
    assert raw["cards"]
    assert raw["unsupported_package"]["package_id"] == "loose-artifact-value"


def test_nissa_random_value_pile_fails_coherence_gate() -> None:
    commander, deck, lookup, packages = _deck_from_fixture()
    report = StrategicCoherenceValidator().validate(
        commander=commander,
        commander_tags=[],
        deck=deck,
        all_cards_lookup=lookup,
        packages=packages,
    )

    assert report.primary_plan == "landfall"
    assert report.warning_card_oracle_ids
    assert report.warnings


def test_nissa_fixture_rejects_loose_artifact_value_package() -> None:
    commander, deck, lookup, packages = _deck_from_fixture()
    report = StrategicCoherenceValidator().validate(
        commander=commander,
        commander_tags=[],
        deck=deck,
        all_cards_lookup=lookup,
        packages=packages,
    )

    assert report.active_package_ids == []
    assert any("Treasure/Clue/Food/Map" in warning for warning in report.warnings)


def test_negative_fixture_allows_repaired_deck_variants() -> None:
    commander = _commander()
    landfall_cards = [
        _card_data(
            f"landfall-{i}",
            f"Landfall Card {i}",
            type_line="Creature",
            oracle_text="Landfall - Whenever a land enters under your control, create a token.",
        )
        for i in range(4)
    ]
    ramp = _card_data(
        "ramp",
        "Ramp",
        type_line="Sorcery",
        oracle_text="Search your library for a basic land card.",
    )
    cards = [
        *[_deck_card(card, [CardRole.LANDFALL_SYNERGY.value]) for card in landfall_cards],
        _deck_card(ramp, [CardRole.RAMP.value]),
    ]
    lookup = {card.oracle_id: card for card in [*landfall_cards, ramp]}
    report = StrategicCoherenceValidator().validate(
        commander=commander,
        commander_tags=[
            RoleTag(CardRole.LANDFALL_SYNERGY, confidence=1.0, source="manual")
        ],
        deck=_generated_deck(cards),
        all_cards_lookup=lookup,
        packages=[],
    )

    assert report.primary_plan == "landfall"
    assert report.warnings == []


def test_low_coherence_warning_is_user_visible() -> None:
    commander, deck, lookup, packages = _deck_from_fixture()
    report = StrategicCoherenceValidator().validate(
        commander=commander,
        commander_tags=[],
        deck=deck,
        all_cards_lookup=lookup,
        packages=packages,
    )
    deck.warnings = _merge_warnings(deck.warnings, report.warnings)

    assert any("Strategic coherence" in warning for warning in deck.warnings)


# =========================================================================
# SC-DECK-020: Commander plan overrides and evidence
# =========================================================================

GRETA_ORACLE_ID = "greta-sweettooth-001"
TOLUZ_ORACLE_ID = "toluz-clever-conductor-001"


def _greta_commander() -> CardData:
    return CardData(
        id=GRETA_ORACLE_ID,
        oracle_id=GRETA_ORACLE_ID,
        name="Greta, Sweettooth Scourge",
        color_identity=["B", "G"],
        legalities={"commander": "legal"},
        type_line="Legendary Creature — Goblin Scout",
        oracle_text=(
            "Whenever you sacrifice a Food, you may pay {1}. "
            "If you do, each opponent loses 1 life and you gain 1 life."
        ),
        cmc=2.0,
    )


def _toluz_commander() -> CardData:
    return CardData(
        id=TOLUZ_ORACLE_ID,
        oracle_id=TOLUZ_ORACLE_ID,
        name="Toluz, Clever Conductor",
        color_identity=["U", "B"],
        legalities={"commander": "legal"},
        type_line="Legendary Creature — Human Rogue",
        oracle_text=(
            "Whenever Toluz, Clever Conductor connives, "
            "if a card was put into your graveyard this way, "
            "draw a card at the beginning of the next end step."
        ),
        cmc=3.0,
    )


def test_infer_primary_plan_returns_override_for_greta() -> None:
    """SC-DECK-020: Greta's oracle_id maps to 'food-sacrifice' via plan override."""
    plan = infer_primary_plan(_greta_commander(), [])
    assert plan == "food-sacrifice", f"Expected 'food-sacrifice', got {plan!r}"


def test_infer_primary_plan_returns_override_for_toluz() -> None:
    """SC-DECK-020: Toluz's oracle_id maps to 'connive' via plan override."""
    plan = infer_primary_plan(_toluz_commander(), [])
    assert plan == "connive", f"Expected 'connive', got {plan!r}"


def test_infer_primary_plan_food_sacrifice_from_oracle_text() -> None:
    """SC-DECK-020: commander with 'food' and 'sacrifice' in text gets 'food-sacrifice' plan."""
    commander = CardData(
        id="generic-food-sac",
        oracle_id="generic-food-sac",
        name="Generic Food Sac Commander",
        color_identity=["G"],
        legalities={"commander": "legal"},
        type_line="Legendary Creature",
        oracle_text="Whenever you sacrifice a Food token, draw a card.",
        cmc=3.0,
    )
    plan = infer_primary_plan(commander, [])
    assert plan == "food-sacrifice", (
        f"Expected 'food-sacrifice' (not 'artifacts'), got {plan!r}"
    )


def test_infer_primary_plan_connive_from_oracle_text() -> None:
    """SC-DECK-020: commander with 'connive' in oracle text gets 'connive' plan."""
    commander = CardData(
        id="generic-connive",
        oracle_id="generic-connive",
        name="Generic Connive Commander",
        color_identity=["U"],
        legalities={"commander": "legal"},
        type_line="Legendary Creature",
        oracle_text="Whenever you connive, create a 1/1 Citizen creature token.",
        cmc=3.0,
    )
    plan = infer_primary_plan(commander, [])
    assert plan == "connive", f"Expected 'connive', got {plan!r}"


def test_is_card_justified_positive_evidence_overrides_default() -> None:
    """SC-DECK-020: card matching Greta's positive evidence is justified even with no plan."""
    card_data = _card_data(
        "food-token-maker",
        "Mysterious Cauldron",
        oracle_text="At the beginning of your upkeep, create a Food token.",
        type_line="Artifact",
    )
    deck_card = _deck_card(card_data, roles=[])  # no roles → no infra match

    # primary_plan=None forces the normal path to fail (quality ≈ 0.1, below FLEXIBLE_STAPLE)
    result = is_card_justified(
        card=deck_card,
        card_data=card_data,
        primary_plan=None,
        active_package_ids=set(),
        commander_oracle_id=GRETA_ORACLE_ID,
    )
    assert result is True, "Positive evidence ('food') should justify the card"


def test_is_card_justified_negative_evidence_marks_off_plan() -> None:
    """SC-DECK-020: card matching Greta's negative evidence is unjustified despite RAMP role."""
    card_data = _card_data(
        "treasure-ramp",
        "Gilded Goose Proxy",
        oracle_text="{T}: Sacrifice this: create a Treasure token.",
        type_line="Creature",
    )
    deck_card = _deck_card(card_data, roles=[CardRole.RAMP.value])  # RAMP normally justifies

    result = is_card_justified(
        card=deck_card,
        card_data=card_data,
        primary_plan="food-sacrifice",
        active_package_ids=set(),
        commander_oracle_id=GRETA_ORACLE_ID,
    )
    assert result is False, (
        "Negative evidence ('treasure') must override RAMP infra role justification"
    )


def test_required_role_filler_does_not_automatically_count_as_on_plan() -> None:
    """SC-DECK-022: quota filler status alone is not commander-plan support."""
    commander = _commander()
    removal_card = _card_data(
        "generic-removal-filler",
        "Generic Removal Filler",
        oracle_text="Destroy target creature.",
        type_line="Instant",
    )
    deck = _generated_deck([
        _deck_card(removal_card, [CardRole.SPOT_REMOVAL.value]),
    ])

    report = StrategicCoherenceValidator().validate(
        commander=commander,
        commander_tags=[RoleTag(CardRole.LANDFALL_SYNERGY, confidence=1.0, source="manual")],
        deck=deck,
        all_cards_lookup={commander.oracle_id: commander, removal_card.oracle_id: removal_card},
        packages=[],
    )

    assert report.primary_plan == "landfall"
    assert report.on_plan_count == 0
    assert report.off_plan_count == 1
    assert removal_card.oracle_id in report.warning_card_oracle_ids


def test_multi_tag_package_roles_do_not_inflate_on_plan_count() -> None:
    """SC-DECK-023: raw package tags are evidence, not on-plan slot credit."""
    commander = CardData(
        id="aristocrat-commander",
        oracle_id="aristocrat-commander",
        name="Aristocrat Commander",
        color_identity=["B", "G"],
        legalities={"commander": "legal"},
        type_line="Legendary Creature - Test",
        oracle_text="Whenever another creature dies, each opponent loses 1 life.",
        mana_cost="{2}{B}{G}",
        cmc=4.0,
    )
    tagged_card = _card_data(
        "raw-package-tags",
        "Raw Package Tags",
        oracle_text="Draw two cards.",
        type_line="Sorcery",
    )
    deck_card = _deck_card(
        tagged_card,
        [
            CardRole.SACRIFICE_OUTLET.value,
            CardRole.TOKEN_MAKER.value,
            CardRole.WIN_CONDITION.value,
            CardRole.CARD_DRAW.value,
        ],
    ).model_copy(update={"assigned_role": CardRole.CARD_DRAW.value})
    deck = _generated_deck([deck_card])

    report = StrategicCoherenceValidator().validate(
        commander=commander,
        commander_tags=[
            RoleTag(CardRole.ARISTOCRATS_SYNERGY, confidence=1.0, source="manual")
        ],
        deck=deck,
        all_cards_lookup={commander.oracle_id: commander, tagged_card.oracle_id: tagged_card},
        packages=[],
    )

    assert report.primary_plan == "aristocrats"
    assert report.on_plan_count == 0
    assert report.off_plan_count == 1
    assert tagged_card.oracle_id in report.warning_card_oracle_ids


def test_inactive_package_does_not_increase_on_plan_count() -> None:
    """SC-DECK-025: dense unrelated packages do not justify selected cards."""
    commander = _commander()
    cards = [
        _card_data(
            f"token-unrelated-{i}",
            f"Token Unrelated {i}",
            oracle_text="Create a 1/1 creature token.",
        )
        for i in range(4)
    ]
    package = PackageCluster(
        package_id="dense-token-pile",
        label="token package",
        confidence=0.8,
        card_oracle_ids=[card.oracle_id for card in cards],
        top_roles=[CardRole.TOKEN_MAKER.value],
    )
    deck = _generated_deck([
        _deck_card(
            card,
            [CardRole.TOKEN_MAKER.value],
            package_ids=[package.package_id],
        )
        for card in cards
    ])

    report = StrategicCoherenceValidator().validate(
        commander=commander,
        commander_tags=[
            RoleTag(CardRole.LANDFALL_SYNERGY, confidence=1.0, source="manual")
        ],
        deck=deck,
        all_cards_lookup={commander.oracle_id: commander, **{card.oracle_id: card for card in cards}},
        packages=[package],
    )

    assert report.primary_plan == "landfall"
    assert report.active_package_ids == []
    assert report.on_plan_count == 0
    assert report.off_plan_count == 4


def test_toluz_landfall_primary_plan_is_rejected() -> None:
    """SC-DECK-022: Toluz keeps connive override despite landfall-like card text."""
    toluz = _toluz_commander()
    landfall_card = _card_data(
        "toluz-landfall-mismatch",
        "Landfall Mismatch",
        oracle_text="Landfall — Whenever a land enters, create a token.",
        type_line="Creature",
    )
    deck = _generated_deck([
        _deck_card(landfall_card, [CardRole.LANDFALL_SYNERGY.value]),
    ])

    report = StrategicCoherenceValidator().validate(
        commander=toluz,
        commander_tags=[RoleTag(CardRole.LANDFALL_SYNERGY, confidence=1.0, source="manual")],
        deck=deck,
        all_cards_lookup={toluz.oracle_id: toluz, landfall_card.oracle_id: landfall_card},
        packages=[],
    )

    assert report.primary_plan == "connive"
    assert report.primary_plan != "landfall"
    assert report.off_plan_count == 1
    assert landfall_card.oracle_id in report.warning_card_oracle_ids


def test_greta_fixture_off_plan_cards_now_flagged() -> None:
    """SC-DECK-020: Greta deck with Treasure cards is flagged as off-plan."""
    greta = _greta_commander()

    # On-plan cards for Greta: food/sacrifice themed
    food_card = _card_data(
        "food-synergy",
        "Witch's Oven",
        oracle_text="Sacrifice a creature: create a Food token.",
        type_line="Artifact",
    )
    # Off-plan: Treasure producer — matches negative evidence
    treasure_card = _card_data(
        "treasure-off-plan",
        "Prosperous Thief",
        oracle_text="Whenever this deals combat damage, create a Treasure token.",
        type_line="Creature",
    )

    deck = _generated_deck([
        _deck_card(food_card, [CardRole.SACRIFICE_OUTLET.value]),
        _deck_card(treasure_card, [CardRole.WIN_CONDITION.value]),
    ])
    lookup = {
        greta.oracle_id: greta,
        food_card.oracle_id: food_card,
        treasure_card.oracle_id: treasure_card,
    }

    report = StrategicCoherenceValidator().validate(
        commander=greta,
        commander_tags=[],
        deck=deck,
        all_cards_lookup=lookup,
        packages=[],
    )

    assert report.primary_plan == "food-sacrifice"
    assert report.off_plan_count > 0
    assert treasure_card.oracle_id in report.warning_card_oracle_ids


# ---------------------------------------------------------------------------
# SC-DECK-021: Greta and Toluz negative regression fixtures
# ---------------------------------------------------------------------------

GRETA_FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "negative"
    / "greta_incoherent_generic_pile.json"
)

TOLUZ_FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "negative"
    / "toluz_incoherent_generic_pile.json"
)


def _load_negative_fixture(
    path: Path,
) -> tuple[CardData, GeneratedDeck, dict[str, CardData], list[PackageCluster]]:
    """Generic loader for any negative fixture file."""
    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    commander_raw = raw["commander"]
    color_identity: list[str] = commander_raw["color_identity"]

    commander = CardData(
        id=commander_raw["oracle_id"],
        oracle_id=commander_raw["oracle_id"],
        name=commander_raw["name"],
        color_identity=color_identity,
        legalities=commander_raw.get("legalities", {"commander": "legal"}),
        type_line=commander_raw["type_line"],
        oracle_text=commander_raw.get("oracle_text", ""),
        mana_cost=commander_raw.get("mana_cost", ""),
        cmc=commander_raw.get("cmc", 0.0),
        keywords=commander_raw.get("keywords", []),
    )

    pkg_raw = raw["unsupported_package"]
    package_card_ids = set(pkg_raw["card_oracle_ids"])
    package_id = pkg_raw["package_id"]

    lookup: dict[str, CardData] = {commander.oracle_id: commander}
    deck_cards: list[DeckCard] = []

    for item in raw["cards"]:
        card = CardData(
            id=item["oracle_id"],
            oracle_id=item["oracle_id"],
            name=item["name"],
            color_identity=color_identity,
            legalities={"commander": "legal"},
            type_line=item["type_line"],
            oracle_text=item["oracle_text"],
            cmc=item["cmc"],
        )
        lookup[card.oracle_id] = card
        deck_cards.append(
            DeckCard(
                oracle_id=card.oracle_id,
                name=card.name,
                is_owned=False,
                quantity=1,
                roles=item["roles"],
                package_ids=[package_id] if card.oracle_id in package_card_ids else [],
                selection_reason="test selection",
                synergy_score=0.0,
                color_identity=color_identity,
            )
        )

    package = PackageCluster(**pkg_raw)

    commander_card = DeckCard(
        oracle_id=commander.oracle_id,
        name=commander.name,
        is_owned=True,
        quantity=1,
        roles=[],
        selection_reason="commander",
        color_identity=color_identity,
    )
    deck = GeneratedDeck(
        deck_id=f"negative-fixture-{raw['fixture_id']}",
        session_id="negative-fixture-session",
        commander=commander_card,
        main_deck=deck_cards,
        role_breakdown={},
        quota_status=[],
        package_breakdown=[package],
        warnings=[],
        owned_count=0,
        owned_percentage=0.0,
        is_valid=True,
        validation_errors=[],
    )
    return commander, deck, lookup, [package]


def test_greta_and_toluz_negative_fixtures_are_valid_json() -> None:
    """Fixtures load without errors and have required top-level keys (SC-DECK-021)."""
    for path in (GRETA_FIXTURE, TOLUZ_FIXTURE):
        with path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        for key in ("fixture_id", "commander", "cards", "unsupported_package"):
            assert key in raw, f"{key!r} missing in {path.name}"


def test_greta_incoherent_deck_flags_off_plan_cards() -> None:
    """Greta fixture: off-plan generic pile is flagged by the coherence validator (SC-DECK-021)."""
    commander, deck, lookup, packages = _load_negative_fixture(GRETA_FIXTURE)
    report = StrategicCoherenceValidator().validate(
        commander=commander,
        commander_tags=[],
        deck=deck,
        all_cards_lookup=lookup,
        packages=packages,
    )

    flagged = (
        report.off_plan_count > 0
        or len(report.warning_card_oracle_ids) > 0
        or len(report.warnings) > 0
    )
    assert flagged, (
        "Expected coherence validator to flag off-plan cards for Greta "
        "(food-sacrifice plan). off_plan_count=%d, warning_card_oracle_ids=%r, warnings=%r"
        % (report.off_plan_count, report.warning_card_oracle_ids, report.warnings)
    )


def test_toluz_incoherent_deck_flags_off_plan_cards() -> None:
    """Toluz fixture: connive-less pile is flagged by the coherence validator (SC-DECK-021)."""
    commander, deck, lookup, packages = _load_negative_fixture(TOLUZ_FIXTURE)
    report = StrategicCoherenceValidator().validate(
        commander=commander,
        commander_tags=[],
        deck=deck,
        all_cards_lookup=lookup,
        packages=packages,
    )

    flagged = (
        report.off_plan_count > 0
        or len(report.warning_card_oracle_ids) > 0
        or len(report.warnings) > 0
    )
    assert flagged, (
        "Expected coherence validator to flag off-plan cards for Toluz "
        "(connive/discard plan). off_plan_count=%d, warning_card_oracle_ids=%r, warnings=%r"
        % (report.off_plan_count, report.warning_card_oracle_ids, report.warnings)
    )
