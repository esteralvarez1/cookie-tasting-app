from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.models.enums import ModalityType

MODALITY_ORDER = [item.value for item in ModalityType]

MODALITY_LABELS = {
    'ASPECTO': 'el aspecto',
    'OLOR': 'el olor',
    'TEXTURA': 'la textura',
    'SABOR': 'el sabor',
}

MODALITY_EXAMPLES = {
    'ASPECTO': 'color, forma, tamaño, grosor, brillo, trozos o decoración',
    'OLOR': 'a qué huele, si es intenso o suave, si recuerda a vainilla, cacao o mantequilla',
    'TEXTURA': 'crujiente, blanda, dura, arenosa, seca o pegajosa',
    'SABOR': 'dulce, salado, amargo, suave, intenso o a qué sabe',
}

COMPARISON_MARKERS = [
    # Comparative structures (unambiguous — always cross-sample)
    'mejor que', 'peor que', 'menos que', 'mas que',
    # 'igual que' moved to context-sensitive check in has_comparison()
    # 'en comparacion con', 'comparada con', 'comparado con' moved to has_comparison() with negation guard
    # Generic references to other samples
    'la anterior', 'la otra', 'la primera', 'la segunda', 'la tercera',
    'la de antes', 'las demas', 'otra muestra', 'otra galleta',
    'como la otra', 'como las de', 'que la otra', 'como otra',
    # Relative classification between samples
    'la mejor', 'la peor', 'mejor de todas', 'peor de todas',
    'me gusta mas', 'me gusta menos',
    'esta es mejor', 'esta es peor',
    # Legacy / specific patterns kept for backward compat
    'menos crujiente que', 'mas dulce que',
    # NOTE: 'se parece a' / 'me recuerda a' are NOT hard markers — they are handled by
    # the commercial/market layer (_is_commercial_comparison) so that sensory associations
    # to plain ingredients ("se parece a vainilla", "me recuerda a canela") stay non-comparative.
]

# "igual que" + optional article + internal modality word → intra-sample relation, NOT a comparison
_IGUAL_QUE_INTERNAL = re.compile(
    r'\bigual\s+que\s+(?:su\s+|la\s+|el\s+|tu\s+|mi\s+)?'
    r'(?:aspecto|olor|textura|sabor|color|forma|tamano|'
    r'presentacion|aroma|consistencia|crujiente|apariencia|'
    r'sabores|texturas|olores|colores)\b'
)

# Explicit denial of having made a comparison — early-exit guard in has_comparison()
_NEGATED_COMPARISON = re.compile(
    r'\bno\b.{0,20}?(?:he\s+)?comparad[ao]\s+con\b'
    r'|\bno\s+estoy\s+comparand[ao]\b'
    r'|\bno\s+l[ao]?\s+compar[ao]\b'
    r'|\bno\s+(?:me\s+)?ref(?:iero|eria)\s+a\s+otr[ao]\b'
    r'|\bno\s+(?:estoy|estaba)\s+hablando\s+de\s+otr[ao]\b'
    r'|\bno\s+es\s+(?:una\s+)?comparacion\b'
    r'|\bsolo\s+(?:estoy\s+)?hablando\s+de\s+esta\b'
    r'|\bno\s+hablo\s+de\s+otr[ao]\b'
)

# Commercial brands / market products frequently used by tasters as a comparison anchor.
# Matched on normalize_text output (lowercase, accents stripped), with word boundaries to
# avoid substring hits. Detection only counts inside an association context (_BRAND_CONTEXT).
COMMERCIAL_BRANDS = [
    r'\boreos?\b',
    r'\bmarias?\b',
    r'\bcampurrianas?\b',
    r'\bchiquilin\b',
    r'\bchips\s+ahoy\b', r'\bchipsahoy\b',
    r'\bdigestives?\b',
    r'\bprincipe\b',
    r'\btosta\s+rica\b', r'\btostarica\b',
    r'\bmercadona\b',
    r'\bcuetara\b', r'\bgullon\b', r'\bfontaneda\b', r'\bartiach\b',
    r'\blu\b', r'\blotus\b', r'\bbiscoff\b',
    r'\bcookies?\b',
]

