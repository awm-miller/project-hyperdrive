#!/bin/bash
# Hyperdrive Production Stop Script

echo "Stopping Hyperdrive..."

cd /opt/hyperdrive

# Stop API server
pkill -f uvicorn 2>/dev/null || true

# Stop Docker services
docker-compose -f docker-compose.production.yml down 2>/dev/null || true

echo "All services stopped."

