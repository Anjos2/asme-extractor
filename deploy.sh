#!/usr/bin/env bash
# Deploy ASME Extractor a Docker Swarm (Hostinger).
# Uso: ./deploy.sh [--build] [--force]
#   --build   Rebuild imagen Docker antes de deployar
#   --force   Force update del servicio (cuando tag :latest no cambia)
#
# Requiere: .env con DOMAIN, GLIDE_APP_ID, OPENAI_MODEL, etc.
# Secrets (openai_api_key, glide_api_token, asme_api_key) son Docker secrets externos.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Validar que .env existe
if [ ! -f .env ]; then
    echo "ERROR: .env no encontrado en $SCRIPT_DIR"
    exit 1
fi

# Cargar .env como variables exportadas
# set -a: auto-exporta toda variable asignada (para que envsubst las vea)
# set +a: desactiva ese comportamiento despues de cargar
set -a
source .env
set +a

# Validar variable critica
if [ -z "${DOMAIN:-}" ]; then
    echo "ERROR: DOMAIN no definido en .env"
    exit 1
fi

echo "=== ASME Extractor Deploy ==="
echo "Dominio: $DOMAIN"

# Pull cambios de git
echo "--- git pull ---"
git pull

# Build si se pide
if [[ " $* " == *" --build "* ]]; then
    echo "--- docker build ---"
    docker build -t asme-backend:latest ./backend
fi

# Deploy stack con envsubst (sustituye ${DOMAIN}, ${GLIDE_APP_ID}, etc.)
echo "--- docker stack deploy ---"
envsubst < docker-compose.prod.yml | docker stack deploy -c - asme

# Force update si se pide (necesario cuando tag :latest no cambia)
if [[ " $* " == *" --force "* ]]; then
    echo "--- docker service update --force ---"
    docker service update --force asme_backend
fi

echo "=== Deploy completado ==="
echo "Verificar: curl -s https://$DOMAIN/docs"
