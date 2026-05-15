"""SC-GRAPH-002: Detect cohesive card clusters from synergy graph and role tags."""
from __future__ import annotations

from app.models.deck import DeckCard, PackageCluster
from app.recommendation.role_taxonomy import CardRole, RoleTag
from app.recommendation.synergy_graph import SPECIFIC_ROLES, SynergyGraph


class PackageDetector:
    def detect(
        self,
        candidate_cards: list[DeckCard],
        role_tags: dict[str, list[RoleTag]],
        graph: SynergyGraph,
        min_package_size: int = 4,
    ) -> list[PackageCluster]:
        """Cluster by shared SPECIFIC_ROLE tags.

        Algorithm:
        1. For each SPECIFIC_ROLE in SPECIFIC_ROLES:
           a. Collect all cards that have that role (from role_tags)
           b. If count >= min_package_size: create a PackageCluster
        2. Confidence = avg synergy_score of cluster cards (from graph)
           If no graph data: confidence = 0.3
        3. top_roles = [role.value]
        4. package_id = role.value.lower()
        5. label = "" (filled by PackageLabeler)
        6. Cards may belong to multiple clusters
        7. Sort clusters by len(card_oracle_ids) descending, then package_id for determinism
        """
        candidate_ids = {c.oracle_id for c in candidate_cards}
        clusters: list[PackageCluster] = []

        for role in sorted(SPECIFIC_ROLES, key=lambda r: r.value):
            matching_ids: list[str] = []
            for oracle_id, tags in role_tags.items():
                if oracle_id not in candidate_ids:
                    continue
                for tag in tags:
                    if tag.role == role:
                        matching_ids.append(oracle_id)
                        break

            if len(matching_ids) < min_package_size:
                continue

            # Compute confidence from synergy scores
            scores = [graph.get_synergy_score(oid) for oid in matching_ids]
            avg_score = sum(scores) / len(scores) if scores else 0.0
            confidence = avg_score if avg_score > 0.0 else 0.3

            clusters.append(
                PackageCluster(
                    package_id=role.value.lower(),
                    label="",  # filled by PackageLabeler
                    confidence=confidence,
                    card_oracle_ids=sorted(matching_ids),  # deterministic
                    top_roles=[role.value],
                )
            )

        # Sort by size descending, then package_id ascending
        clusters.sort(key=lambda c: (-len(c.card_oracle_ids), c.package_id))
        return clusters
