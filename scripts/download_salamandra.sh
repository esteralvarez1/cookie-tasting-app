#!/usr/bin/env bash
#
# Descarga BSC-LT/salamandra-2b-instruct en la VM (Ubuntu 24.04 / Python 3.12) para
# servirlo localmente con el servicio interno salamandra-api.
#
# Robusto y compatible con PEP 668 ("externally-managed-environment"):
#   - NO instala paquetes en el Python global del sistema.
#   - NO usa herramientas de línea de comandos de Hugging Face; solo la API de Python.
#   - Descarga el modelo con la API de Python: snapshot_download de huggingface_hub.
#
# Ejecutar SIN sudo:
#   bash scripts/download_salamandra.sh
#
# sudo se usa únicamente (si hace falta) para crear /opt/sensia y ajustar su propietario;
# nunca para instalar paquetes Python ni para descargar el modelo.
#
set -Eeuo pipefail

# --- Rutas y modelo (sobrescribibles por entorno, con estos valores por defecto) -----
SALAMANDRA_HF_MODEL_ID="${SALAMANDRA_HF_MODEL_ID:-BSC-LT/salamandra-2b-instruct}"
SENSIA_BASE_DIR="${SENSIA_BASE_DIR:-/opt/sensia}"
SENSIA_MODELS_DIR="${SENSIA_MODELS_DIR:-/opt/sensia/models}"
SALAMANDRA_MODEL_DIR="${SALAMANDRA_MODEL_DIR:-/opt/sensia/models/salamandra-2b-instruct}"
HF_DOWNLOAD_VENV="${HF_DOWNLOAD_VENV:-/opt/sensia/hf-download-env}"

VENV_DIR="${HF_DOWNLOAD_VENV}"
DEST_DIR="${SALAMANDRA_MODEL_DIR}"
MODEL_ID="${SALAMANDRA_HF_MODEL_ID}"

# --- Utilidades de mensajes -------------------------------------------------
info()  { echo "==> $*"; }
warn()  { echo "ADVERTENCIA: $*" >&2; }
error() { echo "ERROR: $*" >&2; exit 1; }

# El modelo solo se considera COMPLETO si existen ambas cosas:
#   1) config.json
#   2) al menos un fichero de pesos (*.safetensors o *.bin)
# Una carpeta vacía o con descarga parcial NO cuenta como válida.
model_is_complete() {
  [ -f "${DEST_DIR}/config.json" ] || return 1
  find "${DEST_DIR}" -maxdepth 2 -type f \
    \( -name '*.safetensors' -o -name '*.bin' \) 2>/dev/null | grep -q . || return 1
  return 0
}

# --- Limpieza del fichero temporal Python -----------------------------------
TMP_SCRIPT=""
cleanup() { [ -n "${TMP_SCRIPT}" ] && rm -f "${TMP_SCRIPT}" || true; }
trap cleanup EXIT

# --- 1) No ejecutar como root / con sudo ------------------------------------
if [ "$(id -u)" -eq 0 ]; then
  error "No ejecutes este script con sudo. Ejecuta: bash scripts/download_salamandra.sh"
fi

CURRENT_USER="$(id -un)"
CURRENT_GROUP="$(id -gn)"

info "Modelo:           ${MODEL_ID}"
info "Destino:          ${DEST_DIR}"
info "Entorno virtual:  ${VENV_DIR}"
info "Usuario:          ${CURRENT_USER}:${CURRENT_GROUP}"

# --- Comprobación previa: ¿ya está el modelo descargado y completo? ----------
if model_is_complete; then
  info "El modelo ya está descargado y completo en ${DEST_DIR}. Nada que hacer."
  du -sh "${DEST_DIR}"
  exit 0
fi
if [ -d "${DEST_DIR}" ] && [ -n "$(ls -A "${DEST_DIR}" 2>/dev/null || true)" ]; then
  echo "Modelo incompleto o descarga parcial detectada. Se continuará la descarga."
fi

# --- 2) Comprobar dependencias del sistema ----------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  error "python3 no está instalado.
Instálalo con:  sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
fi

# Comprueba que se puede crear un entorno virtual (módulo venv + ensurepip).
if ! python3 -c "import venv, ensurepip" >/dev/null 2>&1; then
  error "Falta el soporte de entornos virtuales de Python.
Instálalo con:  sudo apt update && sudo apt install -y python3-venv"
fi

