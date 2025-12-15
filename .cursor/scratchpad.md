# Nitter Tweet Analyzer - Scratchpad

## Background and Motivation

Building a Python web application that:
1. Uses a self-hosted Nitter instance to scrape tweets from a specified user
2. Compiles tweets into a structured format
3. Sends them to Google Gemini for thematic summary analysis
4. Displays results via a web interface

## Key Challenges and Analysis

1. **Nitter Scraping**: Nitter pages use HTML rendering, need BeautifulSoup to parse tweet content
2. **Pagination**: Nitter uses cursor-based pagination, need to follow "Load more" links
3. **Rate Limiting**: Must respect both Nitter and Gemini rate limits
4. **Token Limits**: Gemini has context limits (~30k tokens), may need to truncate/batch tweets

## High-level Task Breakdown

1. [x] Initialize project structure, requirements.txt, and environment configuration
2. [x] Create Docker Compose config for self-hosted Nitter instance with Redis
3. [x] Build Nitter scraper module with pagination and rate-limit handling
4. [x] Build Gemini integration module for tweet analysis
5. [x] Create FastAPI endpoints connecting scraper and analyzer
6. [x] Build web interface for username input and results display
7. [x] End-to-end testing with real Nitter instance and Gemini API

## Project Status Board

- [x] Project structure created
- [x] requirements.txt created
- [x] env.example created (note: .env.example was blocked by globalignore)
- [x] Docker Compose for Nitter + Redis created
- [x] nitter.conf configuration created
- [x] Scraper module with pagination and rate limiting
- [x] Gemini analyzer module
- [x] FastAPI endpoints (/api/analyze, /api/scrape, /health)
- [x] Web UI with modern dark theme
- [x] Integration test script (test_app.py)
- [x] README with documentation

## Executor's Feedback or Assistance Requests

All tasks completed. To use the application:

1. Start Nitter: `docker-compose up -d`
2. Copy `env.example` to `.env` and add your Gemini API key
3. Install deps: `pip install -r requirements.txt`
4. Run tests: `python test_app.py`
5. Start app: `uvicorn app.main:app --reload`
6. Open http://localhost:8000

## Lessons

- .env.example files may be blocked by globalignore - use env.example instead
- Nitter requires Redis for caching
- Self-hosted Nitter still relies on Twitter backend and may need guest tokens
- **Mullvad VPN in Docker**: Mullvad overrides DNS, breaking Docker hostname resolution. Fix: resolve hostnames to IPs BEFORE Mullvad connects and add to /etc/hosts
- **Redis package**: Must be in requirements.txt for workers to connect to job queue
- **API server restart**: After code changes, must restart uvicorn (it was running since Dec 12!)
- **Worker heartbeat TTL**: Workers filtered out if last_seen > 30 seconds ago

## Production Deployment Notes (DigitalOcean VPS)

### Current Architecture
- **VPS**: 161.35.160.229, running Ubuntu
- **FastAPI**: uvicorn on port 3000 (running on host, not in container)
- **Workers**: 2 Docker containers (worker-1, worker-2) with Mullvad VPN each
- **Nitter**: 2 instances (nitter-1:8081, nitter-2:8082) with dedicated Redis caches
- **Job Queue**: Redis (redis-queue:6379)

### Known Issues & Maintenance Tasks

#### Nitter Session Management (CRITICAL)
- **Problem**: Nitter requires valid Twitter guest tokens/sessions to work
- **Symptom**: `[sessions] no sessions available for API: .../SearchTimeline`
- **Current state**: sessions.jsonl has 1 account session but it may be expired/rate-limited
- **TODO**: 
  1. Need to regularly refresh sessions.jsonl with valid guest tokens
  2. Build telemetry dashboard to monitor Nitter health
  3. Auto-restart Nitter when sessions expire
  4. Consider running Nitter session generator (nitter-guest-tokens project?)

#### How to Refresh Session Cookies
1. Log into a Twitter/X account in browser (use burner accounts!)
2. Export cookies using a browser extension (e.g., "Get cookies.txt LOCALLY")
3. Convert Netscape cookie format to Nitter JSONL format:
   ```
   {"kind":"cookie","username":"YOUR_USERNAME","id":"USER_ID","auth_token":"AUTH_TOKEN_VALUE","ct0":"CT0_VALUE"}
   ```
   - `auth_token` = from cookie named `auth_token`
   - `ct0` = from cookie named `ct0`
   - `id` = from `twid` cookie, decode URL: `u%3D1234567890` → `1234567890`
4. Put in `sessions.jsonl` file in Nitter container
5. Restart Nitter: `docker restart nitter-1 nitter-2`

**IMPORTANT**: Use MULTIPLE different accounts to avoid rate limits. Twitter rate-limits per account, not per IP.

#### Mullvad Device Limit
- Mullvad allows max 5 devices per account
- Each worker container registers as a new device on startup
- **Fix**: Revoke old devices at https://mullvad.net/en/account before restarting workers

### Startup Commands (VPS)
```bash
cd /opt/project-hyperdrive
source venv/bin/activate

# Start API server
nohup uvicorn app.main:app --host 0.0.0.0 --port 3000 > app.log 2>&1 &

# Start workers (after docker-compose infra is up)
docker run -d --name worker-1 --network project-hyperdrive_default \
  --cap-add=NET_ADMIN --device /dev/net/tun \
  -e WORKER_ID=worker1 -e NITTER_URL=http://nitter-1:8080 \
  -e REDIS_URL=redis://redis-queue:6379 -e NITTER_REDIS_HOST=nitter-redis-1 \
  -e MULLVAD_ACCOUNT="$MULLVAD_ACCOUNT" -e GEMINI_API_KEY="$GEMINI_API_KEY" \
  project-hyperdrive_worker-1:latest
```