# Generic references to "a supermarket / commercial / industrial / cheap / brand cookie".
# These phrases are an unambiguous comparison with the market on their own.
MARKET_REFERENCE_PATTERNS = [
    r'\bgalletas?\s+del\s+supermercado\b',
    r'\bgalletas?\s+de\s+supermercado\b',
    r'\bgalletas?\s+del\s+mercado\b',
    r'\bgalletas?\s+comercial(?:es)?\b',
    r'\bgalletas?\s+industrial(?:es)?\b',
    r'\bgalletas?\s+barat[ao]s?\b',
    r'\bgalletas?\s+de\s+marca\b',
]

# Association cues ("sabe a", "tipo", "me recuerda a", "se parece a", "como"...). A brand
# only counts as a comparison when one of these is present; otherwise the brand token is
# ignored. The cues are intentionally broad because they only gate the brand list.
_BRAND_CONTEXT = re.compile(
    r'\bsabe\b|\bsabor\b|\bme\s+recuerda\b|\brecuerda\b'
    r'|\bse\s+parece\b|\bparecid[oa]\b|\bparece\b'
    r'|\bes\s+tipo\b|\btipo\b|\bsimilar\b|\bes\s+como\b|\bcomo\b'
)

GLOBAL_OPINION_PATTERNS = [
    r'\bme gusta\b', r'\bno me gusta\b', r'\best[aá] bien\b', r'\best[aá] buena\b',
    r'\best[aá] rico\b', r'\best[aá] rica\b', r'\bnormal\b', r'\bsin m[aá]s\b', r'\bni fu ni fa\b',
    r'\bme encanta\b', r'\best[aá] mal\b', r'\best[aá] mala\b',
]

GENERIC_VAGUE_PATTERNS = [
    r'\bbien\b', r'\bnormal\b', r'\bsin m[aá]s\b', r'\bno s[eé]\b', r'\bok\b', r'\bvale\b',
    r'\bme gusta\b', r'\bno me gusta\b', r'\bregular\b', r'\best[aá] bien\b',
]

# ---------------------------------------------------------------------------
# Context anchor patterns — used to guard cross-modal descriptor assignment.
# All patterns are matched against normalize_text output (lowercase, no accents).
# ---------------------------------------------------------------------------

SMELL_CONTEXT_PATTERNS = [
    r'\bolor\b', r'\baroma\b', r'\bhuele?\b', r'\bhuelo\b', r'\bhuelen\b',
    r'\bolfato\b', r'\boli[ao]\b', r'\bnariz\b',
]
TASTE_CONTEXT_PATTERNS = [
    r'\bsabor\b', r'\bgusto\b', r'\bsabe\b', r'\bpaladar\b',
    r'\bretrogusto\b', r'\bregusto\b', r'\bpostgusto\b',
]
TEXTURE_CONTEXT_PATTERNS = [
    r'\btextura\b', r'\bcrujiente\b', r'\bcruje\b', r'\bbland[ao]\b',
    r'\bdur[ao]\b', r'\bseca\b', r'\barenos[ao]\b', r'\bboronos[ao]\b',
    r'\bmigas?\b', r'\bse\s+deshace\b', r'\bmorder\b', r'\bmasticar\b',
]
ASPECT_CONTEXT_PATTERNS = [
    r'\baspecto\b', r'\bpresentaci[oó]n\b', r'\bse\s+ve\b', r'\bvisual\b',
    r'\bcolor\b', r'\bforma\b', r'\baparencia\b', r'\bpinta\b',
    r'\bdorad[ao]\b', r'\btostad[ao]\b',
    # Refuerzo ASPECTO: diseño / apariencia / presentación visual / decoración.
    r'\bdise[nñ]o\b', r'\bapariencia\b', r'\bdecoraci[oó]n\b', r'\bdibujo\b',
    r'\bvista\b', r'\btama[nñ]o\b',
]

# ---------------------------------------------------------------------------
# Mention patterns — sentences containing these strongly suggest the modality
# is being discussed.  Kept unambiguous: no word shared between modalities.
# ---------------------------------------------------------------------------

