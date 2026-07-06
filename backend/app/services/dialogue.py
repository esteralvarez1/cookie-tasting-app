from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
import re as _re

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.entities import ConversationTurn, EvaluationAnalysis, ModalityAnalysis, SampleEvaluation, TastingSession
from app.models.enums import AnalysisScope, EvaluationState, EvaluationStatus, MessageType, SessionStatus, SpeakerType
from app.services.analyzer.factory import get_analyzer
from app.services.analyzer.models import AnalysisResult, AnalyzerUnavailableError, ModalityResult
from app.services.messages import (
    COMPARISON_REFORMULATION,
    INITIAL_QUESTION,
    LLM_RETRY_MESSAGE,
    OPEN_REPROMPT,
    SAMPLE_COMPLETED_MESSAGE,
    build_modality_question,
)
from app.services.modality_metadata import (
    DESCRIPTOR_WORDS,
    MODALITY_ORDER,
    VALUATION_MARKERS,
    detect_modality_absence,
    find_valuation_in_text,
    has_comparison,
    is_brief_valuation,
    is_neutral_valuation,
    mentions_other_modality_only,
    normalize_text,
    _has_specific_modality_evidence,
)

logger = logging.getLogger(__name__)


def _compute_is_vague_from_coverage(
    analysis_scope: str,
    current_state: str,
    analysis: AnalysisResult,
) -> bool:
    """Deterministic vagueness, decided by the backend (never by the LLM).

    In this application 'vague' means: the INITIAL open answer does not cover
    enough complete sensory modalities. A modality is complete only when its
    mention_text, descriptor_text and valuation_text are all non-empty
    (already recomputed by _normalized_analysis before this is called).

    Rules:
      - In directed modality questions (MODALITY_QUESTION) → always False.
      - In intermediate (non-initial) turns → always False.
      - In the INITIAL turn → True when 2 or fewer modalities are complete.
    """
    if current_state == EvaluationState.MODALITY_QUESTION.value:
        return False
    if analysis_scope != AnalysisScope.INITIAL.value:
        return False
    completed_modalities = sum(
        1 for result in analysis.modalities.values() if result.is_complete
    )
    return completed_modalities <= 2


_NO_SMELL_PATTERNS_DIALOGUE = [
    r'no (?:me )?(?:huele?|oli[ao])\b',
    r'\bno (?:tiene?|tenia?) (?:ningun )?olor\b',
    r'\bsin olor\b',
    r'\bno (?:percibo|noto)\b',
    r'\bapenas?\s+huele?\b',
]


def _non_empty(value: str | None) -> bool:
    return bool((value or '').strip())


def _was_asking_for_valuation(question: str | None) -> bool:
    """Returns True if the previous bot question was asking for a valuation."""
    if not question:
        return False
    q = normalize_text(question)
    return 'te parece' in q or 'te gusta' in q


def _is_brief_response(text: str) -> bool:
    """Returns True if the response is short enough to be a direct answer to the current question."""
    return len(_re.findall(r'\w+', text, flags=_re.UNICODE)) <= 8


def _matches_no_smell(text: str) -> bool:
    lowered = normalize_text(text)
    return any(_re.search(p, lowered) for p in _NO_SMELL_PATTERNS_DIALOGUE)


def _is_likely_descriptor(text: str, modality: str) -> bool:
    """Returns True only for SHORT PURE sensory descriptors with no valuation signal.

    Mixed responses like "sí, tiene olor dulce" or "me gusta, es crujiente" must
    return False so the valuation-injection path can proceed.
    """
    word_count = len(_re.findall(r'\w+', text, flags=_re.UNICODE))
    if word_count > 5:
        return False
    lowered = normalize_text(text)
    # Explicit valuation markers → not a pure descriptor
    all_markers = VALUATION_MARKERS['positive'] + VALUATION_MARKERS['negative']
    if any(normalize_text(m) in lowered for m in all_markers):
        return False
    # Monosyllabic affirmative/negative answers are valuations, not descriptors.
    # normalize_text strips accents so "sí" → "si".
    if _re.search(r'\bsi\b', lowered) or _re.search(r'\bno\b', lowered):
        return False
    words = DESCRIPTOR_WORDS.get(modality, [])
    return any(normalize_text(w) in lowered for w in words)


def _sanitize_bot_text_from_mentions(analysis: AnalysisResult, bot_question: str | None) -> AnalysisResult:
    """Guard: if the LLM hallucinated bot-question text into a mention_text field, clear it.

    The bot's previous question is context only — it must never appear as user evidence.
    Any mention_text that is a substantial substring of the bot question is rejected so
    that the fallback in _apply_modality_context can recover from last_message instead.
    """
    if not bot_question:
        return analysis
    q_norm = normalize_text(bot_question)
    changed: dict[str, ModalityResult] = {}
    for modality, result in analysis.modalities.items():
        if not result.mention_text:
            continue
        m_norm = normalize_text(result.mention_text)
        if len(m_norm) >= 15 and m_norm in q_norm:
            changed[modality] = result.model_copy(update={'mention_text': '', 'is_complete': False})
    if not changed:
        return analysis
    return analysis.model_copy(update={'modalities': {**analysis.modalities, **changed}})


def _latest_modality_result_from_db(evaluation: SampleEvaluation, modality: str) -> ModalityResult:
    """Get the most recently persisted result for a modality from the evaluation's analyses."""
    if not evaluation.analyses:
        return ModalityResult()
    latest = max(evaluation.analyses, key=lambda a: a.created_at, default=None)
    if not latest:
        return ModalityResult()
    for row in latest.modalities:
        if row.modality == modality:
            return ModalityResult(
                mention_text=row.mention_text or '',
                descriptor_text=row.descriptor_text or '',
                valuation_text=row.valuation_text or '',
                is_complete=row.is_complete,
            )
    return ModalityResult()


