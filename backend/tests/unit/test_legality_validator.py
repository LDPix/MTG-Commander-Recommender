import pytest

from app.models.card import CardData
from app.recommendation.legality_validator import DeckEntry, LegalityValidator


def make_card(
    oracle_id: str,
    name: str,
    color_identity: list[str],
    *,
    legality: str = "legal",
    type_line: str = "Instant",
) -> CardData:
    return CardData(
        id=f"id-{oracle_id}",
        oracle_id=oracle_id,
        name=name,
        color_identity=color_identity,
        legalities={"commander": legality},
        type_line=type_line,
    )


def make_commander(oracle_id: str, name: str, colors: list[str]) -> CardData:
    return make_card(
        oracle_id, name, colors, type_line="Legendary Creature — Human"
    )


# ── SC-LEGAL-001: Card Legality ──────────────────────────────────────────────


class TestCardLegality:
    def test_banned_card_is_rejected(self):
        validator = LegalityValidator()
        banned = make_card("b-001", "Banned Card", [], legality="banned")
        result = validator.validate_card_legality([banned])
        assert not result.valid
        assert len(result.errors) == 1
        assert result.errors[0].error_type == "banned"
        assert result.errors[0].card_name == "Banned Card"

    def test_commander_legal_card_is_allowed(self):
        validator = LegalityValidator()
        legal = make_card("l-001", "Sol Ring", [])
        result = validator.validate_card_legality([legal])
        assert result.valid
        assert result.errors == []

    def test_illegal_card_removed_from_candidate_pool(self):
        validator = LegalityValidator()
        illegal = make_card("ill-001", "Not Legal Card", ["W"], legality="not_legal")
        legal = make_card("leg-001", "Legal Card", ["W"])
        filtered = validator.filter_legal_cards([illegal, legal])
        assert len(filtered) == 1
        assert filtered[0].oracle_id == "leg-001"

    def test_legality_error_is_actionable(self):
        validator = LegalityValidator()
        banned = make_card("b-001", "Banned Card", [], legality="banned")
        result = validator.validate_card_legality([banned])
        error = result.errors[0]
        assert error.card_name == "Banned Card"
        assert error.oracle_id == "b-001"
        assert error.reason
        assert error.error_type in ("banned", "illegal")

    def test_validator_reused_by_deck_generation(self):
        validator = LegalityValidator()
        card = make_card("x-001", "Test Card", [])
        r1 = validator.validate_card_legality([card])
        r2 = validator.validate_card_legality([card])
        assert r1.valid == r2.valid is True


# ── SC-LEGAL-002: Color Identity ─────────────────────────────────────────────


class TestColorIdentity:
    def test_off_color_card_rejected(self):
        validator = LegalityValidator()
        commander = make_commander("cmd-001", "Mono White Commander", ["W"])
        blue_card = make_card("u-001", "Blue Card", ["U"])
        result = validator.validate_color_identity(commander, [blue_card])
        assert not result.valid
        assert any(e.oracle_id == "u-001" for e in result.errors)

    def test_colorless_card_allowed(self):
        validator = LegalityValidator()
        commander = make_commander("cmd-001", "Mono White Commander", ["W"])
        sol_ring = make_card("sr-001", "Sol Ring", [])
        result = validator.validate_color_identity(commander, [sol_ring])
        assert result.valid

    def test_land_with_off_color_identity_rejected(self):
        validator = LegalityValidator()
        commander = make_commander("cmd-001", "Mono White Commander", ["W"])
        breeding_pool = make_card(
            "bp-001", "Breeding Pool", ["G", "U"], type_line="Land — Forest Island"
        )
        result = validator.validate_color_identity(commander, [breeding_pool])
        assert not result.valid
        assert any(e.oracle_id == "bp-001" for e in result.errors)

    def test_multicolor_commander_allows_matching_cards(self):
        validator = LegalityValidator()
        commander = make_commander("cmd-001", "Meren of Clan Nel Toth", ["B", "G"])
        black_card = make_card("blk-001", "Dark Ritual", ["B"])
        green_card = make_card("grn-001", "Cultivate", ["G"])
        colorless_card = make_card("clr-001", "Sol Ring", [])
        result = validator.validate_color_identity(
            commander, [black_card, green_card, colorless_card]
        )
        assert result.valid

    def test_color_identity_error_lists_cards(self):
        validator = LegalityValidator()
        commander = make_commander("cmd-001", "Mono White Commander", ["W"])
        red_card = make_card("r-001", "Red Card", ["R"])
        blue_card = make_card("u-001", "Blue Card", ["U"])
        result = validator.validate_color_identity(commander, [red_card, blue_card])
        assert not result.valid
        error_ids = {e.oracle_id for e in result.errors}
        assert "r-001" in error_ids
        assert "u-001" in error_ids


