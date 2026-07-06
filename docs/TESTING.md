# Testing

## Estrategia

Pruebas de backend con **pytest** + `TestClient` de FastAPI, contra una base de datos
PostgreSQL de test independiente. El LLM se fuerza a `rules` para no depender de servicios
externos. No hay pruebas de frontend.

## Configuración (`backend/tests/conftest.py`)

- Variables de entorno fijadas antes del primer import (`APP_ENV=development`,
  `DATABASE_URL` → `…:5434/cookie_tasting_test`, claves de test, `LLM_PROVIDER=rules`,
  rate limits altos).
- El esquema se crea con `Base.metadata.create_all` al inicio de la sesión y se elimina al
  final; cada test hace `TRUNCATE … CASCADE` para aislamiento.
- Fixtures reutilizables: `client`, `admin_headers`, `researcher_headers`,
  `tasting_config`, `participant_session`, `session_headers`, `evaluation`.

## Cómo ejecutar

```bash
cd backend
pip install -r requirements-test.txt
export PYTHONPATH=$(pwd)
pytest -q
```

En Docker, sin Python local (requiere Postgres dev en `:5434`):

```bash
./run_tests.sh                          # suite completa
./run_tests.sh -k valuation             # filtrar
./run_tests.sh -q tests/test_exports.py # un archivo
```

## Qué se cubre

| Archivo | Qué valida |
|---|---|
| `test_dialog_flow.py` | Flujo conversacional completo |
| `test_comparison_detection.py` | Detección de comparación (casos A–F) |
| `test_rule_based_analyzer.py` | Analizador por reglas |
| `test_exports.py` | Las tres exportaciones y sus filtros |
| `test_llm_context.py` | Contexto minimal enviado al LLM |
| `test_llm_strict_validation.py` | Validación estricta del JSON del LLM |
| `test_modality_focus_and_consolidation.py` | Foco por modalidad + consolidación |
| `test_modality_absence.py` | Ausencia/neutralidad y guardas cruzadas |
| `test_modality_questions.py` | Texto neutro y conciso de las preguntas |
| `test_valuation_extraction.py` / `test_valuation_only_merge.py` | Extracción/merge de valoración |
| `test_is_vague_coverage.py` | Vaguedad decidida por cobertura (backend) |
| `test_fallback_analyzer.py` | Fallback automático a reglas |
| `test_security.py` | Autenticación de endpoints protegidos |
| `test_tasting_sessions.py` / `test_participant_sessions.py` / `test_evaluations.py` | CRUD y ciclo de vida |
| `test_aspecto_mention_regression.py` / `test_excel_realcase_consolidation.py` | Regresiones sobre casos reales |

## Qué NO se cubre (riesgos)

- **Frontend:** no hay tests (0 archivos).
- **Migraciones Alembic:** el esquema de test se crea desde el ORM (`create_all`), no con
  `alembic upgrade head`. Un fallo en una migración no lo detecta la suite.
- **Trigger de máximo de evaluaciones:** no se ejercita (el esquema ORM no lo crea).
- **Rate limiting real** y **expiración de token end-to-end en la UI**.

## Pruebas manuales recomendadas

- Flujo participante completo con LLM real (usar `POST /debug/llm/probe` para verificar).
- Expiración del token de sesión (`SESSION_TOKEN_TTL_HOURS` bajo).
- Borrado en cascada de una sesión con análisis del LLM (`DELETE /tasting-sessions/{id}`).
- Descarga XLSX de la exportación estructurada.
- CORS entre dominios reales.
- Arranque con `APP_ENV=production` y claves por defecto (debe fallar).

## Mejora recomendada de CI

Añadir un job que ejecute `alembic upgrade head` sobre una base limpia, para validar las
migraciones que hoy la suite no ejercita.
