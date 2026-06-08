from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.enums import ModalityType
from app.services.analyzer.base import BaseAnalyzer
from app.services.analyzer.models import AnalysisResult, ModalityResult
from app.services.modality_metadata import (
    ASPECT_CONTEXT_PATTERNS,
    COMPARISON_MARKERS,
    DESCRIPTOR_WORDS,
    GENERIC_VAGUE_PATTERNS,
    GLOBAL_OPINION_PATTERNS,
    MENTION_PATTERNS,
    MODALITY_ORDER,
    SMELL_CONTEXT_PATTERNS,
    TASTE_CONTEXT_PATTERNS,
    TEXTURE_CONTEXT_PATTERNS,
    VALUATION_MARKERS,
    has_comparison,
    is_global_opinion_only,
    normalize_text,
    split_sentences,
)

# Words shared between OLOR and SABOR that require an explicit smell context
# anchor (olor, aroma, huele…) in the same sentence to be assigned to OLOR,
# or an explicit taste anchor to be assigned to SABOR when smell is dominant.
# All values are pre-normalized (no accents, lowercase).
_OLOR_SABOR_AMBIGUOUS: frozenset[str] = frozenset({
    # Flavor / aroma words
    'vainilla', 'chocolate', 'cacao', 'mantequilla',
    'canela', 'jengibre', 'caramelo', 'azucar tostada',
    'a vainilla', 'a chocolate', 'a cacao', 'a canela',
    'a jengibre', 'a caramelo', 'a mantequilla', 'a azucar tostada', 'a quemado',
    'artificial', 'natural', 'rancio', 'rancia',
    'dulce', 'especiado', 'especiada',
    # Intensity / quality words — appear in both OLOR and SABOR vocabulary;
    # without an explicit smell anchor they must not be assigned to OLOR.
    'fuerte', 'suave', 'intenso', 'intensa', 'leve', 'debil',
    'casi imperceptible', 'imperceptible',
    'agradable', 'desagradable',
    'rico', 'rica',
})

_NO_SMELL_PATTERNS = [
    r'no (?:me )?(?:huele?|oli[ao])\b',
    r'\bno (?:tiene?|tenia?) (?:ningun )?olor\b',
    r'\bsin olor\b',
    r'\bno (?:percibo|noto)\b',
    r'\bolor\s+(?:muy\s+)?(?:suave|imperceptible|ligero)\b',
    r'\bapenas?\s+huele?\b',
    r'\bhuelo\s+(?:muy\s+)?poco\b',
]

ANCHOR_PATTERNS = {
    'ASPECTO': ASPECT_CONTEXT_PATTERNS,
    'OLOR': SMELL_CONTEXT_PATTERNS,
    'TEXTURA': TEXTURE_CONTEXT_PATTERNS,
    'SABOR': TASTE_CONTEXT_PATTERNS,
}


@dataclass(frozen=True)
class SentenceEvidence:
    sentence: str
    score: int