def _is_valuation_only_response(
    last_message: str,
    previous_bot_question: str | None,
    current_modality: str,
) -> bool:
    """True when the bot asked for a valuation and the user replied with a brief
    opinion that adds NO new specific descriptor for the modality.

    Such answers (e.g. "no me encanta", "regular", "no mucho") must only fill
    valuation_text — never replace mention_text or descriptor_text. Returns False
    when the answer also carries modality-specific evidence (e.g. "me gusta porque
    es crujiente" → has a TEXTURA descriptor), so those still update normally.
    """
    if not _was_asking_for_valuation(previous_bot_question):
        return False
    if not _is_brief_response(last_message):
        return False
    if _has_specific_modality_evidence(last_message, current_modality):
        return False
    return is_brief_valuation(last_message)


def _apply_modality_context(
    evaluation: SampleEvaluation,
    analysis: AnalysisResult,
    current_modality: str,
    last_message: str,
    previous_bot_question: str | None,
) -> AnalysisResult:
    """Merge previous analysis data and apply contextual valuation for directed modality questions.

    Prevents info loss when the LLM re-analyzes accumulated text (Problema 5) and
    treats short responses to directed questions as valuations (Problema 1, 4).
    """
    prev = _latest_modality_result_from_db(evaluation, current_modality)
    curr = analysis.modalities.get(current_modality, ModalityResult())

    # Valuation-only answer to a valuation question (general for the four modalities):
    # keep the modality's previous mention and descriptor, fill ONLY the valuation.
    # A short opinion like "no me encanta" must never overwrite mention_text/descriptor_text,
    # and curr.mention_text / curr.descriptor_text from the LLM are ignored in this branch.
    if _is_valuation_only_response(last_message, previous_bot_question, current_modality):
        prev_mention = (prev.mention_text or '').strip()
        prev_descriptor = (prev.descriptor_text or '').strip()
        valuation = (curr.valuation_text or '').strip() or last_message.strip()
        merged = ModalityResult(
            mention_text=prev_mention,
            descriptor_text=prev_descriptor,
            valuation_text=valuation,
            is_complete=bool(prev_mention and prev_descriptor and valuation),
        )
        updated_modalities = {**analysis.modalities, current_modality: merged}
        return analysis.model_copy(update={'modalities': updated_modalities})

    # Cross-modal guard: an answer whose sensory content belongs ONLY to another
    # modality (e.g. "rancia" / "no sabe a nada" / "huele raro" given when the bot
    # asked about texture) must not complete the current modality. Keep only the
    # previously persisted evidence so the flow re-asks the current modality.
    if mentions_other_modality_only(last_message, current_modality):
        preserved = _normalized_modality_result(prev)
        updated_modalities = {**analysis.modalities, current_modality: preserved}
        return analysis.model_copy(update={'modalities': updated_modalities})

    # Merge: prefer new non-empty values, fallback to previous persisted values
    merged_mention = (curr.mention_text or '').strip() or (prev.mention_text or '').strip()
    merged_descriptor = (curr.descriptor_text or '').strip() or (prev.descriptor_text or '').strip()
    merged_valuation = (curr.valuation_text or '').strip() or (prev.valuation_text or '').strip()

    # Guard (belt-and-suspenders): reject merged_mention if it came from the bot question
    # (handles the case where both curr and prev were contaminated by the same LLM hallucination).
    if previous_bot_question and merged_mention:
        _m_norm = normalize_text(merged_mention)
        if len(_m_norm) >= 15 and _m_norm in normalize_text(previous_bot_question):
            merged_mention = ''

    # Absence / neutrality specific to the modality being asked: a valid
    # "no huele a nada" / "no sabe a nada" / "es normal" answer resolves the
    # descriptor for THIS modality (and a neutral valuation when none is present).
    if not merged_descriptor:
        absence_descriptor = detect_modality_absence(last_message, current_modality)
        if absence_descriptor:
            merged_descriptor = absence_descriptor
            if not merged_valuation:
                merged_valuation = last_message.strip()
            if not merged_mention:
                merged_mention = last_message.strip()

    # Neutral valuation ("no tengo opinión", "me da igual") answered to a directed
    # modality question counts as a (neutral) valuation for that modality.
    if not merged_valuation and is_neutral_valuation(last_message):
        merged_valuation = last_message.strip()

    # If valuation still missing: use last message when bot asked for valuation, response is short,
    # and it does not look like a pure sensory descriptor (e.g. "crujiente" alone).
    if (
        not merged_valuation
        and _was_asking_for_valuation(previous_bot_question)
        and _is_brief_response(last_message)
        and not _is_likely_descriptor(last_message, current_modality)
    ):
        merged_valuation = last_message.strip()

    # For OLOR: when last_message describes absence-of-smell it IS the OLOR evidence.
    # Override any wrong mention that the rules analyzer may have taken from another modality's sentence.
    if current_modality == 'OLOR' and _matches_no_smell(last_message):
        merged_mention = last_message.strip()
        if not merged_descriptor:
            merged_descriptor = 'sin olor'
        if not merged_valuation:
            merged_valuation = last_message.strip()

    # For OLOR: if descriptor is still missing after the merge, try to pull it directly
    # from last_message (handles "Sí, tiene olor dulce" when the bot asked only for valuation
    # but the user also volunteered a descriptor, or full-question answers where the analyzer
    # missed the descriptor word in the accumulated text).
    if current_modality == 'OLOR' and not merged_descriptor:
        _lowered_last = normalize_text(last_message)
        _found_descs = [w for w in DESCRIPTOR_WORDS.get('OLOR', []) if normalize_text(w) in _lowered_last]
        if _found_descs:
            merged_descriptor = ', '.join(sorted(dict.fromkeys(_found_descs), key=normalize_text))

    # Re-anchor the mention to the participant's CURRENT answer when this turn provides
    # specific evidence for the modality being asked and we already have a descriptor.
    # Without this, a fresh descriptor extracted from the current message could be paired
    # with a STALE mention pulled from an earlier sentence about another modality, e.g.
    # ASPECTO descriptor "soso, redondo" (from "es un poco soso, redondo") left with a
    # SABOR/OLOR mention like "una galleta demasiado dulce...". The mention must describe
    # the same evidence as the descriptor. A mention that is already a substring of the
    # current message is kept as-is (the LLM extracted a precise span).
    if (
        merged_descriptor
        and merged_mention
        and _has_specific_modality_evidence(last_message, current_modality)
        and normalize_text(merged_mention) not in normalize_text(last_message)
    ):
        merged_mention = last_message.strip()

    # If mention still empty but we already have descriptor or valuation context,
    # use last message as the mention anchor.
    if not merged_mention and (merged_descriptor or merged_valuation):
        merged_mention = last_message.strip()

    is_complete = bool(merged_mention and merged_descriptor and merged_valuation)
    merged_result = ModalityResult(
        mention_text=merged_mention,
        descriptor_text=merged_descriptor,
        valuation_text=merged_valuation,
        is_complete=is_complete,
    )
    updated_modalities = {**analysis.modalities, current_modality: merged_result}
    return analysis.model_copy(update={'modalities': updated_modalities})


