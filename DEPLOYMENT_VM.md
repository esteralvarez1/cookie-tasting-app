# Despliegue en VM con Docker Compose

## 1. Objetivo del documento

Este documento describe cómo desplegar la versión funcional actual de la aplicación de cata de galletas en una VM de la universidad usando Docker Compose.

Esta versión utiliza **Groq** como proveedor LLM externo para validar el flujo completo de la aplicación: creación de sesiones, conversación con participantes y exportación de resultados.

La integración con modelos locales mediante `transformers` se realizará en una fase posterior y no está incluida en este documento.

---

## 2. Arquitectura de despliegue

```
Usuario
  ↓
http://IP-DE-LA-VM
  ↓
Caddy  (proxy inverso, puerto 80)
  ├── /api/* → backend FastAPI:8000
  └── resto  → frontend Nginx:80

backend
  ├── PostgreSQL (red interna Docker)
  └── Groq API (HTTPS saliente)
```

| Servicio   | Descripción |
|------------|-------------|
| `db`       | Base de datos PostgreSQL 16. Datos persistentes en volumen Docker. |
| `backend`  | API FastAPI. Ejecuta migraciones Alembic al arrancar. Puerto interno 8000. |
| `frontend` | Interfaz React compilada con Vite, servida por Nginx. Puerto interno 80. |
| `caddy`    | Proxy inverso público. Recibe tráfico en el puerto 80 y enruta al servicio correspondiente. |
| Groq       | Proveedor LLM externo. No es un contenedor: se llama desde el backend mediante HTTPS a `api.groq.com`. |

---

## 3. Requisitos de la VM

**Sistema operativo:** Ubuntu 22.04 LTS.

**Software necesario:**
- Docker (versión 24 o superior)
- Docker Compose (incluido en Docker Desktop o como plugin `docker compose`)

**Puertos que deben estar abiertos en el firewall de la VM:**

| Puerto | Uso |
|--------|-----|
| 22     | SSH |
| 80     | Acceso HTTP público (Caddy) |
| 443    | HTTPS público (solo si se configura dominio) |

Los puertos 5432 (PostgreSQL), 8000 (backend) y 5173 (dev frontend) **no deben exponerse** públicamente.

**Acceso a Internet:**
La VM necesita salida HTTPS para que el backend pueda llamar a la API de Groq (`api.groq.com:443`).

**No es necesario instalar Python ni Node.js** en la VM. Ambos van dentro de los contenedores Docker.

---

## 4. Archivos relevantes del despliegue

| Archivo | Descripción |
|---------|-------------|
| `backend/Dockerfile` | Imagen del backend. Usa `python:3.11-slim`, instala dependencias y ejecuta `alembic upgrade head` antes de Uvicorn. |
| `frontend/Dockerfile` | Imagen del frontend. Build multi-stage: Node 20 compila el proyecto, Nginx sirve el resultado. |
| `frontend/nginx.conf` | Configuración de Nginx para la SPA. Incluye `try_files` para que las rutas internas de React funcionen. |
| `docker-compose.prod.yml` | Orquestación de los cuatro servicios en producción. |
| `Caddyfile` | Configuración del proxy inverso Caddy. |
| `.env.example` | Plantilla de variables de entorno sin secretos reales. **Sí se sube al repositorio.** |
| `.env.prod` | Variables de entorno con valores reales para producción. **No debe subirse a GitHub.** |

---

## 5. Clonar el repositorio

```bash
git clone https://github.com/esteralvarez1/cookie-tasting-app.git
cd cookie-tasting-app
```

Si la URL del repositorio es diferente, sustitúyela en el comando anterior.

---

## 6. Crear el archivo `.env.prod`

El archivo `.env.prod` no está en el repositorio porque contiene secretos reales. Hay que crearlo a partir de la plantilla:

```bash
cp .env.example .env.prod
nano .env.prod
```

### Variables que deben modificarse obligatoriamente

```env
PUBLIC_APP_URL=http://IP-DE-LA-VM        # IP real de la VM
BACKEND_CORS_ORIGINS=http://IP-DE-LA-VM  # Debe coincidir con PUBLIC_APP_URL

POSTGRES_PASSWORD=CAMBIAR                # Contraseña segura para PostgreSQL
ADMIN_API_KEY=CAMBIAR                    # Clave para el panel de administración
RESEARCHER_API_KEY=CAMBIAR               # Clave para endpoints de investigador
LLM_API_KEY=CAMBIAR                      # Clave API de Groq
```

Para generar claves aleatorias seguras:

```bash
openssl rand -hex 32
```

### Plantilla completa de `.env.prod`

