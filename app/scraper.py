"""
Nitter Tweet Scraper Module

Scrapes tweets from a Nitter instance with pagination and rate-limit handling.
"""

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse, parse_qs

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
logger = logging.getLogger("scraper")


@dataclass
class Tweet:
    """Represents a single tweet."""
    id: str
    content: str
    timestamp: str
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


class NitterScraper:
    """Scrapes tweets from a Nitter instance."""

    def __init__(
        self,
        nitter_url: Optional[str] = None,
        delay_seconds: float = 1.0,
        max_tweets: int = 500,
    ):
        self.nitter_url = nitter_url or os.getenv("NITTER_URL", "http://localhost:8080")
        self.delay_seconds = delay_seconds
        self.max_tweets = max_tweets
        self.client: Optional[httpx.AsyncClient] = None
        logger.info(f"NitterScraper initialized: url={self.nitter_url}, delay={delay_seconds}s, max_tweets={max_tweets}")

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

    def _parse_tweet(self, tweet_elem, username: str) -> Optional[Tweet]:
        """Parse a single tweet element from Nitter HTML."""
        try:
            # Get tweet link to extract ID
            tweet_link = tweet_elem.select_one('.tweet-link')
            if not tweet_link:
                return None
            
            href = tweet_link.get('href', '')
            # Extract tweet ID from URL like /username/status/1234567890
            match = re.search(r'/status/(\d+)', href)
            if not match:
                return None
            tweet_id = match.group(1)

            # Get tweet content
            content_elem = tweet_elem.select_one('.tweet-content')
            content = content_elem.get_text(strip=True) if content_elem else ""

            # Get timestamp
            time_elem = tweet_elem.select_one('.tweet-date a')
            timestamp = time_elem.get('title', '') if time_elem else ""

            # Get engagement stats
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

            # Check if retweet
            retweet_header = tweet_elem.select_one('.retweet-header')
            is_retweet = retweet_header is not None

            # Check if reply
            replying_to = tweet_elem.select_one('.replying-to')
            is_reply = replying_to is not None

            return Tweet(
                id=tweet_id,
                content=content,
                timestamp=timestamp,
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
        """Extract the next page cursor from the 'Load more' link."""
        # Look for .show-more links that contain a cursor parameter
        show_more_links = soup.select('.show-more a[href*="cursor"]')
        if not show_more_links:
            logger.debug("No .show-more a[href*=cursor] element found")
            return None
        
        # Use the first link with a cursor
        show_more = show_more_links[0]
        href = show_more.get('href', '')
        logger.debug(f"Found show-more href: {href[:100]}...")
        parsed = urlparse(href)
        params = parse_qs(parsed.query)
        cursor = params.get('cursor', [None])[0]
        if cursor:
            logger.info(f"Found next cursor: {cursor[:30]}...")
        return cursor

    async def scrape_user(
        self,
        username: str,
        include_retweets: bool = False,
        include_replies: bool = False,
        progress_callback=None,
    ) -> ScrapeResult:
        """
        Scrape tweets from a user's timeline.
        
        Args:
            username: Twitter username (without @)
            include_retweets: Whether to include retweets
            include_replies: Whether to include replies
            progress_callback: Optional async callback(current_count, status_message)
        
        Returns:
            ScrapeResult with collected tweets
        """
        if not self.client:
            raise RuntimeError("Scraper must be used as async context manager")

        logger.info(f"")
        logger.info(f"{'='*60}")
        logger.info(f"SCRAPE START: @{username}")
        logger.info(f"{'='*60}")
        logger.info(f"  Max tweets: {self.max_tweets}")
        logger.info(f"  Include RTs: {include_retweets} | Include replies: {include_replies}")
        logger.info(f"  Delay between pages: {self.delay_seconds}s")
        logger.info(f"{'='*60}")
        
        result = ScrapeResult(username=username)
        seen_ids = set()
        cursor = None
        consecutive_empty = 0
        page_count = 0

        while len(result.tweets) < self.max_tweets:
            page_count += 1
            
            # Build URL
            url = f"{self.nitter_url}/{username}"
            if cursor:
                url += f"?cursor={cursor}"

            logger.info(f"")
            logger.info(f"[PAGE {page_count}] Fetching...")

            if progress_callback:
                await progress_callback(
                    len(result.tweets),
                    f"Fetching page {page_count}... ({len(result.tweets)} tweets so far)"
                )

            try:
                response = await self.client.get(url)
                logger.info(f"[PAGE {page_count}] Response: HTTP {response.status_code}")
                
                if response.status_code == 429:
                    result.rate_limited = True
                    result.error = "Rate limited by Nitter instance"
                    logger.warning(f"RATE LIMITED after {len(result.tweets)} tweets on page {page_count}")
                    break
                
                if response.status_code == 404:
                    result.error = f"User @{username} not found"
                    logger.error(f"User @{username} not found (404)")
                    break
                
                if response.status_code != 200:
                    result.error = f"HTTP error: {response.status_code}"
                    logger.error(f"HTTP error: {response.status_code}")
                    break

                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Check for error messages
                error_panel = soup.select_one('.error-panel')
                if error_panel:
                    error_text = error_panel.get_text(strip=True)
                    logger.error(f"Nitter error panel: {error_text}")
                    if "not found" in error_text.lower():
                        result.error = f"User @{username} not found"
                    elif "rate" in error_text.lower():
                        result.rate_limited = True
                        result.error = "Rate limited"
                    else:
                        result.error = error_text
                    break

                # Parse tweets
                tweet_elements = soup.select('.timeline-item .tweet-body')
                
                new_tweets_count = 0
                skipped_retweets = 0
                skipped_replies = 0
                skipped_duplicates = 0

                for elem in tweet_elements:
                    if len(result.tweets) >= self.max_tweets:
                        logger.info(f"Reached max_tweets limit ({self.max_tweets})")
                        break
                    
                    # Get parent timeline-item for full context
                    parent = elem.find_parent(class_='timeline-item')
                    if not parent:
                        continue

                    tweet = self._parse_tweet(parent, username)
                    if not tweet:
                        continue
                    
                    if tweet.id in seen_ids:
                        skipped_duplicates += 1
                        continue
                    
                    # Filter based on preferences
                    if not include_retweets and tweet.is_retweet:
                        skipped_retweets += 1
                        continue
                    if not include_replies and tweet.is_reply:
                        skipped_replies += 1
                        continue
                    
                    seen_ids.add(tweet.id)
                    result.tweets.append(tweet)
                    new_tweets_count += 1

                logger.info(f"[PAGE {page_count}] +{new_tweets_count} tweets (skipped: {skipped_retweets} RTs, {skipped_replies} replies, {skipped_duplicates} dupes)")
                logger.info(f"[PAGE {page_count}] TOTAL: {len(result.tweets)}/{self.max_tweets} tweets collected")

                if new_tweets_count == 0:
                    consecutive_empty += 1
                    logger.warning(f"[PAGE {page_count}] No new tweets (consecutive empty: {consecutive_empty}/3)")
                    if consecutive_empty >= 3:
                        logger.info("[STOP] 3 consecutive empty pages")
                        break
                else:
                    consecutive_empty = 0

                # Get next page cursor
                cursor = self._get_next_cursor(soup)
                if not cursor:
                    logger.info("[STOP] No more pages available")
                    break

                # Rate limit delay
                logger.info(f"[PAGE {page_count}] Waiting {self.delay_seconds}s...")
                await asyncio.sleep(self.delay_seconds)

            except httpx.TimeoutException:
                result.error = "Request timed out"
                logger.error(f"Request timed out on page {page_count}")
                break
            except httpx.RequestError as e:
                result.error = f"Request error: {str(e)}"
                logger.error(f"Request error on page {page_count}: {e}")
                break
            except Exception as e:
                result.error = f"Unexpected error: {str(e)}"
                logger.exception(f"Unexpected error on page {page_count}")
                break

        result.total_scraped = len(result.tweets)
        
        logger.info(f"")
        logger.info(f"{'='*60}")
        logger.info(f"SCRAPE COMPLETE: @{username}")
        logger.info(f"{'='*60}")
        logger.info(f"  Total tweets: {result.total_scraped}")
        logger.info(f"  Pages fetched: {page_count}")
        logger.info(f"  Rate limited: {result.rate_limited}")
        logger.info(f"  Error: {result.error or 'None'}")
        logger.info(f"{'='*60}")
        
        if progress_callback:
            status = "Complete" if not result.error else f"Stopped: {result.error}"
            await progress_callback(result.total_scraped, status)

        return result


def compile_tweets_for_analysis(result: ScrapeResult, max_chars: int = 100000) -> str:
    """
    Compile scraped tweets into a text format suitable for Gemini analysis.
    
    Args:
        result: ScrapeResult from scraper
        max_chars: Maximum characters to include (to respect token limits)
    
    Returns:
        Formatted string of tweets
    """
    if not result.tweets:
        return ""

    lines = [
        f"Tweets from @{result.username}",
        f"Total tweets: {result.total_scraped}",
        "=" * 50,
        ""
    ]

    for tweet in result.tweets:
        tweet_text = f"[{tweet.timestamp}] {tweet.content}"
        if tweet.is_retweet:
            tweet_text = "[RT] " + tweet_text
        if tweet.is_reply:
            tweet_text = "[Reply] " + tweet_text
        
        lines.append(tweet_text)
        lines.append(f"  Likes: {tweet.likes} | Retweets: {tweet.retweets} | Replies: {tweet.replies}")
        lines.append("")

    compiled = "\n".join(lines)
    
    # Truncate if too long
    if len(compiled) > max_chars:
        logger.info(f"Truncating compiled tweets from {len(compiled)} to {max_chars} chars")
        compiled = compiled[:max_chars]
        compiled += "\n\n[... truncated due to length ...]"

    logger.info(f"Compiled {result.total_scraped} tweets into {len(compiled)} characters")
    return compiled