def _apply_comparison_guard(
    analysis: AnalysisResult,
    user_last_message: str,
    other_sample_codes: list[str],
) -> AnalysisResult:
    """Force has_comparison=True when the deterministic check fires but the LLM returned False.

    Never converts True → False: only fills the gap when the LLM misses an obvious marker.
    Operates exclusively on user_last_message to avoid false positives from old turns
    already stored in accumulated_text.
    """
    if analysis.has_comparison:
        return analysis
    if has_comparison(user_last_message, other_sample_codes):
        return analysis.model_copy(update={'has_comparison': True})
    return analysis


def _is_purely_comparative(text: str, other_sample_codes: list[str]) -> bool:
    """True when the entire message is a comparison with no independent sensory content.

    Conservative threshold: short messages (≤ 12 words) that contain a comparison marker
    are treated as purely comparative. Longer messages may be mixed and are left to the LLM.
    """
    normalized = normalize_text(text)
    word_count = len(_re.findall(r'\w+', normalized))
    if word_count > 12:
        return False
    return has_comparison(text, other_sample_codes)


def _reset_modalities_to_empty(analysis: AnalysisResult) -> AnalysisResult:
    """Return a copy of the analysis with all modality results cleared.

    Used when the entire turn is purely comparative: we must not persist comparative
    fragments as modality evidence, since they describe another sample, not this one.
    """
    empty_modalities = {m: ModalityResult() for m in analysis.modalities}
    return analysis.model_copy(update={'modalities': empty_modalities})


def _apply_valuation_fallback(analysis: AnalysisResult, accumulated_text: str, only_modality: str | None = None) -> AnalysisResult:
    """Conservative deterministic fallback: fills valuation_text when LLM left it empty.

    Conditions to activate for a modality:
    - mention_text and descriptor_text are already present
    - valuation_text is empty
    - accumulated_text contains a literal valuation expression for that modality

    When ``only_modality`` is set (directed MODALITY_QUESTION turns), only that
    modality may be touched, so a valuation answer about one modality can never
    fill another modality's valuation.

    Never invents text. Uses literal sentences from accumulated_text.
    is_complete is recomputed by the next _normalized_analysis call.
    """
    changed: dict[str, ModalityResult] = {}
    for modality, result in analysis.modalities.items():
        if only_modality is not None and modality != only_modality:
            continue
        if _non_empty(result.valuation_text):
            continue
        if not _non_empty(result.mention_text) or not _non_empty(result.descriptor_text):
            continue
        found = find_valuation_in_text(accumulated_text, modality)
        if not found:
            continue
        changed[modality] = result.model_copy(update={'valuation_text': found, 'is_complete': True})
    if not changed:
        return analysis
    return analysis.model_copy(update={'modalities': {**analysis.modalities, **changed}})


def _normalized_modality_result(result: ModalityResult | None) -> ModalityResult:
    if result is None:
        return ModalityResult()
    return result.model_copy(
        update={
            'is_complete': _non_empty(result.mention_text) and _non_empty(result.descriptor_text) and _non_empty(result.valuation_text),
        }
    )


def _normalized_analysis(analysis: AnalysisResult) -> AnalysisResult:
    normalized_modalities = {
        modality: _normalized_modality_result(result)
        for modality, result in analysis.modalities.items()
    }
    for modality in MODALITY_ORDER:
        normalized_modalities.setdefault(modality, ModalityResult())
    return analysis.model_copy(update={'modalities': normalized_modalities})


def _best_persisted_modality_result(evaluation: SampleEvaluation, modality: str) -> ModalityResult:
    """Most reliable persisted result for a modality across ALL analyses.

    Prefers the most recent COMPLETE result; otherwise the most recent non-empty
    one; otherwise empty. Guarantees a covered modality is never lost or downgraded
    by a later turn that returned nothing (or worse) for it.
    """
    if not evaluation.analyses:
        return ModalityResult()
    best_complete: ModalityResult | None = None
    best_nonempty: ModalityResult | None = None
    for analysis in sorted(evaluation.analyses, key=lambda item: item.created_at):
        for row in analysis.modalities:
            if row.modality != modality:
                continue
            result = ModalityResult(
                mention_text=row.mention_text or '',
                descriptor_text=row.descriptor_text or '',
                valuation_text=row.valuation_text or '',
                is_complete=row.is_complete,
            )
            if result.is_complete:
                best_complete = result
            if result.mention_text or result.descriptor_text or result.valuation_text:
                best_nonempty = result
    return best_complete or best_nonempty or ModalityResult()


