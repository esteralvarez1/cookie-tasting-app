# API

Todas las rutas cuelgan del prefijo **`/api/v1`**. El formato de respuesta correcto es
siempre `{ "success": true, "data": ..., "message": "..." }`. Los errores se devuelven como
`HTTPException` con el campo `detail`.

## Autenticación

| Cabecera | Uso | Almacenamiento |
|---|---|---|
| `X-Session-Token` | Participante: operar sobre su sesión y evaluaciones | Hash SHA-256 en DB, con TTL (`SESSION_TOKEN_TTL_HOURS`) |
| `X-Researcher-Key` | Exportaciones | Valor de configuración |
| `X-Admin-Key` | Administración y depuración | Valor de configuración |

La comparación de claves es en tiempo constante (`hmac.compare_digest`). El token de sesión
expira según el TTL; pasado ese tiempo se responde `401` con `detail = "session_expired"`.

## Endpoints

| Método | Ruta | Auth | Función |
|---|---|---|---|
| GET | `/` | Pública | Metadatos de la API |
| GET | `/health` | Pública | Healthcheck (no comprueba la DB) |
| GET | `/debug/llm` | Admin | Proveedor, modelo y versión de prompt activos |
| POST | `/debug/llm/probe` | Admin | Llamada real al LLM y latencia |
| POST | `/tasting-sessions` | Admin | Crear sesión de cata |
| GET | `/tasting-sessions` | Admin | Listar sesiones de cata |
| POST | `/tasting-sessions/{id}/close` | Admin | Cerrar una sesión |
| DELETE | `/tasting-sessions/{id}` | Admin | Borrar una sesión y todos sus datos (cascada) |
| GET | `/tasting-sessions/public/{token}` | Pública (rate-limit) | Datos públicos para el participante |
| POST | `/sessions` | Pública (rate-limit) | Crear o recuperar sesión de participante |
| GET | `/sessions/{id}/next-step` | Session token | Calcular el siguiente paso |
| POST | `/sessions/{id}/survey` | Session token | **Legacy**: encuesta global (no usado por el frontend) |
| POST | `/evaluations` | Session token | Crear o recuperar la evaluación de una muestra |
| POST | `/evaluations/{id}/dialog` | Session token (rate-limit) | Enviar un turno del participante |
| GET | `/evaluations/{id}` | Session token | Estado de la evaluación |
| GET | `/evaluations/{id}/conversation` | Session token | Histórico de turnos |
| GET | `/evaluations/{id}/analysis` | Session token | Último análisis |
| POST | `/evaluations/{id}/final-comment` | Session token | Guardar el comentario por muestra |
| POST | `/evaluations/{id}/finalize` | Admin | Cierre manual de una evaluación |
| GET | `/export/conversations` | Researcher/Admin | Exportar conversación completa |
| GET | `/export/user-responses` | Researcher/Admin | Exportar solo respuestas del usuario |
| GET | `/export/structured` | Researcher/Admin | Exportar clasificación estructurada |

## Parámetros de exportación

Filtro obligatorio: **al menos uno** de `session_id`, `participant_code`,
`tasting_session_config_id` (si no → `400`).

```
format=csv|json                    # conversations, user-responses
format=csv|json|xlsx               # structured
```

`structured` incluye únicamente evaluaciones en estado `COMPLETED`. El nombre del archivo se
genera a partir del título de la sesión y la fecha, y se transmite en la cabecera
`Content-Disposition`.

## Ejemplo de request/response

Turno conversacional:

```http
POST /api/v1/evaluations/{evaluation_id}/dialog
X-Session-Token: <token>
Content-Type: application/json

{ "user_message": "Es crujiente y dulce, me gusta" }
```

```json
{
  "success": true,
  "data": {
    "evaluation_id": "…",
    "current_state": "MODALITY_QUESTION",
    "current_modality": "OLOR",
    "bot_message": "Ahora cuéntame cómo es el olor de la galleta y qué te parece.",
    "analysis": {
      "analysis_scope": "INTERMEDIATE",
      "is_vague": false,
      "has_comparison": false,
      "next_action": "ASK_MODALITY_OLOR",
      "modalities": {
        "ASPECTO": { "mention_text": "", "descriptor_text": "", "valuation_text": "", "is_complete": false },
        "TEXTURA": { "mention_text": "Es crujiente", "descriptor_text": "crujiente", "valuation_text": "me gusta", "is_complete": true }
      }
    },
    "next_step": null,
    "turns": [ … ]
  },
  "message": "Turno procesado correctamente"
}
```

Crear sesión de participante:

```http
POST /api/v1/sessions
Content-Type: application/json

{ "participant_code": "P001", "tasting_session_id": "<config_id>" }
```

Devuelve `session_token`, `session_token_expires_at`, `completed_sample_codes` y
`pending_sample_codes`. Si ya existía una sesión para ese participante y esa configuración,
la **recupera** y emite un token nuevo.

## Errores comunes

| Código | Situación |
|---|---|
| 400 | Falta filtro de exportación / el código de muestra no pertenece a la sesión |
| 401 | Token de participante ausente, inválido o expirado (`session_expired`) / clave admin/researcher incorrecta |
| 403 | La sesión de cata está cerrada |
| 404 | Sesión, evaluación o token público inexistente |
| 409 | Conflicto de estado (evaluación ya completada, sesión completada, sesión ya cerrada, límite de muestras) |
| 429 | Límite de tasa superado |

## Seguridad de la API

- Los endpoints de participante exigen `X-Session-Token` válido y no expirado.
- Las operaciones administrativas y de depuración exigen `X-Admin-Key`.
- Las exportaciones aceptan `X-Researcher-Key` o `X-Admin-Key`.
- Rate limiting por IP en los endpoints sensibles (`/sessions`, `/tasting-sessions/public`,
  `/evaluations/{id}/dialog`). El almacenamiento es en memoria (no persiste entre reinicios).
