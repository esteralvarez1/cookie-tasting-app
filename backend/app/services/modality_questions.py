from __future__ import annotations

from app.services.modality_metadata import MODALITY_LABELS, infer_question_needs

INITIAL_QUESTION = (
    'Prueba la galleta que tienes delante y danos tu opinión de manera escrita.\n'
    'Es importante que escribas todo lo que pienses sobre la galleta:\n'
    'Si te gusta o no.\n'
    'Lo que te gusta de la galleta.\n'
    'Lo que no te gusta de la galleta.\n'
    'Qué te parecen sus características sensoriales como la textura, el aspecto, el sabor y el olor.\n'
    'En resumen, danos tu opinión de la manera más detallada posible.'
)

OPEN_REPROMPT = '¿Puedes contarme un poco más sobre esta galleta y dar más detalles?'
COMPARISON_REFORMULATION = 'Por favor, describe esta galleta sin compararla con otra.'
SAMPLE_COMPLETED_MESSAGE = 'Gracias. Ya hemos terminado con esta muestra.'
LLM_RETRY_MESSAGE = 'Ha habido un problema al analizar tu respuesta. Inténtalo de nuevo, por favor.'


def build_modality_question(modality: str, mention_text: str = '', descriptor_text: str = '', valuation_text: str = '') -> str:
    needs = infer_question_needs(mention_text, descriptor_text, valuation_text)
    name = MODALITY_LABELS[modality]

    if needs.descriptor_missing and needs.valuation_missing:
        if modality == 'ASPECTO':
            return 'Ahora cuéntame cómo es el aspecto de la galleta y qué te parece.'
        if modality == 'OLOR':
            return 'Ahora cuéntame cómo es el olor de la galleta y qué te parece.'
        if modality == 'TEXTURA':
            return 'Ahora cuéntame cómo es la textura de la galleta y qué te parece.'
        return 'Ahora cuéntame cómo es el sabor de la galleta y qué te parece.'

    if needs.descriptor_missing:
        if modality == 'ASPECTO':
            return '¿Cómo describirías el aspecto de la galleta?'
        if modality == 'OLOR':
            return '¿Cómo describirías el olor de la galleta?'
        if modality == 'TEXTURA':
            return '¿Cómo describirías la textura de la galleta?'
        return '¿Cómo describirías el sabor de la galleta?'

    if needs.valuation_missing:
        return f'¿Y qué te parece {name}, te gusta o no te gusta?'

    return f'Cuéntame un poco más sobre {name}.'