MENTION_PATTERNS = {
    'ASPECTO': [
        r'\baspecto\b', r'\bpresentaci[oó]n\b', r'\bse\s+ve\b', r'\bvisual\b',
        r'\bcolor\b', r'\bforma\b', r'\btama[nñ]o\b', r'\bbrillo\b',
        r'\baparencia\b', r'\bpinta\b', r'\bvista\b',
        r'\bdorad[ao]\b', r'\btostad[ao]\b',
        # Refuerzo ASPECTO: diseño, apariencia, decoración, dibujo.
        r'\bdise[nñ]o\b', r'\bapariencia\b', r'\bdecoraci[oó]n\b', r'\bdibujo\b',
    ],
    'OLOR': [
        r'\bolor\b', r'\baroma\b', r'\bhuele?\b', r'\bolfato\b',
        r'\boli[ao]\b', r'\bhuelo\b', r'\bhuelen\b', r'\bnariz\b',
    ],
    'TEXTURA': [
        r'\btextura\b', r'\bcrujiente\b', r'\bbland[ao]\b', r'\bdur[ao]\b',
        r'\bseca\b', r'\barenos[ao]\b', r'\bcrujido\b', r'\bpegajos',
        r'\bboronos[ao]\b', r'\bharinos[ao]\b',
        r'\bmigas?\b', r'\bse\s+deshace\b', r'\bcruje\b',
        r'\bmorder\b', r'\bmasticar\b',
    ],
    'SABOR': [
        r'\bsabor\b', r'\bgusto\b', r'\bsabe\b', r'\bdulce\b',
        r'\bamarg[ao]\b', r'\bsalad[ao]\b', r'\bempalag',
        r'\bretrogusto\b', r'\bpostgusto\b', r'\bregusto\b',
        r'\bpaladar\b',
    ],
}

# ---------------------------------------------------------------------------
# Descriptor vocabularies — expanded for cookie-tasting domain.
# Ambiguous OLOR/SABOR words (vainilla, chocolate, etc.) are guarded at
# extraction time in rules.py via _OLOR_SABOR_AMBIGUOUS.
# ---------------------------------------------------------------------------

DESCRIPTOR_WORDS = {
    'ASPECTO': [
        # shape
        'redonda', 'redondo', 'grande', 'pequeña', 'pequeño',
        'mediana', 'mediano', 'enorme', 'minúscula', 'minúsculo',
        'gruesa', 'grueso', 'delgada', 'delgado', 'fina', 'fino',
        'alargada', 'alargado', 'ovalada', 'ovalado',
        'cuadrada', 'cuadrado', 'rectangular',
        'irregular', 'deformada', 'deformado',
        'rota', 'roto', 'agrietada', 'agrietado',
        # appearance / finish
        'dorada', 'dorado', 'tostada', 'tostado',
        'oscura', 'oscuro', 'clara', 'claro',
        'pálida', 'pálido', 'quemada', 'quemado',
        'brillante', 'mate', 'opaca', 'opaco',
        'uniforme', 'lisa', 'liso', 'rugosa', 'rugoso',
        'bonita', 'bonito', 'fea', 'feo',
        # Refuerzo ASPECTO: juicios visuales frecuentes en cata de galletas.
        'original', 'graciosa', 'gracioso', 'divertida', 'divertido',
        'llamativa', 'llamativo', 'casera', 'casero', 'apagada', 'apagado',
        'apetecible', 'poco apetecible',
        'atractiva', 'atractivo', 'poco atractiva', 'poco atractivo',
        'artesanal', 'industrial',
        'decorada', 'decorado',
        # colors
        'café', 'cafe', 'marrón', 'marron', 'negro', 'negra', 'blanco', 'blanca',
        'gris', 'beige', 'crema', 'amarillo', 'amarilla', 'naranja',
        'rojizo', 'rojiza', 'rosado', 'rosada',
        # surface / visible contents
        'con manchas', 'con trozos', 'con pepitas', 'pepitas',
        'con chips', 'con chocolate visible', 'con chispas', 'con semillas',
        'con nueces visibles',
        # decorations
        'figuras', 'figura', 'corazon', 'estrella', 'estrellas',
        'osito', 'ositos', 'muñequito', 'muñequitos',
        'animal', 'animales', 'personaje', 'letra', 'letras',
    ],
    'OLOR': [
        # intensity
        'suave', 'fuerte', 'intenso', 'intensa', 'débil', 'leve',
        'casi imperceptible', 'imperceptible', 'penetrante', 'sutil',
        # quality descriptors
        'agradable', 'desagradable', 'rico', 'rica',
        'artificial', 'natural', 'rancio', 'rancia',
        # specific aromas — require smell context (see _OLOR_SABOR_AMBIGUOUS in rules.py)
        'vainilla', 'chocolate', 'cacao', 'mantequilla',
        'canela', 'jengibre', 'caramelo', 'azúcar tostada',
        'a quemado', 'a mantequilla', 'a vainilla', 'a chocolate',
        'a canela', 'a jengibre', 'a caramelo',
        'dulce', 'especiado', 'especiada', 'mantecoso', 'mantecosa',
        'a galleta', 'a bizcocho',
    ],
    'TEXTURA': [
        # hardness / structure
        'crujiente', 'crujientes', 'cruje',
        'blanda', 'blando', 'dura', 'duro', 'tierna', 'tierno',
        'quebradiza', 'quebradizo',
        'apelmazada', 'apelmazado',
        'gomosa', 'gomoso',
        # moisture
        'seca', 'seco', 'húmeda', 'húmedo', 'pastosa', 'pastoso',
        # granularity
        'arenosa', 'arenoso', 'granulosa', 'granuloso',
        'harinosa', 'harinoso', 'boronosa', 'boronoso',
        # behavior / mouthfeel
        'pegajosa', 'pegajoso',
        'se deshace', 'hace migas', 'muchas migas', 'genera migas',
        'fácil de morder', 'difícil de morder', 'dura al morder',
        'textura agradable', 'textura desagradable',
    ],
    'SABOR': [
        # basic tastes
        'dulce', 'amargo', 'amarga', 'salado', 'salada', 'ácido', 'ácida',
        # sweetness nuance
        'demasiado dulce', 'muy dulce', 'poco dulce', 'bastante dulce',
        'empalagosa', 'empalagoso', 'empalaga',
        # quality
        'suave', 'intenso', 'intensa',
        'equilibrado', 'equilibrada',
        'insípido', 'insípida', 'sin sabor', 'soso', 'sosa',
        # artificial / industrial
        'artificial', 'natural', 'químico', 'química', 'industrial',
        # specific flavors — require taste context (see _OLOR_SABOR_AMBIGUOUS in rules.py)
        'vainilla', 'chocolate', 'cacao', 'mantequilla',
        'canela', 'jengibre', 'caramelo', 'azúcar tostada',
        'a mantequilla', 'a vainilla', 'a chocolate', 'a cacao',
        'a canela', 'a jengibre', 'a caramelo', 'a azúcar tostada',
        # aftertaste
        'retrogusto', 'regusto', 'postgusto',
        'deja buen sabor', 'deja mal sabor', 'deja resabio',
        # richness
        'rico', 'rica', 'bueno', 'buena', 'rancio', 'rancia',
        'sabor intenso', 'sabor suave', 'sabor artificial',
    ],
}

