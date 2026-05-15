"""SC-GRAPH-001: Commander-conditioned synergy graph."""
from __future__ import annotations

import json
from typing import Protocol

from app.models.deck import DeckCard, SynergyEdge
from app.recommendation.role_taxonomy import CardRole, RoleTag


# Roles that are "specific" (not generic) — used for edge weight calculation
SPECIFIC_ROLES: frozenset[CardRole] = frozenset({
    CardRole.ARISTOCRATS_SYNERGY,
    CardRole.LANDFALL_SYNERGY,
    CardRole.BLINK_SYNERGY,
    CardRole.SPELLSLINGER_SYNERGY,
    CardRole.TRIBAL_SUPPORT,
    CardRole.RECURSION,
    CardRole.SACRIFICE_OUTLET,
    CardRole.TOKEN_MAKER,
})


class SynergyDataProvider(Protocol):
    def get_edges(
        self,
        commander_oracle_id: str | None,
        color_identity: list[str],
    ) -> list[SynergyEdge]: ...


class RoleTagSynergyProvider:
    """MVP: derives edges from shared specific role tags."""

    def get_edges(
        self,
        commander_oracle_id: str | None,
        color_identity: list[str],
    ) -> list[SynergyEdge]:
        return []  # edges computed in SynergyGraph.build() from role_tags


class FixtureSynergyProvider:
    """Loads synergy edges from a JSON fixture file."""

    def __init__(self, fixture_path: str) -> None:
        with open(fixture_path, "r") as f:
            raw = json.load(f)
        self._edges: list[SynergyEdge] = [SynergyEdge(**edge) for edge in raw]

    def get_edges(
        self,
        commander_oracle_id: str | None,
        color_identity: list[str],
    ) -> list[SynergyEdge]:
        return list(self._edges)


class SynergyGraph:
    """Weighted card-to-card synergy graph. Deterministic build."""

    def __init__(self) -> None:
        # adjacency: oracle_id -> {neighbor_id -> weight}
        self._adj: dict[str, dict[str, float]] = {}
        # normalized synergy scores per oracle_id
        self._scores: dict[str, float] = {}

    def build(
        self,
        candidate_cards: list[DeckCard],
        role_tags: dict[str, list[RoleTag]],
        provider: SynergyDataProvider,
        commander_oracle_id: str,
        color_identity: list[str],
    ) -> None:
        """Build graph. Provider edges + role-tag-derived edges (deduplicated, max weight wins)."""
        self._adj = {}
        self._scores = {}

        card_ids = {c.oracle_id for c in candidate_cards}

        # Step 1: Get provider edges
        provider_edges = provider.get_edges(commander_oracle_id, color_identity)

        # Step 2: Compute role-tag edges
        # Build mapping: oracle_id -> set of specific roles
        specific_role_map: dict[str, set[CardRole]] = {}
        for card in candidate_cards:
            card_specific_roles: set[CardRole] = set()
            for tag in role_tags.get(card.oracle_id, []):
                if tag.role in SPECIFIC_ROLES:
                    card_specific_roles.add(tag.role)
            if card_specific_roles:
                specific_role_map[card.oracle_id] = card_specific_roles

        role_edges: list[SynergyEdge] = []
        specific_cards = sorted(specific_role_map.keys())  # deterministic order
        num_specific_roles = len(SPECIFIC_ROLES)

        for i, id_a in enumerate(specific_cards):
            for id_b in specific_cards[i + 1:]:
                shared = specific_role_map[id_a] & specific_role_map[id_b]
                if shared:
                    weight = min(1.0, len(shared) / num_specific_roles)
                    role_edges.append(
                        SynergyEdge(
                            card_a_oracle_id=id_a,
                            card_b_oracle_id=id_b,
                            weight=weight,
                            metric="role_tag",
                            sample_size=0,
                        )
                    )

        # Step 3: Merge all edges, keep max weight per pair
        # Normalize pair key as (min_id, max_id)
        merged: dict[tuple[str, str], float] = {}

        all_edges = list(provider_edges) + role_edges
        for edge in all_edges:
            a, b = edge.card_a_oracle_id, edge.card_b_oracle_id
            # Only include edges where both cards are in the candidate pool
            if a not in card_ids or b not in card_ids:
                continue
            key = (min(a, b), max(a, b))
            weight = max(0.0, min(1.0, edge.weight))  # clamp
            if key not in merged or weight > merged[key]:
                merged[key] = weight

        # Step 4: Build adjacency dict
        for (a, b), weight in merged.items():
            if a not in self._adj:
                self._adj[a] = {}
            if b not in self._adj:
                self._adj[b] = {}
            self._adj[a][b] = weight
            self._adj[b][a] = weight

        # Step 5: Compute raw scores (sum of edge weights per card)
        raw_scores: dict[str, float] = {}
        for card in candidate_cards:
            neighbors = self._adj.get(card.oracle_id, {})
            raw_scores[card.oracle_id] = sum(neighbors.values())

        # Step 6: Min-max normalize
        if raw_scores:
            min_score = min(raw_scores.values())
            max_score = max(raw_scores.values())
            if max_score > min_score:
                self._scores = {
                    oid: (score - min_score) / (max_score - min_score)
                    for oid, score in raw_scores.items()
                }
            else:
                # All same score — use 0.5 for cards with edges, 0.0 otherwise
                self._scores = {
                    oid: 0.5 if score > 0 else 0.0
                    for oid, score in raw_scores.items()
                }
        else:
            self._scores = {}

    def get_synergy_score(self, oracle_id: str) -> float:
        """Normalized sum of edge weights for a card (0.0 if absent)."""
        return self._scores.get(oracle_id, 0.0)

    def get_neighbors(self, oracle_id: str, top_k: int = 10) -> list[str]:
        """Top-k neighbors by edge weight, deterministic order."""
        neighbors = self._adj.get(oracle_id, {})
        # Sort by weight descending, then oracle_id ascending for determinism
        sorted_neighbors = sorted(
            neighbors.items(),
            key=lambda item: (-item[1], item[0]),
        )
        return [oid for oid, _ in sorted_neighbors[:top_k]]
