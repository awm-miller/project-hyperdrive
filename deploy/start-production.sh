#!/bin/bash
# Hyperdrive Production Startup Script
# Runs on the VPS to start all services

set -e

APP_DIR="${APP_DIR:-/opt/hyperdrive}"
cd "$APP_DIR"

echo "=============================================="
echo "HYPERDRIVE PRODUCTION STARTUP"
echo "=============================================="

# Check required files
if [ ! -f ".env" ]; then
    echo "ERROR: .env file not found!"
    echo "Create it with: GEMINI_API_KEY, MULLVAD_ACCOUNT"
    exit 1
fi

if [ ! -f "sessions.jsonl" ]; then
    echo "ERROR: sessions.jsonl not found!"
    exit 1
fi

# Load environment
export $(grep -v '^#' .env | xargs)

echo ""
echo "[1/6] Stopping existing services..."
pkill -f uvicorn 2>/dev/null || true
docker rm -f worker-1 worker-2 2>/dev/null || true
docker-compose -f docker-compose.production.yml down 2>/dev/null || true

echo ""
echo "[2/6] Building worker image..."
docker-compose -f docker-compose.production.yml build worker-1

echo ""
echo "[3/6] Starting infrastructure (Redis, Nitter)..."
docker-compose -f docker-compose.production.yml up -d redis-queue nitter-redis-1 nitter-redis-2 nitter-1 nitter-2

echo ""
echo "[4/6] Waiting for Nitter to be ready..."
sleep 10

echo ""
echo "[5/6] Starting workers with Mullvad VPN..."
# Get network name
NETWORK=$(docker network ls --filter name=hyperdrive -q | head -1)
NETWORK_NAME=$(docker network inspect $NETWORK --format '{{.Name}}' 2>/dev/null || echo "project-hyperdrive_default")

# Worker 1
docker run -d --name worker-1 \
  --cap-add=NET_ADMIN \
  --device=/dev/net/tun \
  --network="$NETWORK_NAME" \
  -e WORKER_ID=worker1 \
  -e NITTER_URL=http://nitter-1:8080 \
  -e REDIS_URL=redis://redis-queue:6379 \
  -e NITTER_REDIS_HOST=nitter-redis-1 \
  -e MULLVAD_ACCOUNT="$MULLVAD_ACCOUNT" \
  -e GEMINI_API_KEY="$GEMINI_API_KEY" \
  --restart=unless-stopped \
  project-hyperdrive_worker-1

# Worker 2
docker run -d --name worker-2 \
  --cap-add=NET_ADMIN \
  --device=/dev/net/tun \
  --network="$NETWORK_NAME" \
  -e WORKER_ID=worker2 \
  -e NITTER_URL=http://nitter-2:8080 \
  -e REDIS_URL=redis://redis-queue:6379 \
  -e NITTER_REDIS_HOST=nitter-redis-2 \
  -e MULLVAD_ACCOUNT="$MULLVAD_ACCOUNT" \
  -e GEMINI_API_KEY="$GEMINI_API_KEY" \
  --restart=unless-stopped \
  project-hyperdrive_worker-1

echo ""
echo "[6/6] Starting API server..."
source venv/bin/activate 2>/dev/null || { python3 -m venv venv && source venv/bin/activate; }
pip install -q -r requirements.txt
nohup uvicorn app.main:app --host 0.0.0.0 --port 3000 > app.log 2>&1 &

echo ""
echo "=============================================="
echo "STARTUP COMPLETE"
echo "=============================================="
echo ""
echo "Services running:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""
echo "API Server: http://$(curl -s ifconfig.me 2>/dev/null || echo 'YOUR_IP'):3000"
echo ""
echo "Useful commands:"
echo "  View API logs:     tail -f $APP_DIR/app.log"
echo "  View worker logs:  docker logs -f worker-1"
echo "  View all services: docker ps"
echo "  Stop everything:   $APP_DIR/deploy/stop-production.sh"
echo ""

