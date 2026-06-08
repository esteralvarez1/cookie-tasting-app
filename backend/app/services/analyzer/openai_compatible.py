from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, ValidationError, field_validator

from app.core.config import settings
from app.models.enums import ModalityType
from app.services.analyzer.base import BaseAnalyzer
from app.services.analyzer.models import AnalysisResult, AnalyzerUnavailableError, ModalityResult

logger = logging.getLogger(__name__)

PROMPT_VERSION_LEGACY = 'openai_compatible_v6_comparison_context'
PROMPT_VERSION_MINIMAL = 'openai_compatible_v6_minimal_context'

SYSTEM_PROMPT = """Eres un analizador estricto de respuestas de una aplicación de cata de galletas en español.

Tu tarea es analizar EXCLUSIVAMENTE el comentario acumulado de una sola galleta y devolver SOLO un objeto JSON válido.
El backend decide el flujo final del sistema. Tú solo analizas evidencia textual.
No devuelvas markdown.
No devuelvas texto antes ni después del JSON.
No uses comillas triples.
No añadas explicaciones.
No añadas claves distintas de las pedidas.
No omitas ninguna clave obligatoria.
No inventes información.
No uses el estado conversacional ni las modalidades ya cubiertas para fabricar evidencia.

Debes devolver SIEMPRE un JSON con EXACTAMENTE esta estructura de nivel superior:

{
  "analysis_scope": "string",
  "is_vague": false,
  "has_comparison": false,
  "reasoning_summary": "",
  "modalities": {
    "ASPECTO": {
      "mention_text": "",
      "descriptor_text": "",
      "valuation_text": "",
      "is_complete": false
    },
    "OLOR": {
      "mention_text": "",
      "descriptor_text": "",
      "valuation_text": "",
      "is_complete": false
    },
    "TEXTURA": {
      "mention_text": "",
      "descriptor_text": "",
      "valuation_text": "",
      "is_complete": false
    },
    "SABOR": {
      "mention_text": "",
      "descriptor_text": "",
      "valuation_text": "",
      "is_complete": false
    }
  }
}

Reglas obligatorias:

1. Las únicas modalidades válidas son: ASPECTO, OLOR, TEXTURA y SABOR.

2. La clave "modalities" es obligatoria y debe existir siempre.
Nunca la omitas. Nunca la renombres. Nunca uses "modalidades" ni "por_modalidad".

3. Dentro de "modalities" deben existir siempre las cuatro claves: "ASPECTO", "OLOR", "TEXTURA" y "SABOR".

4. Dentro de cada modalidad deben existir siempre estas cuatro claves:
- "mention_text"
- "descriptor_text"
- "valuation_text"
- "is_complete"

5. Si no hay evidencia suficiente para una modalidad, usa:
- "mention_text": ""
- "descriptor_text": ""
- "valuation_text": ""
- "is_complete": false

6. Trabaja solo con evidencia textual clara del comentario analizado.
No infieras datos por conocimiento general ni por probabilidad.
No traslades evidencia de una modalidad a otra.

7. Un juicio global como "me gusta", "no me gusta", "está rica" o "está buena" NO implica automáticamente valoración de ASPECTO, OLOR, TEXTURA o SABOR.
Si la valoración no está ligada a una modalidad concreta, deja "valuation_text" vacío en esa modalidad.
EXCEPCIÓN: si la valoración está explícitamente ligada a un término de modalidad en la misma frase ("me gusta mucho la presentación", "me gusta el olor", "me encanta la textura", "me gusta el sabor"), SÍ es una valoración válida de esa modalidad. No la trates como opinión global.

8. Significado exacto de los campos por modalidad:
- "mention_text": cita breve y literal o casi literal del texto del PARTICIPANTE que demuestre que esa modalidad aparece mencionada. NUNCA uses texto de la pregunta del bot.
- "descriptor_text": descriptor concreto de esa modalidad. No pongas el nombre de la modalidad ni un resumen general.
  Para ASPECTO son descriptores válidos: color (dorado, tostado, oscuro, claro, brillante), forma (redondo, corazón, figuras, con formas), tamaño (grande, pequeño), visual del tostado, las figuras, con semillas, con trozos, uniforme, luminoso.
  "tostado", "figuras de la galleta", "forma de corazón", "visual del tostado" son descriptores ASPECTO válidos aunque el participante no use la palabra "aspecto".
- "valuation_text": fragmento literal del texto del participante que exprese un juicio, agrado, rechazo, exceso, defecto o reacción subjetiva ante esa modalidad.
  IMPORTANTE: la valoración NO se limita a "me gusta" / "no me gusta". Son valoraciones válidas:
    · Rechazo explícito:    "no me gusta", "no me convence", "malo", "desagradable"
    · Exceso percibido:     "empalaga", "demasiado dulce", "demasiada azúcar", "muy intenso", "demasiado fuerte"
    · Defecto funcional:    "genera muchas migas", "se deshace", "muy seca", "muy dura", "boronosa"
    · Artificialidad:       "sabor artificial", "jengibre artificial", "olor artificial"
    · Agrado implícito:     "bonita", "agradable", "me gusta cómo se ve", "suave y agradable"
  Usa siempre fragmentos literales del texto del participante. Nunca inventes texto.
  Una modalidad solo tiene is_complete=true si los tres campos (mention, descriptor, valuation) son no vacíos.
- "is_complete": true solo si hay evidencia textual suficientemente específica de esa modalidad y esa evidencia aporta contenido útil para el análisis, no una mención superficial o aislada.

9. Separa estrictamente mención, descriptor y valoración.
No copies el mismo contenido en los tres campos salvo que el texto realmente lo exija.
No conviertas una valoración en descriptor ni un descriptor en valoración por defecto.

10. No mezcles modalidades.
Ejemplos:
- "vainilla" o "chocolate" solo cuentan como OLOR si el texto habla explícitamente de olor, aroma o huele.
- "vainilla" o "chocolate" solo cuentan como SABOR si el texto habla explícitamente de sabor, sabe o gusto, o si el contexto local deja claro que se refiere al sabor.
- Una frase sobre textura no debe rellenar sabor, olor ni aspecto.

11. Detección de vaguedad:
"is_vague" debe ser true cuando el comentario no aporte suficiente información sensorial o valorativa para continuar el análisis sin ayuda adicional.
No bases esta decisión solo en la longitud.
Una respuesta breve puede NO ser vaga si aporta información sensorial clara y útil.
Una respuesta larga puede SÍ ser vaga si sigue siendo genérica, pobre o poco desarrollada.
Marca "is_vague": true si el comentario es demasiado genérico, poco específico, apenas descriptivo o solo expresa una opinión global sin detalle sensorial suficiente.
Marca también "is_vague": true si menciona rasgos aislados pero no aporta suficiente riqueza descriptiva o valorativa.
No uses como único criterio un número fijo de caracteres ni el número de modalidades cubiertas.
Si current_state es MODALITY_QUESTION y el usuario da una respuesta corta pero pertinente a la pregunta del bot, NO la marques como vaga.

12. Detección de comparación — REGLA CRÍTICA:
"has_comparison" debe basarse EXCLUSIVAMENTE en el ÚLTIMO MENSAJE DEL PARTICIPANTE.
Si el participante comparó en un turno anterior, el TEXTO ACUMULADO puede contener esa comparación,
pero NO debes marcar has_comparison=true en este turno a menos que el ÚLTIMO MENSAJE también tenga comparación.
El TEXTO ACUMULADO sirve únicamente para extraer evidencia de modalidades (mention, descriptor, valuation).
NUNCA uses el TEXTO ACUMULADO para determinar has_comparison — solo mira el ÚLTIMO MENSAJE.

Marca has_comparison = true si ÚLTIMO MENSAJE contiene:
- Código de otra muestra de la sesión (ver other_sample_codes): por ejemplo "G102", "G103"
- Referencia genérica a otra muestra: "la anterior", "la otra", "la primera", "la segunda",
  "la tercera", "la de antes", "las demás", "otra muestra", "otra galleta"
- Estructura comparativa: "más que", "menos que", "mejor que", "peor que", "igual que",
  "comparada con", "en comparación con"
- Clasificación relativa: "la mejor", "la peor", "la mejor de todas", "me gusta más (esta)",
  "me gusta menos (esta)", "esta es mejor", "esta es peor"

NO marques has_comparison por simples intensificadores o valoraciones:
"muy crujiente" → NO    "demasiado dulce" → NO    "empalaga" → NO

NO marques has_comparison si el participante compara dos atributos de la misma galleta:
"tiene buen sabor, igual que buena textura" → NO (relación interna, no comparación de muestras)
"su sabor es bueno igual que su textura" → NO (relación interna entre atributos de la misma galleta)

NO marques has_comparison si el participante niega haber comparado:
"no la he comparado con otra" → NO    "no estoy comparando" → NO    "no me refiero a otra galleta" → NO

SÍ marca has_comparison:
"más crujiente que la anterior" → SÍ
"me gusta más que G102" → SÍ
"la primera estaba mejor" → SÍ
"esta es la peor de todas" → SÍ
"comparada con la G103, esta tiene menos olor" → SÍ

Cuando has_comparison = true:
- No uses fragmentos comparativos como evidencia suficiente para completar una modalidad
- Si el mensaje tiene partes NO comparativas, extráelas como evidencia
- Ejemplo de mensaje mixto:
  "Es crujiente y me gusta, aunque es menos dulce que la anterior."
  has_comparison = true
  TEXTURA: mention="Es crujiente y me gusta", descriptor="crujiente", valuation="me gusta", is_complete=true
  SABOR: todos los campos vacíos (la comparación no describe el sabor actual de forma autónoma)

13. "analysis_scope" debe devolverse siempre y debe reflejar el valor de entrada.
14. "reasoning_summary" debe ser una frase breve y técnica, basada solo en la evidencia textual.
15. Devuelve solo JSON válido.

16. Interpretación de respuestas dirigidas:
Si current_state es MODALITY_QUESTION y current_modality no es null, el ÚLTIMO MENSAJE del participante es una respuesta a una pregunta concreta sobre esa modalidad.
Úsalo prioritariamente para completar los campos faltantes de esa modalidad, incluso si el usuario no repite el nombre de la modalidad.
Si la pregunta previa del bot pedía valoración (contiene "te parece", "te gusta"), una respuesta corta como "no", "sí", "no mucho", "regular", "bastante bien", "es raro" es una valoración válida de la modalidad current_modality.
Si la pregunta previa del bot pedía descripción, una respuesta como "crujiente", "suave", "sin olor" es un descriptor válido.

17. Ausencia de olor como descriptor válido:
Las expresiones "no huele a nada", "no me olía a nada", "no tiene olor", "sin olor", "apenas huele", "olor muy suave", "no percibo olor", "no noto olor" son descriptores VÁLIDOS de OLOR, no respuestas vacías ni vagas.
Para OLOR, usa "sin olor" o la frase literal como descriptor_text cuando la persona describa ausencia de olor.

18. La clave "pregunta_previa_del_bot" es SOLO contexto conversacional para interpretar la intención del participante.
NUNCA uses texto de "pregunta_previa_del_bot" como evidencia.
NUNCA copies frases de "pregunta_previa_del_bot" en "mention_text", "descriptor_text" ni "valuation_text".
Toda evidencia debe proceder exclusivamente del texto del participante (TEXTO ACUMULADO o ÚLTIMO MENSAJE).
Si el participante no menciona la modalidad preguntada, deja los campos vacíos; no uses la pregunta del bot para rellenarlos.

EJEMPLO FEW-SHOT — memoriza este patrón de extracción:

Texto de entrada:
"Textura seca y boronosa, genera muchas migas, retrogusto largo con sabor a azúcar tostada y jengibre artificial. Empalaga y tiene demasiada azúcar."

Salida esperada (parcial, solo TEXTURA y SABOR):
TEXTURA:
  mention_text:    "Textura seca y boronosa, genera muchas migas"
  descriptor_text: "seca, boronosa, muchas migas"
  valuation_text:  "genera muchas migas"
  is_complete:     true

SABOR:
  mention_text:    "retrogusto largo con sabor a azúcar tostada y jengibre artificial. Empalaga y tiene demasiada azúcar"
  descriptor_text: "azúcar tostada, jengibre artificial"
  valuation_text:  "Empalaga y tiene demasiada azúcar"
  is_complete:     true

¿Por qué?
- "genera muchas migas" es valoración negativa de TEXTURA: indica un defecto funcional (la galleta se deshace excesivamente).
- "Empalaga y tiene demasiada azúcar" es valoración negativa de SABOR: expresa rechazo directo ("empalaga") y exceso ("demasiada azúcar").
- "jengibre artificial" es descriptor de SABOR (qué sabe), pero también puede contribuir a la valoración porque "artificial" implica un juicio negativo.
- Si el texto solo dice "El sabor es dulce", valuation_text debe quedar vacío: "dulce" es un descriptor neutro, no un juicio.
"""


