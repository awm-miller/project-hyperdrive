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
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .scraper_search import NitterSearchScraper
from .scraper_timeline import NitterTimelineScraper
from .analyzer import GeminiAnalyzer

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("api")

# Get configuration from environment
NITTER_URL = os.getenv("NITTER_URL", "http://localhost:8080")
DOCKER_COMPOSE_PATH = os.getenv("DOCKER_COMPOSE_PATH", "C:\\Users\\Alex\\GitHub\\project-hyperdrive")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("=" * 60)
    logger.info("NITTER TWEET ANALYZER - STARTING UP")
    logger.info("=" * 60)
    logger.info(f"Nitter URL: {NITTER_URL}")
    logger.info(f"Docker Compose Path: {DOCKER_COMPOSE_PATH}")
    logger.info(f"Gemini API key configured: {bool(os.getenv('GEMINI_API_KEY'))}")
    logger.info("=" * 60)
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="Nitter Tweet Analyzer",
    description="Scrape tweets via Nitter and analyze them with Gemini",
    version="2.0.0",
    lifespan=lifespan,
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


class AnalyzeResponse(BaseModel):
    """Response for analysis endpoint."""
    username: str
    tweets_scraped: int
    retweets_scraped: int
    analysis: str
    themes: list[str]
    error: Optional[str] = None
    rate_limited: bool = False


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    nitter_url: str
    gemini_configured: bool


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
    
    # Compile tweets for analysis
    compiled_lines = []
    for t in all_tweets:
        prefix = "[RT] " if getattr(t, 'is_retweet', False) else ""
        compiled_lines.append(f"{prefix}[{t.timestamp}] {t.content}")
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

    return AnalyzeResponse(
        username=username,
        tweets_scraped=tweets_count,
        retweets_scraped=retweets_count,
        analysis=analysis_result.summary,
        themes=analysis_result.themes,
        error=analysis_result.error,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)
