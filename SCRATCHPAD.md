# Project Hyperdrive - Operations Scratchpad

## Branching Strategy

| Branch | Purpose | Netlify | VPS |
|--------|---------|---------|-----|
| `main` | Production | project-hyperdrive.netlify.app | 161.35.160.229 (prod) |
| `staging` | Testing | staging--project-hyperdrive.netlify.app | TBD (staging droplet) |

**Workflow:**
1. Develop on `staging` branch
2. Test on staging environment
3. When ready, merge `staging` → `main` for production

```bash
# Switch to staging for development
git checkout staging

# Make changes, commit, push
git add -A && git commit -m "feature" && git push

# When ready for prod
git checkout main
git merge staging
git push
```

---

## VPS Deployment Notes

### Why Workers Need Manual Start

The `docker-compose.production.yml` has `depends_on` with health checks for Nitter.
But Nitter instances often report "unhealthy" even when working (the health check is finicky).
This blocks `docker-compose up` from starting workers.

**WORKAROUND: Start workers manually with `docker run`:**

```bash
# FIRST: Load env vars (MUST do this in each new shell session!)
cd /opt/project-hyperdrive
export $(grep -v '^#' .env | xargs)

# Verify they're set
echo "MULLVAD: $MULLVAD_ACCOUNT"
echo "GEMINI: $GEMINI_API_KEY"

# Worker 1
docker run -d \
  --name worker-1 \
  --network project-hyperdrive_default \
  --cap-add=NET_ADMIN \
  --device /dev/net/tun \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e WORKER_ID=worker1 \
  -e NITTER_URL=http://nitter-1:8080 \
  -e REDIS_URL=redis://redis-queue:6379 \
  -e NITTER_REDIS_HOST=nitter-redis-1 \
  -e MULLVAD_ACCOUNT="$MULLVAD_ACCOUNT" \
  -e GEMINI_API_KEY="$GEMINI_API_KEY" \
  project-hyperdrive_worker-1:latest

# Worker 2
docker run -d \
  --name worker-2 \
  --network project-hyperdrive_default \
  --cap-add=NET_ADMIN \
  --device /dev/net/tun \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e WORKER_ID=worker2 \
  -e NITTER_URL=http://nitter-2:8080 \
  -e REDIS_URL=redis://redis-queue:6379 \
  -e NITTER_REDIS_HOST=nitter-redis-2 \
  -e MULLVAD_ACCOUNT="$MULLVAD_ACCOUNT" \
  -e GEMINI_API_KEY="$GEMINI_API_KEY" \
  project-hyperdrive_worker-1:latest
```

### Rebuilding Workers After Code Changes

```bash
cd /opt/project-hyperdrive
git pull
docker-compose -f docker-compose.production.yml build worker-1

# Stop old, remove, start new
docker stop worker-1 && docker rm worker-1
# Then run the docker run command above
```

### Nitter Unhealthy But Working

Nitter health check uses: `wget -nv --tries=1 --spider http://127.0.0.1:8080/Jack/status/20`

This fails if:
- No Twitter sessions available
- Rate limited

But Nitter may still work for searches. Check manually:
```bash
curl -s http://localhost:8081/search?q=test | head -5
```

---

## Current Issues

1. **Nitter health checks are too strict** - Consider removing or relaxing them
2. **Workers block on unhealthy Nitter** - Use manual docker run as workaround
3. **API runs on host, not in Docker** - Should containerize for consistency
4. **Redis persistence** - Need to set up persistent volume for redis-queue to survive reboots

---

## VPS Startup Procedure (After Reboot)

Run these commands in order after a VPS restart:

```bash
# 1. Navigate to project
cd /opt/project-hyperdrive

# 2. Start Redis queue (job storage)
docker start redis-queue

# 3. Start API server
docker-compose up -d api

# 4. Start Nitter Redis caches
docker start nitter-redis-1 nitter-redis-2

# 5. Start Nitter instances
docker start nitter-1 nitter-2

# 6. Wait for Nitter to be ready
sleep 10

# 7. Start workers
docker start worker-1 worker-2

# 8. Connect Mullvad VPNs
docker exec worker-1 mullvad connect
docker exec worker-2 mullvad connect

# 9. Start dashboard
sudo systemctl start hyperdrive-dashboard

# 10. Verify everything is running
docker ps
sudo systemctl status hyperdrive-dashboard
```

### Quick Health Check

```bash
# All containers running?
docker ps

# Workers connected to VPN?
docker exec worker-1 mullvad status
docker exec worker-2 mullvad status

# Dashboard running?
curl -s http://127.0.0.1:8888/api/health

# API running?
curl -s http://localhost:3000/api/health
```

---

## Quick Commands

```bash
# Check worker logs
docker logs -f worker-1

# Check job queue
docker exec redis-queue redis-cli LRANGE hyperdrive:jobs:pending 0 -1

# Submit test job
curl -X POST http://localhost:3000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"username":"elonmusk","start_date":"2025-01-01","end_date":"2025-04-30"}'

# Restart Nitter
docker restart nitter-1

# Flush Nitter cache
docker exec nitter-redis-1 redis-cli FLUSHALL
```

