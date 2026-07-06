# Operaciones

Guía operativa para el despliegue con `docker-compose.prod.yml` (db, backend, frontend, caddy).

## Arranque

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

El backend aplica `alembic upgrade head` automáticamente antes de arrancar Uvicorn.

## Parada

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml down          # conserva volúmenes
docker compose --env-file .env.prod -f docker-compose.prod.yml down -v       # ELIMINA datos (¡cuidado!)
```

## Logs

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f backend
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f caddy
```

El backend usa `logging.basicConfig` con nivel `LOG_LEVEL`. Los fallos del LLM se registran
con traza (`logger.exception` / `logger.warning` al usar el fallback).

## Backups

La base vive en el volumen `postgres_data`. Copia lógica recomendada:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec db \
  pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup_$(date +%F).sql
```

Restauración:

```bash
cat backup_YYYY-MM-DD.sql | docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T db \
  psql -U "$POSTGRES_USER" "$POSTGRES_DB"
```

## Actualización de la aplicación

```bash
git pull
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

Las migraciones nuevas se aplican solas al reiniciar el backend. Haz un backup antes de
actualizar si la revisión incluye cambios de esquema.

## Migraciones manuales

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec backend alembic current
docker compose --env-file .env.prod -f docker-compose.prod.yml exec backend alembic upgrade head
docker compose --env-file .env.prod -f docker-compose.prod.yml exec backend alembic downgrade -1
```

## Monitorización

- Salud del backend: `curl http://<IP>/api/v1/health` (no verifica la DB; considerar
  añadir un chequeo de conexión).
- Estado de contenedores: `docker compose --env-file .env.prod -f docker-compose.prod.yml ps`.
- Salud de la DB: healthcheck `pg_isready` integrado en el compose.
- LLM efectivo: `GET /api/v1/debug/llm` y `POST /api/v1/debug/llm/probe` (requieren
  `X-Admin-Key`); el panel admin lo expone en la pantalla **Healthcheck**.

## Diagnóstico de errores frecuentes

| Síntoma | Causa | Acción |
|---|---|---|
| Backend reinicia en bucle | Claves por defecto con `APP_ENV=production` | Configurar claves reales |
| Backend no conecta a la DB | `DATABASE_URL` o credenciales incorrectas | Revisar `.env.prod`; `docker compose logs db` |
| El LLM no responde | Clave/URL inválida o servicio caído | `POST /debug/llm/probe`; activar `LLM_FALLBACK_TO_RULES` como colchón |
| Descargas sin nombre correcto | Falta cabecera `Content-Disposition` | Verificar CORS (`expose_headers`) y proxy |
| Participantes ven `429` | Rate limit demasiado bajo | Ajustar `RATE_LIMIT_*` |
| Datos crecen mucho | `accumulated_text` completo por trazabilidad | Purga/archivado periódico si procede |