VALUATION_MARKERS = {
    'positive': [
        'me gusta', 'me encanta', 'me resulta agradable', 'me parece bien',
        'agradable', 'rico', 'rica', 'bueno', 'buena',
        'muy buena', 'muy bueno', 'muy rica', 'muy rico',
        'está buena', 'está rica', 'está bien',
        'correcto', 'correcta', 'equilibrado', 'equilibrada',
        'bonito', 'bonita',
        # Refuerzo ASPECTO: valoraciones visuales ("el diseño me parece original").
        'original', 'graciosa', 'gracioso', 'divertida', 'divertido',
        'llamativa', 'llamativo', 'casera', 'casero',
        'apetecible', 'disfrutable', 'positivo', 'positiva',
    ],
    'negative': [
        'no me gusta', 'no me convence', 'no me agrada', 'me disgusta',
        'malo', 'mala', 'desagradable',
        'feo', 'fea',
        'empalaga', 'empalagoso', 'empalagosa',
        'demasiado', 'excesivo', 'excesiva',
        'artificial', 'rancio', 'rancia',
        'decepcionante', 'flojo', 'floja', 'pobre',
        'raro', 'rara', 'extraño', 'extraña',
        'poco apetecible', 'poco atractivo', 'poco atractiva',
        'genera muchas migas', 'se deshace demasiado', 'deja mal sabor',
        'grasienta', 'grasiento',
        'incómodo', 'incómoda', 'molesto', 'molesta',
    ],
}