```env
# ─── Entorno ─────────────────────────────────────────────────────────────────
APP_ENV=production
LOG_LEVEL=INFO

# URL pública de la aplicación tal como la ve el navegador.
# Cambia por la IP real de la VM o por el dominio cuando lo tengas.
PUBLIC_APP_URL=http://IP-DE-LA-VM

# ─── PostgreSQL ───────────────────────────────────────────────────────────────
POSTGRES_DB=cookie_tasting
POSTGRES_USER=cookie_user
POSTGRES_PASSWORD=CHANGE_ME_LONG_RANDOM_PASSWORD

# ─── Seguridad / Administración ───────────────────────────────────────────────
ADMIN_API_KEY=CHANGE_ME_LONG_RANDOM_ADMIN_KEY
RESEARCHER_API_KEY=CHANGE_ME_LONG_RANDOM_RESEARCHER_KEY
BACKEND_CORS_ORIGINS=http://IP-DE-LA-VM

# ─── LLM (Groq) ───────────────────────────────────────────────────────────────
LLM_PROVIDER=groq
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=CHANGE_ME_GROQ_API_KEY
LLM_MODEL=llama-3.1-8b-instant

LLM_TIMEOUT_SECONDS=120
LLM_CONNECT_TIMEOUT_SECONDS=10
LLM_MAX_RETRIES=1
LLM_RESPONSE_FORMAT_JSON=true
LLM_CONTEXT_MAX_CHARS=3000
LLM_CONTEXT_MODE=minimal
LLM_FALLBACK_TO_RULES=false

# ─── Sesiones ─────────────────────────────────────────────────────────────────
SESSION_TOKEN_TTL_HOURS=24

# ─── Flujo conversacional ─────────────────────────────────────────────────────
MAX_VAGUE_RETRIES=1
MAX_COMPARISON_RETRIES=2
MAX_MODALITY_ATTEMPTS=2

# ─── Rate limiting ────────────────────────────────────────────────────────────
RATE_LIMIT_SESSIONS_PER_MINUTE=200
RATE_LIMIT_DIALOG_PER_MINUTE=500
```

`PUBLIC_APP_URL` y `BACKEND_CORS_ORIGINS` deben coincidir exactamente con la IP o dominio real desde el que se accederá a la aplicación.

---

## 7. Levantar la aplicación

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

Este comando:

1. Construye la imagen del backend (`backend/Dockerfile`).
2. Construye la imagen del frontend (`frontend/Dockerfile`), pasando `VITE_API_BASE_URL` al compilador de Vite.
3. Levanta el contenedor de PostgreSQL.
4. Arranca el backend: ejecuta `alembic upgrade head` (migraciones) y luego Uvicorn.
5. Arranca Nginx con el frontend compilado.
6. Arranca Caddy como proxy inverso en el puerto 80.

El primer arranque puede tardar varios minutos porque Docker descarga las imágenes base y compila el frontend.

---

## 8. Comprobar estado de contenedores

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
```

Todos los servicios deben aparecer en estado `running` (o `healthy` para `db`):

```
db        running (healthy)
backend   running
frontend  running
caddy     running
```

Si algún servicio aparece como `exited`, revisar sus logs (ver sección 13).

---

## 9. Probar backend

```bash
curl http://IP-DE-LA-VM/api/v1/health
```

Respuesta esperada:

```json
{"status": "ok"}
```

---

## 10. Probar conexión con Groq

```bash
curl -X POST "http://IP-DE-LA-VM/api/v1/debug/llm/probe" \
  -H "X-Admin-Key: ADMIN_API_KEY_REAL"
```

Sustituye `ADMIN_API_KEY_REAL` por el valor configurado en `.env.prod`.

Una respuesta con `"llm_status": "ok"` confirma que el backend se comunica correctamente con Groq.

---

## 11. Acceder al panel de administración

```
http://IP-DE-LA-VM/admin
```

Introduce la clave configurada en `ADMIN_API_KEY` cuando se solicite.

Desde el panel de administración se pueden:
- Ver y gestionar sesiones de cata.
- Crear nuevas sesiones y añadir muestras.
- Generar el enlace público para participantes.
- Exportar resultados.

---

## 12. Probar flujo completo

1. Entrar en `http://IP-DE-LA-VM/admin` e iniciar sesión con `ADMIN_API_KEY`.
2. Crear una nueva sesión de cata.
3. Añadir los códigos de las muestras.
4. Copiar el enlace público generado para participantes.
5. Abrir el enlace como participante en otro navegador o pestaña.
6. Introducir el identificador del participante.
7. Completar la conversación de la primera muestra.
8. Guardar el comentario final de la muestra.
9. Repetir para todas las muestras de la sesión.
10. Volver al panel admin y exportar los resultados.

---

## 13. Ver logs

Todos los servicios:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f
```

Solo el backend:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f backend
```

