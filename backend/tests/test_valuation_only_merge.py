"""Regression: a valuation-only answer must not overwrite mention/descriptor.

General bug (all four modalities): after the user gave a modality descriptor and the
bot asks for the valuation, a short opinion like "no me encanta" / "me gusta" /
"regular" / "no mucho" must fill ONLY valuation_text, preserving the previous
mention_text and descriptor_text of that modality.
"""
from __future__ import annotations

from types import SimpleNamespace
from datetime import datetime, timezone

import pytest

from app.services.analyzer.models import AnalysisResult, ModalityResult
from app.services.dialogue import _apply_modality_context, _is_valuation_only_response

_T0 = datetime(2026, 6, 13, tzinfo=timezone.utc)


def _row(modality, mention, descriptor, valuation, complete):
    return SimpleNamespace(
        modality=modality, mention_text=mention, descriptor_text=descriptor,
        valuation_text=valuation, is_complete=complete,
    )


def _evaluation_with_prev(modality, mention, descriptor):
    prev_analysis = SimpleNamespace(
        created_at=_T0,
        modalities=[_row(modality, mention, descriptor, '', False)],
    )
    return SimpleNamespace(analyses=[prev_analysis])


def _curr_with_polluted_modality(modality, polluting_message):
    """Simulate an LLM that wrongly echoes the short valuation answer as the
    modality's mention/descriptor; the branch must ignore it."""
    mods = {m: ModalityResult() for m in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR')}
    mods[modality] = ModalityResult(
        mention_text=polluting_message,
        descriptor_text='basura-del-llm',
        valuation_text=polluting_message,
        is_complete=False,
    )
    return AnalysisResult(
        analysis_scope='INTERMEDIATE', is_vague=False, has_comparison=False,
        reasoning_summary='', modalities=mods,
    )


_VAL_QUESTION = {
    'ASPECTO': '¿Y qué te parece el aspecto, te gusta o no te gusta?',
    'OLOR': '¿Y qué te parece el olor, te gusta o no te gusta?',
    'TEXTURA': '¿Y qué te parece la textura, te gusta o no te gusta?',
    'SABOR': '¿Y qué te parece el sabor, te gusta o no te gusta?',
}


class TestValuationOnlyPreservesMentionAndDescriptor:
    @pytest.mark.parametrize('modality, mention, descriptor, answer', [
        ('ASPECTO', 'Tiene un aspecto apagado y no muy dorado', 'apagado, no muy dorado', 'no me encanta'),
        ('OLOR', 'Huele a canela', 'canela', 'me gusta'),
        ('TEXTURA', 'La textura es crujiente', 'crujiente', 'regular'),
        ('SABOR', 'Tiene un sabor suave', 'suave', 'no mucho'),
    ])
    def test_valuation_only_fills_only_valuation(self, modality, mention, descriptor, answer):
        ev = _evaluation_with_prev(modality, mention, descriptor)
        curr = _curr_with_polluted_modality(modality, answer)
        out = _apply_modality_context(ev, curr, modality, answer, _VAL_QUESTION[modality])
        result = out.modalities[modality]
        assert result.mention_text == mention, 'la mención previa debe conservarse'
        assert result.descriptor_text == descriptor, 'el descriptor previo debe conservarse'
        assert result.valuation_text == answer
        assert result.is_complete is True
        # The polluting LLM values must NOT survive.
        assert result.mention_text != answer
        assert result.descriptor_text != 'basura-del-llm'

    def test_other_modalities_untouched(self):
        ev = _evaluation_with_prev('ASPECTO', 'aspecto apagado', 'apagado')
        curr = _curr_with_polluted_modality('ASPECTO', 'no me encanta')
        out = _apply_modality_context(ev, curr, 'ASPECTO', 'no me encanta', _VAL_QUESTION['ASPECTO'])
        for other in ('OLOR', 'TEXTURA', 'SABOR'):
            assert out.modalities[other].mention_text == ''
            assert out.modalities[other].descriptor_text == ''


class TestValuationOnlyDetection:
    @pytest.mark.parametrize('answer', [
        'sí', 'no', 'me gusta', 'no me gusta', 'me encanta', 'no me encanta',
        'regular', 'normal', 'no mucho', 'me parece bien', 'me parece mal',
        'demasiado', 'un poco', 'está bien', 'no está mal',
    ])
    def test_positive_examples(self, answer):
        assert _is_valuation_only_response(answer, '¿Y qué te parece el aspecto, te gusta o no te gusta?', 'ASPECTO') is True

    @pytest.mark.parametrize('answer, modality', [
        ('es un poco soso, redondo', 'ASPECTO'),   # aporta descriptor ASPECTO (redondo)
        ('huele a canela', 'OLOR'),                # aporta descriptor OLOR
        ('es crujiente', 'TEXTURA'),               # aporta descriptor TEXTURA
        ('es dulce', 'SABOR'),                     # aporta descriptor SABOR
        ('me gusta porque es crujiente', 'TEXTURA'),  # valoración + descriptor
    ])
    def test_negative_examples_with_descriptor(self, answer, modality):
        assert _is_valuation_only_response(answer, _VAL_QUESTION[modality], modality) is False

    def test_negative_when_bot_not_asking_valuation(self):
        # A descriptor question is not a valuation question.
        assert _is_valuation_only_response('me gusta', '¿Cómo describirías el aspecto de la galleta?', 'ASPECTO') is False


class TestDescriptorAnswerStillUpdates:
    def test_descriptor_answer_is_not_valuation_only(self):
        # "es un poco soso, redondo" to an ASPECTO question must update mention/descriptor,
        # i.e. it must NOT go through the valuation-only branch.
        ev = _evaluation_with_prev('ASPECTO', '', '')
        curr = AnalysisResult(
            analysis_scope='INTERMEDIATE', is_vague=False, has_comparison=False, reasoning_summary='',
            modalities={
                'ASPECTO': ModalityResult(mention_text='', descriptor_text='soso, redondo', valuation_text='no', is_complete=False),
                'OLOR': ModalityResult(), 'TEXTURA': ModalityResult(), 'SABOR': ModalityResult(),
            },
        )
        out = _apply_modality_context(ev, curr, 'ASPECTO', 'es un poco soso, redondo', 'Ahora cuéntame cómo es el aspecto de la galleta y qué te parece.')
        aspecto = out.modalities['ASPECTO']
        assert aspecto.mention_text == 'es un poco soso, redondo'
        assert aspecto.descriptor_text == 'soso, redondo'