# Patterns for the deterministic valuation fallback (dialogue.py).
# Applied ONLY when mention_text + descriptor_text are already present but
# valuation_text is empty.  All patterns match normalize_text output (ASCII, lowercase).
VALUATION_PATTERNS: dict[str, list[str]] = {
    'SABOR': [
        r'\bempalaga\b', r'\bempalagos[ao]\b',
        r'\bdemasiada?\s+azucar\b', r'\bdemasiado\s+dulce\b', r'\bmuy\s+dulce\b',
        r'\bpoco\s+dulce\b', r'\bsin\s+sabor\b', r'\bsos[ao]\b', r'\binsipid[ao]\b',
        r'\bjengibre\s+artificial\b', r'\bsabor\s+artificial\b', r'\bartificial\b',
        r'\bdemasiado\s+intenso\b', r'\bmuy\s+intenso\b',
        r'\bno\s+me\s+gusta\b', r'\bno\s+me\s+convence\b',
        r'\bdesagradable\b', r'\bpresiento\s+demasiada?\b',
        r'\brancio\b', r'\brancia\b',
        r'\bdeja\s+mal\s+sabor\b', r'\bdeja\s+resabio\b',
        r'\bquimico\b', r'\bquimica\b',
        r'\bme\s+gusta\b', r'\bme\s+encanta\b', r'\besta\s+buena\b', r'\besta\s+rica\b',
        r'\brico\b', r'\brica\b', r'\bbueno\b', r'\bbuena\b',
        r'\bagradable\b', r'\bequilibrad[ao]\b',
    ],
    'TEXTURA': [
        r'\bgenera\s+muchas\s+migas\b', r'\bmuchas\s+migas\b',
        r'\bse\s+deshace\b', r'\bhace\s+migas\b',
        r'\bdemasiado\s+seca\b', r'\bmuy\s+seca\b',
        r'\bdemasiado\s+dura\b', r'\bmuy\s+dura\b',
        r'\bdemasiado\s+bland[ao]\b', r'\bmuy\s+bland[ao]\b',
        r'\bboronos[ao]\b', r'\barenos[ao]\b', r'\bpegajos[ao]\b',
        r'\bno\s+me\s+gusta\b', r'\bdesagradable\b',
        r'\bme\s+gusta\b', r'\bagradable\b',
        r'\bfacil\s+de\s+morder\b', r'\bdificil\s+de\s+morder\b',
        r'\bdura\s+al\s+morder\b',
        r'\bapelmazad[ao]\b', r'\bgomosa?\b',
    ],
    'OLOR': [
        r'\bagradable\b', r'\bdesagradable\b',
        r'\bdemasiado\s+fuerte\b', r'\bmuy\s+fuerte\b', r'\bdemasiado\s+intenso\b',
        r'\bhuele\s+bien\b', r'\bhuele\s+mal\b',
        r'\bolor\s+artificial\b', r'\bolor\s+agradable\b', r'\bolor\s+desagradable\b',
        r'\brancio\b', r'\brancia\b',
        r'\bme\s+gusta\b', r'\bno\s+me\s+gusta\b', r'\bme\s+encanta\b',
        r'\bno\s+me\s+convence\b',
        r'\brico\b', r'\brica\b', r'\bsuave\b', r'\bpenetrante\b',
    ],
    'ASPECTO': [
        # Visual-specific valuation expressions
        r'\bbonit[ao]\b',
        r'\bfe[ao]\b',
        r'\bbasic[ao]\b', r'\bsencill[ao]\b',
        r'\bpoco\s+atractiv[ao]\b', r'\bpoco\s+apetecible\b',
        r'\bno\s+atractiv[ao]\b', r'\batractiv[ao]\b',
        r'\bapetecible\b',
        r'\bme\s+gusta\s+como\s+se\s+ve\b', r'\bno\s+me\s+gusta\s+como\s+se\s+ve\b',
        r'\bno\s+llama\s+la\s+atencion\b',
        # Refuerzo ASPECTO: diseño/apariencia/decoración con juicio visual.
        r'\boriginal\b', r'\bgracios[ao]\b', r'\bdivertid[ao]\b',
        r'\bllamativ[ao]\b', r'\bcaser[ao]\b', r'\bapagad[ao]\b',
    ],
}


# ---------------------------------------------------------------------------
# Absence / neutrality handling per modality.
#
# Some valid answers describe the ABSENCE of a trait ("no huele a nada",
# "no sabe a nada") or a NEUTRAL impression ("es normal", "no destaca").
# These must complete the *currently asked* modality, but an answer that clearly
# belongs to ANOTHER modality must never complete the current one.
# All patterns match normalize_text output (ASCII, lowercase).
# ---------------------------------------------------------------------------

# Canonical descriptor stored when a modality is resolved as absent/neutral.
ABSENCE_DESCRIPTORS = {
    'ASPECTO': 'normal',
    'OLOR': 'sin olor',
    'TEXTURA': 'normal',
    'SABOR': 'sin sabor',
}

