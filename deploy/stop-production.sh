#!/bin/bash
# Hyperdrive Production Stop Script

APP_DIR="${APP_DIR:-/opt/hyperdrive}"

echo "Stopping Hyperdrive..."

# Stop API server
pkill -f uvicorn 2>/dev/null || true

# Stop workers
docker rm -f worker-1 worker-2 2>/dev/null || true

# Stop Docker infrastructure
cd "$APP_DIR"
docker-compose -f docker-compose.production.yml down 2>/dev/null || true

echo "All services stopped."

