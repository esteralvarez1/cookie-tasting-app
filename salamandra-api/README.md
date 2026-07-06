# salamandra-api (servicio interno)

Microservicio **interno** que sirve el modelo local `BSC-LT/salamandra-2b-instruct`
mediante `transformers` sobre **CPU**, exponiendo una interfaz **compatible con OpenAI**
que el backend ya sabe consumir.

> **No es una API pública.** Se ejecuta dentro de `docker-compose` y solo es accesible por
> la red interna Docker. El backend lo consume en `http://salamandra-api:8001/v1`.
> No se publica por Caddy, Nginx ni con `ports:`.

## Endpoints

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/health` | No | Estado del servicio y si el modelo está cargado |
| GET | `/v1/models` | Bearer | Lista el modelo local disponible |
| POST | `/v1/chat/completions` | Bearer | Completions de chat (formato OpenAI) |

Autenticación: cabecera `Authorization: Bearer <SALAMANDRA_API_KEY>`. Si
`SALAMANDRA_API_KEY` está vacía, no se exige token (solo para desarrollo local).

## Variables de entorno

| Variable | Por defecto | Descripción |
|---|---|---|
| `SALAMANDRA_MODEL_PATH` | `/models/salamandra-2b-instruct` | Ruta local montada del modelo |
| `SALAMANDRA_API_KEY` | *(vacía)* | Token Bearer interno |
| `SALAMANDRA_MODEL_ID` | `local-salamandra-2b-instruct` | Nombre reportado del modelo |
| `SALAMANDRA_MAX_NEW_TOKENS` | `700` | Tokens máximos generados si el request no fija `max_tokens` |
| `SALAMANDRA_NUM_THREADS` | `0` (auto) | Hilos de CPU para PyTorch |
| `HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE` | `1` | Fuerzan modo offline |

## Carga del modelo

El modelo **no se descarga dentro del contenedor**. Se monta como volumen de solo
lectura y se carga con `local_files_only=True` (float32, CPU). Descárgalo antes en la VM
con [`../scripts/download_salamandra.sh`](../scripts/download_salamandra.sh).

## Prompt

El servicio construye el prompt a partir de los mensajes `system`/`user`/`assistant`.
Si el tokenizer trae `chat_template`, usa `tokenizer.apply_chat_template`; si no,
construye un prompt textual simple.

## Ejecución (dentro de docker-compose.prod.yml)

Se levanta junto con el resto de servicios:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build salamandra-api
```

Guía completa en [`../DEPLOYMENT_SALAMANDRA_LOCAL.md`](../DEPLOYMENT_SALAMANDRA_LOCAL.md).

## Limitaciones en CPU

- La primera carga del modelo puede tardar **minutos**; la primera inferencia también.
- La latencia por turno en CPU es alta; ajusta `LLM_TIMEOUT_SECONDS` en el backend.
- Un modelo 2B en CPU no garantiza JSON perfecto: el backend mantiene **reglas
  deterministas y fallback** como red de seguridad.