def _consolidate_modalities_for_modality_question(
    evaluation: SampleEvaluation,
    analysis: AnalysisResult,
    current_modality: str,
) -> AnalysisResult:
    """In MODALITY_QUESTION mode, only ``current_modality`` may change this turn.

    Every other modality is restored from its best persisted value, so the LLM can
    never blank or reopen a previously covered modality, and any new data it
    returned for a non-current modality is ignored in this mode.
    """
    consolidated: dict[str, ModalityResult] = {}
    for modality in MODALITY_ORDER:
        if modality == current_modality:
            consolidated[modality] = analysis.modalities.get(modality, ModalityResult())
        else:
            consolidated[modality] = _best_persisted_modality_result(evaluation, modality)
    return analysis.model_copy(update={'modalities': consolidated})


def _filled_field_count(result: ModalityResult) -> int:
    return sum(1 for value in (result.mention_text, result.descriptor_text, result.valuation_text) if (value or '').strip())


def _merge_keep_best(primary: ModalityResult, secondary: ModalityResult) -> ModalityResult:
    """Return whichever result preserves the most validated evidence.

    A complete result always wins over an incomplete one; otherwise the one with
    more non-empty fields wins; ties keep ``primary`` (the fresher turn).
    """
    primary = _normalized_modality_result(primary)
    secondary = _normalized_modality_result(secondary)
    if primary.is_complete and not secondary.is_complete:
        return primary
    if secondary.is_complete and not primary.is_complete:
        return secondary
    return primary if _filled_field_count(primary) >= _filled_field_count(secondary) else secondary


def _build_consolidated_final_analysis(
    evaluation: SampleEvaluation,
    final_analysis: AnalysisResult | None,
) -> AnalysisResult:
    """Build the FINAL analysis as a CONSOLIDATION of already-validated data.

    It never re-interprets the whole conversation with the LLM. Per modality it
    keeps whichever of the persisted best result or the (already consolidated)
    closing-turn result holds more validated evidence. A FINAL is always produced
    so the structured export can rely on it and previously covered modalities are
    never blanked.
    """
    final_modalities = final_analysis.modalities if final_analysis is not None else {}
    modalities: dict[str, ModalityResult] = {}
    for modality in MODALITY_ORDER:
        persisted = _best_persisted_modality_result(evaluation, modality)
        fresh = final_modalities.get(modality, ModalityResult())
        modalities[modality] = _normalized_modality_result(_merge_keep_best(fresh, persisted))
    has_comparison = bool(final_analysis.has_comparison) if final_analysis is not None else False
    return AnalysisResult(
        analysis_scope=AnalysisScope.FINAL.value,
        is_vague=False,
        has_comparison=has_comparison,
        reasoning_summary='Análisis FINAL consolidado a partir de los datos ya validados (sin reanálisis global del LLM).',
        modalities=modalities,
    )


@dataclass(frozen=True)
class ModalityResolution:
    descriptor_filled: bool
    valuation_filled: bool
    complete: bool
    exhausted: bool

    @property
    def resolved(self) -> bool:
        return self.complete or self.exhausted


@dataclass
class DialogueOutcome:
    evaluation: SampleEvaluation
    analysis: AnalysisResult | None
    bot_message: str
    next_step: str | None = None
    effective_next_action: str | None = None
    llm_error: bool = False
    conversation_turns: list[dict[str, str | int]] | None = None


class ConversationService:
    @staticmethod
    def add_turn(db: Session, evaluation: SampleEvaluation, speaker: str, message_type: str, text: str) -> ConversationTurn:
        turn = ConversationTurn(
            evaluation_id=evaluation.id,
            turn_index=evaluation.next_turn_index,
            speaker=speaker,
            message_type=message_type,
            message_text=text,
        )
        evaluation.next_turn_index += 1
        db.add(turn)
        db.flush()
        if 'turns' in evaluation.__dict__:
            evaluation.turns.append(turn)
        return turn

    @staticmethod
    def latest_user_turn(db: Session, evaluation: SampleEvaluation) -> ConversationTurn | None:
        return db.scalar(
            select(ConversationTurn)
            .where(ConversationTurn.evaluation_id == evaluation.id, ConversationTurn.speaker == SpeakerType.USER.value)
            .order_by(ConversationTurn.turn_index.desc())
            .limit(1)
        )

    @staticmethod
    def serialize_turns(evaluation: SampleEvaluation) -> list[dict[str, str | int]]:
        return [
            {
                'turn_index': turn.turn_index,
                'speaker': turn.speaker,
                'message_type': turn.message_type,
                'message_text': turn.message_text,
                'created_at': turn.created_at.isoformat(),
            }
            for turn in sorted(evaluation.turns, key=lambda item: item.turn_index)
        ]


