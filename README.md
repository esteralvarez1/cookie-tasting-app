# Cookie Tasting App

Aplicación web para realizar catas de galletas mediante una conversación guiada. La aplicación permite configurar sesiones de cata desde un panel de administración, recoger respuestas de participantes, analizar sus opiniones por modalidades sensoriales y exportar los resultados.

## Ideas principales de diseño

- El **backend decide siempre la siguiente acción** de la conversación.
- El LLM **solo analiza la respuesta del usuario**. Puede extraer información, pero no gobierna el flujo.
- La conversación completa, las respuestas del usuario y la salida estructurada se guardan y exportan por separado.
- El flujo de la cata es determinista: el backend controla vaguedad, comparaciones, modalidades pendientes, intentos máximos y cierre de muestra.

## Estructura del proyecto

```text
cookie-tasting-v1-1/
├── backend/              # FastAPI + SQLAlchemy + Alembic + PostgreSQL
├── frontend/             # React + Vite + TypeScript
├── docker-compose.yml    # PostgreSQL del proyecto expuesto en localhost:5434
├── README.md
└── docs/
```

## Requisitos previos

- Python 3.11
- Node.js y npm
- Docker y Docker Compose
- PostgreSQL, si no se usa el contenedor del proyecto

## Variables de entorno

El backend lee variables desde un archivo `.env` situado en la raíz del proyecto o dentro de `backend/`.

El repositorio debe incluir un `.env.example` sin claves reales. Para crear tu configuración local:

```bash
cp .env.example .env
```

Variables principales:

```env
APP_ENV=development
LOG_LEVEL=INFO

DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5434/cookie_tasting

LLM_PROVIDER=rules
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=
LLM_MODEL=llama-3.1-8b-instant
LLM_TIMEOUT_SECONDS=20
LLM_CONNECT_TIMEOUT_SECONDS=10
LLM_MAX_RETRIES=2
LLM_RESPONSE_FORMAT_JSON=true
LLM_CONTEXT_MAX_CHARS=3000

ADMIN_API_KEY=change-me
RESEARCHER_API_KEY=change-me-researcher
BACKEND_CORS_ORIGINS=http://localhost:5173

SESSION_TOKEN_TTL_HOURS=24
MAX_VAGUE_RETRIES=1
MAX_COMPARISON_RETRIES=2
MAX_MODALITY_ATTEMPTS=2

RATE_LIMIT_SESSIONS_PER_MINUTE=10
RATE_LIMIT_DIALOG_PER_MINUTE=30
```

No subas el archivo `.env` real al repositorio.

## Arranque con el PostgreSQL del proyecto

El `docker-compose.yml` expone la base de datos del proyecto en `localhost:5434` para evitar conflictos con un PostgreSQL local en `5432`.

```bash
docker compose up -d db
```

En `.env`, usa:

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5434/cookie_tasting
```

## Arranque con PostgreSQL local existente en 5432

Si ya tienes un PostgreSQL local en `localhost:5432` y quieres usarlo en lugar del contenedor del proyecto, crea primero la base:

```bash
createdb cookie_tasting
```

Después, en `.env`, usa:

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/cookie_tasting
```

Si usas otro contenedor de PostgreSQL ya existente, crea la base con `psql` o `docker exec` y ajusta `DATABASE_URL` al puerto correspondiente.

## Backend

Desde la raíz del proyecto:

```bash
python3.11 -m venv venv
source venv/bin/activate

cd backend
pip install --upgrade pip
pip install -r requirements.txt

export PYTHONPATH=$(pwd)
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API disponible en:

```text
http://127.0.0.1:8000
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

Healthcheck:

```text
http://127.0.0.1:8000/api/v1/health
```

## Frontend

En otra terminal:

```bash
cd frontend
npm install
npm run dev
```

Frontend disponible normalmente en:

```text
http://127.0.0.1:5173
```

