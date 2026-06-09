FROM python:3.11-slim

WORKDIR /app

# Evita .pyc en la imagen y hace el log visible en tiempo real en docker logs.
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# curl: útil para healthcheck en docker-compose.prod.yml.
# --no-install-recommends mantiene la imagen ligera.
# rm -rf /var/lib/apt/lists/* elimina la caché de apt.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar solo requirements.txt primero para aprovechar la caché de capas de Docker:
# si el código cambia pero las dependencias no, pip install no se re-ejecuta.
COPY requirements.txt .

RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copiar el resto del backend (el .dockerignore excluye tests, __pycache__, etc.)
COPY . .

EXPOSE 8000

# Aplica las migraciones antes de arrancar el servidor.
# Se usa sh -c para encadenar los dos comandos con &&.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
