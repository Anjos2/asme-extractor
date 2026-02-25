#!/bin/bash
# Deploy ASME Extractor to Docker Swarm
set -euo pipefail

echo "=== ASME Extractor Deploy ==="

if [ ! -f .env ]; then
    echo "ERROR: .env file not found. Copy .env.example and configure."
    exit 1
fi

source .env

echo "Building backend image..."
docker build -t asme-backend:latest ./backend

echo "Deploying stack..."
docker stack deploy -c docker-compose.prod.yml asme

echo "Waiting for services..."
sleep 5
docker stack services asme

echo "=== Deploy complete ==="
echo "Check: https://${DOMAIN}/api/health"
