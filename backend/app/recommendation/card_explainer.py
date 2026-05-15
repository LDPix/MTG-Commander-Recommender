"""Card-level explanations for generated Commander decks."""
from __future__ import annotations

from app.models.deck import (
    CardExplanation,
    DeckCard,
    GeneratedDeck,
    PackageCluster,
    QuotaStatus,
)
from app.recommendation.deck_generator import BASIC_LAND_NAMES


class CardExplainer:
    """Render deterministic explanations from structured deck evidence."""

    def explain_deck(
        self,
        deck: GeneratedDeck,
        packages: list[PackageCluster],
        quota_status: list[QuotaStatus],
    ) -> dict[str, CardExplanation]:
        package_labels = {p.package_id: p.label for p in packages}
        quota_by_role = {q.role: q for q in quota_status}

        explanations: dict[str, CardExplanation] = {}
        for card in [deck.commander] + deck.main_deck:
            explanations[card.oracle_id] = self._explain_card(
                card=card,
                package_labels=package_labels,
                quota_by_role=quota_by_role,
            )
        return explanations

    def _explain_card(
        self,
        card: DeckCard,
        package_labels: dict[str, str],
        quota_by_role: dict[str, QuotaStatus],
    ) -> CardExplanation:
        roles = sorted(set(card.roles))
        package_ids = sorted(set(card.package_ids))
        evidence: list[str] = []

        if card.selection_reason:
            evidence.append(f"Selection reason: {card.selection_reason}.")

        if roles:
            evidence.append(f"Roles: {', '.join(roles)}.")
            quota_roles = [
                role for role in roles
                if role in quota_by_role and quota_by_role[role].target_min > 0
            ]
            if quota_roles:
                evidence.append(
                    f"Contributes to tracked quota(s): {', '.join(quota_roles)}."
                )

        if package_ids:
            labels = [package_labels.get(pid, pid) for pid in package_ids]
            evidence.append(f"Package membership: {', '.join(labels)}.")

        if card.synergy_score > 0:
            evidence.append(f"Synergy score: {card.synergy_score:.2f}.")

        evidence.append(
            "Owned card." if card.is_owned else "Missing card; shown as an upgrade path."
        )

        if card.name in BASIC_LAND_NAMES and not roles:
            roles = ["LAND"]
        if card.name in BASIC_LAND_NAMES and not any(
            "mana base" in e.lower() for e in evidence
        ):
            evidence.insert(0, "Basic land supports the mana base.")

        summary = self._summary(card, roles, package_ids, package_labels)
        return CardExplanation(
            oracle_id=card.oracle_id,
            name=card.name,
            summary=summary,
            evidence=evidence,
            roles=roles,
            package_ids=package_ids,
            synergy_score=card.synergy_score,
            is_owned=card.is_owned,
        )

    def _summary(
        self,
        card: DeckCard,
        roles: list[str],
        package_ids: list[str],
        package_labels: dict[str, str],
    ) -> str:
        ownership = "owned" if card.is_owned else "missing"
        if card.selection_reason == "commander":
            return f"{card.name} is the commander and anchors the deck's color identity and plan."
        if card.name in BASIC_LAND_NAMES:
            return f"{card.name} supports the mana base as an {ownership} basic land."

        parts: list[str] = []
        if roles:
            parts.append(f"fills {', '.join(roles[:2])}")
        if package_ids:
            labels = [package_labels.get(pid, pid) for pid in package_ids[:2]]
            parts.append(f"supports {', '.join(labels)}")
        if card.synergy_score > 0:
            parts.append(f"carries synergy score {card.synergy_score:.2f}")
        if not parts:
            parts.append(card.selection_reason or "adds legal utility")
        return (
            f"{card.name} is included as a {ownership} card because it "
            + "; ".join(parts)
            + "."
        )
