#!/bin/bash
# Hyperdrive Production Startup Script
# Runs on the VPS to start all services

set -e

echo "=============================================="
echo "HYPERDRIVE PRODUCTION STARTUP"
echo "=============================================="

cd /opt/hyperdrive

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
echo "[1/5] Stopping existing services..."
pkill -f uvicorn 2>/dev/null || true
pkill -f "worker.py" 2>/dev/null || true
docker-compose -f docker-compose.production.yml down 2>/dev/null || true
docker-compose -f docker-compose.workers.yml down 2>/dev/null || true
docker-compose down 2>/dev/null || true

echo ""
echo "[2/5] Building worker containers..."
docker-compose -f docker-compose.production.yml build

echo ""
echo "[3/5] Starting Docker services..."
docker-compose -f docker-compose.production.yml up -d

echo ""
echo "[4/5] Waiting for services to be healthy..."
sleep 15

echo ""
echo "[5/5] Starting API server..."
source venv/bin/activate 2>/dev/null || python3 -m venv venv && source venv/bin/activate
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
echo "API Server: http://$(curl -s ifconfig.me):3000"
echo ""
echo "Useful commands:"
echo "  View API logs:     tail -f /opt/hyperdrive/app.log"
echo "  View worker logs:  docker logs -f worker-1"
echo "  View all services: docker ps"
echo "  Stop everything:   /opt/hyperdrive/deploy/stop-production.sh"
echo ""