class _RawModalityPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')

    mention_text: StrictStr
    descriptor_text: StrictStr
    valuation_text: StrictStr
    is_complete: StrictBool

    @field_validator('mention_text', 'descriptor_text', 'valuation_text')
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class _RawAnalysisPayload(BaseModel):
    model_config = ConfigDict(extra='ignore')

    analysis_scope: str = ''
    is_vague: bool = False
    has_comparison: bool = False
    reasoning_summary: str = ''
    modalities: dict[str, _RawModalityPayload]

    @field_validator('analysis_scope', 'reasoning_summary', mode='before')
    @classmethod
    def normalize_strings(cls, value: Any) -> str:
        if value is None:
            return ''
        return str(value).strip()


_EXPECTED_MODALITIES: frozenset[str] = frozenset({'ASPECTO', 'OLOR', 'TEXTURA', 'SABOR'})


def _build_chat_completions_url(base_url: str) -> str:
    cleaned = (base_url or '').strip().strip('"').strip("'").rstrip('/')

    if not cleaned:
        raise AnalyzerUnavailableError('LLM_BASE_URL is empty')

    if not cleaned.startswith(('http://', 'https://')):
        cleaned = 'https://' + cleaned

    if cleaned.endswith('/chat/completions'):
        return cleaned

    if cleaned.endswith('/v1'):
        return cleaned + '/chat/completions'

    return cleaned + '/v1/chat/completions'