# Modality-agnostic neutrality. Acceptable for whichever modality is being asked,
# because it does not claim any *other* modality.
GENERIC_NEUTRAL_PATTERNS = [
    r'\bsimple\b', r'\bsencill[ao]\b', r'\bbasic[ao]\b',
    r'\bnormal\b', r'\bcorriente\b', r'\bdel\s+monton\b',
    r'\bno\s+tiene\s+nada\s+(?:especial|destacable)\b',
    r'\bnada\s+(?:especial|destacable)\b',
    r'\bno\s+(?:me\s+)?destaca\b',
    r'\bno\s+(?:me\s+)?llama\s+la\s+atencion\b',
    r'\bno\s+noto\s+nada\s+(?:especial|destacable)\b',
    r'\bparece\s+una\s+galleta\s+normal\b',
]

# Neutral / absent VALUATION ("no opinion"). Treated as a valid neutral valuation
# for the modality being asked.
NEUTRAL_VALUATION_PATTERNS = [
    r'\bno\s+tengo\s+(?:una\s+)?opinion(?:es)?\b',
    r'\bsin\s+opinion\b',
    r'\bme\s+da\s+igual\b',
    r'\bme\s+es\s+indiferente\b', r'\bindiferente\b',
    r'\bni\s+fu\s+ni\s+fa\b',
    r'\bno\s+sabria\s+decir\b',
]

# Modality-SPECIFIC absence/neutrality. Only valid for its own modality: these
# are strong signals that the trait of THIS modality is absent or flat.
MODALITY_SPECIFIC_ABSENCE_PATTERNS = {
    'ASPECTO': [
        r'\bno\s+tiene\s+(?:buena\s+|mala\s+)?pinta\b',
    ],
    'OLOR': [
        r'\bno\s+(?:me\s+)?huele(?:\s+a\s+nada)?\b',
        r'\bno\s+tiene\s+olor\b', r'\bsin\s+olor\b',
        r'\bapenas\s+huele\b', r'\bhuele\s+poco\b', r'\bhuelo\s+poco\b',
        r'\bno\s+(?:noto|percibo)\s+(?:el\s+|ningun\s+)?olor\b',
        r'\bno\s+huele\s+a\s+nada\b', r'\bno\s+olia\s+a\s+nada\b',
    ],
    'TEXTURA': [
        r'\bno\s+(?:tiene|noto)\s+(?:una\s+)?textura\s+(?:especial|destacable)\b',
        r'\btextura\s+normal\b',
        r'\bno\s+noto\s+nada\s+especial\s+en\s+la\s+textura\b',
    ],
    'SABOR': [
        r'\bno\s+sabe\s+a\s+(?:casi\s+)?nada\b',
        r'\bno\s+tiene\s+sabor\b', r'\bsin\s+sabor\b',
        r'\bapenas\s+sabe\b', r'\bsabe\s+a?\s*poco\b',
        r'\bsos[ao]\b', r'\binsipid[ao]\b',
        r'\bno\s+(?:noto|percibo)\s+(?:el\s+|ningun\s+)?sabor\b',
    ],
}

# Context anchors per modality (the modality is explicitly being talked about).
_ANCHOR_PATTERNS_BY_MODALITY = {
    'ASPECTO': ASPECT_CONTEXT_PATTERNS,
    'OLOR': SMELL_CONTEXT_PATTERNS,
    'TEXTURA': TEXTURE_CONTEXT_PATTERNS,
    'SABOR': TASTE_CONTEXT_PATTERNS,
}


def _modality_anchor_count(sentence_norm: str, modality: str) -> int:
    """Number of context anchors of ``modality`` present in a normalized sentence."""
    return sum(
        1 for pattern in _ANCHOR_PATTERNS_BY_MODALITY.get(modality, [])
        if re.search(pattern, sentence_norm)
    )


def _is_dominated_by_other_modality(sentence_norm: str, modality: str) -> bool:
    """True when another modality has strictly more context anchors in the sentence.

    Prevents a valuation pattern that overlaps modalities (e.g. "insípida" in SABOR)
    from pulling a sentence that is really about ANOTHER modality (e.g. an ASPECTO
    sentence "...no está muy dorada... puede que sea insípida").
    """
    own = _modality_anchor_count(sentence_norm, modality)
    for other in MODALITY_ORDER:
        if other == modality:
            continue
        if _modality_anchor_count(sentence_norm, other) > own:
            return True
    return False


