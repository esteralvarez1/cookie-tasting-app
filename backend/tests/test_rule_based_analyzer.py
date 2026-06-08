"""Tests for the rule-based analyzer (RuleBasedAnalyzer).

All tests are pure unit tests — no DB or HTTP layer needed.
The analyzer is called directly via analyze() with accumulated_text equal to
the test message (single-turn scenario).
"""
from __future__ import annotations

import asyncio

import pytest

from app.services.analyzer.rules import RuleBasedAnalyzer

_analyzer = RuleBasedAnalyzer()


def _analyze(text: str):
    """Helper: analyze a single-turn message and return AnalysisResult."""
    return asyncio.run(_analyzer.analyze(
        analysis_scope='INITIAL_QUESTION',
        current_state='INITIAL_QUESTION',
        current_modality=None,
        user_last_message=text,
        accumulated_text=text,
        covered_modalities=[],
        vague_retry_count=0,
        comparison_retry_count=0,
    ))


def _mod(result, modality: str):
    return result.modalities[modality]


# ---------------------------------------------------------------------------
# Case 1 — Textura seca y boronosa
# ---------------------------------------------------------------------------

class TestCase1TexturaSeca:
    """TEXTURA must detect descriptor + valuation; ASPECTO must NOT complete."""

    TEXT = 'La textura es seca y boronosa, genera muchas migas.'

    def test_textura_has_mention(self):
        r = _analyze(self.TEXT)
        assert _mod(r, 'TEXTURA').mention_text

    def test_textura_has_descriptor(self):
        r = _analyze(self.TEXT)
        desc = _mod(r, 'TEXTURA').descriptor_text.lower()
        assert 'seca' in desc or 'boronosa' in desc

    def test_textura_has_valuation(self):
        r = _analyze(self.TEXT)
        val = _mod(r, 'TEXTURA').valuation_text.lower()
        assert 'migas' in val or 'boronosa' in val

    def test_textura_is_complete(self):
        r = _analyze(self.TEXT)
        assert _mod(r, 'TEXTURA').is_complete is True

    def test_aspecto_not_complete(self):
        r = _analyze(self.TEXT)
        assert _mod(r, 'ASPECTO').is_complete is False

    def test_no_false_descriptor_in_aspecto(self):
        # 'seca' must not appear as an ASPECTO descriptor when sentence is about texture
        r = _analyze(self.TEXT)
        desc = _mod(r, 'ASPECTO').descriptor_text.lower()
        assert 'seca' not in desc


# ---------------------------------------------------------------------------
# Case 2 — Sabor con azúcar tostada y empalaga
# ---------------------------------------------------------------------------

class TestCase2SaborEmpalaga:
    """SABOR must detect descriptor + negative valuation; OLOR must NOT complete."""

    TEXT = 'El sabor tiene azúcar tostada y jengibre artificial. Empalaga mucho.'

    def test_sabor_has_mention(self):
        r = _analyze(self.TEXT)
        assert _mod(r, 'SABOR').mention_text

    def test_sabor_has_descriptor(self):
        r = _analyze(self.TEXT)
        desc = _mod(r, 'SABOR').descriptor_text.lower()
        assert 'jengibre' in desc or 'azucar' in desc or 'artificial' in desc

    def test_sabor_has_valuation(self):
        r = _analyze(self.TEXT)
        val = _mod(r, 'SABOR').valuation_text.lower()
        assert 'empalaga' in val or 'artificial' in val

    def test_sabor_is_complete(self):
        r = _analyze(self.TEXT)
        assert _mod(r, 'SABOR').is_complete is True

    def test_olor_not_complete(self):
        # 'jengibre' must not complete OLOR when the sentence has only taste context
        r = _analyze(self.TEXT)
        assert _mod(r, 'OLOR').is_complete is False

    def test_olor_mention_text_empty_or_irrelevant(self):
        r = _analyze(self.TEXT)
        # OLOR should not have a non-empty mention pointing to taste text
        mention = _mod(r, 'OLOR').mention_text
        # If OLOR has a mention, it must not be the sabor sentence
        if mention:
            assert 'sabor' not in mention.lower()


# ---------------------------------------------------------------------------
# Case 3 — Olor a vainilla vs sabor a chocolate
# ---------------------------------------------------------------------------

