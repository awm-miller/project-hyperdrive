"""
Nitter Timeline Scraper - For Retweets

Scrapes the user's timeline to collect retweets.
Uses pagination to go as far back as possible.
"""

import asyncio
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, parse_qs

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
logger = logging.getLogger("timeline_scraper")


@dataclass
class Tweet:
    """Represents a single tweet/retweet."""
    id: str
    content: str
    timestamp: str
    url: str = ""
    images: list = field(default_factory=list)
    original_author: str = ""  # For retweets, the original author
    retweets: int = 0
    quotes: int = 0
    likes: int = 0
    replies: int = 0
    is_retweet: bool = False


@dataclass
class ScrapeResult:
    """Result of a scraping operation."""
    username: str
    tweets: list[Tweet] = field(default_factory=list)
    error: Optional[str] = None
    rate_limited: bool = False
    total_scraped: int = 0
    pages_processed: int = 0


class NitterTimelineScraper:
    """Scrapes retweets from user timeline with rate limit handling."""

    # Mullvad CLI path - auto-detect OS, override with MULLVAD_CLI env var
    if os.name == 'nt':  # Windows
        MULLVAD_CLI = os.getenv("MULLVAD_CLI", r"C:\Program Files\Mullvad VPN\resources\mullvad.exe")
    else:  # Linux/Mac
        MULLVAD_CLI = os.getenv("MULLVAD_CLI", "/usr/bin/mullvad")
    VPN_COUNTRIES = ["us", "gb", "de", "nl", "se", "ch", "ca", "fr", "jp", "au", "sg", "br", "it", "es", "pl", "fi", "no", "dk", "at", "be"]

    def __init__(
        self,
        nitter_url: Optional[str] = None,
        delay_seconds: float = 0.5,
        max_retweets: int = 10000,
        max_restarts: int = 1000,
        docker_compose_path: str = ".",
    ):
        self.nitter_url = nitter_url or os.getenv("NITTER_URL", "http://localhost:8080")
        self.delay_seconds = delay_seconds
        self.max_retweets = max_retweets
        self.max_restarts = max_restarts
        self.docker_compose_path = docker_compose_path
        self.restart_count = 0
        self.client: Optional[httpx.AsyncClient] = None
        logger.info(f"NitterTimelineScraper initialized: url={self.nitter_url}, max_retweets={max_retweets}")

    def _flush_redis(self) -> bool:
        """Flush Redis to clear rate limit cache."""
        logger.info("    Flushing Redis cache...")
        result = subprocess.run(
            ["docker", "exec", "nitter-redis", "redis-cli", "FLUSHALL"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0

    def _stop_nitter(self) -> bool:
        """Stop Nitter container."""
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
            
            subprocess.run(
                [self.MULLVAD_CLI, "relay", "set", "location", country],
                capture_output=True,
                text=True,
                timeout=30
            )
            
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
            asyncio.sleep(3)  # Give it time to connect
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
            if self.client:
                await self.client.aclose()
                self.client = None
            
            # Connect VPN first (if not already connected)
            self._connect_vpn()
            
            self._flush_redis()
            
            if not self._stop_nitter():
                logger.warning("    Failed to stop Nitter (continuing anyway)")
            
            if not self._switch_vpn():
                logger.warning("    VPN switch failed (continuing anyway)")
            
            if not self._start_nitter():
                logger.error("    Failed to start Nitter")
                return False
            
            logger.info("    Waiting for Nitter...")
            await asyncio.sleep(8)
            
            self.client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
            )
            
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

    def _parse_retweet(self, tweet_elem) -> Optional[Tweet]:
        """Parse a retweet element from Nitter HTML."""
        import re
        try:
            # Check if this is a retweet
            retweet_header = tweet_elem.select_one('.retweet-header')
            if not retweet_header:
                return None  # Not a retweet, skip
            
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

            # Get original author from the tweet body
            username_elem = tweet_elem.select_one('.tweet-body .username')
            original_author = username_elem.get_text(strip=True) if username_elem else ""

            content_elem = tweet_elem.select_one('.tweet-content')
            content = content_elem.get_text(strip=True) if content_elem else ""

            time_elem = tweet_elem.select_one('.tweet-date a')
            timestamp = time_elem.get('title', '') if time_elem else ""
            
            # Extract images
            images = []
            media_container = tweet_elem.select_one('.attachments')
            if media_container:
                img_elems = media_container.select('img')
                for img in img_elems:
                    src = img.get('src', '')
                    if src and '/pic/' in src:
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

            return Tweet(
                id=tweet_id,
                content=content,
                timestamp=timestamp,
                url=tweet_url,
                images=images,
                original_author=original_author,
                retweets=retweets,
                quotes=quotes,
                likes=likes,
                replies=replies,
                is_retweet=True,
            )
        except Exception as e:
            logger.error(f"Error parsing retweet: {e}")
            return None

    def _get_next_cursor(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract the next page cursor from 'Load more' link."""
        # Look for the load more link with cursor parameter
        show_more_links = soup.select('.show-more a[href*="cursor"]')
        if not show_more_links:
            return None
        
        # Get the last one (pagination, not "load newest")
        for link in show_more_links:
            href = link.get('href', '')
            if 'cursor=' in href:
                parsed = urlparse(href)
                params = parse_qs(parsed.query)
                cursor = params.get('cursor', [None])[0]
                if cursor:
                    return cursor
        return None

    async def scrape_retweets(
        self,
        username: str,
    ) -> ScrapeResult:
        """
        Scrape all retweets from user's timeline.
        Goes as far back as possible using pagination.
        """
        if not self.client:
            raise RuntimeError("Scraper must be used as async context manager")

        logger.info(f"")
        logger.info(f"{'='*60}")
        logger.info(f"TIMELINE RETWEET SCRAPE: @{username}")
        logger.info(f"{'='*60}")
        logger.info(f"  Max retweets: {self.max_retweets}")
        logger.info(f"  Delay between pages: {self.delay_seconds}s")
        logger.info(f"{'='*60}")

        result = ScrapeResult(username=username)
        seen_ids = set()
        cursor = None
        page = 0
        consecutive_empty = 0

        while len(result.tweets) < self.max_retweets:
            page += 1
            
            # Build URL
            url = f"{self.nitter_url}/{username}"
            if cursor:
                url += f"?cursor={cursor}"

            logger.info(f"[Page {page}] Fetching...")

            try:
                response = await self.client.get(url)
                
                # Handle rate limiting
                if response.status_code == 429:
                    logger.warning(f"[Page {page}] RATE LIMITED")
                    
                    if await self._reset_for_rate_limit():
                        logger.info(f"    Resuming from page {page}")
                        page -= 1
                        continue
                    else:
                        result.rate_limited = True
                        result.error = "Rate limited (reset failed)"
                        break
                
                if response.status_code != 200:
                    result.error = f"HTTP {response.status_code}"
                    logger.error(f"[Page {page}] HTTP error: {response.status_code}")
                    break

                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Check for rate limit in page content
                error_panel = soup.select_one('.error-panel')
                if error_panel:
                    error_text = error_panel.get_text(strip=True)
                    if "rate" in error_text.lower():
                        logger.warning(f"[Page {page}] Rate limit in page")
                        if await self._reset_for_rate_limit():
                            page -= 1
                            continue
                        else:
                            result.rate_limited = True
                            result.error = "Rate limited (reset failed)"
                            break
                    else:
                        result.error = error_text
                        logger.error(f"[Page {page}] Nitter error: {error_text}")
                        break

                # Check for "no more items"
                timeline_end = soup.select_one('.timeline-end')
                if timeline_end:
                    logger.info(f"[Page {page}] Reached end of timeline")
                    break

                # Parse retweets only
                timeline_items = soup.select('.timeline-item')
                new_count = 0
                page_total = 0

                for item in timeline_items:
                    page_total += 1
                    tweet = self._parse_retweet(item)
                    if not tweet:
                        continue  # Not a retweet
                    
                    if tweet.id in seen_ids:
                        continue
                    
                    seen_ids.add(tweet.id)
                    result.tweets.append(tweet)
                    new_count += 1

                logger.info(f"[Page {page}] +{new_count} retweets (from {page_total} items) | Total: {len(result.tweets)}")

                if new_count == 0:
                    consecutive_empty += 1
                    if consecutive_empty >= 5:
                        logger.info(f"[Page {page}] 5 consecutive pages with no new retweets, stopping")
                        break
                else:
                    consecutive_empty = 0

                # Get next cursor
                cursor = self._get_next_cursor(soup)
                if not cursor:
                    logger.info(f"[Page {page}] No more pages (no cursor)")
                    break

                result.pages_processed = page
                await asyncio.sleep(self.delay_seconds)

            except httpx.TimeoutException:
                result.error = "Timeout"
                logger.error(f"[Page {page}] Timeout")
                break
            except Exception as e:
                result.error = str(e)
                logger.exception(f"[Page {page}] Error")
                break

        result.total_scraped = len(result.tweets)
        result.pages_processed = page
        
        # Disconnect VPN if we used it (to restore server accessibility)
        if self.restart_count > 0:
            logger.info("    Disconnecting VPN (restoring server access)...")
            self._disconnect_vpn()
        
        logger.info(f"")
        logger.info(f"{'='*60}")
        logger.info(f"RETWEET SCRAPE COMPLETE: @{username}")
        logger.info(f"{'='*60}")
        logger.info(f"  Total retweets: {result.total_scraped}")
        logger.info(f"  Pages processed: {result.pages_processed}")
        logger.info(f"  VPN/Nitter restarts: {self.restart_count}")
        logger.info(f"  Rate limited: {result.rate_limited}")
        logger.info(f"  Error: {result.error or 'None'}")
        logger.info(f"{'='*60}")

        return result

