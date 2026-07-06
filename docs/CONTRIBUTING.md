# Contribuir

## Convenciones de código

**Backend (Python 3.11)**
- `from __future__ import annotations` y *type hints* en todo el código.
- Pydantic para validación de entrada (`schemas/`) y de la salida del LLM.
- La lógica de negocio vive en `services/`; los routers (`api/routes/`) solo orquestan HTTP
  y transacciones (`commit`/`rollback` en el handler, nunca en los servicios).
- Comentarios en español, alineados con el estilo existente (denso y explicativo en las
  zonas críticas: `dialogue.py`, `security.py`, migraciones).
- Cualquier cambio de esquema requiere una **migración Alembic** encadenada a la anterior.

**Frontend (TypeScript / React 18)**
- Componentes funcionales con hooks; sin librería de estado (solo `useState`/`useEffect`).
- El cliente de API centraliza `fetch` y la clasificación de errores (`ApiError`).
- No introducir variables `VITE_*` con secretos: se embeben en el bundle.

## Estructura de ramas

- `main`: rama estable.
- `revision-final` (u otras de trabajo): desarrollo previo a la entrega.
- Ramas de característica: `feat/…`, `fix/…`, `docs/…`.

## Cómo ejecutar las pruebas

```bash
cd backend
pip install -r requirements.txt -r requirements-test.txt
export PYTHONPATH=$(pwd)
pytest -q
# o ./run_tests.sh en Docker
```

Verificación de tipos del frontend:

```bash
cd frontend && npm run typecheck
```

## Cómo proponer cambios

1. Crear una rama desde `main`.
2. Implementar el cambio con su(s) test(s); si tocas el esquema, añade la migración.
3. Ejecutar `pytest -q` y `npm run typecheck` en verde.
4. Actualizar la documentación afectada en `docs/` y el `CHANGELOG.md`.
5. Abrir un *merge/pull request* describiendo el cambio y su motivación.

## Revisión antes de merge

- [ ] Tests en verde (backend) y `typecheck` en verde (frontend).
- [ ] Migración incluida y encadenada si cambia el esquema.
- [ ] Sin secretos ni ficheros generados (`.env`, `venv/`, `__pycache__/`, `.DS_Store`).
- [ ] Documentación y `CHANGELOG.md` actualizados.
- [ ] Sin código muerto ni endpoints/pantallas sin documentar.