def find_valuation_in_text(text: str, modality: str) -> str:
    """Return the first sentence in text matching a valuation pattern for the given modality.

    Uses literal user text — never invents. Returns '' when no pattern matches.
    Patterns are tested against normalize_text(sentence) so accents are stripped.
    Sentences dominated by another modality's context are skipped so a valuation is
    never taken from a sentence that belongs to a different modality.
    """
    patterns = VALUATION_PATTERNS.get(modality, [])
    if not patterns or not text:
        return ''
    for sentence in split_sentences(text):
        sentence_norm = normalize_text(sentence)
        if _is_dominated_by_other_modality(sentence_norm, modality):
            continue
        for pattern in patterns:
            if re.search(pattern, sentence_norm):
                return sentence.strip()
    return ''


@dataclass(frozen=True)
class QuestionNeeds:
    mention_missing: bool
    descriptor_missing: bool
    valuation_missing: bool


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize('NFKD', text or '')
    return ''.join(char for char in normalized if not unicodedata.combining(char)).lower()


def split_sentences(text: str) -> list[str]:
    parts = [piece.strip() for piece in re.split(r'(?<=[\.\!?])\s+|\n+', text or '') if piece.strip()]
    if parts:
        return parts
    stripped = (text or '').strip()
    return [stripped] if stripped else []


def has_comparison(text: str, other_sample_codes: list[str] | None = None) -> bool:
    """Detect comparison with other samples.

    Returns True only when text compares the current sample against another
    distinct sample, product, or brand. Avoids two classes of false positives:
    - "igual que" connecting same-sample attributes ("su sabor bueno igual que su textura")
    - negated comparison statements ("no la he comparado con otra", "no estoy comparando")
    """
    lowered = normalize_text(text)

    # Early exit: user explicitly denies having made a comparison
    if _NEGATED_COMPARISON.search(lowered):
        return False

    # Unambiguous markers — any occurrence means cross-sample comparison
    if any(marker in lowered for marker in COMPARISON_MARKERS):
        return True

    # "igual que" is context-sensitive: comparison only when NOT followed by an
    # internal modality attribute of the same sample
    if 'igual que' in lowered and not _IGUAL_QUE_INTERNAL.search(lowered):
        return True

    # "comparad[ao] con" / "en comparacion con" — negation already excluded above
    if re.search(r'\bcomparad[ao]\s+con\b', lowered):
        return True
    if re.search(r'\ben\s+comparacion\s+con\b', lowered):
        return True

    # Reference to a commercial brand or the market in general ("sabe a Oreo",
    # "tipo Chiquilín", "galleta del supermercado"). Sensory ingredient associations
    # ("sabe a vainilla", "me recuerda a canela") carry no brand and are excluded.
    if _is_commercial_comparison(lowered):
        return True

    if other_sample_codes:
        for code in other_sample_codes:
            if normalize_text(code) in lowered:
                return True
    return False


def _is_commercial_comparison(lowered: str) -> bool:
    """True when the (already normalized) text compares the sample against a commercial
    product, a brand, or the market in general.

    Rules:
    - A market phrase ("galleta del supermercado", "galleta barata"...) is a comparison
      on its own.
    - A brand name ("oreo", "chiquilin"...) only counts inside an association context cue
      ("sabe a", "tipo", "me recuerda a", "como"...).
    - A commercial/market reference always wins over a co-occurring sensory ingredient, so
      "sabe a Oreo" → True while "sabe a mantequilla" → False (no brand token present).
    """
    if _search_any(MARKET_REFERENCE_PATTERNS, lowered):
        return True
    if _BRAND_CONTEXT.search(lowered) and _search_any(COMMERCIAL_BRANDS, lowered):
        return True
    return False


def is_global_opinion_only(text: str) -> bool:
    lowered = normalize_text(text)
    if not lowered:
        return True
    matched = any(re.search(pattern, lowered) for pattern in GLOBAL_OPINION_PATTERNS)
    has_modality_anchor = any(re.search(pattern, lowered) for patterns in MENTION_PATTERNS.values() for pattern in patterns)
    return matched and not has_modality_anchor


def infer_question_needs(mention_text: str, descriptor_text: str, valuation_text: str) -> QuestionNeeds:
    return QuestionNeeds(
        mention_missing=not bool((mention_text or '').strip()),
        descriptor_missing=not bool((descriptor_text or '').strip()),
        valuation_missing=not bool((valuation_text or '').strip()),
    )