def _contains_any_pattern(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _count_pattern_hits(text: str, patterns: list[str]) -> int:
    return sum(1 for pattern in patterns if re.search(pattern, text))


def _descriptor_hits(text: str, modality: str) -> list[str]:
    """Return DESCRIPTOR_WORDS entries found in text, with cross-modal guards."""
    lowered = normalize_text(text)
    has_smell = _contains_any_pattern(lowered, SMELL_CONTEXT_PATTERNS)
    has_taste = _contains_any_pattern(lowered, TASTE_CONTEXT_PATTERNS)
    has_aspect = _contains_any_pattern(lowered, ASPECT_CONTEXT_PATTERNS)

    descriptors = []
    for word in DESCRIPTOR_WORDS[modality]:
        word_norm = normalize_text(word)
        if word_norm not in lowered:
            continue

        # Guard: ambiguous OLOR/SABOR flavor words require an explicit context anchor.
        if modality == 'OLOR' and word_norm in _OLOR_SABOR_AMBIGUOUS:
            # Skip if no smell anchor in the sentence
            if not has_smell:
                continue

        if modality == 'SABOR' and word_norm in _OLOR_SABOR_AMBIGUOUS:
            # Skip if the sentence is exclusively a smell context (no taste anchor)
            if has_smell and not has_taste:
                continue

        # Guard: ASPECTO descriptors that overlap with other modalities need an
        # explicit visual/aspect anchor when other modality context is dominant.
        if modality == 'ASPECTO' and not has_aspect:
            # Only skip visually ambiguous words that also appear in texture context
            if word_norm in {'seca', 'seco', 'compacta', 'compacto'}:
                if _contains_any_pattern(lowered, TEXTURE_CONTEXT_PATTERNS):
                    continue

        descriptors.append(word)

    return list(dict.fromkeys(descriptors))


def _cross_modality_penalty(text: str, modality: str) -> int:
    lowered = normalize_text(text)
    has_smell = _contains_any_pattern(lowered, SMELL_CONTEXT_PATTERNS)
    has_taste = _contains_any_pattern(lowered, TASTE_CONTEXT_PATTERNS)
    has_texture = _contains_any_pattern(lowered, TEXTURE_CONTEXT_PATTERNS)
    has_aspect = _contains_any_pattern(lowered, ASPECT_CONTEXT_PATTERNS)

    if modality == 'SABOR' and has_smell and not has_taste:
        return 3
    if modality == 'OLOR' and has_taste and not has_smell:
        return 3
    # Penalise ASPECTO when the sentence is dominated by a different modality context
    # and has no explicit visual anchor (aspecto, color, forma, etc.).
    if modality == 'ASPECTO' and not has_aspect:
        if has_taste or has_smell or has_texture:
            return 2
    return 0


def _valuation_score(text: str) -> int:
    lowered = normalize_text(text)
    positive = sum(1 for marker in VALUATION_MARKERS['positive'] if normalize_text(marker) in lowered)
    negative = sum(1 for marker in VALUATION_MARKERS['negative'] if normalize_text(marker) in lowered)
    return positive + negative


def _marker_spans(text: str, patterns: list[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            spans.append(match.span())
    return spans


def _term_spans(text: str, terms: list[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for term in terms:
        term_norm = normalize_text(term)
        if not term_norm:
            continue
        start = 0
        while True:
            idx = text.find(term_norm, start)
            if idx == -1:
                break
            spans.append((idx, idx + len(term_norm)))
            start = idx + len(term_norm)
    return spans


def _valuation_is_local(sentence: str, modality: str) -> bool:
    lowered = normalize_text(sentence)
    valuation_spans = _term_spans(lowered, VALUATION_MARKERS['positive'] + VALUATION_MARKERS['negative'])
    if not valuation_spans:
        return False
    anchor_spans = _marker_spans(lowered, MENTION_PATTERNS[modality]) + _term_spans(lowered, DESCRIPTOR_WORDS[modality])
    if not anchor_spans:
        return False
    for a_start, a_end in anchor_spans:
        for v_start, v_end in valuation_spans:
            if min(abs(v_start - a_end), abs(a_start - v_end)) <= 45:
                return True
    return False


def _best_sentence(sentences: list[str], modality: str, require_valuation: bool = False) -> str:
    best: SentenceEvidence | None = None
    patterns = MENTION_PATTERNS[modality]

    for sentence in sentences:
        lowered = normalize_text(sentence)
        descriptors = _descriptor_hits(sentence, modality)
        anchor_hits = _count_pattern_hits(lowered, patterns)
        descriptor_hits = len(descriptors)
        valuation_hits = _valuation_score(sentence)
        score = anchor_hits + descriptor_hits + valuation_hits - _cross_modality_penalty(sentence, modality)
        if has_comparison(sentence):
            score -= 4
        if require_valuation and valuation_hits == 0:
            continue
        if require_valuation and (anchor_hits + descriptor_hits) == 0:
            continue
        if require_valuation and not _valuation_is_local(sentence, modality):
            continue
        if score <= 0:
            continue
        if best is None or score > best.score:
            best = SentenceEvidence(sentence=sentence.strip(), score=score)
    return best.sentence if best else ''


def _find_descriptors(text: str, modality: str) -> str:
    descriptors = _descriptor_hits(text, modality)
    if not descriptors and modality == 'OLOR':
        lowered = normalize_text(text)
        if any(re.search(p, lowered) for p in _NO_SMELL_PATTERNS):
            return 'sin olor'
    return ', '.join(sorted(dict.fromkeys(descriptors), key=lambda item: normalize_text(item)))


def _is_modality_complete(mention_text: str, descriptor_text: str, valuation_text: str) -> bool:
    return bool(mention_text.strip() and descriptor_text.strip() and valuation_text.strip())


def _has_any_modality_signal(accumulated_text: str) -> bool:
    lowered = normalize_text(accumulated_text)
    return any(_contains_any_pattern(lowered, patterns) for patterns in MENTION_PATTERNS.values())


def _is_vague(accumulated_text: str, modalities: dict[str, ModalityResult]) -> bool:
    lowered = normalize_text(accumulated_text)
    word_count = len(re.findall(r'\w+', lowered, flags=re.UNICODE))
    if not lowered:
        return True
    if any(re.fullmatch(pattern, lowered.strip()) for pattern in GENERIC_VAGUE_PATTERNS):
        return True
    if is_global_opinion_only(accumulated_text):
        return True

    completed_modalities = sum(1 for result in modalities.values() if result.is_complete)
    descriptive_modalities = sum(1 for result in modalities.values() if result.descriptor_text.strip())
    valuation_modalities = sum(1 for result in modalities.values() if result.valuation_text.strip())
    any_signal = _has_any_modality_signal(accumulated_text) or any(result.mention_text for result in modalities.values())

    if word_count < 3:
        return True
    if word_count < 6 and descriptive_modalities == 0:
        return True
    if word_count < 10 and not any_signal:
        return True
    if descriptive_modalities == 0 and valuation_modalities == 0:
        return True
    if completed_modalities == 0 and word_count < 14:
        return True
    return False


class RuleBasedAnalyzer(BaseAnalyzer):
    provider_name = 'rules'
    model_name = 'local-rules'
    prompt_version = 'rules_v6_cookie_domain'

    async def analyze(
        self,
        analysis_scope: str,
        current_state: str,
        current_modality: str | None,
        user_last_message: str,
        accumulated_text: str,
        covered_modalities: list[str],
        vague_retry_count: int,
        comparison_retry_count: int,
        previous_bot_question: str | None = None,
        current_sample_code: str | None = None,
        session_sample_codes: list[str] | None = None,
        other_sample_codes: list[str] | None = None,
    ) -> AnalysisResult:
        sentences = split_sentences(accumulated_text)
        has_comparison_flag = has_comparison(user_last_message, other_sample_codes or [])

        modalities: dict[str, ModalityResult] = {}
        for modality in MODALITY_ORDER:
            mention_text = _best_sentence(sentences, modality)
            descriptor_text = _find_descriptors(mention_text or accumulated_text, modality)
            valuation_text = _best_sentence(sentences, modality, require_valuation=True)
            is_complete = _is_modality_complete(mention_text, descriptor_text, valuation_text)
            modalities[modality] = ModalityResult(
                mention_text=mention_text,
                descriptor_text=descriptor_text,
                valuation_text=valuation_text,
                is_complete=is_complete,
            )

        return AnalysisResult(
            analysis_scope=analysis_scope,
            is_vague=_is_vague(accumulated_text, modalities),
            has_comparison=has_comparison_flag,
            reasoning_summary='Análisis por reglas locales con separación estricta por modalidad',
            modalities=modalities,
        )
