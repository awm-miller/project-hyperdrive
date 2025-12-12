#!/bin/bash
set -e

echo "=== Worker Container Starting ==="
echo "Worker ID: $WORKER_ID"
echo "Nitter URL: $NITTER_URL"
echo "Redis URL: $REDIS_URL"

# Start Mullvad daemon
echo "Starting Mullvad daemon..."
mullvad-daemon &
sleep 3

# Login to Mullvad if account provided
if [ -n "$MULLVAD_ACCOUNT" ]; then
    echo "Logging into Mullvad..."
    mullvad account login "$MULLVAD_ACCOUNT"
    
    # Allow LAN access (important for Docker networking)
    mullvad lan set allow
    
    # Set to auto-connect
    mullvad auto-connect set on
    
    # Connect
    echo "Connecting to Mullvad VPN..."
    mullvad connect
    
    # Wait for connection
    sleep 5
    mullvad status
else
    echo "WARNING: No MULLVAD_ACCOUNT set, running without VPN"
fi

echo "=== Starting Worker ==="
exec python3 worker.py --id "$WORKER_ID" --nitter "$NITTER_URL" --redis "$REDIS_URL"

