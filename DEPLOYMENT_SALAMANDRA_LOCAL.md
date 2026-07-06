# Despliegue con Salamandra local (CPU, sin GPU, sin APIs externas)

Guía para desplegar SensIABot / cookie-tasting en una **VM básica de la UPM** usando el
modelo **`BSC-LT/salamandra-2b-instruct`** descargado localmente, cargado con
`transformers` sobre **CPU**, y servido como **servicio interno** `salamandra-api` con una
interfaz **compatible con OpenAI** que el backend ya sabe consumir.

## 1. Qué problema resuelve

El backend ya sabe hablar con proveedores LLM compatibles con OpenAI (por ejemplo Groq).
La UPM **no ofrece VM con GPU**, pero sí tiene una VM básica donde `salamandra-2b-instruct`
funciona sobre CPU. Esta solución sustituye el proveedor externo por un **servicio local
interno**, de modo que:

- No se depende de ninguna **API externa** ni de claves de terceros en producción.
- El modelo se ejecuta **dentro de la red interna Docker**, sin exponerse públicamente.
- El backend no cambia su lógica: sigue usando la interfaz OpenAI-compatible.

## 2. Por qué se descartan Qwen / vLLM / GPU / fine-tuning

- **GPU:** la VM de la UPM no tiene GPU. Todo debe funcionar en CPU.
- **vLLM:** está orientado a GPU y a servir modelos con alto rendimiento; no aporta en CPU
  básica y añade complejidad innecesaria.
- **Qwen:** el modelo indicado y validado por la UPM es Salamandra (modelo del BSC en
  español), no Qwen.
- **Fine-tuning / LoRA:** fuera de alcance; se usa el modelo tal cual, con **reglas
  deterministas** en el backend para robustez.
- **APIs externas (Groq, etc.):** se descartan como solución final por el requisito de no
  depender de servicios externos.

## 3. Qué significa "descargar Salamandra localmente"

El modelo (pesos + tokenizer + config) se descarga **una vez** en el disco de la VM, en:

```
/opt/sensia/models/salamandra-2b-instruct
```

