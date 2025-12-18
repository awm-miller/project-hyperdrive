"""
Nitter Tweet Analyzer - FastAPI Application

Main entry point for the web application.
Supports:
- Search-based scraping (tweets/replies with date range)
- Timeline scraping (retweets)
- Gemini analysis
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .scraper_search import NitterSearchScraper
from .scraper_timeline import NitterTimelineScraper
from .analyzer import GeminiAnalyzer
from .jobs import JobQueue, Job, JobStatus

# Import screenshot tool (optional - may not be installed)
SCREENSHOT_AVAILABLE = False
screenshot_tweet = None
try:
    import sys
    from pathlib import Path
    # Add project root to path for tools import
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from tools.screenshot_tweet import screenshot_tweet
    SCREENSHOT_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Screenshot tool not available: {e}")

load_dotenv()

# Redis URL for job queue
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("api")

# Get configuration from environment
NITTER_URL = os.getenv("NITTER_URL", "http://localhost:8080")
DOCKER_COMPOSE_PATH = os.getenv("DOCKER_COMPOSE_PATH", ".")


# Global job queue instance
job_queue: Optional[JobQueue] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global job_queue
    logger.info("=" * 60)
    logger.info("NITTER TWEET ANALYZER - STARTING UP")
    logger.info("=" * 60)
    logger.info(f"Nitter URL: {NITTER_URL}")
    logger.info(f"Docker Compose Path: {DOCKER_COMPOSE_PATH}")
    logger.info(f"Redis URL: {REDIS_URL}")
    logger.info(f"Gemini API key configured: {bool(os.getenv('GEMINI_API_KEY'))}")
    
    # Initialize job queue
    try:
        job_queue = JobQueue(REDIS_URL)
        logger.info("Job queue connected to Redis")
    except Exception as e:
        logger.warning(f"Could not connect to Redis: {e}")
        logger.warning("Job queue features will be disabled")
    
    logger.info("=" * 60)
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="Nitter Tweet Analyzer",
    description="Scrape tweets via Nitter and analyze them with Gemini",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS - allow Netlify and local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (Netlify URLs are dynamic)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup templates
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)


# Request/Response Models
class ScrapeSearchRequest(BaseModel):
    """Request for search-based scraping (tweets/replies)."""
    username: str = Field(..., description="Twitter username (without @)")
    start_date: Optional[str] = Field(default=None, description="Start date YYYY-MM-DD")
    end_date: Optional[str] = Field(default=None, description="End date YYYY-MM-DD")
    include_retweets: bool = Field(default=True, description="Include retweets in search")
    include_replies: bool = Field(default=True, description="Include replies in search")
    max_tweets: int = Field(default=5000, description="Max tweets to scrape")


class ScrapeRetweetsRequest(BaseModel):
    """Request for timeline retweet scraping."""
    username: str = Field(..., description="Twitter username (without @)")
    max_retweets: int = Field(default=10000, description="Max retweets to scrape")


class AnalyzeRequest(BaseModel):
    """Request for full analysis (scrape + Gemini)."""
    username: str = Field(..., description="Twitter username (without @)")
    start_date: Optional[str] = Field(default=None, description="Start date YYYY-MM-DD")
    end_date: Optional[str] = Field(default=None, description="End date YYYY-MM-DD")
    include_tweets: bool = Field(default=True, description="Include original tweets")
    include_retweets: bool = Field(default=True, description="Include retweets")
    include_replies: bool = Field(default=True, description="Include replies")
    max_tweets: int = Field(default=5000, description="Max tweets to scrape")
    custom_prompt: Optional[str] = Field(default=None, description="Custom analysis prompt")


class TweetData(BaseModel):
    """Tweet data for responses."""
    id: str
    content: str
    timestamp: str
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    is_retweet: bool = False
    is_reply: bool = False
    original_author: str = ""


class ScrapeResponse(BaseModel):
    """Response for scrape endpoints."""
    username: str
    tweets_scraped: int
    tweets: list[TweetData]
    error: Optional[str] = None
    rate_limited: bool = False
    restarts: int = 0


class HighlightedTweet(BaseModel):
    """A notable tweet picked by AI."""
    text: str
    reason: str = ""
    url: str = ""
    images: list[str] = []


class StoredTweet(BaseModel):
    """A tweet stored with flag information."""
    index: int
    id: str = ""  # Tweet ID for screenshots
    text: str
    date: str = ""
    url: str = ""
    is_retweet: bool = False
    original_author: Optional[str] = None
    images: list[str] = []
    flagged: bool = False
    flag_reason: Optional[str] = None


class PaginatedTweetsResponse(BaseModel):
    """Paginated response for all tweets."""
    job_id: str
    username: str
    total_tweets: int
    total_flagged: int
    page: int
    per_page: int
    total_pages: int
    tweets: list[StoredTweet]
    analysis: str = ""


class AnalyzeResponse(BaseModel):
    """Response for analysis endpoint."""
    username: str
    tweets_scraped: int
    retweets_scraped: int
    analysis: str
    themes: list[str]
    highlighted_tweets: list[HighlightedTweet] = []
    chunks_processed: int = 1
    error: Optional[str] = None
    rate_limited: bool = False


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    nitter_url: str
    gemini_configured: bool


# Job-related models
class JobSubmitRequest(BaseModel):
    """Request to submit a new analysis job."""
    username: str = Field(..., description="Twitter username (without @)")
    start_date: Optional[str] = Field(default=None, description="Start date YYYY-MM-DD")
    end_date: Optional[str] = Field(default=None, description="End date YYYY-MM-DD")
    include_tweets: bool = Field(default=True)
    include_retweets: bool = Field(default=True)
    include_replies: bool = Field(default=True)
    custom_prompt: Optional[str] = Field(default=None)


class JobSubmitResponse(BaseModel):
    """Response when submitting a job."""
    job_id: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    """Full job status and results."""
    job_id: str
    username: str
    status: str
    progress: int
    current_step: str
    tweets_scraped: int
    retweets_scraped: int
    analysis: str = ""
    themes: list[str] = []
    highlighted_tweets: list[HighlightedTweet] = []
    error: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    worker_id: Optional[str] = None


class JobListResponse(BaseModel):
    """List of jobs."""
    jobs: list[JobStatusResponse]
    queue_length: int


# Endpoints
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Serve the main web interface."""
    logger.info("GET / - Serving home page")
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "nitter_url": NITTER_URL}
    )


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Check application health and configuration."""
    gemini_key = os.getenv("GEMINI_API_KEY")
    return HealthResponse(
        status="healthy",
        nitter_url=NITTER_URL,
        gemini_configured=bool(gemini_key and len(gemini_key) > 10),
    )


# ==================== JOB QUEUE ENDPOINTS ====================

@app.post("/api/jobs", response_model=JobSubmitResponse)
async def submit_job(request: JobSubmitRequest):
    """
    Submit a new analysis job to the queue.
    Returns immediately with job ID - workers process in background.
    """
    if not job_queue:
        raise HTTPException(status_code=503, detail="Job queue not available (Redis not connected)")
    
    username = request.username.lstrip("@").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    
    job = job_queue.create_job(
        username=username,
        start_date=request.start_date,
        end_date=request.end_date,
        include_tweets=request.include_tweets,
        include_retweets=request.include_retweets,
        include_replies=request.include_replies,
        custom_prompt=request.custom_prompt,
    )
    
    logger.info(f"Job {job.id} submitted for @{username}")
    
    return JobSubmitResponse(
        job_id=job.id,
        status=job.status.value,
        message=f"Job queued. Position: {job_queue.get_queue_length()}",
    )


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """Get status and results of a specific job."""
    if not job_queue:
        raise HTTPException(status_code=503, detail="Job queue not available")
    
    job = job_queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Convert highlighted tweets to response format
    highlighted = [
        HighlightedTweet(
            text=ht.get("text", ""),
            reason=ht.get("reason", ""),
            url=ht.get("url", ""),
            images=ht.get("images", []),
        )
        for ht in job.highlighted_tweets
    ]
    
    return JobStatusResponse(
        job_id=job.id,
        username=job.username,
        status=job.status.value,
        progress=job.progress,
        current_step=job.current_step,
        tweets_scraped=job.tweets_scraped,
        retweets_scraped=job.retweets_scraped,
        analysis=job.analysis,
        themes=job.themes,
        highlighted_tweets=highlighted,
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        worker_id=job.worker_id,
    )


@app.get("/api/jobs/{job_id}/tweets", response_model=PaginatedTweetsResponse)
async def get_job_tweets(
    job_id: str,
    page: int = 1,
    per_page: int = 20,
    flagged_first: bool = True,
):
    """
    Get paginated tweets for a job with flag information.
    
    Tweets are sorted with flagged tweets first (if flagged_first=true),
    then by date descending.
    """
    if not job_queue:
        raise HTTPException(status_code=503, detail="Job queue not available")
    
    job = job_queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    all_tweets = job.all_tweets or []
    
    # Sort: flagged first if requested, then by date
    if flagged_first:
        sorted_tweets = sorted(
            all_tweets,
            key=lambda t: (not t.get("flagged", False), t.get("date", "")),
        )
    else:
        sorted_tweets = sorted(
            all_tweets,
            key=lambda t: t.get("date", ""),
            reverse=True,
        )
    
    # Count flagged
    total_flagged = sum(1 for t in all_tweets if t.get("flagged", False))
    
    # Paginate
    total_tweets = len(sorted_tweets)
    total_pages = (total_tweets + per_page - 1) // per_page if per_page > 0 else 1
    
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_tweets = sorted_tweets[start_idx:end_idx]
    
    # Convert to response model
    tweet_responses = [
        StoredTweet(
            index=t.get("index", 0),
            id=t.get("id", ""),
            text=t.get("text", ""),
            date=t.get("date", ""),
            url=t.get("url", ""),
            is_retweet=t.get("is_retweet", False),
            original_author=t.get("original_author"),
            images=t.get("images", []),
            flagged=t.get("flagged", False),
            flag_reason=t.get("flag_reason"),
        )
        for t in page_tweets
    ]
    
    return PaginatedTweetsResponse(
        job_id=job.id,
        username=job.username,
        total_tweets=total_tweets,
        total_flagged=total_flagged,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        tweets=tweet_responses,
        analysis=job.analysis,
    )


@app.get("/api/jobs", response_model=JobListResponse)
async def list_jobs(limit: int = 20):
    """List recent jobs."""
    if not job_queue:
        raise HTTPException(status_code=503, detail="Job queue not available")
    
    jobs = job_queue.list_jobs(limit=limit)
    
    job_responses = []
    for job in jobs:
        highlighted = [
            HighlightedTweet(
                text=ht.get("text", ""),
                reason=ht.get("reason", ""),
                url=ht.get("url", ""),
                images=ht.get("images", []),
            )
            for ht in job.highlighted_tweets
        ]
        job_responses.append(JobStatusResponse(
            job_id=job.id,
            username=job.username,
            status=job.status.value,
            progress=job.progress,
            current_step=job.current_step,
            tweets_scraped=job.tweets_scraped,
            retweets_scraped=job.retweets_scraped,
            analysis=job.analysis,
            themes=job.themes,
            highlighted_tweets=highlighted,
            error=job.error,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            worker_id=job.worker_id,
        ))
    
    return JobListResponse(
        jobs=job_responses,
        queue_length=job_queue.get_queue_length(),
    )


@app.get("/api/workers")
async def get_workers():
    """Get active workers."""
    if not job_queue:
        return {"workers": [], "count": 0}
    
    workers = job_queue.get_active_workers()
    return {
        "workers": workers,
        "count": len(workers)
    }


# ==================== SCREENSHOT ENDPOINT ====================


@app.get("/api/screenshot")
async def screenshot_tweet_api(
    tweet_id: str,
    username: str,
):
    """
    Screenshot a tweet using Twitter embed.
    
    Only supports regular tweets, not retweets.
    
    Returns: PNG image
    """
    if not SCREENSHOT_AVAILABLE:
        raise HTTPException(
            status_code=501, 
            detail="Screenshot feature not available. Install playwright: pip install playwright && playwright install chromium"
        )
    
    try:
        png_bytes = await screenshot_tweet(
            tweet_id=tweet_id,
            username=username,
        )
        
        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={
                "Content-Disposition": f"inline; filename=tweet_{tweet_id}.png"
            }
        )
    except Exception as e:
        logger.error(f"Screenshot error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== LEGACY DIRECT ENDPOINTS ====================


@app.get("/api/logs")
async def get_logs(lines: int = 100):
    """Get recent app logs."""
    import subprocess
    try:
        # Try to read the app.log file
        log_file = "app.log"
        if os.path.exists(log_file):
            with open(log_file, "r") as f:
                all_lines = f.readlines()
                recent = all_lines[-lines:] if len(all_lines) > lines else all_lines
                return {"logs": "".join(recent), "total_lines": len(all_lines)}
        else:
            return {"logs": "No log file found", "total_lines": 0}
    except Exception as e:
        return {"logs": f"Error reading logs: {str(e)}", "total_lines": 0}


@app.get("/api/status")
async def get_status():
    """Get system status including VPN and Docker."""
    import subprocess
    status = {
        "app": "running",
        "vpn": "unknown",
        "nitter": "unknown",
    }
    
    try:
        # Check Mullvad status
        result = subprocess.run(["mullvad", "status"], capture_output=True, text=True, timeout=5)
        status["vpn"] = result.stdout.strip().split('\n')[0] if result.returncode == 0 else "not installed"
    except:
        status["vpn"] = "not available"
    
    try:
        # Check if Nitter is responding
        import httpx
        resp = httpx.get(f"{NITTER_URL}/", timeout=5)
        status["nitter"] = "running" if resp.status_code == 200 else f"error: {resp.status_code}"
    except Exception as e:
        status["nitter"] = f"error: {str(e)}"
    
    return status


@app.post("/api/scrape/search", response_model=ScrapeResponse)
async def scrape_search(request: ScrapeSearchRequest):
    """
    Scrape tweets using search with date range.
    Good for: tweets, replies (with date filtering)
    """
    username = request.username.lstrip("@").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")

    logger.info(f"POST /api/scrape/search - @{username}")
    logger.info(f"  Date range: {request.start_date} to {request.end_date}")
    logger.info(f"  Include RTs: {request.include_retweets}, Replies: {request.include_replies}")

    # Parse dates
    start_date = None
    end_date = None
    if request.start_date:
        start_date = datetime.strptime(request.start_date, "%Y-%m-%d")
    if request.end_date:
        end_date = datetime.strptime(request.end_date, "%Y-%m-%d")

    async with NitterSearchScraper(
        nitter_url=NITTER_URL,
        delay_seconds=0.5,
        max_tweets=request.max_tweets,
        docker_compose_path=DOCKER_COMPOSE_PATH,
    ) as scraper:
        result = await scraper.scrape_user(
            username=username,
            start_date=start_date,
            end_date=end_date,
            include_retweets=request.include_retweets,
            include_replies=request.include_replies,
        )

    tweets_data = [
        TweetData(
            id=t.id,
            content=t.content,
            timestamp=t.timestamp,
            likes=t.likes,
            retweets=t.retweets,
            replies=t.replies,
            is_retweet=t.is_retweet,
            is_reply=t.is_reply,
        )
        for t in result.tweets
    ]

    logger.info(f"  Result: {result.total_scraped} tweets, restarts={scraper.restart_count}")

    return ScrapeResponse(
        username=username,
        tweets_scraped=result.total_scraped,
        tweets=tweets_data,
        error=result.error,
        rate_limited=result.rate_limited,
        restarts=scraper.restart_count,
    )


@app.post("/api/scrape/retweets", response_model=ScrapeResponse)
async def scrape_retweets(request: ScrapeRetweetsRequest):
    """
    Scrape retweets from user's timeline.
    Goes as far back as the timeline allows.
    """
    username = request.username.lstrip("@").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")

    logger.info(f"POST /api/scrape/retweets - @{username}")
    logger.info(f"  Max retweets: {request.max_retweets}")

    async with NitterTimelineScraper(
        nitter_url=NITTER_URL,
        delay_seconds=0.5,
        max_retweets=request.max_retweets,
        docker_compose_path=DOCKER_COMPOSE_PATH,
    ) as scraper:
        result = await scraper.scrape_retweets(username=username)

    tweets_data = [
        TweetData(
            id=t.id,
            content=t.content,
            timestamp=t.timestamp,
            likes=t.likes,
            retweets=t.retweets,
            replies=t.replies,
            is_retweet=True,
            original_author=t.original_author,
        )
        for t in result.tweets
    ]

    logger.info(f"  Result: {result.total_scraped} retweets, restarts={scraper.restart_count}")

    return ScrapeResponse(
        username=username,
        tweets_scraped=result.total_scraped,
        tweets=tweets_data,
        error=result.error,
        rate_limited=result.rate_limited,
        restarts=scraper.restart_count,
    )


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze_tweets(request: AnalyzeRequest):
    """
    Full analysis: scrape tweets + retweets, then analyze with Gemini.
    """
    username = request.username.lstrip("@").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")

    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")

    logger.info(f"POST /api/analyze - @{username}")
    logger.info(f"  Date range: {request.start_date} to {request.end_date}")
    logger.info(f"  Tweets: {request.include_tweets}, RTs: {request.include_retweets}, Replies: {request.include_replies}")

    all_tweets = []
    retweets_count = 0
    tweets_count = 0
    total_restarts = 0

    # Parse dates
    start_date = None
    end_date = None
    if request.start_date:
        start_date = datetime.strptime(request.start_date, "%Y-%m-%d")
    if request.end_date:
        end_date = datetime.strptime(request.end_date, "%Y-%m-%d")

    # Step 1: Scrape retweets from timeline (if requested)
    if request.include_retweets:
        logger.info("[Step 1] Scraping retweets from timeline...")
        async with NitterTimelineScraper(
            nitter_url=NITTER_URL,
            delay_seconds=0.5,
            max_retweets=request.max_tweets,
            docker_compose_path=DOCKER_COMPOSE_PATH,
        ) as scraper:
            rt_result = await scraper.scrape_retweets(username=username)
            all_tweets.extend(rt_result.tweets)
            retweets_count = rt_result.total_scraped
            total_restarts += scraper.restart_count
        logger.info(f"[Step 1] Got {retweets_count} retweets")

    # Step 2: Scrape tweets/replies from search (if requested)
    if request.include_tweets or request.include_replies:
        logger.info("[Step 2] Scraping tweets/replies via search...")
        async with NitterSearchScraper(
            nitter_url=NITTER_URL,
            delay_seconds=0.5,
            max_tweets=request.max_tweets,
            docker_compose_path=DOCKER_COMPOSE_PATH,
        ) as scraper:
            search_result = await scraper.scrape_user(
                username=username,
                start_date=start_date,
                end_date=end_date,
                include_retweets=False,  # Already got from timeline
                include_replies=request.include_replies,
            )
            all_tweets.extend(search_result.tweets)
            tweets_count = search_result.total_scraped
            total_restarts += scraper.restart_count
        logger.info(f"[Step 2] Got {tweets_count} tweets/replies")

    if not all_tweets:
        return AnalyzeResponse(
            username=username,
            tweets_scraped=0,
            retweets_scraped=0,
            analysis="No tweets found to analyze.",
            themes=[],
            error="No content found",
        )

    # Step 3: Compile and analyze with Gemini
    logger.info(f"[Step 3] Analyzing {len(all_tweets)} total items with Gemini...")
    
    # Build lookup for tweet content -> tweet data (for matching highlighted tweets later)
    tweet_lookup = {}
    for t in all_tweets:
        # Use first 100 chars of content as key for matching
        key = t.content[:100].lower().strip() if t.content else ""
        if key:
            tweet_lookup[key] = {
                "url": getattr(t, 'url', ''),
                "images": getattr(t, 'images', []),
            }
    
    # Compile tweets for analysis - include retweet info and original author
    compiled_lines = []
    for t in all_tweets:
        if getattr(t, 'is_retweet', False):
            original_author = getattr(t, 'original_author', 'unknown')
            line = f"[RETWEET of @{original_author}] [{t.timestamp}] {t.content}"
        else:
            line = f"[{t.timestamp}] {t.content}"
        compiled_lines.append(line)
    compiled = "\n---\n".join(compiled_lines)
    
    # Truncate if too long (Gemini context limit)
    if len(compiled) > 100000:
        compiled = compiled[:100000] + "\n\n[TRUNCATED - too many tweets]"

    try:
        analyzer = GeminiAnalyzer(api_key=gemini_key)
        analysis_result = analyzer.analyze(
            compiled_tweets=compiled,
            username=username,
            tweet_count=len(all_tweets),
            custom_prompt=request.custom_prompt,
        )
        logger.info(f"[Step 3] Analysis complete")
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # Match highlighted tweets to their URLs and images
    highlighted_with_urls = []
    for ht in analysis_result.highlighted_tweets:
        text = ht.get("text", "")
        reason = ht.get("reason", "")
        
        # Try to find matching tweet by content prefix
        key = text[:100].lower().strip() if text else ""
        matched = tweet_lookup.get(key, {})
        
        # Also try fuzzy matching if exact match fails
        if not matched and text:
            for lookup_key, data in tweet_lookup.items():
                if lookup_key[:50] in text[:60].lower() or text[:50].lower() in lookup_key[:60]:
                    matched = data
                    break
        
        highlighted_with_urls.append(HighlightedTweet(
            text=text,
            reason=reason,
            url=matched.get("url", ""),
            images=matched.get("images", []),
        ))

    return AnalyzeResponse(
        username=username,
        tweets_scraped=tweets_count,
        retweets_scraped=retweets_count,
        analysis=analysis_result.summary,
        themes=analysis_result.themes,
        highlighted_tweets=highlighted_with_urls,
        chunks_processed=analysis_result.chunks_processed,
        error=analysis_result.error,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)
