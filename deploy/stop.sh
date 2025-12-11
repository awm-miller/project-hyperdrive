#!/bin/bash
# Stop Hyperdrive on VPS

echo "Stopping Hyperdrive..."

# Stop Python app
if [ -f "../hyperdrive.pid" ]; then
    kill $(cat ../hyperdrive.pid) 2>/dev/null || true
    rm ../hyperdrive.pid
    echo "App stopped"
fi

# Stop Docker containers
docker-compose -f docker-compose.prod.yml down
echo "Nitter and Redis stopped"

echo "Done!"

