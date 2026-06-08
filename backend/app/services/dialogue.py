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
    GENERIC_VAGUE_PATTERNS,
    MENTION_PATTERNS,
    VALUATION_MARKERS,
    find_valuation_in_text,
    has_comparison,
    is_global_opinion_only,
    normalize_text,
)

logger = logging.getLogger(__name__)


def _looks_clearly_vague(text: str) -> bool:
    """Deterministic pre-filter for evidently vague inputs.

    It ensures that generic replies such as 'está bien', 'ok' or 'me gusta'
    always trigger the open reprompt, independently of the configured analyzer.
    """
    if not text:
        return True
    normalized = normalize_text(text).strip()
    if not normalized:
        return True
    word_count = len(_re.findall(r'\w+', normalized, flags=_re.UNICODE))
    if word_count < 3:
        return True
    if any(_re.fullmatch(pattern, normalized) for pattern in GENERIC_VAGUE_PATTERNS):
        return True
    if is_global_opinion_only(text):
        return True
    has_any_mention = any(
        _re.search(pattern, normalized)
        for patterns in MENTION_PATTERNS.values()
        for pattern in patterns
    )
    if word_count < 8 and not has_any_mention:
        return True
    return False


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


def _apply_valuation_fallback(analysis: AnalysisResult, accumulated_text: str) -> AnalysisResult:
    """Conservative deterministic fallback: fills valuation_text when LLM left it empty.

    Conditions to activate for a modality:
    - mention_text and descriptor_text are already present
    - valuation_text is empty
    - accumulated_text contains a literal valuation expression for that modality

    Never invents text. Uses literal sentences from accumulated_text.
    is_complete is recomputed by the next _normalized_analysis call.
    """
    changed: dict[str, ModalityResult] = {}
    for modality, result in analysis.modalities.items():
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

        #3. Guarda el turno del usuario
        self.conversation_service.add_turn(db, evaluation, SpeakerType.USER.value, MessageType.USER_RESPONSE.value, cleaned_message)

        #4. Añade el mensaje al texto acumulado
        evaluation.accumulated_text = '\n'.join(filter(None, [evaluation.accumulated_text.strip(), cleaned_message])).strip()
        
        #5. Decide si el análisis es INITIAL o INTERMEDIATE
        if not evaluation.initial_response_text:
            evaluation.initial_response_text = cleaned_message
            analysis_scope = AnalysisScope.INITIAL.value
        else:
            analysis_scope = AnalysisScope.INTERMEDIATE.value

        covered_modalities = ModalityCoverageService.covered_modalities_from_latest(evaluation)
        # Capture previous bot question before FlowDecisionEngine overwrites next_question
        previous_bot_question = evaluation.next_question

        # Derive sample context for comparison detection
        current_sample_code: str | None = evaluation.sample.sample_code if evaluation.sample else None
        _config = evaluation.session.admin_session if evaluation.session else None
        session_sample_codes: list[str] = (
            list(_config.sample_codes_json) if _config and _config.sample_codes_json else
            ([current_sample_code] if current_sample_code else [])
        )
        other_sample_codes: list[str] = [c for c in session_sample_codes if c != current_sample_code]

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

        # 7c. Suppress is_vague from LLM for directed modality-question turns.
        # Responses to "¿te gusta?" are valid short answers — marking them vague is wrong
        # and would pollute the persisted analysis with misleading vagueness flags.
        if evaluation.current_state == EvaluationState.MODALITY_QUESTION.value:
            analysis = analysis.model_copy(update={'is_vague': False})

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
        analysis = _apply_valuation_fallback(analysis, evaluation.accumulated_text)
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

        #9. Aplica detección determinista de vaguedad (solo fuera de preguntas dirigidas)
        if evaluation.current_state != EvaluationState.MODALITY_QUESTION.value and _looks_clearly_vague(cleaned_message):
            analysis = analysis.model_copy(update={'is_vague': True})

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
        resolved_final_analysis = final_analysis.model_copy(update={'analysis_scope': AnalysisScope.FINAL.value}) if final_analysis is not None else None
        if resolved_final_analysis is None:
            try:
                resolved_final_analysis = await self.analyzer.analyze(
                    analysis_scope=AnalysisScope.FINAL.value,
                    current_state=evaluation.current_state,
                    current_modality=evaluation.current_modality,
                    user_last_message=evaluation.accumulated_text,
                    accumulated_text=evaluation.accumulated_text,
                    covered_modalities=ModalityCoverageService.covered_modalities_from_latest(evaluation),
                    vague_retry_count=evaluation.vague_retry_count,
                    comparison_retry_count=evaluation.comparison_retry_count,
                )
                resolved_final_analysis = _normalized_analysis(resolved_final_analysis)
            except AnalyzerUnavailableError as exc:
                logger.exception('Final analyzer unavailable, closing evaluation with latest persisted analysis: %s', exc)
                resolved_final_analysis = None
        if resolved_final_analysis is not None:
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