# ── SC-LEGAL-003: Singleton and Quantity Rules ───────────────────────────────


class TestSingletonRules:
    def test_duplicate_nonbasic_rejected(self):
        validator = LegalityValidator()
        entries = [
            DeckEntry(oracle_id="sr-001", name="Sol Ring", quantity=2, is_basic_land=False)
        ]
        result = validator.validate_singleton(entries)
        assert not result.valid
        assert any(e.error_type == "duplicate" for e in result.errors)

    def test_basic_land_duplicates_allowed(self):
        validator = LegalityValidator()
        entries = [
            DeckEntry(oracle_id="forest-001", name="Forest", quantity=10, is_basic_land=True)
        ]
        result = validator.validate_singleton(entries)
        assert result.valid

    def test_owned_quantity_respected(self):
        validator = LegalityValidator()
        owned = {"sr-001": 0}
        entries = [
            DeckEntry(oracle_id="sr-001", name="Sol Ring", quantity=1, is_basic_land=False)
        ]
        result = validator.validate_singleton(entries, owned_quantities=owned)
        assert any(w.warning_type == "missing_card" for w in result.warnings)

    def test_missing_card_marked_missing(self):
        validator = LegalityValidator()
        owned = {"sr-001": 0}
        entries = [
            DeckEntry(oracle_id="sr-001", name="Sol Ring", quantity=1, is_basic_land=False)
        ]
        result = validator.validate_singleton(entries, owned_quantities=owned)
        assert any("Sol Ring" in w.message for w in result.warnings)

    def test_singleton_errors_are_actionable(self):
        validator = LegalityValidator()
        entries = [
            DeckEntry(
                oracle_id="card-001", name="Duplicate Card", quantity=2, is_basic_land=False
            )
        ]
        result = validator.validate_singleton(entries)
        assert not result.valid
        error = result.errors[0]
        assert error.oracle_id == "card-001"
        assert error.reason


# ── SC-DECK-007: Full Deck Validation ────────────────────────────────────────


def _make_main_deck(count: int, colors: list[str] = []) -> list[tuple[CardData, int]]:
    return [
        (make_card(f"card-{i:03d}", f"Card {i}", colors, type_line="Sorcery"), 1)
        for i in range(count)
    ]


class TestDeckValidation:
    def test_valid_deck_passes_validation(self):
        validator = LegalityValidator()
        commander = make_commander("cmd-001", "Test Commander", ["W"])
        main_deck = _make_main_deck(99)
        result = validator.validate_deck(commander, main_deck)
        assert result.valid
        assert result.errors == []

    def test_wrong_card_count_fails_validation(self):
        validator = LegalityValidator()
        commander = make_commander("cmd-001", "Test Commander", ["W"])
        main_deck = _make_main_deck(80)  # 81 total — not 100
        result = validator.validate_deck(commander, main_deck)
        assert not result.valid
        assert any("100" in e.reason for e in result.errors)

    def test_off_color_card_fails_validation(self):
        validator = LegalityValidator()
        commander = make_commander("cmd-001", "Mono White Commander", ["W"])
        main_deck = _make_main_deck(98)
        off_color = make_card("u-001", "Blue Card", ["U"])
        main_deck.append((off_color, 1))  # 99 total ✓
        result = validator.validate_deck(commander, main_deck)
        assert not result.valid
        assert any(e.error_type == "off_color" for e in result.errors)

    def test_duplicate_nonbasic_fails_validation(self):
        validator = LegalityValidator()
        commander = make_commander("cmd-001", "Test Commander", ["W"])
        main_deck = _make_main_deck(97)
        sol_ring = make_card("sr-001", "Sol Ring", [])
        main_deck.append((sol_ring, 2))  # 97 + 2 = 99 total ✓, but singleton violated
        result = validator.validate_deck(commander, main_deck)
        assert not result.valid
        assert any(e.error_type == "duplicate" for e in result.errors)

    def test_validation_warnings_are_visible(self):
        validator = LegalityValidator()
        commander = make_commander("cmd-001", "Test Commander", ["W"])
        main_deck = _make_main_deck(99)
        owned = {card.oracle_id: 0 for card, _ in main_deck[:5]}
        result = validator.validate_deck(commander, main_deck, owned_quantities=owned)
        assert result.valid  # still valid — missing cards are warnings, not errors
        assert result.warnings
        assert all(w.warning_type == "missing_card" for w in result.warnings)
