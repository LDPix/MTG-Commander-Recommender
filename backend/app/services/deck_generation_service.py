"""Deck generation service layer (SC-API-003 prerequisite)."""
from __future__ import annotations

from app.data_pipeline.card_resolver import CardNotFoundError, CardResolver
from app.models.card import CanonicalCard, CardData
from collections import defaultdict

from app.models.deck import DeckCard, GeneratedDeck, PackageCluster
from app.models.score_log import DATA_VERSION, ScoreLog
from app.recommendation.card_explainer import CardExplainer
from app.recommendation.deck_candidate_pool import DeckCandidatePool
from app.recommendation.deck_generator import DeckGenerator
from app.recommendation.package_detector import PackageDetector
from app.recommendation.package_labeler import PackageLabeler
from app.recommendation.quota_config import adjust_quotas_for_commander, BASELINE_QUOTAS as _BASELINE_QUOTAS
from app.recommendation.role_taxonomy import RoleTag
from app.data_pipeline.scryfall_tagger import get_scryfall_tagger_store
from app.recommendation.role_tagger import HybridTagger
from app.recommendation.synergy_graph import RoleTagSynergyProvider, SynergyGraph, SynergyDataProvider
from app.recommendation.upgrade_suggester import UpgradeSuggester
from app.repositories.collection_repo import CollectionRepository


def _canonical_to_card_data(canonical: CanonicalCard) -> CardData:
    return CardData(
        id=canonical.oracle_id,
        oracle_id=canonical.oracle_id,
        name=canonical.name,
        color_identity=canonical.color_identity,
        legalities=canonical.legalities,
        type_line=canonical.type_line,
        oracle_text=canonical.oracle_text,
        mana_cost=canonical.mana_cost,
        cmc=canonical.cmc,
        keywords=canonical.keywords,
        card_faces=canonical.card_faces,
        layout=canonical.layout,
        edhrec_rank=canonical.edhrec_rank,
        rarity=canonical.rarity,
    )


