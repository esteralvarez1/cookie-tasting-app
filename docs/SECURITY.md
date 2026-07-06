# Seguridad

## Modelo de acceso

| Rol | Cabecera | Alcance |
|---|---|---|
| Participante | `X-Session-Token` | Su propia sesión y sus evaluaciones |
| Investigador | `X-Researcher-Key` | Exportaciones |
| Administrador | `X-Admin-Key` | Gestión de catas, finalización manual, depuración |

## Tokens y claves

- El **token de participante** se genera con `secrets.token_urlsafe`, se almacena **hasheado
  con SHA-256** (`session_token_hash`) y tiene un **TTL** (`SESSION_TOKEN_TTL_HOURS`); la
  expiración se guarda en `config_json.session_token_expires_at`. Pasado el TTL se responde
  `401` con `detail = "session_expired"`.
- Las **claves admin y researcher** son valores de configuración y se comparan en **tiempo
  constante** (`hmac.compare_digest`).
- En `APP_ENV=production`, el backend **rechaza el arranque** si `ADMIN_API_KEY` o
  `RESEARCHER_API_KEY` toman valores de la lista negra (`change-me`, `admin`, `secret`, …).

## CORS y rate limiting

- CORS restringido a `BACKEND_CORS_ORIGINS`. Actualmente `allow_credentials=True` aunque la
  app no usa cookies (se recomienda `False`).
- Rate limiting por IP (slowapi) en `/sessions`, `/tasting-sessions/public/{token}` y
  `/evaluations/{id}/dialog`. Almacenamiento **en memoria**: no persiste entre reinicios ni
  se comparte entre procesos.

## Protección de datos

- `participant_code` es texto libre: **no introducir datos personales**; informar a los
  participantes.
- Las exportaciones contienen todas las respuestas de los participantes: proteger su
  distribución y acceso.

## Endpoints sensibles

- Administración: todo `tasting-sessions` (salvo el público), `finalize`, `debug/llm`,
  `debug/llm/probe`.
- Exportación: `export/*` (researcher o admin).
- El endpoint raíz `/` y `/docs` (Swagger) están abiertos por defecto.

## Riesgos conocidos y recomendaciones

| Riesgo | Severidad | Recomendación |
|---|---|---|
| Secretos reales en `.env` / `.env.prod` en la carpeta entregada | **Crítica** | Purgar del entregable y **rotar todas las claves** (admin, researcher, contraseña de DB, credencial del proveedor LLM) |
| Sin TLS por defecto (Caddy en `:80`) | **Alta** | Configurar dominio → TLS automático de Caddy |
| Rate limiting casi anulado en producción (`200`/`500`) | **Alta** | Valores restrictivos (`10`/`30`) |
| Clave admin en `sessionStorage` (expuesta a XSS) | Media | Asumir modelo de admin único; mitigar XSS; considerar sesión de servidor |
| Claves estáticas y compartidas, sin roles ni rotación | Media | Documentar rotación; roadmap a autenticación por usuario |
| Swagger `/docs` abierto en producción | Media | `docs_url=None` en producción |
| `allow_credentials=True` sin uso de cookies | Baja | Poner `allow_credentials=False` |
| Código muerto `api.debugLlm` / `VITE_ADMIN_API_KEY` | Baja | Eliminar para evitar embeber la clave en el bundle |
| Health no comprueba la DB | Informativa | Añadir verificación de conexión |

## Checklist de seguridad para producción

- [ ] Rotar `ADMIN_API_KEY`, `RESEARCHER_API_KEY`, `POSTGRES_PASSWORD` y `LLM_API_KEY`.
- [ ] Eliminar `.env` y `.env.prod` de cualquier entregable.
- [ ] Activar TLS (dominio en Caddy).
- [ ] Endurecer `RATE_LIMIT_*`.
- [ ] `docs_url=None` y `allow_credentials=False`.
- [ ] No definir `VITE_ADMIN_API_KEY`.