def _truncate_for_llm(text: str) -> str:
    """Return at most settings.llm_context_max_chars of accumulated_text for the LLM.

    The full text is always persisted in the database. This function only limits what
    is forwarded to the external model to control context-window size and API cost.
    Truncation takes the most recent content (tail), then advances to the next newline
    to avoid cutting mid-sentence.
    """
    max_chars = settings.llm_context_max_chars
    if len(text) <= max_chars:
        return text
    tail = text[-max_chars:]
    first_newline = tail.find('\n')
    if first_newline > 0:
        tail = tail[first_newline + 1:]
    return '[…contexto previo omitido por límite de ventana de análisis…]\n' + tail


class OpenAICompatibleAnalyzer(BaseAnalyzer):
    provider_name = settings.llm_provider
    model_name = settings.llm_model

    @property
    def prompt_version(self) -> str:  # type: ignore[override]
        return PROMPT_VERSION_MINIMAL if settings.llm_context_mode != 'legacy' else PROMPT_VERSION_LEGACY

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
        user_content = self._format_user_message(
            analysis_scope=analysis_scope,
            current_state=current_state,
            current_modality=current_modality,
            user_last_message=user_last_message,
            accumulated_text=accumulated_text,
            covered_modalities=covered_modalities,
            vague_retry_count=vague_retry_count,
            comparison_retry_count=comparison_retry_count,
            previous_bot_question=previous_bot_question,
            current_sample_code=current_sample_code,
            session_sample_codes=session_sample_codes,
            other_sample_codes=other_sample_codes,
        )
        logger.debug(
            'LLM request [mode=%s scope=%s state=%s modality=%s]:\n%s',
            settings.llm_context_mode, analysis_scope, current_state, current_modality, user_content,
        )
        payload: dict[str, Any] = {
            'model': settings.llm_model,
            'temperature': 0,
            'messages': [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': user_content},
            ],
        }
        if settings.llm_response_format_json:
            payload['response_format'] = {'type': 'json_object'}
        headers = {
            'Authorization': f'Bearer {settings.llm_api_key}',
            'Content-Type': 'application/json',
        }
        # url = settings.llm_base_url.rstrip('/') + '/chat/completions'
        url = _build_chat_completions_url(settings.llm_base_url)
        timeout = httpx.Timeout(
            connect=float(settings.llm_connect_timeout_seconds),
            read=float(settings.llm_timeout_seconds),
            write=30.0,
            pool=5.0,
        )
        last_exc: Exception | None = None
        for _ in range(settings.llm_max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                logger.debug('LLM raw response: %s', response.text)
                return self._parse_analysis_response(response.json(), analysis_scope)
            except (httpx.TimeoutException, httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:  # pragma: no cover - external service
                last_exc = exc
                logger.exception('LLM analyzer call failed: %s', exc)
        raise AnalyzerUnavailableError(str(last_exc) if last_exc else 'Unknown analyzer error')

    def _format_user_message_legacy(
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
    ) -> str:
        context_lines = [
            f'analysis_scope: {analysis_scope}',
            f'current_state: {current_state}',
            f'current_modality: {current_modality or "ninguna"}',
            f'covered_modalities: {", ".join(covered_modalities) if covered_modalities else "ninguna"}',
            f'vague_retry_count: {vague_retry_count}',
            f'comparison_retry_count: {comparison_retry_count}',
        ]
        if current_sample_code:
            context_lines.append(f'current_sample_code: {current_sample_code}')
        if session_sample_codes:
            context_lines.append(f'session_sample_codes: {", ".join(session_sample_codes)}')
        if other_sample_codes:
            context_lines.append(
                f'other_sample_codes: {", ".join(other_sample_codes)}'
                ' (si aparece alguno de estos en el último mensaje → has_comparison=true)'
            )
        if previous_bot_question:
            context_lines.append(f'pregunta_previa_del_bot: {previous_bot_question}')

        last_msg_note = (
            'ÚLTIMO MENSAJE DEL PARTICIPANTE (es respuesta a la pregunta previa del bot sobre la modalidad actual — úsalo para completar los campos faltantes de esa modalidad):'
            if current_state == 'MODALITY_QUESTION' and current_modality
            else 'ÚLTIMO MENSAJE DEL PARTICIPANTE (usa solo para detección de comparación):'
        )

        llm_context = _truncate_for_llm(accumulated_text)
        return (
            'TEXTO ACUMULADO DEL PARTICIPANTE (fuente principal para extracción):\n'
            '"""\n'
            f'{llm_context}\n'
            '"""\n\n'
            f'{last_msg_note}\n'
            '"""\n'
            f'{user_last_message}\n'
            '"""\n\n'
            'CONTEXTO DE LA CONVERSACIÓN:\n'
            + '\n'.join(context_lines)
        )

    def _format_user_message_minimal(
        self,
        current_state: str,
        current_modality: str | None,
        user_last_message: str,
        accumulated_text: str,
        other_sample_codes: list[str] | None,
        previous_bot_question: str | None,
    ) -> str:
        """Minimal context: only the four fields the LLM actually needs."""
        context_lines = [
            f'current_state: {current_state}',
            f'current_modality: {current_modality or "ninguna"}',
        ]
        if other_sample_codes:
            context_lines.append(
                f'other_sample_codes: {", ".join(other_sample_codes)}'
                ' (si aparece alguno de estos en el último mensaje → has_comparison=true)'
            )
        if previous_bot_question:
            context_lines.append(f'pregunta_previa_del_bot: {previous_bot_question}')

        last_msg_note = (
            'ÚLTIMO MENSAJE DEL PARTICIPANTE (es respuesta a la pregunta previa del bot sobre la modalidad actual — úsalo para completar los campos faltantes de esa modalidad):'
            if current_state == 'MODALITY_QUESTION' and current_modality
            else 'ÚLTIMO MENSAJE DEL PARTICIPANTE (usa solo para detección de comparación):'
        )

        llm_context = _truncate_for_llm(accumulated_text)
        return (
            'TEXTO ACUMULADO DEL PARTICIPANTE (fuente principal para extracción):\n'
            '"""\n'
            f'{llm_context}\n'
            '"""\n\n'
            f'{last_msg_note}\n'
            '"""\n'
            f'{user_last_message}\n'
            '"""\n\n'
            'CONTEXTO DE LA CONVERSACIÓN:\n'
            + '\n'.join(context_lines)
        )

    def _format_user_message(
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
    ) -> str:
        """Dispatcher: routes to minimal or legacy formatter based on LLM_CONTEXT_MODE."""
        if settings.llm_context_mode == 'legacy':
            return self._format_user_message_legacy(
                analysis_scope=analysis_scope,
                current_state=current_state,
                current_modality=current_modality,
                user_last_message=user_last_message,
                accumulated_text=accumulated_text,
                covered_modalities=covered_modalities,
                vague_retry_count=vague_retry_count,
                comparison_retry_count=comparison_retry_count,
                previous_bot_question=previous_bot_question,
                current_sample_code=current_sample_code,
                session_sample_codes=session_sample_codes,
                other_sample_codes=other_sample_codes,
            )
        return self._format_user_message_minimal(
            current_state=current_state,
            current_modality=current_modality,
            user_last_message=user_last_message,
            accumulated_text=accumulated_text,
            other_sample_codes=other_sample_codes,
            previous_bot_question=previous_bot_question,
        )

    def _parse_analysis_response(self, response_json: dict[str, Any], fallback_scope: str) -> AnalysisResult:
        content = self._extract_content(response_json)
        try:
            raw_payload = _RawAnalysisPayload.model_validate_json(content)
        except ValidationError as exc:
            logger.error('LLM response failed structural validation: %s', exc)
            raise AnalyzerUnavailableError(f'LLM response structural validation failed: {exc}') from exc
        received = frozenset(raw_payload.modalities.keys())
        if received != _EXPECTED_MODALITIES:
            msg = (
                f'Invalid modality keys in LLM response: '
                f'expected {sorted(_EXPECTED_MODALITIES)}, got {sorted(received)}'
            )
            logger.error(msg)
            raise AnalyzerUnavailableError(msg)
        modalities = self._normalize_modalities(raw_payload.modalities)
        # In minimal mode analysis_scope is not sent to the LLM, so the LLM's echo value
        # is unreliable. Always use the Python-side fallback_scope in that case.
        effective_scope = (
            fallback_scope
            if settings.llm_context_mode != 'legacy'
            else (raw_payload.analysis_scope or fallback_scope)
        )
        return AnalysisResult(
            analysis_scope=effective_scope,
            is_vague=raw_payload.is_vague,
            has_comparison=raw_payload.has_comparison,
            reasoning_summary=raw_payload.reasoning_summary,
            modalities=modalities,
        )

    def _extract_content(self, response_json: dict[str, Any]) -> str:
        content = response_json['choices'][0]['message']['content']
        if isinstance(content, dict):
            return json.dumps(content, ensure_ascii=False)
        if isinstance(content, list):
            joined = ''.join(str(item.get('text', '')) if isinstance(item, dict) else str(item) for item in content)
            return self._strip_code_fences(joined)
        return self._strip_code_fences(str(content))

    def _normalize_modalities(self, payload: dict[str, _RawModalityPayload]) -> dict[str, ModalityResult]:
        normalized: dict[str, ModalityResult] = {}
        for modality in ModalityType:
            item = payload[modality.value]
            normalized[modality.value] = ModalityResult(
                mention_text=item.mention_text,
                descriptor_text=item.descriptor_text,
                valuation_text=item.valuation_text,
                is_complete=bool((item.mention_text or '').strip() and (item.descriptor_text or '').strip() and (item.valuation_text or '').strip()),
            )
        return normalized

    def _strip_code_fences(self, content: str) -> str:
        stripped = content.strip()
        if stripped.startswith('```') and stripped.endswith('```'):
            lines = stripped.splitlines()
            inner = lines[1:-1] if len(lines) >= 2 else []
            return '\n'.join(inner).strip()
        return stripped