class ModalityCoverageService:
    @staticmethod
    def covered_modalities_from_latest(evaluation: SampleEvaluation) -> list[str]:
        if not evaluation.analyses:
            return []
        covered: set[str] = set()
        for analysis in evaluation.analyses:
            for row in analysis.modalities:
                if row.is_complete:
                    covered.add(row.modality)
        return sorted(covered)

    @staticmethod
    def modality_attempts(evaluation: SampleEvaluation) -> dict[str, int]:
        payload = evaluation.modality_attempts_json or {}
        attempts = {modality: int(payload.get(modality, 0) or 0) for modality in MODALITY_ORDER}
        return attempts

    @staticmethod
    def modality_resolution(result: ModalityResult | None, attempts: int) -> ModalityResolution:
        normalized = _normalized_modality_result(result)
        mention_filled = _non_empty(normalized.mention_text)
        descriptor_filled = _non_empty(normalized.descriptor_text)
        valuation_filled = _non_empty(normalized.valuation_text)
        complete = mention_filled and descriptor_filled and valuation_filled
        exhausted = (not complete) and attempts >= settings.max_modality_attempts
        return ModalityResolution(
            descriptor_filled=descriptor_filled,
            valuation_filled=valuation_filled,
            complete=complete,
            exhausted=exhausted,
        )

    @staticmethod
    def pending_modalities(
        analysis: AnalysisResult,
        exhausted_modalities: list[str] | None,
        preserved_covered_modalities: list[str] | None,
        attempts_by_modality: dict[str, int],
    ) -> list[str]:
        exhausted_set = set(exhausted_modalities or [])
        covered_set = set(preserved_covered_modalities or [])
        pending: list[str] = []
        for modality in MODALITY_ORDER:
            if modality in exhausted_set:
                continue
            if modality in covered_set:
                continue
            resolution = ModalityCoverageService.modality_resolution(
                analysis.modalities.get(modality),
                attempts_by_modality.get(modality, 0),
            )
            if resolution.resolved:
                continue
            pending.append(modality)
        return pending


class AnalysisPersistenceService:
    @staticmethod
    def persist_analysis(
        db: Session,
        evaluation: SampleEvaluation,
        analyzer_provider: str,
        analyzer_model: str,
        prompt_version: str,
        source_turn_id: str | None,
        analysis: AnalysisResult,
        effective_next_action: str | None,
    ) -> EvaluationAnalysis:
        normalized_analysis = _normalized_analysis(analysis)
        record = EvaluationAnalysis(
            evaluation_id=evaluation.id,
            source_turn_id=source_turn_id,
            analysis_scope=normalized_analysis.analysis_scope,
            accumulated_text_snapshot=evaluation.accumulated_text,
            is_vague=normalized_analysis.is_vague,
            has_comparison=normalized_analysis.has_comparison,
            effective_next_action=effective_next_action,
            reasoning_summary=normalized_analysis.reasoning_summary,
            llm_provider=analyzer_provider,
            llm_model=analyzer_model,
            prompt_version=prompt_version,
            raw_response_json=normalized_analysis.model_dump(),
        )
        db.add(record)
        db.flush()
        modality_rows: list[ModalityAnalysis] = []
        for modality, result in normalized_analysis.modalities.items():
            modality_row = ModalityAnalysis(
                analysis_id=record.id,
                modality=modality,
                mention_text=result.mention_text,
                descriptor_text=result.descriptor_text,
                valuation_text=result.valuation_text,
                is_complete=result.is_complete,
            )
            modality_rows.append(modality_row)
            db.add(modality_row)
        db.flush()
        record.modalities = modality_rows
        if 'analyses' in evaluation.__dict__:
            evaluation.analyses.append(record)
        return record


class SessionProgressService:
    @staticmethod
    def compute_next_step(session: TastingSession) -> str:
        completed = sum(1 for item in session.evaluations if item.status == EvaluationStatus.COMPLETED.value)
        if completed < session.total_samples:
            return 'NEXT_SAMPLE'
        return 'SESSION_COMPLETED'

    @staticmethod
    def sync_session_status(session: TastingSession, current_time: datetime) -> None:
        completed_evals = [item for item in session.evaluations if item.status == EvaluationStatus.COMPLETED.value]
        completed = len(completed_evals)
        if completed == 0:
            session.status = SessionStatus.CREATED.value
            return
        if completed < session.total_samples:
            session.status = SessionStatus.IN_PROGRESS.value
            return
        # All evaluations COMPLETED. Only transition to COMPLETED once every per-sample
        # comment is resolved (final_comment is not None, even if empty string).
        # While any comment is still None the session stays IN_PROGRESS so the participant
        # can reach the sample_comment screen again after a page refresh or re-login.
        if any(item.final_comment is None for item in completed_evals):
            session.status = SessionStatus.IN_PROGRESS.value
            return
        session.status = SessionStatus.COMPLETED.value
        session.finished_at = current_time