Panel de administración:

```text
http://127.0.0.1:5173/admin
```

Pantalla de participante:

```text
http://127.0.0.1:5173/?token=<public_token>
```

## Flujo principal de la aplicación

### Flujo administrador

1. El administrador accede al panel admin.
2. Crea una sesión de cata.
3. Define el título y los códigos de muestra.
4. La aplicación genera un `public_token` y un enlace público.
5. El administrador puede consultar sesiones creadas.
6. El administrador puede cerrar una sesión de cata.
7. El administrador puede exportar resultados.

### Flujo participante

1. El participante entra con el enlace público.
2. Introduce su código de participante.
3. El backend crea o recupera su sesión de participante.
4. Si hay una sola muestra, empieza directamente.
5. Si hay varias muestras, selecciona el código de muestra correspondiente.
6. El backend crea una evaluación para esa muestra.
7. El chatbot lanza la pregunta inicial.
8. El participante responde.
9. El LLM o el analizador por reglas extrae información de la respuesta.
10. El backend decide la siguiente acción.
11. Cuando termina una muestra, se muestran las escalas de valoración y, a continuación, la pantalla de comentario final de esa muestra (`sample_comment`).
12. Si quedan muestras pendientes, el participante selecciona la siguiente muestra.
13. Después del comentario final de la última muestra, se muestra directamente la pantalla final de sesión.

## Endpoints principales

### Sistema

- `GET /api/v1/health`

### Sesiones de cata configuradas por admin

- `POST /api/v1/tasting-sessions` — crear sesión de cata configurada. Requiere `X-Admin-Key`.
- `GET /api/v1/tasting-sessions` — listar sesiones de cata configuradas. Requiere `X-Admin-Key`.
- `POST /api/v1/tasting-sessions/{session_config_id}/close` — cerrar sesión de cata. Requiere `X-Admin-Key`.
- `GET /api/v1/tasting-sessions/public/{token}` — obtener información pública de una sesión de cata.

### Sesiones de participante

- `POST /api/v1/sessions` — crear o recuperar sesión de participante.
- `GET /api/v1/sessions/{session_id}/next-step` — consultar siguiente paso de la sesión.
- `POST /api/v1/sessions/{session_id}/survey` — _(legacy, no usado por el frontend actual)_ endpoint de encuesta final global de sesión. El flujo actual usa el comentario final por muestra (`POST /api/v1/evaluations/{evaluation_id}/final-comment`).

### Evaluaciones de muestra

- `POST /api/v1/evaluations` — crear o recuperar evaluación de una muestra.
- `POST /api/v1/evaluations/{evaluation_id}/dialog` — enviar respuesta del participante al chatbot.
- `GET /api/v1/evaluations/{evaluation_id}` — consultar estado de evaluación.
- `GET /api/v1/evaluations/{evaluation_id}/conversation` — consultar conversación de evaluación.
- `GET /api/v1/evaluations/{evaluation_id}/analysis` — consultar análisis de evaluación.
- `POST /api/v1/evaluations/{evaluation_id}/final-comment` — guardar comentario final de muestra.
- `POST /api/v1/evaluations/{evaluation_id}/finalize` — finalizar evaluación manualmente. Requiere `X-Admin-Key`.

### Exportaciones

- `GET /api/v1/export/conversations` — exportar conversación completa. Requiere `X-Researcher-Key` o `X-Admin-Key`.
- `GET /api/v1/export/user-responses` — exportar solo respuestas del usuario. Requiere `X-Researcher-Key` o `X-Admin-Key`.
- `GET /api/v1/export/structured` — exportar clasificación estructurada. Requiere `X-Researcher-Key` o `X-Admin-Key`.

Parámetros comunes de exportación:

```text
format=csv|json
session_id=<id_sesion_participante>
participant_code=<codigo_participante>
tasting_session_config_id=<id_sesion_admin>
```