Solo Caddy:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f caddy
```

---

## 14. Parar la aplicación

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml down
```

Este comando detiene y elimina los contenedores, pero **no borra los datos de PostgreSQL** porque están en el volumen persistente `postgres_data`.

Para parar y borrar también los volúmenes (elimina todos los datos):

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml down -v
```

---

## 15. Actualizar la aplicación

```bash
git pull
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

Docker reconstruye solo las imágenes que han cambiado. Las migraciones de Alembic se ejecutan automáticamente al reiniciar el backend.

---

## 16. Backup de PostgreSQL

```bash
mkdir -p backups

docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T db \
  pg_dump -U cookie_user cookie_tasting \
  > backups/cookie_tasting_$(date +%Y-%m-%d_%H-%M).sql
```

El backup se guarda en la carpeta `backups/` con la fecha y hora en el nombre.

Listar backups disponibles:

```bash
ls -lh backups/
```

---

## 17. Restaurar backup

```bash
cat backups/NOMBRE_BACKUP.sql | \
  docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T db \
  psql -U cookie_user cookie_tasting
```

Sustituye `NOMBRE_BACKUP.sql` por el nombre real del archivo de backup.

---

## 18. Errores comunes

### El frontend no conecta con el backend

El frontend se compiló con una `VITE_API_BASE_URL` incorrecta. Revisar en `.env.prod`:

```env
PUBLIC_APP_URL=http://IP-DE-LA-VM
```

Reconstruir el frontend:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build frontend caddy
```

### Error de CORS

El backend rechaza peticiones del frontend porque los orígenes no coinciden. Revisar:

```env
BACKEND_CORS_ORIGINS=http://IP-DE-LA-VM
```

Debe coincidir exactamente con la URL desde la que accede el navegador, incluyendo el protocolo (`http://` o `https://`) y sin barra final.

### El backend no arranca (error en logs)

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f backend
```

Causas frecuentes:
- `ADMIN_API_KEY` o `RESEARCHER_API_KEY` tienen un valor inseguro (`change-me`, `admin`, etc.). El backend lo rechaza al arrancar en `APP_ENV=production`.
- `DATABASE_URL` no es alcanzable. Esperar a que `db` esté `healthy` antes de que arranque el backend (gestionado automáticamente por el `healthcheck` del compose).

### Error con Groq

Revisar en `.env.prod`:

```env
LLM_API_KEY=...        # Clave válida de Groq
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=llama-3.1-8b-instant
```

Probar el endpoint de diagnóstico:

```bash
curl -X POST "http://IP-DE-LA-VM/api/v1/debug/llm/probe" \
  -H "X-Admin-Key: ADMIN_API_KEY_REAL"
```

### Puerto 80 ocupado

Comprobar si hay otro servicio usando el puerto 80 en la VM:

```bash
sudo ss -tlnp | grep :80
```

Detener el servicio que lo ocupe (por ejemplo Apache o un Nginx nativo) antes de levantar Docker Compose.

---

## 19. Seguridad

- **No subir `.env.prod` a GitHub.** Está excluido por `.gitignore`. Comprobar antes de cualquier `git push`.
- **No exponer PostgreSQL públicamente.** El puerto 5432 solo debe ser accesible dentro de la red Docker interna.
- **No exponer el puerto 8000 públicamente.** El backend solo debe recibir tráfico a través de Caddy.
- **No usar claves por defecto en producción.** El backend rechaza el arranque si `ADMIN_API_KEY` o `RESEARCHER_API_KEY` tienen valores como `change-me`.
- Cambiar siempre `ADMIN_API_KEY`, `RESEARCHER_API_KEY` y `POSTGRES_PASSWORD` por valores aleatorios generados con `openssl rand -hex 32`.
- La clave de Groq debe configurarse exclusivamente en `.env.prod`, nunca en el código ni en variables `VITE_`.
- **No añadir `VITE_ADMIN_API_KEY` como variable de build.** Cualquier variable `VITE_*` queda embebida en el bundle JavaScript y es visible para cualquier usuario del navegador.

---

## 20. Futura integración con modelos locales

Esta versión utiliza Groq para validar el flujo funcional completo. En una fase posterior se podrá sustituir el proveedor LLM por un servicio de inferencia local basado en `transformers` (por ejemplo, un modelo ejecutado con `vLLM` o `Ollama`).

Para ello bastará con:
- Añadir un nuevo servicio de inferencia en `docker-compose.prod.yml`.
- Actualizar en `.env.prod` las variables `LLM_PROVIDER`, `LLM_BASE_URL` y `LLM_MODEL` para apuntar al servicio interno.
- No será necesario modificar el backend ni el frontend.

Esta fase queda pendiente para después de validar el flujo completo con Groq.
