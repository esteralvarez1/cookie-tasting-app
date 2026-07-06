"""Tests for per-modality absence / neutrality detection and the cross-modal guard.

These are pure-function tests over the deterministic layer that decides, for a
DIRECTED modality question, whether a short answer:
  - resolves the modality as absent/neutral ("no huele a nada", "es normal"), or
  - belongs to a DIFFERENT modality and must not complete the current one.

Covers the five required scenarios:
  ASPECTO  "es cuadrada muy simple"          -> completes ASPECTO
  OLOR     "huele a galleta no tengo opiniones" -> completes OLOR (neutral valuation)
  TEXTURA  "es seca y dura"                   -> completes TEXTURA
  TEXTURA  "rancia"                           -> does NOT complete TEXTURA (cross-modal)
  SABOR    "no sabe a nada"                   -> completes SABOR (sin sabor)
"""
from __future__ import annotations

from app.services.modality_metadata import (
    detect_modality_absence,
    is_neutral_valuation,
    mentions_other_modality_only,
)


class TestAspectoAbsence:
    def test_simple_completes_aspecto(self):
        assert detect_modality_absence('es cuadrada muy simple', 'ASPECTO') == 'normal'
        assert mentions_other_modality_only('es cuadrada muy simple', 'ASPECTO') is False

    def test_generic_neutral_phrases_complete_aspecto(self):
        for text in (
            'es simple', 'es normal', 'no tiene nada especial', 'no destaca',
            'no me llama la atención', 'parece una galleta normal',
        ):
            assert detect_modality_absence(text, 'ASPECTO') == 'normal', text

    def test_visual_descriptor_is_not_cross_modal(self):
        # "es marrón" / "es redonda" carry a real ASPECTO descriptor.
        assert mentions_other_modality_only('es marrón', 'ASPECTO') is False
        assert mentions_other_modality_only('es redonda', 'ASPECTO') is False


class TestOlorAbsenceAndNeutralValuation:
    def test_no_smell_completes_olor(self):
        for text in (
            'no huele a nada', 'no tiene olor', 'sin olor',
            'apenas huele', 'huele poco', 'no noto olor',
        ):
            assert detect_modality_absence(text, 'OLOR') == 'sin olor', text

    def test_huele_a_galleta_is_not_cross_modal(self):
        # Has an explicit smell anchor -> belongs to OLOR, not off-topic.
        assert mentions_other_modality_only('huele a galleta no tengo opiniones', 'OLOR') is False

    def test_no_opinion_is_neutral_valuation(self):
        assert is_neutral_valuation('no tengo opiniones') is True
        assert is_neutral_valuation('me da igual') is True
        assert is_neutral_valuation('ni fu ni fa') is True


class TestTexturaStrictness:
    def test_valid_texture_answer_completes(self):
        assert detect_modality_absence('es normal', 'TEXTURA') == 'normal'
        assert mentions_other_modality_only('es seca y dura', 'TEXTURA') is False
        assert mentions_other_modality_only('es crujiente', 'TEXTURA') is False

    def test_texture_specific_absence(self):
        assert detect_modality_absence('no tiene una textura destacable', 'TEXTURA') == 'normal'
        assert detect_modality_absence('no noto nada especial en la textura', 'TEXTURA') == 'normal'

    def test_cross_modal_answers_do_not_belong_to_texture(self):
        # Taste / smell remarks given when the bot asked about texture.
        assert mentions_other_modality_only('rancia', 'TEXTURA') is True
        assert mentions_other_modality_only('sosa', 'TEXTURA') is True
        assert mentions_other_modality_only('no sabe a nada', 'TEXTURA') is True
        assert mentions_other_modality_only('huele raro', 'TEXTURA') is True

    def test_cross_modal_answer_is_not_resolved_as_texture_absence(self):
        # "rancia" must not be interpreted as a neutral texture descriptor.
        assert detect_modality_absence('rancia', 'TEXTURA') is None


class TestSaborAbsence:
    def test_no_sabe_a_nada_completes_sabor(self):
        assert detect_modality_absence('no sabe a nada', 'SABOR') == 'sin sabor'
        assert mentions_other_modality_only('no sabe a nada', 'SABOR') is False

    def test_other_taste_absence_expressions(self):
        for text in ('no tiene sabor', 'sin sabor', 'apenas sabe', 'sabe a poco', 'es soso', 'es insípida'):
            assert detect_modality_absence(text, 'SABOR') == 'sin sabor', text

    def test_flavor_descriptor_is_not_cross_modal(self):
        # "está dulce" / "sabe a vainilla" carry real SABOR content.
        assert mentions_other_modality_only('está dulce', 'SABOR') is False
        assert mentions_other_modality_only('sabe a vainilla', 'SABOR') is False
