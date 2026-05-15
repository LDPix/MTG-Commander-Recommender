"""Commander candidate pool builder (SC-CMD-001)."""
from __future__ import annotations

from dataclasses import dataclass

from app.data_pipeline.card_resolver import CardResolver
from app.models.card import CanonicalCard


@dataclass
class CandidateCommander:
    oracle_id: str
    name: str
    color_identity: list[str]
    type_line: str
    oracle_text: str | None
    cmc: float
    is_owned: bool


class CommanderPool:
    """Builds a pool of Commander-eligible candidates from the card catalog."""

    def __init__(self, card_resolver: CardResolver) -> None:
        self._resolver = card_resolver

    def is_commander_eligible(self, card: CanonicalCard) -> bool:
        """Return True if the card can legally serve as a commander."""
        if "Legendary Creature" in card.type_line:
            return True
        if card.card_faces and any(
            "Legendary Creature" in face.type_line for face in card.card_faces
        ):
            return True
        # Explicit "can be your commander" oracle text (e.g. non-traditional commanders)
        texts: list[str] = []
        if card.oracle_text:
            texts.append(card.oracle_text)
        if card.card_faces:
            texts.extend(f.oracle_text for f in card.card_faces if f.oracle_text)
        return "can be your commander" in " ".join(texts).lower()

    def build_candidate_pool(
        self,
        owned_oracle_ids: set[str],
        supported_oracle_ids: set[str] | None = None,
    ) -> list[CandidateCommander]:
        """Return legal, eligible commanders sorted deterministically.

        Args:
            owned_oracle_ids: Oracle IDs the user owns (marks is_owned).
            supported_oracle_ids: If provided, restrict pool to this set.

        Returns:
            Sorted list of CandidateCommander objects.
        """
        candidates: list[CandidateCommander] = []

        for card in sorted(self._resolver.get_all(), key=lambda c: c.oracle_id):
            if not self.is_commander_eligible(card):
                continue
            if card.legalities.get("commander") != "legal":
                continue
            if supported_oracle_ids is not None and card.oracle_id not in supported_oracle_ids:
                continue

            candidates.append(
                CandidateCommander(
                    oracle_id=card.oracle_id,
                    name=card.name,
                    color_identity=list(card.color_identity),
                    type_line=card.type_line,
                    oracle_text=card.oracle_text,
                    cmc=card.cmc,
                    is_owned=card.oracle_id in owned_oracle_ids,
                )
            )

        return candidates
