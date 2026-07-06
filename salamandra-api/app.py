"""salamandra-api — servicio interno OpenAI-compatible para el modelo local
BSC-LT/salamandra-2b-instruct cargado con transformers sobre CPU.

Este servicio NO es una API pública: se ejecuta dentro de docker-compose y solo es
accesible por la red interna Docker (el backend lo consume en
http://salamandra-api:8001/v1/chat/completions). No expone puertos públicos.

Contrato mínimo compatible con OpenAI:
  - GET  /health
  - GET  /v1/models
  - POST /v1/chat/completions

El modelo se carga EXCLUSIVAMENTE desde una ruta local montada en el contenedor
(SALAMANDRA_MODEL_PATH, por defecto /models/salamandra-2b-instruct) con
local_files_only=True. El contenedor nunca descarga el modelo.
"""
from __future__ import annotations

import hmac
import logging
import os
import time
import uuid
from typing import Any

import torch
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from transformers import AutoModelForCausalLM, AutoTokenizer

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("salamandra-api")

# --- Configuración por entorno ---------------------------------------------
MODEL_PATH = os.environ.get("SALAMANDRA_MODEL_PATH", "/models/salamandra-2b-instruct")
MODEL_ID = os.environ.get("SALAMANDRA_MODEL_ID", "local-salamandra-2b-instruct")
API_KEY = os.environ.get("SALAMANDRA_API_KEY", "")
# Salida por defecto conservadora para CPU + poca RAM (antes 700).
DEFAULT_MAX_NEW_TOKENS = int(os.environ.get("SALAMANDRA_MAX_NEW_TOKENS", "160"))
# Tope duro real de tokens de salida: la generación nunca lo supera.
MAX_NEW_TOKENS_HARD_LIMIT = int(os.environ.get("SALAMANDRA_MAX_NEW_TOKENS_HARD_LIMIT", "200"))
# Truncación de la entrada para acotar memoria/latencia en CPU.
MAX_INPUT_TOKENS = int(os.environ.get("SALAMANDRA_MAX_INPUT_TOKENS", "2048"))
NUM_THREADS = int(os.environ.get("SALAMANDRA_NUM_THREADS", "0") or "0")

# dtype de carga del modelo: auto | float32 | float16 | bfloat16 (por defecto auto).
TORCH_DTYPE = os.environ.get("SALAMANDRA_TORCH_DTYPE", "auto").strip().lower()


def _env_bool(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


# use_cache desactivado por defecto para reducir el pico de RAM en CPU.
USE_CACHE = _env_bool("SALAMANDRA_USE_CACHE", "false")

# Mapeo explícito de dtype. torch.float32 solo aparece aquí (mapeo), nunca como
# dtype fijo obligatorio en from_pretrained.
_DTYPE_MAP = {
    "float32": torch.float32,
    "float16": torch.float16,
    "bfloat16": torch.bfloat16,
}


def _resolve_torch_dtype():
    """Devuelve 'auto' o un torch.dtype según SALAMANDRA_TORCH_DTYPE."""
    if TORCH_DTYPE == "auto":
        return "auto"
    if TORCH_DTYPE in _DTYPE_MAP:
        return _DTYPE_MAP[TORCH_DTYPE]
    logger.warning("SALAMANDRA_TORCH_DTYPE=%r no reconocido; usando 'auto'.", TORCH_DTYPE)
    return "auto"


# Fuerza modo offline: transformers no intentará contactar con Hugging Face Hub.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

if NUM_THREADS > 0:
    torch.set_num_threads(NUM_THREADS)

app = FastAPI(title="salamandra-api (internal)", version="1.0.0")

# Estado global del modelo (se carga en el evento de arranque).
_state: dict[str, Any] = {"tokenizer": None, "model": None, "loaded": False, "error": None}


# --- Autenticación Bearer ---------------------------------------------------
def require_bearer(authorization: str | None = Header(default=None)) -> None:
    """Valida el token Bearer contra SALAMANDRA_API_KEY (comparación en tiempo constante).

    Si SALAMANDRA_API_KEY está vacía (solo recomendable en desarrollo), no se exige token.
    """
    if not API_KEY:
        return
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token or not hmac.compare_digest(token, API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
        )


# --- Esquemas de request/response ------------------------------------------
class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: str
    content: str = ""


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: str = MODEL_ID
    messages: list[ChatMessage] = Field(default_factory=list)
    temperature: float = 0.0
    max_tokens: int | None = None
    # response_format se acepta por compatibilidad pero se ignora: el modelo local
    # no garantiza JSON estructurado; el backend ya fuerza JSON vía el system prompt.
    response_format: Any = None


# --- Carga del modelo -------------------------------------------------------
@app.on_event("startup")
def _load_model() -> None:
    resolved_dtype = _resolve_torch_dtype()
    logger.info(
        "Cargando modelo desde %s (local_files_only=True, CPU, dtype=%s)...",
        MODEL_PATH, TORCH_DTYPE,
    )
    try:
        tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, local_files_only=True)
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_PATH,
            local_files_only=True,
            torch_dtype=resolved_dtype,  # 'auto' por defecto; no se fuerza float32
            low_cpu_mem_usage=True,
        )
        model.eval()
        _state.update(tokenizer=tokenizer, model=model, loaded=True, error=None)
        logger.info("Modelo cargado correctamente.")
    except Exception as exc:  # pragma: no cover - depende del entorno de la VM
        _state.update(loaded=False, error=str(exc))
        logger.exception("No se pudo cargar el modelo: %s", exc)


