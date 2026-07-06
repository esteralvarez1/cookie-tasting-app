# Changelog

Formato basado en *Keep a Changelog*. Versionado según `version` de la app
(`backend` y `frontend/package.json`).

## [2.0.0] — Versión actual

### Añadido
- Sesiones de cata configurables por el administrador (`TastingSessionConfig`) con
  `public_token`, título, códigos de muestra y `final_redirect_url`.
- Comentario por muestra (`POST /evaluations/{id}/final-comment`) sustituyendo la encuesta
  global de sesión.
- Exportación de respuestas de usuario y exportación estructurada en **XLSX** (18 columnas
  canónicas), además de CSV y JSON.
- Preguntas por modalidad adaptativas (distinguen mención, descriptor y valoración).
- Cálculo **determinista** de vaguedad y comparación en el backend; el LLM ya no decide
  ninguna acción de flujo.
- Análisis FINAL como **consolidación** de datos ya validados (sin re-análisis global).
- Almacenamiento del `session_token` mediante hash SHA-256 y TTL de sesión.
- Rate limiting por IP en endpoints sensibles.
- `next_turn_index` para evitar recalcular `max(turn_index)` en cada inserción.
- Trigger de base de datos que impide superar `total_samples`.
- Borrado de sesiones de cata en cascada (`DELETE /tasting-sessions/{id}`).
- Suite de tests de backend (flujo, reglas, seguridad, exportaciones, validación del LLM).
- Despliegue con Docker Compose + Caddy + Nginx (`docker-compose.prod.yml`).

### Cambiado
- El endpoint `dialog` devuelve el snapshot completo de evaluación, análisis y conversación
  para reducir llamadas del frontend.
- Ruta del participante servida en `/cata` (el `/` redirige al panel admin).

### Obsoleto (legacy, conservado por compatibilidad)
- `POST /sessions/{id}/survey` y la entidad `FinalSurveyResponse`: el flujo actual usa el
  comentario por muestra.

### Migraciones de esquema
- 0001 esquema inicial · 0002 hash de token + limpieza · 0003 intentos por modalidad ·
  0004 elimina `mentioned_flag` · 0005 trigger de máximo de evaluaciones ·
  0006 `tasting_session_configs` + comentario por muestra · 0007 `final_redirect_url` ·
  0008 FK `source_turn_id` con `ON DELETE SET NULL`.

## Cambios pendientes / mejoras futuras

- **Seguridad de producción:** activar TLS, endurecer rate limits, rotar claves, cerrar
  Swagger, `allow_credentials=False`.
- **Calidad:** versionar `frontend/public/logo_final.png`; eliminar código muerto
  (`api.debugLlm`, `VITE_ADMIN_API_KEY`).
- **Mantenibilidad:** dividir `services/dialogue.py` en un paquete.
- **Tests:** cobertura de frontend y validación de migraciones en CI.
- **Datos:** decidir sobre la retención o eliminación del endpoint/tabla `survey` legacy.
- **Roadmap** (según `DEPLOYMENT_VM.md`): integración de modelos locales vía `transformers`
  (no incluida en esta versión).
