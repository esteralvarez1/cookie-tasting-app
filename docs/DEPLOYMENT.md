# Despliegue

Existe además una guía extendida orientada a una VM universitaria en
[`../DEPLOYMENT_VM.md`](../DEPLOYMENT_VM.md). Este documento resume el despliegue local y de
producción y añade el endurecimiento recomendado.

## Despliegue local (desarrollo)

```bash
docker compose up -d db          # PostgreSQL 16 en localhost:5434
# Backend
cd backend && export PYTHONPATH=$(pwd)
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
# Frontend
cd ../frontend && npm install && npm run dev   # http://127.0.0.1:5173
```

## Despliegue de producción (Docker Compose)

`docker-compose.prod.yml` orquesta cuatro servicios:

| Servicio | Imagen / build | Puerto | Notas |
|---|---|---|---|
| `db` | postgres:16 | interno 5432 | Volumen `postgres_data`, healthcheck `pg_isready` |
| `backend` | `./backend` | interno 8000 | `env_file: .env.prod`; ejecuta `alembic upgrade head` al arrancar |
| `frontend` | `./frontend` | interno 80 | Nginx sirve el build de Vite (`VITE_API_BASE_URL=PUBLIC_APP_URL`) |
| `caddy` | caddy:2-alpine | **80 / 443** | Proxy inverso público |

Orden de arranque: `db` (healthy) → `backend` → `frontend` / `caddy`.

### Enrutado (Caddyfile)

```
/api/*  → backend:8000
resto   → frontend:80
```

### Pasos reproducibles

```bash
git clone <repo> && cd cookie-tasting-v1-1

# 1. Crear .env.prod (NUNCA se versiona) con claves reales:
#    ADMIN_API_KEY / RESEARCHER_API_KEY  →  openssl rand -hex 32
#    POSTGRES_PASSWORD                    →  openssl rand -hex 24
#    LLM_API_KEY                          →  clave real del proveedor
#    PUBLIC_APP_URL y BACKEND_CORS_ORIGINS = URL pública exacta (sin barra final)

# 2. Levantar
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build

# 3. Verificar
curl http://<IP>/api/v1/health
```

## Variables de entorno

### Backend

| Variable | Obligatoria | Ejemplo | Descripción |
|---|---|---|---|
| `APP_ENV` | Sí (prod) | `production` | Activa la validación anti-claves-por-defecto |
| `LOG_LEVEL` | No | `INFO` | Nivel de logging |
| `DATABASE_URL` | Sí | `postgresql+psycopg://…` | Conexión a PostgreSQL |
| `LLM_PROVIDER` | No | `groq` / `rules` | Selección de analizador |
| `LLM_BASE_URL` | Cond. | `https://api.groq.com/openai/v1` | URL del proveedor |
| `LLM_API_KEY` | Cond. | — | Clave del proveedor (si no, se usa `rules`) |
| `LLM_MODEL` | No | `llama-3.1-8b-instant` | Modelo |
| `LLM_TIMEOUT_SECONDS` / `LLM_CONNECT_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` | No | `20` / `10` / `2` | Ajustes de red del LLM |
| `LLM_RESPONSE_FORMAT_JSON` | No | `true` | Forzar `response_format` JSON |
| `LLM_CONTEXT_MAX_CHARS` | No | `3000` | Ventana enviada al LLM (la persistencia es completa) |
| `LLM_CONTEXT_MODE` | No | `minimal` | `minimal` \| `legacy` |
| `LLM_FALLBACK_TO_RULES` | No | `false` | Fallback a reglas ante fallo del LLM |
| `ADMIN_API_KEY` | Sí (prod) | hex(32) | Clave de administración |
| `RESEARCHER_API_KEY` | Sí (prod) | hex(32) | Clave de exportación |
| `BACKEND_CORS_ORIGINS` | Sí (prod) | `http://IP` | Orígenes CORS (coma-separados) |
| `SESSION_TOKEN_TTL_HOURS` | No | `24` | Vigencia del token de participante |
| `MAX_VAGUE_RETRIES` / `MAX_COMPARISON_RETRIES` / `MAX_MODALITY_ATTEMPTS` | No | `1` / `2` / `2` | Reintentos del flujo |
| `RATE_LIMIT_SESSIONS_PER_MINUTE` / `RATE_LIMIT_DIALOG_PER_MINUTE` | No | `10` / `30` | Límites por IP |

### Frontend (build) y Docker Compose

| Variable | Dónde | Descripción |
|---|---|---|
| `VITE_API_BASE_URL` | build frontend | URL del backend (queda embebida en el bundle) |
| `VITE_ADMIN_HEADER_NAME` | build frontend | Nombre de la cabecera admin (por defecto `X-Admin-Key`) |
| `PUBLIC_APP_URL` | compose prod | URL pública; se usa como `VITE_API_BASE_URL` al compilar |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | compose prod | Credenciales de la DB |

> **No definir `VITE_ADMIN_API_KEY`.** Cualquier variable `VITE_*` se embebe en el bundle
> del navegador; una clave real quedaría expuesta. El Dockerfile del frontend la omite a
> propósito.

## Puertos

- Públicos: **80** (HTTP) y **443** (HTTPS, si se configura dominio).
- **No exponer**: 5432 (Postgres), 8000 (backend), 5173 (dev frontend).

## Migraciones

Automáticas: el `CMD` del `backend/Dockerfile` ejecuta `alembic upgrade head` antes de
Uvicorn. En local se lanzan a mano con `alembic upgrade head`.

## Healthchecks

- `db`: `pg_isready` en el compose de producción.
- Backend: `GET /api/v1/health` (responde `{status: ok}`; **no** comprueba la conexión a la DB).

## Endurecimiento recomendado antes de producción

1. **TLS:** configurar un dominio en el `Caddyfile` para que Caddy emita certificado
   automático; no servir en `:80` plano.
2. **Rate limiting:** usar valores restrictivos (p. ej. `10` / `30`), no `200` / `500`.
3. **Swagger:** `docs_url=None` en producción.
4. **Claves:** rotarlas si `.env`/`.env.prod` se han compartido.
5. **CORS:** `allow_credentials=False` (la app no usa cookies).

## Troubleshooting

| Síntoma | Causa probable | Solución |
|---|---|---|
| El backend no arranca | Claves por defecto con `APP_ENV=production` | Poner claves reales (validador de arranque) |
| `401` en el panel admin | `X-Admin-Key` incorrecta | Revisar `ADMIN_API_KEY` / `VITE_*` |
| El frontend no ve el logo | `frontend/public/logo_final.png` sin versionar | Añadir el asset al repositorio |
| CORS bloqueado | `BACKEND_CORS_ORIGINS` ≠ URL pública | Igualar protocolo y host (sin barra final) |
| Rate limit se "resetea" | Almacenamiento en memoria | Usar backend Redis si hay varios procesos |