def _build_prompt(messages: list[ChatMessage]) -> str:
    tokenizer = _state["tokenizer"]
    dicts = [{"role": m.role, "content": m.content} for m in messages]
    chat_template = getattr(tokenizer, "chat_template", None)
    if chat_template:
        return tokenizer.apply_chat_template(
            dicts, tokenize=False, add_generation_prompt=True
        )
    # Fallback textual simple si el tokenizer no trae chat_template.
    parts: list[str] = []
    for m in dicts:
        role = m["role"].lower()
        label = {"system": "Sistema", "user": "Usuario", "assistant": "Asistente"}.get(role, role)
        parts.append(f"{label}: {m['content']}")
    parts.append("Asistente:")
    return "\n".join(parts)


# --- Endpoints --------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {
        "status": "ok" if _state["loaded"] else "loading",
        "model_loaded": _state["loaded"],
        "model": MODEL_ID,
        "model_path": MODEL_PATH,
        "error": _state["error"],
    }


@app.get("/v1/models", dependencies=[Depends(require_bearer)])
def list_models() -> dict:
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_ID,
                "object": "model",
                "created": 0,
                "owned_by": "local",
            }
        ],
    }


@app.post("/v1/chat/completions", dependencies=[Depends(require_bearer)])
def chat_completions(req: ChatCompletionRequest) -> dict:
    if not _state["loaded"]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Model not loaded: {_state['error'] or 'still loading'}",
        )
    if not req.messages:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="messages must not be empty")

    tokenizer = _state["tokenizer"]
    model = _state["model"]

    # Tope duro real de salida: nunca se supera MAX_NEW_TOKENS_HARD_LIMIT.
    requested_max_tokens = int(req.max_tokens or DEFAULT_MAX_NEW_TOKENS)
    max_new_tokens = min(requested_max_tokens, MAX_NEW_TOKENS_HARD_LIMIT)
    do_sample = req.temperature is not None and req.temperature > 0

    try:
        prompt = _build_prompt(req.messages)
        # Truncación de la entrada para acotar memoria/latencia en CPU.
        inputs = tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=MAX_INPUT_TOKENS,
        )
        prompt_tokens = int(inputs["input_ids"].shape[1])

        gen_kwargs: dict[str, Any] = {
            "max_new_tokens": max_new_tokens,
            "do_sample": do_sample,
            "use_cache": USE_CACHE,
            "pad_token_id": tokenizer.pad_token_id
            if tokenizer.pad_token_id is not None
            else tokenizer.eos_token_id,
        }
        if do_sample:
            gen_kwargs["temperature"] = float(req.temperature)

        logger.info(
            "Generando: input_tokens=%d max_new_tokens=%d temperature=%s use_cache=%s dtype=%s",
            prompt_tokens, max_new_tokens, req.temperature, USE_CACHE, TORCH_DTYPE,
        )

        with torch.inference_mode():
            output_ids = model.generate(**inputs, **gen_kwargs)

        generated = output_ids[0][prompt_tokens:]
        completion_tokens = int(generated.shape[0])
        text = tokenizer.decode(generated, skip_special_tokens=True).strip()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error durante la tokenización/generación: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Generation failed: {exc}",
        ) from exc

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
