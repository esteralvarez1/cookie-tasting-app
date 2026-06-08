"""Tests for modality question text — verifies that questions are neutral and concise.

Ensures that build_modality_question() does not include lists of concrete sensory
attributes that could bias participant responses.
"""
from __future__ import annotations

import pytest

from app.services.modality_questions import INITIAL_QUESTION, build_modality_question

# Attribute examples that must NOT appear in directed questions
_BIASING_WORDS = [
    'color', 'forma', 'tamaño', 'grosor',
    'crujiente', 'blanda', 'dura', 'seca', 'arenosa', 'pegajosa',
    'dulce', 'salada', 'salado', 'amarga', 'amargo',
    'suave', 'intenso', 'intensa',
    'a qué huele',
]

_ALL_MODALITIES = ['ASPECTO', 'OLOR', 'TEXTURA', 'SABOR']


class TestBuildModalityQuestionNeutral:
    """Primary modality question (no mention, no descriptor, no valuation) must be neutral."""

    @pytest.mark.parametrize('modality', _ALL_MODALITIES)
    def test_primary_question_contains_no_biasing_examples(self, modality):
        question = build_modality_question(modality)
        lower = question.lower()
        for word in _BIASING_WORDS:
            assert word not in lower, (
                f'La pregunta principal de {modality} contiene el ejemplo condicionante "{word}": {question!r}'
            )

    @pytest.mark.parametrize('modality', _ALL_MODALITIES)
    def test_primary_question_mentions_modality_name(self, modality):
        question = build_modality_question(modality)
        modality_label = {'ASPECTO': 'aspecto', 'OLOR': 'olor', 'TEXTURA': 'textura', 'SABOR': 'sabor'}[modality]
        assert modality_label in question.lower()

    def test_aspecto_primary_exact(self):
        assert build_modality_question('ASPECTO') == 'Ahora cuéntame cómo es el aspecto de la galleta y qué te parece.'

    def test_olor_primary_exact(self):
        assert build_modality_question('OLOR') == 'Ahora cuéntame cómo es el olor de la galleta y qué te parece.'

    def test_textura_primary_exact(self):
        assert build_modality_question('TEXTURA') == 'Ahora cuéntame cómo es la textura de la galleta y qué te parece.'

    def test_sabor_primary_exact(self):
        assert build_modality_question('SABOR') == 'Ahora cuéntame cómo es el sabor de la galleta y qué te parece.'


class TestBuildModalityQuestionDescriptorMissing:
    """When valuation exists but descriptor is missing, question must ask for description without examples."""

    @pytest.mark.parametrize('modality', _ALL_MODALITIES)
    def test_descriptor_question_contains_no_biasing_examples(self, modality):
        question = build_modality_question(modality, mention_text='lo mencioné', valuation_text='me gusta')
        lower = question.lower()
        for word in _BIASING_WORDS:
            assert word not in lower, (
                f'La pregunta de descriptor de {modality} contiene "{word}": {question!r}'
            )

    def test_aspecto_descriptor_exact(self):
        q = build_modality_question('ASPECTO', mention_text='algo', valuation_text='me gusta')
        assert q == '¿Cómo describirías el aspecto de la galleta?'

    def test_olor_descriptor_exact(self):
        q = build_modality_question('OLOR', mention_text='algo', valuation_text='me gusta')
        assert q == '¿Cómo describirías el olor de la galleta?'

    def test_textura_descriptor_exact(self):
        q = build_modality_question('TEXTURA', mention_text='algo', valuation_text='me gusta')
        assert q == '¿Cómo describirías la textura de la galleta?'

    def test_sabor_descriptor_exact(self):
        q = build_modality_question('SABOR', mention_text='algo', valuation_text='me gusta')
        assert q == '¿Cómo describirías el sabor de la galleta?'


class TestBuildModalityQuestionValuationMissing:
    """When valuation is the only missing field, question must ask directly for it."""

    @pytest.mark.parametrize('modality', _ALL_MODALITIES)
    def test_valuation_question_asks_te_gusta(self, modality):
        question = build_modality_question(modality, mention_text='algo', descriptor_text='desc')
        lower = question.lower()
        assert 'te parece' in lower or 'te gusta' in lower

    @pytest.mark.parametrize('modality', _ALL_MODALITIES)
    def test_valuation_question_contains_no_biasing_examples(self, modality):
        question = build_modality_question(modality, mention_text='algo', descriptor_text='desc')
        lower = question.lower()
        for word in _BIASING_WORDS:
            assert word not in lower


class TestInitialQuestion:
    def test_initial_question_does_not_list_sensory_attributes(self):
        lower = INITIAL_QUESTION.lower()
        # Specific sensory attribute words must not appear
        for word in ('crujiente', 'dulce', 'salado', 'color', 'forma', 'grosor'):
            assert word not in lower, f'INITIAL_QUESTION contiene "{word}": {INITIAL_QUESTION!r}'

    def test_initial_question_mentions_four_modalities(self):
        lower = INITIAL_QUESTION.lower()
        for modality in ('aspecto', 'olor', 'textura', 'sabor'):
            assert modality in lower