class FlowDecisionEngine:
    def __init__(self, conversation_service: ConversationService) -> None:
        self.conversation_service = conversation_service

    def apply(
        self,
        db: Session,
        evaluation: SampleEvaluation,
        analysis: AnalysisResult,
        covered_modalities: list[str],
    ) -> tuple[str, str, str | None]:
        #1. Si hay comparación → pedir reformulación
        if analysis.has_comparison and evaluation.comparison_retry_count < settings.max_comparison_retries:
            evaluation.comparison_retry_count += 1
            evaluation.current_state = EvaluationState.COMPARISON_REFORMULATION.value
            evaluation.next_question = COMPARISON_REFORMULATION
            self.conversation_service.add_turn(db, evaluation, SpeakerType.BOT.value, MessageType.COMPARISON_WARNING.value, COMPARISON_REFORMULATION)
            return 'ASK_REFORMULATION_NO_COMPARISON', COMPARISON_REFORMULATION, None
        #2. Si es respuesta inicial y es vaga → pedir más detalle
        if analysis.analysis_scope == AnalysisScope.INITIAL.value and analysis.is_vague and evaluation.vague_retry_count < settings.max_vague_retries:
            evaluation.vague_retry_count += 1
            evaluation.current_state = EvaluationState.OPEN_REPROMPT.value
            evaluation.next_question = OPEN_REPROMPT
            self.conversation_service.add_turn(db, evaluation, SpeakerType.BOT.value, MessageType.OPEN_REPROMPT.value, OPEN_REPROMPT)
            return 'ASK_OPEN_REPROMPT', OPEN_REPROMPT, None

        attempts_by_modality = ModalityCoverageService.modality_attempts(evaluation)
        pending_modalities = ModalityCoverageService.pending_modalities(
            analysis=analysis,
            exhausted_modalities=evaluation.exhausted_modalities_json,
            preserved_covered_modalities=covered_modalities,
            attempts_by_modality=attempts_by_modality,
        )
        # 3. Si faltan modalidades → preguntar por la siguiente modalidad pendiente
        if pending_modalities:
            next_modality = pending_modalities[0]
            next_attempt = attempts_by_modality.get(next_modality, 0) + 1
            attempts_by_modality[next_modality] = next_attempt
            evaluation.modality_attempts_json = attempts_by_modality
            evaluation.current_modality = next_modality
            evaluation.current_modality_attempt = next_attempt

            if next_attempt > settings.max_modality_attempts:
                exhausted = set(evaluation.exhausted_modalities_json or [])
                exhausted.add(next_modality)
                evaluation.exhausted_modalities_json = sorted(exhausted)
                attempts_by_modality[next_modality] = settings.max_modality_attempts
                evaluation.modality_attempts_json = attempts_by_modality
                evaluation.current_modality = None
                evaluation.current_modality_attempt = 0
                pending_modalities = ModalityCoverageService.pending_modalities(
                    analysis=analysis,
                    exhausted_modalities=evaluation.exhausted_modalities_json,
                    preserved_covered_modalities=covered_modalities,
                    attempts_by_modality=attempts_by_modality,
                )
                #4. Si no falta nada → cerrar muestra
                if not pending_modalities:
                    return 'FORCE_CLOSE_SAMPLE', SAMPLE_COMPLETED_MESSAGE, None
                next_modality = pending_modalities[0]
                next_attempt = attempts_by_modality.get(next_modality, 0) + 1
                attempts_by_modality[next_modality] = next_attempt
                evaluation.modality_attempts_json = attempts_by_modality
                evaluation.current_modality = next_modality
                evaluation.current_modality_attempt = next_attempt

            current_result = _normalized_modality_result(analysis.modalities.get(next_modality))
            question = build_modality_question(
                next_modality,
                mention_text=current_result.mention_text,
                descriptor_text=current_result.descriptor_text,
                valuation_text=current_result.valuation_text,
            )
            evaluation.current_state = EvaluationState.MODALITY_QUESTION.value
            evaluation.next_question = question
            self.conversation_service.add_turn(db, evaluation, SpeakerType.BOT.value, MessageType.MODALITY_QUESTION.value, question)
            return f'ASK_MODALITY_{next_modality}', question, None

        return 'CLOSE_SAMPLE', SAMPLE_COMPLETED_MESSAGE, None


