# Cookie Tasting

Aplicación web para realizar **catas sensoriales de galletas guiadas por conversación**.
Un administrador crea "sesiones de cata" (plantillas con códigos de muestra y un enlace
público); los participantes acceden por ese enlace, describen cada muestra en un chat, y
un analizador (LLM externo o reglas locales) extrae evidencia por **4 modalidades
sensoriales** (ASPECTO, OLOR, TEXTURA, SABOR). Los investigadores exportan los resultados
en CSV, JSON y XLSX.

## Principio de diseño

- El **backend decide siempre la siguiente acción** de la conversación.
- El LLM **solo analiza la respuesta del usuario**: extrae información, pero no gobierna el flujo.
- La **vaguedad** y la **comparación** se recalculan de forma **determinista en el backend**,
  ignorando lo que devuelva el LLM.
- La conversación completa, las respuestas del usuario y la salida estructurada se guardan y
  exportan por separado.

## Stack tecnológico

| Capa | Tecnología |
|---|---|
| Backend | FastAPI 2.0 · SQLAlchemy 2 · Alembic · PostgreSQL 16 |
| Analizador | API compatible OpenAI (Groq por defecto) con *fallback* a reglas locales |
| Frontend | React 18 · Vite 5 · TypeScript · react-router 6 |
| Despliegue | Docker Compose · Caddy (proxy inverso) · Nginx (SPA) |

## Arquitectura resumida

```text
Participante (/cata)  ─┐
                       ├─► API FastAPI ─► DialogueService/FlowDecisionEngine ─► Analyzer ─► PostgreSQL
Admin/Investigador (/admin) ─┘                                         (LLM externo / reglas)
```

Detalle completo en [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Requisitos previos

- Python 3.11
- Node.js 20 y npm
- Docker y Docker Compose

## Variables de entorno

El backend lee las variables desde un `.env` en la raíz del proyecto o dentro de `backend/`.
Copia la plantilla y ajústala:

```bash
cp .env.example .env
```

**Nunca subas `.env` ni `.env.prod` reales al repositorio.** Variables principales:

```env
APP_ENV=development
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5434/cookie_tasting

LLM_PROVIDER=rules            # rules | groq | openai | openai-compatible | ollama
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=
LLM_MODEL=llama-3.1-8b-instant
LLM_FALLBACK_TO_RULES=false

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

La tabla completa de variables está en [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Ejecución en desarrollo

Base de datos (Postgres del proyecto, expuesto en `localhost:5434` para no chocar con un
Postgres local en `5432`):

```bash
docker compose up -d db
```

Backend:

```bash
python3.11 -m venv venv
source venv/bin/activate
cd backend
pip install --upgrade pip && pip install -r requirements.txt
export PYTHONPATH=$(pwd)
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- API: `http://127.0.0.1:8000`
- Swagger: `http://127.0.0.1:8000/docs`
- Healthcheck: `http://127.0.0.1:8000/api/v1/health`

Frontend (en otra terminal):

```bash
cd frontend
npm install
npm run dev            # http://127.0.0.1:5173
```

Rutas del frontend:

- Panel de administración: `http://127.0.0.1:5173/admin`
- Pantalla de participante: `http://127.0.0.1:5173/cata?token=<public_token>`

## Ejecución con Docker (producción)

```bash
# Crear .env.prod con claves reales (ver docs/DEPLOYMENT.md)
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

Levanta cuatro servicios: `db`, `backend`, `frontend` y `caddy` (proxy en el puerto 80/443).
Guía completa en [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

### Despliegue con modelo local Salamandra (CPU, sin GPU)

Para el despliegue final en una VM básica de la UPM con el modelo local
`salamandra-2b-instruct` servido por el servicio interno `salamandra-api` (interfaz
OpenAI-compatible, sin APIs externas), sigue la guía dedicada:
**[DEPLOYMENT_SALAMANDRA_LOCAL.md](DEPLOYMENT_SALAMANDRA_LOCAL.md)**. En ese modo se levanta
además el servicio `salamandra-api` y el backend usa `LLM_PROVIDER=openai-compatible`
apuntando a `http://salamandra-api:8001/v1`.

## Tests

```bash
cd backend
pip install -r requirements-test.txt
export PYTHONPATH=$(pwd)
pytest -q
# Alternativa en Docker (requiere Postgres dev en :5434):
./run_tests.sh
```

Detalle en [docs/TESTING.md](docs/TESTING.md).

## Exportaciones

Tres exportaciones, todas protegidas por `X-Researcher-Key` o `X-Admin-Key`:

- `GET /api/v1/export/conversations` — conversación completa (csv, json)
- `GET /api/v1/export/user-responses` — solo respuestas del participante (csv, json)
- `GET /api/v1/export/structured` — clasificación por modalidad, 18 columnas (csv, json, **xlsx**;
  solo evaluaciones completadas)

Filtro obligatorio: al menos uno de `session_id`, `participant_code`,
`tasting_session_config_id`. Ver [docs/API.md](docs/API.md).

## Seguridad básica

- Participante: `X-Session-Token` (hasheado con SHA-256, con TTL).
- Investigador: `X-Researcher-Key`. Administración y depuración: `X-Admin-Key`.
- En `APP_ENV=production` el backend **rechaza el arranque** si las claves siguen siendo
  valores por defecto.

Antes de desplegar a producción revisa [docs/SECURITY.md](docs/SECURITY.md) (TLS, rate limits,
rotación de claves, cierre de Swagger).

## Estructura del repositorio

```text
cookie-tasting-v1-1/
├── backend/              # FastAPI + SQLAlchemy + Alembic + PostgreSQL
│   ├── app/              # api/ core/ models/ schemas/ services/
│   ├── alembic/          # migraciones 0001→0008
│   └── tests/            # suite pytest
├── frontend/             # React + Vite + TypeScript
│   ├── src/              # App participante (/cata)
│   └── src/admin/        # panel admin (/admin)
├── docker-compose.yml        # Postgres dev en localhost:5434
├── docker-compose.prod.yml   # 4 servicios de producción
├── Caddyfile                 # proxy inverso
├── docs/                     # documentación oficial
└── README.md
```

## Estado actual del proyecto

Versión **2.0.0**, funcional. Pendiente antes de un despliegue serio a producción:
activar TLS, endurecer los límites de rate limiting, rotar las claves y desactivar `/docs`.
Registro de cambios en [docs/CHANGELOG.md](docs/CHANGELOG.md).