class DeckGenerationService:
    def __init__(
        self,
        collection_repo: CollectionRepository,
        card_resolver: CardResolver,
        synergy_provider: SynergyDataProvider | None = None,
    ) -> None:
        self._repo = collection_repo
        self._resolver = card_resolver
        self._tagger = HybridTagger(get_scryfall_tagger_store())
        self._synergy_provider = synergy_provider or RoleTagSynergyProvider()

    def generate_deck(
        self,
        session_id: str,
        commander_oracle_id: str,
    ) -> GeneratedDeck | None:
        """Return GeneratedDeck or None if collection not found.

        Raises ValueError if commander is not legal or not in catalog.
        """
        # Step 1: Load collection
        collection = self._repo.get_collection_by_session(session_id)
        if collection is None:
            return None

        # Step 2: Load commander
        try:
            commander_canonical = self._resolver.resolve_by_oracle_id(commander_oracle_id)
        except CardNotFoundError as e:
            raise ValueError(f"Commander not found: {commander_oracle_id}") from e

        commander = _canonical_to_card_data(commander_canonical)

        # Step 3: Validate commander legality
        if commander.legalities.get("commander") != "legal":
            raise ValueError(
                f"Commander {commander.name!r} is not legal in Commander format."
            )
        if "Legendary Creature" not in commander.type_line and "Legendary" not in commander.type_line:
            raise ValueError(
                f"{commander.name!r} is not a Legendary Creature and cannot be a commander."
            )

        # Step 4: Load collection items and resolve cards
        items = self._repo.get_items(collection.id)
        owned_oracle_ids: set[str] = set()
        owned_cards: list[CardData] = []

        for item in items:
            owned_oracle_ids.add(item.oracle_id)
            try:
                canonical = self._resolver.resolve_by_oracle_id(item.oracle_id)
                owned_cards.append(_canonical_to_card_data(canonical))
            except CardNotFoundError:
                pass

        # Step 5: Build all_cards from resolver
        all_canonicals = self._resolver.get_all()
        all_cards = [_canonical_to_card_data(c) for c in all_canonicals]

        # Build oracle_id -> CardData lookup
        all_cards_lookup: dict[str, CardData] = {c.oracle_id: c for c in all_cards}

        # Step 6: Build role_tags for all cards
        role_tags: dict[str, list[RoleTag]] = {}
        for card in all_cards:
            tags = self._tagger.tag(card)
            if tags:
                role_tags[card.oracle_id] = tags

        commander_tags = role_tags.get(commander.oracle_id, [])

        # Step 7: Build candidate pool
        pool_builder = DeckCandidatePool()
        candidate_pool = pool_builder.build(
            commander=commander,
            owned_cards=owned_cards,
            all_cards=all_cards,
            role_tags=role_tags,
            owned_oracle_ids=owned_oracle_ids,
        )

        # Step 8: Build synergy graph
        graph = SynergyGraph()
        graph.build(
            candidate_cards=candidate_pool,
            role_tags=role_tags,
            provider=self._synergy_provider,
            commander_oracle_id=commander.oracle_id,
            color_identity=commander.color_identity,
        )

        # Step 9: Detect and label packages
        detector = PackageDetector()
        packages = detector.detect(candidate_pool, role_tags, graph)
        labeler = PackageLabeler()
        packages = [labeler.label(p) for p in packages]

        # Step 10: Adjust quotas
        quotas = adjust_quotas_for_commander(
            baseline=list(_BASELINE_QUOTAS),
            commander=commander,
            commander_tags=commander_tags,
        )

        # Step 11: Generate deck
        generator = DeckGenerator()
        deck = generator.generate(
            commander=commander,
            commander_tags=commander_tags,
            candidate_pool=candidate_pool,
            role_tags=role_tags,
            graph=graph,
            packages=packages,
            session_id=session_id,
            quotas=quotas,
            all_cards_lookup=all_cards_lookup,
        )

        enriched_candidate_pool = _enrich_candidate_pool(candidate_pool, graph, packages)
        deck.upgrade_suggestions = UpgradeSuggester().suggest(
            commander=commander,
            generated_deck=deck,
            candidate_pool=enriched_candidate_pool,
            packages=packages,
            quota_status=deck.quota_status,
        )
        deck.card_explanations = CardExplainer().explain_deck(
            deck=deck,
            packages=packages,
            quota_status=deck.quota_status,
        )
        deck.score_logs = _build_deck_score_logs(
            session_id=session_id,
            deck=deck,
        )

        return deck


def _enrich_candidate_pool(
    candidate_pool: list[DeckCard],
    graph: SynergyGraph,
    packages: list[PackageCluster],
) -> list[DeckCard]:
    card_to_packages: dict[str, list[str]] = defaultdict(list)
    for package in packages:
        for oracle_id in package.card_oracle_ids:
            card_to_packages[oracle_id].append(package.package_id)

    return [
        card.model_copy(
            update={
                "synergy_score": graph.get_synergy_score(card.oracle_id),
                "package_ids": sorted(card_to_packages.get(card.oracle_id, [])),
            }
        )
        for card in candidate_pool
    ]


def _build_deck_score_logs(session_id: str, deck: GeneratedDeck) -> list[ScoreLog]:
    logs: list[ScoreLog] = []
    for card in [deck.commander] + sorted(deck.main_deck, key=lambda c: c.oracle_id):
        logs.append(
            ScoreLog(
                session_id=session_id,
                scope="deck_generation",
                data_version=DATA_VERSION,
                subject_id=card.oracle_id,
                score_components={
                    "quantity": float(card.quantity),
                    "synergy_score": round(card.synergy_score, 6),
                    "owned": 1.0 if card.is_owned else 0.0,
                    "role_count": float(len(card.roles)),
                    "package_count": float(len(card.package_ids)),
                },
                selected_reasons=[card.selection_reason] if card.selection_reason else [],
                warnings=[] if card.is_owned else ["missing_card"],
            )
        )
    return logs