# --- 3) Crear /opt/sensia y /opt/sensia/models (idempotente; sudo solo aquí) --
if [ ! -d "${SENSIA_MODELS_DIR}" ] || [ ! -w "${SENSIA_BASE_DIR}" ]; then
  info "Creando ${SENSIA_MODELS_DIR} y asignando propietario a ${CURRENT_USER} (requiere sudo)"
  if ! command -v sudo >/dev/null 2>&1; then
    error "Se necesita sudo para crear ${SENSIA_BASE_DIR}, pero 'sudo' no está disponible.
Crea el directorio manualmente y dale permisos a tu usuario:
  mkdir -p ${SENSIA_MODELS_DIR} && chown -R ${CURRENT_USER}:${CURRENT_GROUP} ${SENSIA_BASE_DIR}"
  fi
  sudo mkdir -p "${SENSIA_MODELS_DIR}"
  sudo chown -R "${CURRENT_USER}:${CURRENT_GROUP}" "${SENSIA_BASE_DIR}"
else
  info "${SENSIA_MODELS_DIR} ya existe y es escribible. No se necesita sudo."
fi

# A partir de aquí, todo debe ser escribible por el usuario actual (sin sudo).
mkdir -p "${SENSIA_MODELS_DIR}"
mkdir -p "${DEST_DIR}"

# --- 4) Crear/reutilizar el entorno virtual dedicado ------------------------
VENV_PY="${VENV_DIR}/bin/python"
if [ -x "${VENV_PY}" ]; then
  info "Reutilizando el entorno virtual existente en ${VENV_DIR}"
else
  info "Creando entorno virtual en ${VENV_DIR}"
  if ! python3 -m venv "${VENV_DIR}"; then
    error "No se pudo crear el entorno virtual.
Instala el soporte necesario:  sudo apt update && sudo apt install -y python3-venv"
  fi
fi

# --- 5) Instalar huggingface_hub DENTRO del venv (nunca en el global) --------
info "Instalando huggingface_hub en el entorno virtual"
"${VENV_PY}" -m pip install --upgrade pip
"${VENV_PY}" -m pip install --upgrade huggingface_hub

# --- 6) Descargar el modelo con Python (snapshot_download), no con CLI --------
TMP_SCRIPT="$(mktemp "${TMPDIR:-/tmp}/salamandra_download.XXXXXX.py")"
cat > "${TMP_SCRIPT}" <<'PYEOF'
import os
import sys

from huggingface_hub import snapshot_download

# MODEL_ID y DEST_DIR se reciben por entorno, no van hardcodeados en este script.
model_id = os.environ["MODEL_ID"]
dest_dir = os.environ["DEST_DIR"]

print(f"[python] Descargando {model_id} en {dest_dir} ...", flush=True)
path = snapshot_download(
    repo_id=model_id,
    local_dir=dest_dir,
    local_dir_use_symlinks=False,
    # Evita pesos innecesarios; snapshot_download reanuda/reutiliza lo ya descargado.
    ignore_patterns=["*.pth", "original/*"],
)
print(f"[python] snapshot_download OK: {path}", flush=True)
sys.exit(0)
PYEOF

info "Iniciando descarga del modelo (puede tardar varios minutos)..."
MODEL_ID="${MODEL_ID}" DEST_DIR="${DEST_DIR}" "${VENV_PY}" "${TMP_SCRIPT}"

# --- 7) Verificación final (vuelve a comprobar config.json + pesos) ----------
info "Verificando la descarga..."
[ -d "${DEST_DIR}" ] || error "No existe ${DEST_DIR} tras la descarga."
[ -f "${DEST_DIR}/config.json" ] || error "Verificación fallida: no se encontró config.json en ${DEST_DIR}."

WEIGHTS_FILE="$(find "${DEST_DIR}" -maxdepth 2 -type f \
  \( -name '*.safetensors' -o -name '*.bin' \) 2>/dev/null | head -n 1 || true)"
[ -n "${WEIGHTS_FILE}" ] || error "Verificación fallida: no se encontró ningún fichero de pesos (*.safetensors o *.bin) en ${DEST_DIR}."

# Doble comprobación de completitud usando el mismo criterio que la comprobación previa.
model_is_complete || error "Verificación fallida: el modelo sigue incompleto en ${DEST_DIR}."

echo ""
info "Descarga completada. Modelo disponible en:"
echo "    ${DEST_DIR}"
echo ""
info "Tamaño en disco:"
du -sh "${DEST_DIR}"
echo ""
info "Contenido:"
ls -lh "${DEST_DIR}" | head -30
echo ""
info "Siguiente paso: levantar Docker Compose (ver DEPLOYMENT_SALAMANDRA_LOCAL.md)."
