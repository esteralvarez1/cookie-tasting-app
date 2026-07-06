#!/usr/bin/env bash
#
# Run the backend test suite without a local Python 3.11 / Postgres setup.
#
# It uses Docker to:
#   1. ensure the test database exists on the dev Postgres (published on :5434);
#   2. run pytest inside a python:3.11 container against that database.
#
# Requirements: Docker running, and the dev Postgres up (docker compose up -d db),
# i.e. a Postgres reachable on host port 5434 with postgres/postgres.
#
# Usage:
#   ./run_tests.sh                          # full suite
#   ./run_tests.sh -q tests/test_exports.py # forward any pytest args
#   PG_PORT=5434 ./run_tests.sh -k valuation # override the host Postgres port
#
set -euo pipefail

cd "$(dirname "$0")"

PG_PORT="${PG_PORT:-5434}"
PG_USER="${PG_USER:-postgres}"
PG_PASSWORD="${PG_PASSWORD:-postgres}"
TEST_DB="${TEST_DB:-cookie_tasting_test}"
PY_IMAGE="${PY_IMAGE:-python:3.11-slim}"
# Host alias usable from inside a container (works on Docker Desktop; the
# --add-host flag below makes it work on Linux too).
DB_HOST="host.docker.internal"

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker no está disponible o el daemon no está corriendo." >&2
  exit 1
fi

echo "==> Asegurando la base de datos de test '${TEST_DB}' en :${PG_PORT}"
docker run --rm --add-host=host.docker.internal:host-gateway \
  -e PGPASSWORD="${PG_PASSWORD}" \
  postgres:16 sh -c "
    psql -h ${DB_HOST} -p ${PG_PORT} -U ${PG_USER} -tc \"SELECT 1 FROM pg_database WHERE datname='${TEST_DB}'\" \
      | grep -q 1 || psql -h ${DB_HOST} -p ${PG_PORT} -U ${PG_USER} -c \"CREATE DATABASE ${TEST_DB}\"
  "

echo "==> Ejecutando pytest en ${PY_IMAGE}"
docker run --rm --add-host=host.docker.internal:host-gateway \
  -v "$PWD":/app -w /app \
  -e DATABASE_URL="postgresql+psycopg://${PG_USER}:${PG_PASSWORD}@${DB_HOST}:${PG_PORT}/${TEST_DB}" \
  -e APP_ENV=development \
  -e LLM_PROVIDER=rules \
  "${PY_IMAGE}" sh -c "
    pip install --quiet --root-user-action=ignore --disable-pip-version-check -r requirements.txt -r requirements-test.txt &&
    python -m pytest ${*:-}
  "