En `/api/v1/export/structured`, además:

```text
format=csv|json|xlsx
```

### Depuración técnica

- `GET /api/v1/debug/llm` — consultar proveedor, modelo y versión de prompt activos. Requiere `X-Admin-Key`.

Este endpoint es técnico. Si no se necesita para la entrega o demo, puede eliminarse o dejarse justificado como endpoint de mantenimiento.

## Autenticación mínima de la versión v1

- El participante recibe un `session_token` al crear o recuperar su sesión.
- El token se debe enviar en la cabecera `X-Session-Token` para operar sobre su sesión y sus evaluaciones.
- El backend almacena el token mediante hash, no en texto plano.
- Las exportaciones requieren `X-Researcher-Key` o `X-Admin-Key`.
- Las operaciones administrativas requieren `X-Admin-Key`.
- La depuración LLM requiere `X-Admin-Key`.

## Analizador LLM y fallback por reglas

La aplicación puede funcionar con dos tipos de analizador:

- `rules`: analizador local basado en reglas.
- `groq` u otro proveedor compatible con OpenAI: analizador LLM externo.

Ejemplo para Groq:

```env
LLM_PROVIDER=groq
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=<tu_clave>
LLM_MODEL=llama-3.1-8b-instant
```

Si `LLM_PROVIDER=groq` pero falta `LLM_API_KEY`, el sistema usa el analizador `rules` como fallback.

La acción devuelta en `analysis.next_action` es la **acción efectiva calculada por el backend**, no una decisión autónoma del LLM.

## Pruebas automatizadas

Para ejecutar las pruebas:

```bash
cd backend
source ../venv/bin/activate
pip install -r requirements-test.txt
export PYTHONPATH=$(pwd)
pytest -q
```

Las pruebas están en:

```text
backend/tests/
```

Cubren, entre otros aspectos:

- flujo conversacional;
- detección de comparaciones;
- preguntas por modalidad;
- extracción de valoración;
- creación de sesiones de cata;
- sesiones de participante;
- evaluaciones;
- seguridad;
- exportaciones.

## Mejoras aplicadas en esta versión

- El LLM ya no decide ninguna acción de flujo; el backend calcula siempre la acción efectiva.
- Las preguntas por modalidad son adaptativas: distinguen entre falta de mención, descriptor y valoración.
- Se mantiene `rules` como fallback real cuando no se usa LLM externo.
- Se ha añadido almacenamiento seguro del `session_token` mediante hash.
- Se ha añadido `next_turn_index` para evitar calcular `max(turn_index)` en cada inserción.
- `POST /api/v1/evaluations/{evaluation_id}/dialog` devuelve el snapshot actualizado de evaluación y conversación para reducir llamadas adicionales desde el frontend.
- Se ha añadido lógica determinista de vaguedad para respuestas claramente pobres como `ok`, `está bien` o `me gusta`.
- `POST /api/v1/evaluations/{evaluation_id}/dialog` devuelve un bloque `analysis` ampliado con `analysis_scope`, `reasoning_summary`, `next_action` y modalidades.
- Se ha añadido exportación de respuestas del usuario.
- Se ha añadido exportación estructurada en `xlsx`.
- Se han añadido pruebas unitarias e integradas para flujo, reglas, seguridad y exportaciones.

## Limpieza recomendada antes de entregar

Antes de subir el proyecto a GitLab o entregar un ZIP, elimina archivos generados o sensibles:

```bash
rm -rf venv
rm -rf frontend/node_modules
rm -rf __MACOSX
find . -name ".DS_Store" -delete
find . -name "__pycache__" -type d -prune -exec rm -rf {} +
find . -name ".pytest_cache" -type d -prune -exec rm -rf {} +
```

Asegúrate de que `.gitignore` contiene:

```gitignore
.env
venv/
node_modules/
__MACOSX/
.DS_Store
__pycache__/
.pytest_cache/
```