class TestCase3OlorVsSabor:
    """OLOR must detect vainilla; SABOR must detect chocolate / jengibre."""

    TEXT = 'Huele a vainilla, pero el sabor es a chocolate con jengibre artificial.'

    def test_olor_has_vainilla(self):
        r = _analyze(self.TEXT)
        desc = _mod(r, 'OLOR').descriptor_text.lower()
        assert 'vainilla' in desc

    def test_olor_has_mention(self):
        r = _analyze(self.TEXT)
        assert _mod(r, 'OLOR').mention_text

    def test_sabor_has_chocolate_or_jengibre(self):
        r = _analyze(self.TEXT)
        desc = _mod(r, 'SABOR').descriptor_text.lower()
        assert 'chocolate' in desc or 'jengibre' in desc

    def test_sabor_has_mention(self):
        r = _analyze(self.TEXT)
        assert _mod(r, 'SABOR').mention_text


# ---------------------------------------------------------------------------
# Case 4 — Aspecto irregular y poco atractivo
# ---------------------------------------------------------------------------

class TestCase4AspectoPocoCAtractivo:
    """ASPECTO must detect descriptor 'irregular' and valuation 'poco atractivo'."""

    TEXT = 'El aspecto es irregular y poco atractivo.'

    def test_aspecto_has_mention(self):
        r = _analyze(self.TEXT)
        assert _mod(r, 'ASPECTO').mention_text

    def test_aspecto_has_descriptor_irregular(self):
        r = _analyze(self.TEXT)
        desc = _mod(r, 'ASPECTO').descriptor_text.lower()
        assert 'irregular' in desc

    def test_aspecto_has_negative_valuation(self):
        r = _analyze(self.TEXT)
        val = _mod(r, 'ASPECTO').valuation_text.lower()
        assert 'poco atractivo' in val or 'atractivo' in val

    def test_aspecto_is_complete(self):
        r = _analyze(self.TEXT)
        assert _mod(r, 'ASPECTO').is_complete is True

    def test_other_modalities_not_complete(self):
        r = _analyze(self.TEXT)
        assert _mod(r, 'OLOR').is_complete is False
        assert _mod(r, 'TEXTURA').is_complete is False
        assert _mod(r, 'SABOR').is_complete is False


# ---------------------------------------------------------------------------
# Case 5 — "Está bien." — vaga sin modalidad concreta
# ---------------------------------------------------------------------------

class TestCase5VagueEstaBien:
    def test_is_vague(self):
        r = _analyze('Está bien.')
        assert r.is_vague is True

    def test_no_modality_complete(self):
        r = _analyze('Está bien.')
        for m in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR'):
            assert _mod(r, m).is_complete is False, f'{m} no debe completarse con "Está bien."'


# ---------------------------------------------------------------------------
# Case 6 — "Me gusta." — valoración global sin modalidad
# ---------------------------------------------------------------------------

class TestCase6VagueMeGusta:
    def test_is_vague(self):
        r = _analyze('Me gusta.')
        assert r.is_vague is True

    def test_no_modality_complete(self):
        r = _analyze('Me gusta.')
        for m in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR'):
            assert _mod(r, m).is_complete is False, f'{m} no debe completarse con "Me gusta."'

    def test_global_valuation_not_assigned_to_specific_modality(self):
        # A positive global marker must not be used to fill a modality valuation
        # without sensory evidence.
        r = _analyze('Me gusta.')
        for m in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR'):
            assert not _mod(r, m).descriptor_text, f'{m} no debe tener descriptor con "Me gusta."'


# ---------------------------------------------------------------------------
# Case 7 — "Me gusta el sabor, aunque es demasiado dulce."
# ---------------------------------------------------------------------------

class TestCase7SaborDulce:
    TEXT = 'Me gusta el sabor, aunque es demasiado dulce.'

    def test_sabor_has_mention(self):
        r = _analyze(self.TEXT)
        assert _mod(r, 'SABOR').mention_text

    def test_sabor_has_descriptor(self):
        r = _analyze(self.TEXT)
        desc = _mod(r, 'SABOR').descriptor_text.lower()
        assert 'dulce' in desc

    def test_aspecto_not_complete(self):
        r = _analyze(self.TEXT)
        assert _mod(r, 'ASPECTO').is_complete is False

    def test_olor_not_complete(self):
        r = _analyze(self.TEXT)
        assert _mod(r, 'OLOR').is_complete is False

    def test_textura_not_complete(self):
        r = _analyze(self.TEXT)
        assert _mod(r, 'TEXTURA').is_complete is False


