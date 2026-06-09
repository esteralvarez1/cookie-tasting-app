FROM node:20-alpine AS build

WORKDIR /app

# package.json + package-lock.json primero para aprovechar la caché de capas:
# si el código cambia pero las dependencias no, npm ci no se re-ejecuta.
COPY package*.json ./
RUN npm ci

COPY . .

# Las variables VITE_* se inyectan en tiempo de build (quedan embebidas en el JS).
# VITE_ADMIN_API_KEY se omite deliberadamente: es una clave real que no debe
# quedar expuesta en el bundle del navegador.
ARG VITE_API_BASE_URL
ARG VITE_ADMIN_HEADER_NAME=X-Admin-Key

ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_ADMIN_HEADER_NAME=$VITE_ADMIN_HEADER_NAME

RUN npm run build

# ── Fase de producción ────────────────────────────────────────────────────────
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