class DialogueService:
    def __init__(self) -> None:
        self.analyzer = get_analyzer()
        self.conversation_service = ConversationService()
        self.analysis_persistence = AnalysisPersistenceService()
        self.session_progress = SessionProgressService()
        self.flow_engine = FlowDecisionEngine(self.conversation_service)

    @staticmethod
    def utcnow() -> datetime:
        return datetime.now(timezone.utc)

    def create_initial_question(self, db: Session, evaluation: SampleEvaluation) -> str:
        evaluation.next_question = INITIAL_QUESTION
        evaluation.current_state = EvaluationState.INITIAL_QUESTION.value
        self.conversation_service.add_turn(db, evaluation, SpeakerType.BOT.value, MessageType.INITIAL_QUESTION.value, INITIAL_QUESTION)
        return INITIAL_QUESTION

    def _build_comparison_reformulation_outcome(
        self, db: Session, evaluation: SampleEvaluation, analysis_scope: str
    ) -> DialogueOutcome:
        """Short-circuit outcome for a comparative turn detected before the LLM call.

        The user turn was already stored for traceability. Here we only: increment the
        comparison retry counter, switch the state to COMPARISON_REFORMULATION and add the
        bot reformulation turn. No LLM call, no accumulated_text change, no analysis
        persisted and no modality completed, so the comparative message never pollutes the
        sensory evidence.

        The returned analysis reflects the ACCUMULATED extraction (best persisted result
        per modality), NOT an empty turn. The comparative turn contributes no new evidence,
        but it must not blank what previous valid turns already captured — the analysis
        panel keeps showing the conserved mention/descriptor/valuation while flagging the
        comparison. This is the analysis of the last turn for display only; nothing is
        persisted, so the stored per-modality extraction stays untouched.
        """
        evaluation.comparison_retry_count += 1
        evaluation.current_state = EvaluationState.COMPARISON_REFORMULATION.value
        evaluation.next_question = COMPARISON_REFORMULATION
        self.conversation_service.add_turn(
            db, evaluation, SpeakerType.BOT.value, MessageType.COMPARISON_WARNING.value, COMPARISON_REFORMULATION
        )
        db.flush()
        accumulated_modalities = {
            modality: _best_persisted_modality_result(evaluation, modality)
            for modality in MODALITY_ORDER
        }
        comparison_analysis = AnalysisResult(
            analysis_scope=analysis_scope,
            is_vague=False,
            has_comparison=True,
            reasoning_summary='',
            modalities=accumulated_modalities,
        )
        return DialogueOutcome(
            evaluation=evaluation,
            analysis=comparison_analysis,
            bot_message=COMPARISON_REFORMULATION,
            effective_next_action='ASK_REFORMULATION_NO_COMPARISON',
            conversation_turns=self.conversation_service.serialize_turns(evaluation),
        )

    async def process_user_turn(self, db: Session, evaluation: SampleEvaluation, user_message: str) -> DialogueOutcome:
        # TRANSACTIONAL CONTRACT: this method performs multiple db.flush() calls to keep
        # in-memory state consistent with pending DB changes, but it never calls db.commit().
        # The caller (the route handler) owns commit/rollback.  If any exception propagates
        # out of this method, the caller must call db.rollback() before re-raising.
        #
        # accumulated_text stores the COMPLETE conversation history for full traceability.
        # Only a bounded window (settings.llm_context_max_chars) is forwarded to the LLM.

        #1. Comprueba que la evaluación no esté terminada
        if evaluation.status == EvaluationStatus.COMPLETED.value:
            raise ValueError('Cannot send dialogue to a completed evaluation.')

        #2. Limpia el mensaje del usuario
        cleaned_message = user_message.strip()

        #3. Guarda el turno del usuario SIEMPRE (incluidos los comparativos): el histórico
        # conversacional debe ser completo para trazabilidad, aunque no se use como evidencia.
        self.conversation_service.add_turn(db, evaluation, SpeakerType.USER.value, MessageType.USER_RESPONSE.value, cleaned_message)

        # Derive sample context for comparison detection (needed BEFORE the LLM call)
        current_sample_code: str | None = evaluation.sample.sample_code if evaluation.sample else None
        _config = evaluation.session.admin_session if evaluation.session else None
        session_sample_codes: list[str] = (
            list(_config.sample_codes_json) if _config and _config.sample_codes_json else
            ([current_sample_code] if current_sample_code else [])
        )
        other_sample_codes: list[str] = [c for c in session_sample_codes if c != current_sample_code]

        # Scope se deriva SIN consumir todavía initial_response_text: un primer mensaje
        # comparativo no debe ocupar el hueco INITIAL — lo hará la respuesta reformulada.
        analysis_scope = (
            AnalysisScope.INITIAL.value if not evaluation.initial_response_text
            else AnalysisScope.INTERMEDIATE.value
        )

        # 3b. Detección determinista de comparación ANTES de llamar al LLM.
        # Si el último mensaje compara (con otra muestra, código o producto del mercado) se
        # pide reformulación y se corta el flujo: NO se añade a accumulated_text, NO se llama
        # al LLM, NO se evalúa vaguedad y NO se completa ninguna modalidad. El mensaje ya quedó
        # guardado en ConversationTurn (paso 3). El tope max_comparison_retries evita el bucle
        # infinito: al agotarse, se deja pasar al flujo normal para no bloquear al participante.
        if (
            has_comparison(cleaned_message, other_sample_codes)
            and evaluation.comparison_retry_count < settings.max_comparison_retries
        ):
            return self._build_comparison_reformulation_outcome(db, evaluation, analysis_scope)

        #4. Añade el mensaje al texto acumulado (solo texto ACEPTADO para análisis sensorial)
        evaluation.accumulated_text = '\n'.join(filter(None, [evaluation.accumulated_text.strip(), cleaned_message])).strip()

        #5. Marca la respuesta inicial (ya garantizado que el turno no es comparativo)
        if not evaluation.initial_response_text:
            evaluation.initial_response_text = cleaned_message

        covered_modalities = ModalityCoverageService.covered_modalities_from_latest(evaluation)
        # Capture previous bot question before FlowDecisionEngine overwrites next_question
        previous_bot_question = evaluation.next_question

        # 6. Llama al analizador
        try:
            analysis = await self.analyzer.analyze(
                analysis_scope=analysis_scope,
                current_state=evaluation.current_state,
                current_modality=evaluation.current_modality,
                user_last_message=cleaned_message,
                accumulated_text=evaluation.accumulated_text,
                covered_modalities=covered_modalities,
                vague_retry_count=evaluation.vague_retry_count,
                comparison_retry_count=evaluation.comparison_retry_count,
                previous_bot_question=previous_bot_question,
                current_sample_code=current_sample_code,
                session_sample_codes=session_sample_codes,
                other_sample_codes=other_sample_codes,
            )
        except AnalyzerUnavailableError as exc:
            logger.exception('Analyzer unavailable: %s', exc)
            self.conversation_service.add_turn(db, evaluation, SpeakerType.SYSTEM.value, MessageType.SYSTEM_ERROR.value, LLM_RETRY_MESSAGE)
            db.flush()
            return DialogueOutcome(
                evaluation=evaluation,
                analysis=None,
                bot_message=LLM_RETRY_MESSAGE,
                llm_error=True,
                conversation_turns=self.conversation_service.serialize_turns(evaluation),
            )

        #7. Normaliza el análisis
        analysis = _normalized_analysis(analysis)

        # 7b-pre. Sobrescritura determinista de has_comparison basada SOLO en el último mensaje.
        # El LLM puede ver comparaciones antiguas en accumulated_text y devolver has_comparison=True
        # aunque el turno actual ya no compare. Esta sobrescritura bidireccional es la fuente de verdad.
        analysis = analysis.model_copy(update={
            'has_comparison': has_comparison(cleaned_message, other_sample_codes)
        })

        # 7b. Guard: rechaza mention_text que sea texto de la pregunta del bot (alucinación del LLM)
        analysis = _sanitize_bot_text_from_mentions(analysis, previous_bot_question)

        #8. Fusión contextual cuando la pregunta era dirigida a una modalidad
        if evaluation.current_state == EvaluationState.MODALITY_QUESTION.value and evaluation.current_modality:
            analysis = _apply_modality_context(
                evaluation=evaluation,
                analysis=analysis,
                current_modality=evaluation.current_modality,
                last_message=cleaned_message,
                previous_bot_question=previous_bot_question,
            )
            # Re-normalize after contextual merge to keep is_complete consistent
            analysis = _normalized_analysis(analysis)

        # 8b. Deterministic valuation fallback: fills empty valuation_text when LLM missed it.
        # Only acts when mention+descriptor are present. Uses literal text, never invents.
        # During a directed modality question, restrict it to the current modality so a
        # valuation answer about one modality cannot fill another modality's valuation.
        _fallback_only = (
            evaluation.current_modality
            if evaluation.current_state == EvaluationState.MODALITY_QUESTION.value
            else None
        )
        analysis = _apply_valuation_fallback(analysis, evaluation.accumulated_text, only_modality=_fallback_only)
        analysis = _normalized_analysis(analysis)

        # 8c. Comparison guard: force has_comparison=True when the LLM missed an obvious marker.
        # Operates only on user_last_message (not accumulated_text) to avoid false positives
        # from comparisons in previous turns that are already stored in the accumulated text.
        analysis = _apply_comparison_guard(analysis, cleaned_message, other_sample_codes)

        # 8d. Invalidate modality completions from purely comparative turns.
        # When the entire message is a short comparison (≤ 12 words), no independent sensory
        # evidence can be trusted — reset all modality results to prevent polluting the DB.
        if analysis.has_comparison and _is_purely_comparative(cleaned_message, other_sample_codes):
            analysis = _reset_modalities_to_empty(analysis)
            analysis = _normalized_analysis(analysis)

        #9. Vaguedad determinista en backend (se ignora por completo el is_vague del LLM).
        # Se calcula tras consolidar/normalizar, cuando is_complete por modalidad ya es definitivo.
        # Significa: la respuesta inicial no cubre suficientes modalidades sensoriales completas.
        analysis = analysis.model_copy(update={
            'is_vague': _compute_is_vague_from_coverage(
                analysis_scope=analysis_scope,
                current_state=evaluation.current_state,
                analysis=analysis,
            )
        })

        # 9b. Consolidación (solo MODALITY_QUESTION): únicamente la modalidad actual puede
        # cambiar este turno; las demás se restauran desde su mejor valor persistido, de modo
        # que el LLM no puede borrar ni reabrir una modalidad ya cubierta, y la información
        # nueva que devuelva para otra modalidad se ignora en este modo. INITIAL es global.
        if evaluation.current_state == EvaluationState.MODALITY_QUESTION.value and evaluation.current_modality:
            analysis = _consolidate_modalities_for_modality_question(
                evaluation, analysis, evaluation.current_modality
            )
            analysis = _normalized_analysis(analysis)

        #10. Llama al FlowDecisionEngine
        effective_next_action, bot_message, next_step = self.flow_engine.apply(db, evaluation, analysis, covered_modalities)

        #11. Guarda el análisis o finaliza la muestra
        if effective_next_action in {'CLOSE_SAMPLE', 'FORCE_CLOSE_SAMPLE'}:
            await self.finalize_evaluation(db, evaluation, final_analysis=analysis)
            next_step = self.session_progress.compute_next_step(evaluation.session)
            effective_next_action = 'CLOSE_SAMPLE'
            bot_message = SAMPLE_COMPLETED_MESSAGE
        else:
            source_turn = self.conversation_service.latest_user_turn(db, evaluation)
            self.analysis_persistence.persist_analysis(
                db=db,
                evaluation=evaluation,
                analyzer_provider=self.analyzer.provider_name,
                analyzer_model=self.analyzer.model_name,
                prompt_version=self.analyzer.prompt_version,
                source_turn_id=source_turn.id if source_turn else None,
                analysis=analysis,
                effective_next_action=effective_next_action,
            )
        # 12. Devuelve el mensaje del bot
        return DialogueOutcome(
            evaluation=evaluation,
            analysis=analysis,
            bot_message=bot_message,
            next_step=next_step,
            effective_next_action=effective_next_action,
            conversation_turns=self.conversation_service.serialize_turns(evaluation),
        )

    async def finalize_evaluation(self, db: Session, evaluation: SampleEvaluation, final_analysis: AnalysisResult | None = None) -> None:
        if evaluation.status == EvaluationStatus.COMPLETED.value:
            return
        # FINAL is a CONSOLIDATION of already-validated data — never a new global LLM pass.
        # It combines the best persisted result per modality with the (already consolidated)
        # closing-turn analysis, so it cannot blank complete modalities nor re-interpret the
        # whole conversation. A FINAL is always persisted so the structured export keeps working.
        resolved_final_analysis = _build_consolidated_final_analysis(evaluation, final_analysis)
        self.analysis_persistence.persist_analysis(
            db=db,
            evaluation=evaluation,
            analyzer_provider=self.analyzer.provider_name,
            analyzer_model=self.analyzer.model_name,
            prompt_version=self.analyzer.prompt_version,
            source_turn_id=None,
            analysis=resolved_final_analysis,
            effective_next_action='CLOSE_SAMPLE',
        )
        evaluation.status = EvaluationStatus.COMPLETED.value
        evaluation.current_state = EvaluationState.SAMPLE_COMPLETED.value
        evaluation.current_modality = None
        evaluation.current_modality_attempt = 0
        evaluation.next_question = SAMPLE_COMPLETED_MESSAGE
        evaluation.finished_at = self.utcnow()
        self.conversation_service.add_turn(db, evaluation, SpeakerType.BOT.value, MessageType.FINAL_MESSAGE.value, SAMPLE_COMPLETED_MESSAGE)
        self.session_progress.sync_session_status(evaluation.session, self.utcnow())

    def compute_next_step(self, db: Session, session_id: str) -> str:
        session = db.scalar(
            select(TastingSession)
            .options(selectinload(TastingSession.evaluations))
            .where(TastingSession.id == session_id)
        )
        if not session:
            return 'SESSION_COMPLETED'
        return self.session_progress.compute_next_step(session)
