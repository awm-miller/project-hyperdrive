#!/bin/bash
set -e

echo "=== Worker Container Starting ==="
echo "Worker ID: $WORKER_ID"
echo "Nitter URL: $NITTER_URL"
echo "Redis URL: $REDIS_URL"

# IMPORTANT: Resolve Docker hostnames BEFORE Mullvad starts
# Mullvad overrides DNS which breaks Docker's internal name resolution
echo "Resolving Docker hostnames to IPs..."

# Extract hostname from Redis URL (redis://redis-queue:6379 -> redis-queue)
REDIS_HOST=$(echo "$REDIS_URL" | sed -E 's|redis://([^:]+):.*|\1|')
REDIS_IP=$(getent hosts "$REDIS_HOST" 2>/dev/null | awk '{print $1}' || echo "")

# Extract hostname from Nitter URL (http://nitter-1:8080 -> nitter-1)
NITTER_HOST=$(echo "$NITTER_URL" | sed -E 's|https?://([^:]+):.*|\1|')
NITTER_IP=$(getent hosts "$NITTER_HOST" 2>/dev/null | awk '{print $1}' || echo "")

# Add to /etc/hosts so they still work after Mullvad changes DNS
if [ -n "$REDIS_IP" ]; then
    echo "$REDIS_IP $REDIS_HOST" >> /etc/hosts
    echo "  Added: $REDIS_HOST -> $REDIS_IP"
else
    echo "  WARNING: Could not resolve $REDIS_HOST"
fi

if [ -n "$NITTER_IP" ]; then
    echo "$NITTER_IP $NITTER_HOST" >> /etc/hosts
    echo "  Added: $NITTER_HOST -> $NITTER_IP"
else
    echo "  WARNING: Could not resolve $NITTER_HOST"
fi

# Also resolve nitter-redis if needed (for scrapers that use it)
NITTER_REDIS_HOST="${NITTER_REDIS_HOST:-}"
if [ -n "$NITTER_REDIS_HOST" ]; then
    NITTER_REDIS_IP=$(getent hosts "$NITTER_REDIS_HOST" 2>/dev/null | awk '{print $1}' || echo "")
    if [ -n "$NITTER_REDIS_IP" ]; then
        echo "$NITTER_REDIS_IP $NITTER_REDIS_HOST" >> /etc/hosts
        echo "  Added: $NITTER_REDIS_HOST -> $NITTER_REDIS_IP"
    fi
fi

echo "Hostname resolution complete."

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