# ---------------------------------------------------------------------------
# Case 8 — Galleta redonda y dorada, me parece apetecible
# ---------------------------------------------------------------------------

class TestCase8AspectoBuenApariencia:
    TEXT = 'La galleta es redonda, dorada y tiene pepitas visibles. Me parece apetecible.'

    def test_aspecto_has_descriptor(self):
        r = _analyze(self.TEXT)
        desc = _mod(r, 'ASPECTO').descriptor_text.lower()
        assert 'redonda' in desc or 'dorada' in desc

    def test_aspecto_has_positive_valuation(self):
        r = _analyze(self.TEXT)
        val = _mod(r, 'ASPECTO').valuation_text.lower()
        assert 'apetecible' in val

    def test_aspecto_is_complete(self):
        r = _analyze(self.TEXT)
        assert _mod(r, 'ASPECTO').is_complete is True


# ---------------------------------------------------------------------------
# Additional vocabulary coverage tests
# ---------------------------------------------------------------------------

class TestVocabularyCoverage:
    """Spot checks for the expanded cookie-tasting vocabulary."""

    def test_textura_crujiente_detected(self):
        r = _analyze('La galleta es muy crujiente y me resulta agradable al morderla.')
        assert _mod(r, 'TEXTURA').is_complete is True

    def test_textura_blanda_detected(self):
        r = _analyze('La textura es bastante blanda y no me gusta nada.')
        assert _mod(r, 'TEXTURA').is_complete is True

    def test_textura_apelmazada_detected(self):
        r = _analyze('Tiene una textura apelmazada y pesada. Es desagradable.')
        desc = _mod(r, 'TEXTURA').descriptor_text.lower()
        assert 'apelmazada' in desc

    def test_olor_vainilla_with_smell_anchor(self):
        r = _analyze('El aroma es a vainilla y es muy agradable.')
        assert _mod(r, 'OLOR').is_complete is True
        desc = _mod(r, 'OLOR').descriptor_text.lower()
        assert 'vainilla' in desc

    def test_olor_rancio_detected(self):
        r = _analyze('Tiene un olor rancio que no me gusta nada.')
        assert _mod(r, 'OLOR').is_complete is True

    def test_olor_almost_imperceptible(self):
        r = _analyze('El olor es casi imperceptible. Me parece bien.')
        desc = _mod(r, 'OLOR').descriptor_text.lower()
        assert 'imperceptible' in desc

    def test_sabor_retrogusto_detected(self):
        r = _analyze('Tiene un retrogusto largo y amargo que resulta desagradable.')
        assert _mod(r, 'SABOR').is_complete is True

    def test_sabor_insipido_detected(self):
        r = _analyze('El sabor es insípido y sin sabor, no me convence.')
        assert _mod(r, 'SABOR').is_complete is True

    def test_aspecto_quemado_detected(self):
        r = _analyze('El aspecto es quemado, oscuro y poco apetecible.')
        desc = _mod(r, 'ASPECTO').descriptor_text.lower()
        assert 'quemado' in desc or 'oscuro' in desc

    def test_aspecto_industrial_detected(self):
        r = _analyze('Tiene aspecto industrial, muy uniforme. No llama la atención.')
        desc = _mod(r, 'ASPECTO').descriptor_text.lower()
        assert 'industrial' in desc or 'uniforme' in desc


# ---------------------------------------------------------------------------
# Cross-modal contamination guards
# ---------------------------------------------------------------------------

