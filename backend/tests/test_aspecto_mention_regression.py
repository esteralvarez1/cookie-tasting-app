"""Regression: ASPECTO:MENCION must not be a stale sabor/olor sentence.

Real case (current_modality = ASPECTO, last message "es un poco soso, redondo"):
the descriptor "soso, redondo" comes from the current turn, but the mention used to
be pulled from an earlier sentence ("una galleta demasiado dulce..."). The mention
must describe the SAME evidence as the descriptor — i.e. the participant's current
answer about the aspect.
"""
from __future__ import annotations

from types import SimpleNamespace
from datetime import datetime, timezone

from app.services.analyzer.models import AnalysisResult, ModalityResult
from app.services.analyzer.openai_compatible import MODALITY_FOCUS_INSTRUCTIONS
from app.services.dialogue import _apply_modality_context, _merge_keep_best

_STALE_SABOR_SENTENCE = 'una galleta demasiado dulce (no consumo azúcar), con un toque a canela muy agradable.'
_ASPECT_QUESTION = '¿Cómo describirías el aspecto de la galleta?'
_T0 = datetime(2026, 6, 13, tzinfo=timezone.utc)


def _row(modality, mention, descriptor, valuation, complete):
    return SimpleNamespace(
        modality=modality, mention_text=mention, descriptor_text=descriptor,
        valuation_text=valuation, is_complete=complete,
    )


def _evaluation_with_prev_aspecto(prev_mention: str):
    """Fake evaluation whose latest persisted ASPECTO holds a stale (sabor) mention."""
    prev_analysis = SimpleNamespace(
        created_at=_T0,
        modalities=[_row('ASPECTO', prev_mention, '', '', False)],
    )
    return SimpleNamespace(analyses=[prev_analysis])


def _curr_analysis(aspecto: ModalityResult) -> AnalysisResult:
    mods = {m: ModalityResult() for m in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR')}
    mods['ASPECTO'] = aspecto
    return AnalysisResult(
        analysis_scope='INTERMEDIATE', is_vague=False, has_comparison=False,
        reasoning_summary='', modalities=mods,
    )


class TestAspectoMentionReanchored:
    def test_mention_uses_current_answer_when_curr_mention_empty(self):
        # Test 1: descriptor fresh from current turn, mention empty → backend used to
        # fall back to the stale persisted sabor sentence. Now it re-anchors to the answer.
        ev = _evaluation_with_prev_aspecto(_STALE_SABOR_SENTENCE)
        curr = _curr_analysis(ModalityResult(
            mention_text='', descriptor_text='soso, redondo', valuation_text='no', is_complete=False,
        ))
        out = _apply_modality_context(ev, curr, 'ASPECTO', 'es un poco soso, redondo', _ASPECT_QUESTION)
        aspecto = out.modalities['ASPECTO']
        assert aspecto.mention_text == 'es un poco soso, redondo'
        assert aspecto.descriptor_text == 'soso, redondo'

    def test_mention_not_taken_from_previous_sabor_sentence(self):
        # Test 3: even if the LLM itself hallucinated the sabor sentence as the ASPECTO
        # mention, it must be re-anchored to the current aspect answer.
        ev = _evaluation_with_prev_aspecto('')
        curr = _curr_analysis(ModalityResult(
            mention_text=_STALE_SABOR_SENTENCE, descriptor_text='soso, redondo', valuation_text='no', is_complete=False,
        ))
        out = _apply_modality_context(ev, curr, 'ASPECTO', 'es un poco soso, redondo', _ASPECT_QUESTION)
        assert out.modalities['ASPECTO'].mention_text == 'es un poco soso, redondo'
        assert _STALE_SABOR_SENTENCE not in out.modalities['ASPECTO'].mention_text

    def test_precise_span_mention_is_kept(self):
        # Defensive: if the mention is already a substring of the current answer, keep it.
        ev = _evaluation_with_prev_aspecto('')
        curr = _curr_analysis(ModalityResult(
            mention_text='es un poco soso, redondo', descriptor_text='soso, redondo', valuation_text='no', is_complete=False,
        ))
        out = _apply_modality_context(ev, curr, 'ASPECTO', 'es un poco soso, redondo', _ASPECT_QUESTION)
        assert out.modalities['ASPECTO'].mention_text == 'es un poco soso, redondo'

    def test_valuation_only_answer_does_not_steal_mention(self):
        # Guard against over-firing: a valuation-only answer ("sí, me gusta") with no
        # aspect evidence must NOT overwrite a previously valid ASPECTO mention.
        ev = SimpleNamespace(analyses=[SimpleNamespace(
            created_at=_T0,
            modalities=[_row('ASPECTO', 'es dorada y redonda', 'dorado, redonda', '', False)],
        )])
        curr = _curr_analysis(ModalityResult())  # LLM returned nothing this turn
        out = _apply_modality_context(ev, curr, 'ASPECTO', 'sí, me gusta', '¿Y qué te parece el aspecto, te gusta o no te gusta?')
        # Mention preserved from the prior valid ASPECTO evidence, not replaced by "sí, me gusta".
        assert out.modalities['ASPECTO'].mention_text == 'es dorada y redonda'


class TestSosoStaysInAspectoInstruction:
    def test_aspecto_focus_instruction_mentions_soso(self):
        # Test 2: "soso" must remain a recognised ASPECTO descriptor in the focus block.
        assert 'soso' in MODALITY_FOCUS_INSTRUCTIONS['ASPECTO'].lower()


class TestMergeKeepBestDoesNotFieldMix:
    def test_merge_returns_whole_result_without_mixing_fields(self):
        # Test 4: _merge_keep_best must return ONE whole result, never a Frankenstein of
        # one result's mention with another result's descriptor.
        fresh = ModalityResult(
            mention_text='es un poco soso, redondo', descriptor_text='soso, redondo',
            valuation_text='no', is_complete=True,
        )
        stale = ModalityResult(
            mention_text=_STALE_SABOR_SENTENCE, descriptor_text='dorado',
            valuation_text='me gusta', is_complete=True,
        )
        out = _merge_keep_best(fresh, stale)
        # Both complete → tie keeps the fresh (primary) result, intact.
        assert out.mention_text == fresh.mention_text
        assert out.descriptor_text == fresh.descriptor_text
        assert out.valuation_text == fresh.valuation_text
        # The two fields never come from different results.
        assert not (out.mention_text == _STALE_SABOR_SENTENCE and out.descriptor_text == 'soso, redondo')