def _search_any(patterns: list[str], lowered: str) -> bool:
    return any(re.search(pattern, lowered) for pattern in patterns)


def detect_specific_absence(text: str, modality: str) -> bool:
    """True when text matches a modality-SPECIFIC absence/neutral expression."""
    lowered = normalize_text(text)
    return _search_any(MODALITY_SPECIFIC_ABSENCE_PATTERNS.get(modality, []), lowered)


def detect_modality_absence(text: str, modality: str) -> str | None:
    """Return the canonical absence/neutral descriptor for ``modality`` when the
    answer describes absence of that trait or a generic neutral impression.

    Returns None when the answer carries no absence/neutral signal. The result is
    intended for the modality the bot is currently asking about — it never marks
    a modality the participant did not actually address.
    """
    if detect_specific_absence(text, modality):
        return ABSENCE_DESCRIPTORS.get(modality)
    lowered = normalize_text(text)
    if _search_any(GENERIC_NEUTRAL_PATTERNS, lowered):
        return ABSENCE_DESCRIPTORS.get(modality)
    return None


def is_neutral_valuation(text: str) -> bool:
    """True when text expresses a neutral/absent opinion ("no tengo opinión")."""
    lowered = normalize_text(text)
    return _search_any(NEUTRAL_VALUATION_PATTERNS, lowered) or _search_any(GENERIC_NEUTRAL_PATTERNS, lowered)


# Brief opinion expressions used to recognise valuation-only answers to a valuation
# question (e.g. "no me encanta", "regular", "no mucho", "sí", "no"). Matched on
# normalize_text output (ASCII, lowercase, accents stripped → "sí" becomes "si").
_BRIEF_VALUATION_PATTERNS = [
    r'^(?:si|no)\b',
    r'\bme\s+gusta\b', r'\bno\s+me\s+gusta\b',
    r'\bme\s+encanta\b', r'\bno\s+me\s+encanta\b',
    r'\bme\s+parece\s+(?:bien|mal|regular)\b',
    r'\bno\s+esta\s+mal\b', r'\besta\s+bien\b',
    r'\bregular\b', r'\bnormal\b',
    r'\bno\s+mucho\b', r'\bun\s+poco\b', r'\bdemasiado\b',
    r'\bbastante\b', r'\bbien\b', r'\bmal\b',
]


def is_brief_valuation(text: str) -> bool:
    """True when text expresses a (brief) valuation/opinion.

    Covers explicit markers ('me gusta', 'no me convence'…), neutral opinions
    ('me da igual', 'normal'…) and the short forms above ('regular', 'no mucho',
    'sí', 'no'). Used together with a 'no specific descriptor' check to detect
    valuation-only answers, so loose matches here are safe.
    """
    lowered = normalize_text(text)
    if not lowered.strip():
        return False
    if _search_any(_BRIEF_VALUATION_PATTERNS, lowered):
        return True
    if is_neutral_valuation(text):
        return True
    markers = VALUATION_MARKERS['positive'] + VALUATION_MARKERS['negative']
    return any(normalize_text(marker) in lowered for marker in markers)


def _has_specific_modality_evidence(text: str, modality: str) -> bool:
    """True when text contains evidence belonging specifically to ``modality``:
    a context anchor, a descriptor word, or a modality-specific absence phrase.

    Generic neutral expressions ("normal", "no destaca") are intentionally
    excluded — they belong to no modality in particular.
    """
    lowered = normalize_text(text)
    if _search_any(_ANCHOR_PATTERNS_BY_MODALITY.get(modality, []), lowered):
        return True
    for word in DESCRIPTOR_WORDS.get(modality, []):
        if normalize_text(word) in lowered:
            return True
    return detect_specific_absence(text, modality)


def mentions_other_modality_only(text: str, current_modality: str) -> bool:
    """True when the answer's sensory content belongs to a DIFFERENT modality and
    provides no specific evidence for ``current_modality``.

    Used to stop an off-topic answer (e.g. a taste/smell remark given when the bot
    asked about texture) from completing the current modality. Generic neutral
    answers ("es normal") are NOT considered off-topic, so they still resolve the
    modality being asked.
    """
    if _has_specific_modality_evidence(text, current_modality):
        return False
    for modality in MODALITY_ORDER:
        if modality == current_modality:
            continue
        if _has_specific_modality_evidence(text, modality):
            return True
    return False
