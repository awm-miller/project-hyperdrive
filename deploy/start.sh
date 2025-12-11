#!/bin/bash
# Start Hyperdrive on VPS
# Run from the deploy directory

set -e

echo "Starting Hyperdrive..."

# Check if .env exists
if [ ! -f "../.env" ]; then
    echo "ERROR: .env file not found!"
    echo "Create one with: GEMINI_API_KEY=your_key"
    exit 1
fi

# Check if sessions.jsonl exists
if [ ! -f "../sessions.jsonl" ]; then
    echo "ERROR: sessions.jsonl not found!"
    echo "Add your Twitter session tokens."
    exit 1
fi

# Copy config files
cp ../nitter.conf ./nitter.conf 2>/dev/null || true
cp ../sessions.jsonl ./sessions.jsonl 2>/dev/null || true

# Start Nitter + Redis
echo "Starting Nitter and Redis..."
docker-compose -f docker-compose.prod.yml up -d nitter-redis nitter

echo "Waiting for Nitter to be ready..."
sleep 10

# Check Nitter is running
if curl -s http://localhost:8080 > /dev/null; then
    echo "Nitter is ready!"
else
    echo "WARNING: Nitter may not be ready yet"
fi

# Start the Python app (not in Docker - easier for Mullvad)
echo "Starting Hyperdrive app..."
cd ..
source .env 2>/dev/null || export $(cat .env | xargs)
export NITTER_URL=http://localhost:8080
export DOCKER_COMPOSE_PATH=$(pwd)/deploy

# Run with uvicorn
nohup uvicorn app.main:app --host 0.0.0.0 --port 3000 > hyperdrive.log 2>&1 &
echo $! > hyperdrive.pid

echo ""
echo "=========================================="
echo "Hyperdrive is running!"
echo "=========================================="
echo "App:    http://localhost:3000"
echo "Nitter: http://localhost:8080"
echo "Logs:   tail -f hyperdrive.log"
echo "Stop:   ./stop.sh"
echo "=========================================="