class TestCrossModalIsolation:
    """Verify that texture words do not contaminate ASPECTO and vice versa,
    and that OLOR/SABOR flavor words are properly separated by context."""

    def test_seca_in_textura_context_not_in_aspecto(self):
        r = _analyze('La textura es seca y hace muchas migas. No me gusta.')
        aspecto_desc = _mod(r, 'ASPECTO').descriptor_text.lower()
        assert 'seca' not in aspecto_desc

    def test_vainilla_in_smell_context_not_assigned_to_sabor_only(self):
        # When 'huele' is the only anchor, vainilla should go to OLOR
        r = _analyze('Huele a vainilla y es un aroma agradable.')
        olor_desc = _mod(r, 'OLOR').descriptor_text.lower()
        assert 'vainilla' in olor_desc

    def test_chocolate_in_taste_context_not_assigned_to_olor(self):
        # When 'sabor' is the only anchor, chocolate should go to SABOR
        r = _analyze('El sabor es a chocolate intenso. No me convence.')
        sabor_desc = _mod(r, 'SABOR').descriptor_text.lower()
        assert 'chocolate' in sabor_desc

    def test_olor_not_complete_from_pure_taste_sentence(self):
        # A sentence with only taste anchor must not complete OLOR
        r = _analyze('El sabor es dulce con notas de vainilla. Me gusta.')
        assert _mod(r, 'OLOR').is_complete is False

    def test_aspecto_not_complete_from_taste_sentence(self):
        r = _analyze('El sabor es a caramelo tostado. Muy rico.')
        assert _mod(r, 'ASPECTO').is_complete is False

    def test_textura_not_complete_from_aspecto_sentence(self):
        r = _analyze('El aspecto es dorado y muy bonito.')
        assert _mod(r, 'TEXTURA').is_complete is False

    def test_fuerte_not_assigned_to_olor_in_taste_context(self):
        # 'fuerte' appears in DESCRIPTOR_WORDS['OLOR'] but must not be extracted
        # when the only context anchor is 'sabor' (taste, not smell).
        r = _analyze('De sabor están bastante buenas, no es un sabor muy fuerte.')
        assert 'fuerte' not in _mod(r, 'OLOR').descriptor_text.lower()

    def test_suave_not_assigned_to_olor_without_smell_anchor(self):
        r = _analyze('El sabor es bastante suave y equilibrado.')
        assert 'suave' not in _mod(r, 'OLOR').descriptor_text.lower()

    def test_intenso_not_assigned_to_olor_in_taste_context(self):
        r = _analyze('El sabor es intenso y un poco amargo.')
        assert 'intenso' not in _mod(r, 'OLOR').descriptor_text.lower()

    def test_fuerte_assigned_to_olor_with_smell_anchor(self):
        # With an explicit smell anchor, 'fuerte' IS valid for OLOR.
        r = _analyze('El olor es muy fuerte y no me agrada.')
        assert 'fuerte' in _mod(r, 'OLOR').descriptor_text.lower()

    def test_suave_assigned_to_olor_with_smell_anchor(self):
        r = _analyze('El aroma es suave y agradable.')
        assert 'suave' in _mod(r, 'OLOR').descriptor_text.lower()


# ---------------------------------------------------------------------------
# Positive and negative valuation detection per modality
# ---------------------------------------------------------------------------

class TestValuationPolarity:
    def test_positive_aspecto(self):
        r = _analyze('La galleta tiene un aspecto dorado y muy bonito.')
        val = _mod(r, 'ASPECTO').valuation_text.lower()
        assert 'bonito' in val or 'bonita' in val

    def test_negative_aspecto(self):
        r = _analyze('El color es oscuro y el aspecto es feo.')
        val = _mod(r, 'ASPECTO').valuation_text.lower()
        assert 'feo' in val

    def test_positive_olor(self):
        r = _analyze('El aroma es a mantequilla y es muy agradable.')
        val = _mod(r, 'OLOR').valuation_text.lower()
        assert 'agradable' in val

    def test_negative_olor(self):
        r = _analyze('El olor es artificial y desagradable.')
        val = _mod(r, 'OLOR').valuation_text.lower()
        assert 'desagradable' in val or 'artificial' in val

    def test_positive_textura(self):
        r = _analyze('La textura es crujiente y me resulta agradable.')
        val = _mod(r, 'TEXTURA').valuation_text.lower()
        assert 'agradable' in val

    def test_negative_textura_migas(self):
        r = _analyze('La textura es seca y genera muchas migas.')
        val = _mod(r, 'TEXTURA').valuation_text.lower()
        assert 'migas' in val

    def test_positive_sabor(self):
        r = _analyze('El sabor es dulce y equilibrado. Me gusta.')
        val = _mod(r, 'SABOR').valuation_text.lower()
        assert 'me gusta' in val or 'equilibrado' in val

    def test_negative_sabor_empalaga(self):
        r = _analyze('El sabor es demasiado dulce. Empalaga bastante.')
        val = _mod(r, 'SABOR').valuation_text.lower()
        assert 'empalaga' in val or 'dulce' in val
