"""
Nitter Search-Based Tweet Scraper

Uses the search endpoint with date ranges to bypass timeline pagination limits.
"""

import asyncio
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin, urlparse, parse_qs, quote

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("search_scraper")


@dataclass
class Tweet:
    """Represents a single tweet."""
    id: str
    content: str
    timestamp: str
    url: str = ""
    images: list = field(default_factory=list)
    retweets: int = 0
    quotes: int = 0
    likes: int = 0
    replies: int = 0
    is_retweet: bool = False
    is_reply: bool = False


@dataclass
class ScrapeResult:
    """Result of a scraping operation."""
    username: str
    tweets: list[Tweet] = field(default_factory=list)
    error: Optional[str] = None
    rate_limited: bool = False
    total_scraped: int = 0
    date_ranges_processed: int = 0


class NitterSearchScraper:
    """Scrapes tweets using Nitter's search endpoint with date chunking."""

    # Mullvad CLI path - auto-detect OS, override with MULLVAD_CLI env var
    if os.name == 'nt':  # Windows
        MULLVAD_CLI = os.getenv("MULLVAD_CLI", r"C:\Program Files\Mullvad VPN\resources\mullvad.exe")
    else:  # Linux/Mac
        MULLVAD_CLI = os.getenv("MULLVAD_CLI", "/usr/bin/mullvad")
    VPN_COUNTRIES = ["us", "gb", "de", "nl", "se", "ch", "ca", "fr", "jp", "au", "sg", "br", "it", "es", "pl", "fi", "no", "dk", "at", "be"]

    def __init__(
        self,
        nitter_url: Optional[str] = None,
        delay_seconds: float = 0.5,  # Fast - we restart on rate limit anyway
        max_tweets: int = 10000,
        chunk_days: int = 30,
        max_restarts: int = 50,  # Allow many restarts for large scrapes
        docker_compose_path: str = ".",
        nitter_redis_host: Optional[str] = None,  # For Docker mode: direct Redis connection
    ):
        self.nitter_url = nitter_url or os.getenv("NITTER_URL", "http://localhost:8080")
        self.delay_seconds = delay_seconds
        self.max_tweets = max_tweets
        self.chunk_days = chunk_days
        self.max_restarts = max_restarts
        self.docker_compose_path = docker_compose_path
        self.restart_count = 0
        self.client: Optional[httpx.AsyncClient] = None
        
        # Docker mode: when running inside a container, use direct Redis connection
        self.nitter_redis_host = nitter_redis_host or os.getenv("NITTER_REDIS_HOST")
        self.docker_mode = self.nitter_redis_host is not None
        
        logger.info(f"NitterSearchScraper initialized: url={self.nitter_url}, delay={delay_seconds}s, chunk_days={chunk_days}")
        if self.docker_mode:
            logger.info(f"  Docker mode: Redis at {self.nitter_redis_host}")

    def _flush_redis(self) -> bool:
        """Flush Redis to clear rate limit cache."""
        logger.info("    Flushing Redis cache...")
        try:
            if self.docker_mode:
                # Docker mode: connect directly to Redis
                result = subprocess.run(
                    ["redis-cli", "-h", self.nitter_redis_host, "FLUSHALL"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
            else:
                # Host mode: use docker exec
                result = subprocess.run(
                    ["docker", "exec", "nitter-redis", "redis-cli", "FLUSHALL"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"    Redis flush error: {e}")
            return False

    def _stop_nitter(self) -> bool:
        """Stop Nitter container (keep Redis running)."""
        if self.docker_mode:
            # In Docker mode, use docker CLI to restart sibling container
            # Extract nitter container name from URL (e.g., http://nitter-1:8080 -> nitter-1)
            nitter_name = self.nitter_url.split("//")[1].split(":")[0]
            logger.info(f"    Docker mode: restarting {nitter_name}...")
            try:
                result = subprocess.run(
                    ["docker", "restart", nitter_name],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    logger.info(f"    Restarted {nitter_name}")
                    return True
                else:
                    logger.warning(f"    Failed to restart {nitter_name}: {result.stderr}")
                    return False
            except Exception as e:
                logger.warning(f"    Docker restart error: {e}")
                return False
        
        logger.info("    Stopping Nitter...")
        result = subprocess.run(
            ["docker-compose", "stop", "nitter"],
            cwd=self.docker_compose_path,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0

    def _start_nitter(self) -> bool:
        """Start Nitter container."""
        if self.docker_mode:
            # In Docker mode, restart already handled in _stop_nitter
            return True
        
        logger.info("    Starting Nitter...")
        result = subprocess.run(
            ["docker-compose", "start", "nitter"],
            cwd=self.docker_compose_path,
            capture_output=True,
            text=True,
            timeout=60
        )
        return result.returncode == 0

    def _switch_vpn(self) -> bool:
        """Switch Mullvad VPN to a new country."""
        country = self.VPN_COUNTRIES[self.restart_count % len(self.VPN_COUNTRIES)]
        
        try:
            logger.info(f"    Switching VPN to {country.upper()}...")
            
            # Set new location
            subprocess.run(
                [self.MULLVAD_CLI, "relay", "set", "location", country],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Reconnect and wait
            logger.info(f"    Reconnecting...")
            result = subprocess.run(
                [self.MULLVAD_CLI, "reconnect", "--wait"],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                logger.error(f"    VPN reconnect failed: {result.stderr}")
                return False
            
            # Verify connection
            result = subprocess.run(
                [self.MULLVAD_CLI, "status"],
                capture_output=True,
                text=True,
                timeout=10
            )
            status = result.stdout.strip().split('\n')[0]
            logger.info(f"    VPN: {status}")
            
            return "Connected" in status
            
        except subprocess.TimeoutExpired:
            logger.error("    VPN command timed out")
            return False
        except FileNotFoundError:
            logger.warning("    Mullvad CLI not found")
            return False
        except Exception as e:
            logger.error(f"    VPN error: {e}")
            return False

    def _connect_vpn(self) -> bool:
        """Connect Mullvad VPN."""
        try:
            logger.info("    Connecting Mullvad VPN...")
            result = subprocess.run(
                [self.MULLVAD_CLI, "connect"],
                capture_output=True,
                text=True,
                timeout=30
            )
            return True
        except Exception as e:
            logger.error(f"    VPN connect error: {e}")
            return False

    def _disconnect_vpn(self) -> bool:
        """Disconnect Mullvad VPN."""
        try:
            logger.info("    Disconnecting Mullvad VPN...")
            result = subprocess.run(
                [self.MULLVAD_CLI, "disconnect"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return True
        except Exception as e:
            logger.error(f"    VPN disconnect error: {e}")
            return False

    async def _reset_for_rate_limit(self) -> bool:
        """Full reset: Connect VPN -> Flush Redis -> Stop Nitter -> Switch VPN -> Start Nitter."""
        self.restart_count += 1
        
        logger.warning(f"")
        logger.warning(f"{'='*60}")
        logger.warning(f"RATE LIMIT - RESET #{self.restart_count}/{self.max_restarts}")
        logger.warning(f"{'='*60}")
        
        if self.restart_count > self.max_restarts:
            logger.error("Max restarts exceeded")
            return False
        
        try:
            # Close HTTP client
            if self.client:
                await self.client.aclose()
                self.client = None
            
            # Connect VPN first (if not already connected)
            self._connect_vpn()
            
            # 1. Flush Redis (clear rate limit cache)
            self._flush_redis()
            
            # 2. Stop Nitter
            if not self._stop_nitter():
                logger.warning("    Failed to stop Nitter (continuing anyway)")
            
            # 3. Switch VPN IP
            if not self._switch_vpn():
                logger.warning("    VPN switch failed (continuing anyway)")
            
            # 4. Start Nitter
            if not self._start_nitter():
                logger.error("    Failed to start Nitter")
                return False
            
            # 5. Wait for Nitter to be ready
            logger.info("    Waiting for Nitter...")
            await asyncio.sleep(8)
            
            # 5. Recreate HTTP client
            self.client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
            )
            
            # 6. Test Nitter
            for attempt in range(5):
                try:
                    resp = await self.client.get(f"{self.nitter_url}/")
                    if resp.status_code == 200:
                        logger.info(f"    Nitter ready!")
                        logger.warning(f"{'='*60}")
                        return True
                except Exception:
                    pass
                await asyncio.sleep(2)
            
            logger.error("    Nitter not responding")
            return False
                
        except Exception as e:
            logger.error(f"Reset error: {e}")
            return False

    async def __aenter__(self):
        logger.info("Opening HTTP client connection")
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            logger.info("Closing HTTP client connection")
            await self.client.aclose()

    def _parse_stat(self, text: str) -> int:
        """Parse engagement stat text like '1.2K' into integer."""
        if not text:
            return 0
        text = text.strip().upper()
        if not text:
            return 0
        try:
            if 'K' in text:
                return int(float(text.replace('K', '').replace(',', '')) * 1000)
            elif 'M' in text:
                return int(float(text.replace('M', '').replace(',', '')) * 1_000_000)
            else:
                return int(text.replace(',', ''))
        except (ValueError, AttributeError):
            return 0

    def _parse_tweet(self, tweet_elem) -> Optional[Tweet]:
        """Parse a single tweet element from Nitter HTML."""
        import re
        try:
            tweet_link = tweet_elem.select_one('.tweet-link')
            if not tweet_link:
                return None
            
            href = tweet_link.get('href', '')
            match = re.search(r'/status/(\d+)', href)
            if not match:
                return None
            tweet_id = match.group(1)
            
            # Extract username from href for URL
            username_match = re.search(r'^/([^/]+)/', href)
            tweet_username = username_match.group(1) if username_match else ""
            tweet_url = f"https://twitter.com/{tweet_username}/status/{tweet_id}" if tweet_username else ""

            content_elem = tweet_elem.select_one('.tweet-content')
            content = content_elem.get_text(strip=True) if content_elem else ""

            time_elem = tweet_elem.select_one('.tweet-date a')
            timestamp = time_elem.get('title', '') if time_elem else ""
            
            # Extract images from tweet
            images = []
            media_container = tweet_elem.select_one('.attachments')
            if media_container:
                img_elems = media_container.select('img')
                for img in img_elems:
                    src = img.get('src', '')
                    if src and '/pic/' in src:
                        # Nitter proxies images, extract the real URL
                        images.append(f"{self.nitter_url}{src}")
                    elif src:
                        images.append(src)

            stats = tweet_elem.select('.tweet-stat')
            replies = retweets = quotes = likes = 0
            
            for stat in stats:
                icon = stat.select_one('.icon-container')
                value_elem = stat.select_one('.tweet-stat-value, .icon-container + span')
                if not icon:
                    continue
                
                icon_class = ' '.join(icon.get('class', []))
                value = value_elem.get_text(strip=True) if value_elem else "0"
                
                if 'comment' in icon_class or 'reply' in icon_class:
                    replies = self._parse_stat(value)
                elif 'retweet' in icon_class:
                    retweets = self._parse_stat(value)
                elif 'quote' in icon_class:
                    quotes = self._parse_stat(value)
                elif 'heart' in icon_class or 'like' in icon_class:
                    likes = self._parse_stat(value)

            retweet_header = tweet_elem.select_one('.retweet-header')
            is_retweet = retweet_header is not None

            replying_to = tweet_elem.select_one('.replying-to')
            is_reply = replying_to is not None

            return Tweet(
                id=tweet_id,
                content=content,
                timestamp=timestamp,
                url=tweet_url,
                images=images,
                retweets=retweets,
                quotes=quotes,
                likes=likes,
                replies=replies,
                is_retweet=is_retweet,
                is_reply=is_reply,
            )
        except Exception as e:
            logger.error(f"Error parsing tweet: {e}")
            return None

    def _get_next_cursor(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract the next page cursor."""
        show_more_links = soup.select('.show-more a[href*="cursor"]')
        if not show_more_links:
            return None
        
        show_more = show_more_links[0]
        href = show_more.get('href', '')
        parsed = urlparse(href)
        params = parse_qs(parsed.query)
        cursor = params.get('cursor', [None])[0]
        return cursor

    def _generate_date_ranges(self, start_date: datetime, end_date: datetime) -> list[tuple[str, str]]:
        """Generate date range chunks from start to end."""
        ranges = []
        current = start_date
        
        while current < end_date:
            chunk_end = min(current + timedelta(days=self.chunk_days), end_date)
            ranges.append((
                current.strftime('%Y-%m-%d'),
                chunk_end.strftime('%Y-%m-%d')
            ))
            current = chunk_end
        
        return ranges

    async def _scrape_date_range(
        self,
        username: str,
        since: str,
        until: str,
        seen_ids: set,
        include_retweets: bool,
        include_replies: bool,
    ) -> tuple[list[Tweet], bool, Optional[str]]:
        """Scrape all tweets within a single date range."""
        tweets = []
        cursor = None
        page = 0
        rate_limited = False
        error = None

        while True:
            page += 1
            
            # Build search query
            query = f"from:{username} since:{since} until:{until}"
            url = f"{self.nitter_url}/search?f=tweets&q={quote(query)}"
            if cursor:
                url += f"&cursor={cursor}"

            logger.info(f"    [Page {page}] Fetching...")

            try:
                response = await self.client.get(url)
                
                # Handle rate limiting - reset everything
                if response.status_code == 429:
                    logger.warning(f"    RATE LIMITED on page {page}")
                    
                    if await self._reset_for_rate_limit():
                        logger.info(f"    Resuming from page {page}")
                        page -= 1
                        continue
                    else:
                        rate_limited = True
                        error = "Rate limited (reset failed)"
                        break
                
                if response.status_code != 200:
                    error = f"HTTP {response.status_code}"
                    logger.error(f"    HTTP error: {response.status_code}")
                    break

                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Check for rate limit in page content
                error_panel = soup.select_one('.error-panel')
                if error_panel:
                    error_text = error_panel.get_text(strip=True)
                    if "rate" in error_text.lower():
                        logger.warning(f"    Rate limit in page")
                        if await self._reset_for_rate_limit():
                            page -= 1
                            continue
                        else:
                            rate_limited = True
                            error = "Rate limited (reset failed)"
                            break
                    else:
                        error = error_text
                        logger.error(f"    Nitter error: {error_text}")
                        break

                # Parse tweets
                tweet_elements = soup.select('.timeline-item .tweet-body')
                new_count = 0

                for elem in tweet_elements:
                    parent = elem.find_parent(class_='timeline-item')
                    if not parent:
                        continue

                    tweet = self._parse_tweet(parent)
                    if not tweet or tweet.id in seen_ids:
                        continue
                    
                    if not include_retweets and tweet.is_retweet:
                        continue
                    if not include_replies and tweet.is_reply:
                        continue
                    
                    seen_ids.add(tweet.id)
                    tweets.append(tweet)
                    new_count += 1

                logger.info(f"    [Page {page}] +{new_count} tweets (total this range: {len(tweets)})")

                if new_count == 0:
                    break

                # Get next cursor
                cursor = self._get_next_cursor(soup)
                if not cursor:
                    logger.info(f"    [Page {page}] No more pages")
                    break

                # Small delay between pages (we reset on rate limit anyway)
                await asyncio.sleep(self.delay_seconds)

            except httpx.TimeoutException:
                error = "Timeout"
                logger.error(f"    Timeout on page {page}")
                break
            except Exception as e:
                error = str(e)
                logger.exception(f"    Error on page {page}")
                break

        return tweets, rate_limited, error

    async def scrape_user(
        self,
        username: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        include_retweets: bool = True,
        include_replies: bool = True,
    ) -> ScrapeResult:
        """
        Scrape tweets using search with date chunking.
        """
        if not self.client:
            raise RuntimeError("Scraper must be used as async context manager")

        # Default date range: last 1 year
        if end_date is None:
            end_date = datetime.now()
        if start_date is None:
            start_date = end_date - timedelta(days=365)

        logger.info(f"")
        logger.info(f"{'='*60}")
        logger.info(f"SEARCH SCRAPE START: @{username}")
        logger.info(f"{'='*60}")
        logger.info(f"  Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        logger.info(f"  Chunk size: {self.chunk_days} days")
        logger.info(f"  Max tweets: {self.max_tweets}")
        logger.info(f"  Include RTs: {include_retweets} | Include replies: {include_replies}")
        logger.info(f"{'='*60}")

        result = ScrapeResult(username=username)
        seen_ids = set()
        
        # Generate date ranges (most recent first)
        date_ranges = self._generate_date_ranges(start_date, end_date)
        date_ranges.reverse()
        
        logger.info(f"Generated {len(date_ranges)} date ranges to process")

        for i, (since, until) in enumerate(date_ranges, 1):
            if len(result.tweets) >= self.max_tweets:
                logger.info(f"Reached max tweets limit ({self.max_tweets})")
                break

            logger.info(f"")
            logger.info(f"[RANGE {i}/{len(date_ranges)}] {since} to {until}")
            
            tweets, rate_limited, error = await self._scrape_date_range(
                username=username,
                since=since,
                until=until,
                seen_ids=seen_ids,
                include_retweets=include_retweets,
                include_replies=include_replies,
            )
            
            result.tweets.extend(tweets)
            result.date_ranges_processed += 1
            
            logger.info(f"[RANGE {i}] Collected {len(tweets)} tweets | Running total: {len(result.tweets)}")
            
            if rate_limited:
                result.rate_limited = True
                result.error = "Rate limited"
                logger.warning("Stopping due to rate limit")
                break

        result.total_scraped = len(result.tweets)
        
        # Disconnect VPN if we used it (to restore server accessibility)
        if self.restart_count > 0:
            logger.info("    Disconnecting VPN (restoring server access)...")
            self._disconnect_vpn()
        
        logger.info(f"")
        logger.info(f"{'='*60}")
        logger.info(f"SEARCH SCRAPE COMPLETE: @{username}")
        logger.info(f"{'='*60}")
        logger.info(f"  Total tweets: {result.total_scraped}")
        logger.info(f"  Date ranges processed: {result.date_ranges_processed}/{len(date_ranges)}")
        logger.info(f"  VPN/Nitter restarts: {self.restart_count}")
        logger.info(f"  Rate limited: {result.rate_limited}")
        logger.info(f"  Error: {result.error or 'None'}")
        logger.info(f"{'='*60}")

        return result
