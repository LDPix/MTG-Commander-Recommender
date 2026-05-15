"""Missing-card upgrade suggestions for generated Commander decks."""
from __future__ import annotations

from app.models.card import CardData
from app.models.deck import (
    DeckCard,
    GeneratedDeck,
    PackageCluster,
    QuotaStatus,
    UpgradeSuggestion,
)


PRIORITY_ORDER: dict[str, int] = {"core": 0, "recommended": 1, "optional": 2}
HIGH_SYNERGY_THRESHOLD = 0.7


class UpgradeSuggester:
    """Suggest deterministic, evidence-led missing upgrades."""

    def suggest(
        self,
        commander: CardData,
        generated_deck: GeneratedDeck,
        candidate_pool: list[DeckCard],
        packages: list[PackageCluster],
        quota_status: list[QuotaStatus],
        max_suggestions: int = 10,
    ) -> list[UpgradeSuggestion]:
        underfilled_roles = {
            q.role for q in quota_status if q.actual_count < q.target_min
        }
        deck_package_counts = self._deck_package_counts(generated_deck, packages)
        package_labels = {p.package_id: p.label for p in packages}
        card_to_packages = self._card_to_packages(packages)
        selected_missing_ids = {
            c.oracle_id for c in generated_deck.main_deck if not c.is_owned
        }

        candidates_by_id: dict[str, DeckCard] = {
            c.oracle_id: c
            for c in candidate_pool
            if not c.is_owned and c.oracle_id != commander.oracle_id
        }
        for card in generated_deck.main_deck:
            if not card.is_owned and card.oracle_id != commander.oracle_id:
                candidates_by_id.setdefault(card.oracle_id, card)

        suggestions: list[UpgradeSuggestion] = []
        for card in candidates_by_id.values():
            package_ids = sorted(
                set(card.package_ids) | set(card_to_packages.get(card.oracle_id, []))
            )
            improves_roles = sorted(set(card.roles))
            improves_packages = [
                package_id for package_id in package_ids
                if deck_package_counts.get(package_id, 0) > 0 or package_id in card.package_ids
            ]

            fills_quota_gap = bool(set(improves_roles) & underfilled_roles)
            strong_package = any(
                deck_package_counts.get(pid, 0) >= 3 for pid in improves_packages
            )
            high_synergy = card.synergy_score >= HIGH_SYNERGY_THRESHOLD
            already_selected = card.oracle_id in selected_missing_ids

            if not (
                already_selected
                or fills_quota_gap
                or improves_packages
                or improves_roles
                or card.synergy_score > 0
            ):
                continue

            priority = self._priority(
                fills_quota_gap=fills_quota_gap,
                high_synergy=high_synergy,
                strong_package=strong_package,
                improves_packages=improves_packages,
                already_selected=already_selected,
                synergy_score=card.synergy_score,
            )
            impact_score = self._impact_score(
                card=card,
                already_selected=already_selected,
                fills_quota_gap=fills_quota_gap,
                high_synergy=high_synergy,
                strong_package=strong_package,
                improves_packages=improves_packages,
            )
            reason = self._reason(
                card=card,
                roles=improves_roles,
                package_ids=improves_packages,
                package_labels=package_labels,
                fills_quota_gap=fills_quota_gap,
                high_synergy=high_synergy,
                already_selected=already_selected,
            )

            suggestions.append(
                UpgradeSuggestion(
                    oracle_id=card.oracle_id,
                    name=card.name,
                    priority=priority,
                    improves_roles=improves_roles,
                    improves_packages=improves_packages,
                    reason=reason,
                    impact_score=round(impact_score, 3),
                    replaces_or_supplements=[],
                )
            )

        suggestions.sort(
            key=lambda s: (
                PRIORITY_ORDER[s.priority],
                -s.impact_score,
                s.name,
                s.oracle_id,
            )
        )
        return suggestions[:max_suggestions]

    def _priority(
        self,
        fills_quota_gap: bool,
        high_synergy: bool,
        strong_package: bool,
        improves_packages: list[str],
        already_selected: bool,
        synergy_score: float,
    ) -> str:
        if fills_quota_gap or high_synergy or strong_package:
            return "core"
        if improves_packages or already_selected or synergy_score >= 0.3:
            return "recommended"
        return "optional"

    def _impact_score(
        self,
        card: DeckCard,
        already_selected: bool,
        fills_quota_gap: bool,
        high_synergy: bool,
        strong_package: bool,
        improves_packages: list[str],
    ) -> float:
        score = card.synergy_score
        if already_selected:
            score += 0.35
        if fills_quota_gap:
            score += 0.3
        if high_synergy:
            score += 0.2
        if strong_package:
            score += 0.25
        score += min(0.15, 0.05 * len(improves_packages))
        return score

    def _reason(
        self,
        card: DeckCard,
        roles: list[str],
        package_ids: list[str],
        package_labels: dict[str, str],
        fills_quota_gap: bool,
        high_synergy: bool,
        already_selected: bool,
    ) -> str:
        parts: list[str] = []
        if roles:
            parts.append(f"improves {', '.join(roles[:2])}")
        if fills_quota_gap and roles:
            parts.append("addresses an underfilled quota")
        if package_ids:
            package_names = [package_labels.get(pid, pid) for pid in package_ids[:2]]
            parts.append(f"supports {', '.join(package_names)}")
        if high_synergy:
            parts.append(f"has a strong synergy score ({card.synergy_score:.2f})")
        elif card.synergy_score > 0:
            parts.append(f"has a synergy score of {card.synergy_score:.2f}")
        if already_selected:
            parts.append("is already in the generated deck as a missing card")
        if not parts:
            parts.append("adds broad utility to the legal candidate pool")
        return f"{card.name} is suggested because it " + "; ".join(parts) + "."

    def _deck_package_counts(
        self,
        generated_deck: GeneratedDeck,
        packages: list[PackageCluster],
    ) -> dict[str, int]:
        deck_ids = {c.oracle_id for c in generated_deck.main_deck}
        counts: dict[str, int] = {}
        for package in packages:
            counts[package.package_id] = len(deck_ids & set(package.card_oracle_ids))
        return counts

    def _card_to_packages(self, packages: list[PackageCluster]) -> dict[str, list[str]]:
        card_to_packages: dict[str, list[str]] = {}
        for package in packages:
            for oracle_id in package.card_oracle_ids:
                card_to_packages.setdefault(oracle_id, []).append(package.package_id)
        return card_to_packages
