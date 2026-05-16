"""Commander recommendation ranker and explainer (SC-CMD-003, SC-CMD-004)."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models.card import CardData
from app.models.score_log import DATA_VERSION, ScoreLog
from app.recommendation.commander_pool import CandidateCommander, CommanderPool
from app.recommendation.commander_profiles import SupportTier
from app.recommendation.commander_scorer import CommanderFitScore, CommanderScorer
from app.recommendation.legality_validator import LegalityValidator
from app.recommendation.role_taxonomy import CardRole

# (keywords_to_match, archetype_label) — first match wins
_ARCHETYPE_RULES: list[tuple[list[str], str]] = [
    (["creature you control dies", "experience counter", "sacrifice"], "Aristocrats"),
    (["landfall", "land enters", "land card"], "Landfall"),
    (["whenever you cast", "instant or sorcery", "noncreature spell"], "Spellslinger"),
    (["proliferate", "counter", "token", "create a"], "Tokens/Counters"),
    (["graveyard", "return from your graveyard", "reanimate"], "Graveyard"),
    (["exile and return", "enters the battlefield"], "Blink/ETB"),
]


def _infer_archetype(name: str, oracle_text: str | None) -> str:
    text = (oracle_text or "").lower()
    for keywords, label in _ARCHETYPE_RULES:
        if any(kw in text for kw in keywords):
            return label
    return "Midrange"


@dataclass
class CommanderExplanation:
    summary: str
    owned_highlights: list[str]
    archetype_label: str
    missing_core_notes: list[str]


@dataclass
class CommanderRecommendation:
    oracle_id: str
    name: str
    color_identity: list[str]
    fit_score: float
    archetype: str
    owned_count: int
    owned_percentage: float
    explanation: CommanderExplanation
    roles_covered: dict[str, int]
    support_tier: SupportTier = "fallback"
    score_log: ScoreLog | None = None


class CommanderRecommender:
    """Ranks commanders by collection fit and generates explanations."""

    def __init__(self, pool: CommanderPool, scorer: CommanderScorer) -> None:
        self._pool = pool
        self._scorer = scorer
        self._validator = LegalityValidator()

    def recommend(
        self,
        owned_oracle_ids: set[str],
        owned_cards: list[CardData],
        supported_oracle_ids: set[str] | None = None,
        top_k: int = 10,
        session_id: str = "",
    ) -> list[CommanderRecommendation]:
        """Return top_k commanders ranked by collection fit score.

        Deterministic for identical inputs: ties broken by oracle_id.
        """
        candidates = self._pool.build_candidate_pool(
            owned_oracle_ids=owned_oracle_ids,
            supported_oracle_ids=supported_oracle_ids,
        )

        results: list[CommanderRecommendation] = []
        for candidate in candidates:
            cmd_card = self._to_card_data(candidate)
            score = self._scorer.compute_fit_score(cmd_card, owned_cards)
            archetype = _infer_archetype(candidate.name, candidate.oracle_text)
            explanation = self._explain(candidate, score, owned_cards, archetype)

            results.append(
                CommanderRecommendation(
                    oracle_id=candidate.oracle_id,
                    name=candidate.name,
                    color_identity=candidate.color_identity,
                    fit_score=score.total_score,
                    archetype=archetype,
                    owned_count=score.owned_count,
                    owned_percentage=score.owned_percentage,
                    explanation=explanation,
                    roles_covered=score.roles_covered,
                    support_tier=candidate.support_tier,
                    score_log=self._score_log(
                        session_id=session_id,
                        subject_id=candidate.oracle_id,
                        score=score,
                        explanation=explanation,
                    ),
                )
            )

        results.sort(key=lambda r: (-r.fit_score, r.oracle_id))
        return results[:top_k]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _to_card_data(self, candidate: CandidateCommander) -> CardData:
        return CardData(
            id=f"id-{candidate.oracle_id}",
            oracle_id=candidate.oracle_id,
            name=candidate.name,
            color_identity=candidate.color_identity,
            legalities={"commander": "legal"},
            type_line=candidate.type_line,
            oracle_text=candidate.oracle_text,
            cmc=candidate.cmc,
        )

    def _explain(
        self,
        candidate: CandidateCommander,
        score: CommanderFitScore,
        owned_cards: list[CardData],
        archetype: str,
    ) -> CommanderExplanation:
        """SC-CMD-004: Template-based explanation using real score data."""
        cmd_card = self._to_card_data(candidate)
        valid_owned = self._validator.filter_legal_cards(owned_cards)
        valid_owned = self._validator.filter_color_identity(cmd_card, valid_owned)

        highlights = [c.name for c in valid_owned[:3]]

        if highlights:
            summary = (
                f"Your collection has {score.owned_count} cards that work with "
                f"{candidate.name} ({archetype}), including {', '.join(highlights)}."
            )
        else:
            summary = (
                f"{candidate.name} is a strong {archetype} commander, but your "
                f"collection has limited support ({score.owned_count} matching cards)."
            )

        missing_notes: list[str] = []
        if score.roles_covered.get(CardRole.RAMP.value, 0) == 0:
            missing_notes.append("Missing ramp support.")
        if score.roles_covered.get(CardRole.CARD_DRAW.value, 0) == 0:
            missing_notes.append("Missing card draw support.")
        if score.roles_covered.get(CardRole.SPOT_REMOVAL.value, 0) == 0:
            missing_notes.append("Missing spot removal.")

        return CommanderExplanation(
            summary=summary,
            owned_highlights=highlights,
            archetype_label=archetype,
            missing_core_notes=missing_notes,
        )

    def _score_log(
        self,
        session_id: str,
        subject_id: str,
        score: CommanderFitScore,
        explanation: CommanderExplanation,
    ) -> ScoreLog:
        score_components = {
            "total_score": score.total_score,
            "owned_percentage": score.owned_percentage,
            **{
                key: round(value, 6)
                for key, value in sorted(score.score_breakdown.items())
            },
        }
        selected_reasons = [explanation.summary]
        selected_reasons.extend(explanation.missing_core_notes)
        return ScoreLog(
            session_id=session_id,
            scope="commander_recommendation",
            data_version=DATA_VERSION,
            subject_id=subject_id,
            score_components=score_components,
            selected_reasons=selected_reasons,
            warnings=list(explanation.missing_core_notes),
        )