Esa carpeta se monta como **volumen de solo lectura** dentro del contenedor `salamandra-api`
en `/models/salamandra-2b-instruct`. El contenedor **nunca** descarga el modelo: lo carga
con `local_files_only=True` y en modo offline (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`).

## 4. Dónde y cómo se descarga el modelo

Ejecuta el script en la **VM** (Ubuntu), no en tu portátil:

```bash
sudo bash scripts/download_salamandra.sh
```

El script:

1. Crea `/opt/sensia/models`.
2. Instala `huggingface-cli` si falta.
3. Descarga `BSC-LT/salamandra-2b-instruct` en `/opt/sensia/models/salamandra-2b-instruct`.
4. Verifica que la carpeta y `config.json` existen.

## 5. Configurar `.env.prod`

Parte de `.env.example` y ajusta los valores. Bloque relevante (usa claves reales, nunca
los placeholders):

```env
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=http://salamandra-api:8001/v1
LLM_MODEL=local-salamandra-2b-instruct
LLM_API_KEY=<misma-clave-que-SALAMANDRA_API_KEY>

LLM_FALLBACK_ENABLED=true
LLM_RESPONSE_FORMAT_JSON=false
LLM_TIMEOUT_SECONDS=180
LLM_CONNECT_TIMEOUT_SECONDS=10
LLM_MAX_RETRIES=1
LLM_CONTEXT_MODE=minimal
LLM_CONTEXT_MAX_CHARS=2500

SALAMANDRA_API_KEY=<clave-interna-larga-y-aleatoria>
SALAMANDRA_MODEL_PATH=/models/salamandra-2b-instruct
SALAMANDRA_MAX_NEW_TOKENS=700
```

> **Importante:** `LLM_API_KEY` (que envía el backend como Bearer token) debe ser **igual**
> a `SALAMANDRA_API_KEY` (que valida el servicio). Genera la clave con
> `openssl rand -hex 32`. Recuerda cambiar también `ADMIN_API_KEY`, `RESEARCHER_API_KEY` y
> `POSTGRES_PASSWORD`.

## 6. Levantar Docker Compose

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

Servicios: `db`, `backend`, **`salamandra-api`**, `frontend`, `caddy`. El backend depende de
`salamandra-api` con `service_started` (no bloquea el arranque mientras el modelo carga; si
aún no está listo, actúan las reglas como fallback).

Sigue el arranque del modelo:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f salamandra-api
```

## 7. Probar `/health` (servicio interno)

`salamandra-api` no está expuesto públicamente: prueba desde otro contenedor de la red:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec backend \
  curl -s http://salamandra-api:8001/health
```

Respuesta esperada cuando el modelo está cargado:

```json
{"status":"ok","model_loaded":true,"model":"local-salamandra-2b-instruct", "...": "..."}
```

Mientras carga, `status` será `loading` y `model_loaded` `false`.

## 8. Probar `/v1/models`

```bash
# sh -c para que $SALAMANDRA_API_KEY se expanda DENTRO del contenedor backend
# (donde .env.prod ya la ha cargado), no en el shell del host.
docker compose --env-file .env.prod -f docker-compose.prod.yml exec backend sh -c \
  'curl -s http://salamandra-api:8001/v1/models -H "Authorization: Bearer $SALAMANDRA_API_KEY"'
```

## 9. Probar `/v1/chat/completions`

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec backend sh -c '
curl -s http://salamandra-api:8001/v1/chat/completions \
  -H "Authorization: Bearer $SALAMANDRA_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"local-salamandra-2b-instruct\",\"temperature\":0,\"max_tokens\":200,\"messages\":[{\"role\":\"system\",\"content\":\"Devuelve solo JSON válido.\"},{\"role\":\"user\",\"content\":\"El diseño me parece original.\"}]}"'
```

Debe responder con la estructura OpenAI (`choices[0].message.content`).

## 10. Probar que el backend usa Salamandra

El endpoint de diagnóstico del backend hace una llamada **real** al analizador configurado:

```bash
# Config efectiva:
curl -s http://<IP>/api/v1/debug/llm -H "X-Admin-Key: $ADMIN_API_KEY"

# Prueba real (latencia + análisis):
curl -s -X POST http://<IP>/api/v1/debug/llm/probe -H "X-Admin-Key: $ADMIN_API_KEY"
```

En `debug/llm/probe`, `effective_analyzer` debe ser `llm` y `provider` `openai-compatible`.
Si el modelo falla, verás `llm_status: error` y, con fallback activo, `used_fallback: true`.
El panel de administración también lo expone en **Healthcheck → Comprobar LLM real**.

## 11. Si el modelo tarda mucho

- La **primera carga** del modelo en CPU puede tardar **minutos**; la primera inferencia
  también. El `HEALTHCHECK` del contenedor tiene `start_period=300s`.
- Sube `LLM_TIMEOUT_SECONDS` en el backend (p. ej. 180–240) si ves errores de timeout.
- Baja `SALAMANDRA_MAX_NEW_TOKENS` (p. ej. 400–500) y `LLM_CONTEXT_MAX_CHARS` (p. ej. 2000)
  para reducir el tiempo por turno.
- Ajusta `SALAMANDRA_NUM_THREADS` al número de vCPU de la VM.

## 12. Si devuelve JSON inválido

Un modelo 2B en CPU no garantiza JSON perfecto. El backend ya lo gestiona:

- Valida estrictamente la respuesta; si no es JSON válido con las claves esperadas, lanza
  `AnalyzerUnavailableError`.
- Con `LLM_FALLBACK_ENABLED=true`, el backend **cae automáticamente al analizador por
  reglas**, de modo que el participante puede continuar la cata.
- Mantén `LLM_RESPONSE_FORMAT_JSON=false` (el modelo local no soporta `response_format`
  fiable; el JSON se fuerza vía el system prompt).

## 13. Si falta RAM

- Un modelo 2B en float32 necesita del orden de **8–10 GB** de RAM. Asegura suficiente RAM
  o swap en la VM.
- `low_cpu_mem_usage=True` ya está activado en la carga.
- Si el contenedor muere por OOM, reduce la carga de trabajo (menos tokens/contexto) o
  aumenta la RAM de la VM. En última instancia, el fallback por reglas mantiene el servicio.

## 14. Qué papel siguen teniendo las reglas deterministas

Las reglas del backend (`app/services/analyzer/rules.py` + `modality_metadata.py`) siguen
siendo esenciales:

- Son el **fallback** cuando el LLM falla, va lento o devuelve JSON inválido.
- Aseguran la **clasificación por modalidad** (incluido el refuerzo de ASPECTO para diseño,
  apariencia, forma, color, decoración, etc.).
- El **flujo conversacional lo decide siempre el backend**: el LLM solo extrae evidencia.

## 15. Limitaciones en CPU

- Latencia por turno notablemente mayor que con Groq/GPU.
- Calidad de extracción de un 2B inferior a modelos grandes; por eso conviven con reglas.
- Sin concurrencia alta: la inferencia en CPU es secuencial y costosa.
- Recomendado para validación de TFG y uso moderado, no para carga masiva simultánea.
