"""
Direct Twitter Scraper using snscrape

Scrapes tweets directly from Twitter without needing Nitter.
"""

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import snscrape.modules.twitter as sntwitter
from dotenv import load_dotenv

load_dotenv()


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


class TwitterScraper:
    """Scrapes tweets directly from Twitter using snscrape."""

    def __init__(
        self,
        max_tweets: int = 500,
    ):
        self.max_tweets = max_tweets

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
        result = ScrapeResult(username=username)
        
        try:
            if progress_callback:
                await progress_callback(0, f"Starting to scrape @{username}...")

            # Build query
            query = f"from:{username}"
            if not include_retweets:
                query += " -filter:retweets"
            if not include_replies:
                query += " -filter:replies"

            # Use snscrape to get tweets
            # Run in executor since snscrape is synchronous
            loop = asyncio.get_event_loop()
            tweets = await loop.run_in_executor(
                None,
                lambda: list(sntwitter.TwitterSearchScraper(query).get_items())[:self.max_tweets]
            )

            for idx, tweet_obj in enumerate(tweets):
                if progress_callback and idx % 10 == 0:
                    await progress_callback(idx, f"Scraped {idx} tweets so far...")

                # Convert to our Tweet format
                tweet = Tweet(
                    id=str(tweet_obj.id),
                    content=tweet_obj.rawContent or tweet_obj.content or "",
                    timestamp=tweet_obj.date.isoformat() if tweet_obj.date else "",
                    retweets=tweet_obj.retweetCount or 0,
                    quotes=tweet_obj.quoteCount or 0,
                    likes=tweet_obj.likeCount or 0,
                    replies=tweet_obj.replyCount or 0,
                    is_retweet=hasattr(tweet_obj, 'retweetedTweet') and tweet_obj.retweetedTweet is not None,
                    is_reply=tweet_obj.inReplyToTweetId is not None,
                )
                
                result.tweets.append(tweet)

            result.total_scraped = len(result.tweets)
            
            if progress_callback:
                await progress_callback(result.total_scraped, f"Complete! Scraped {result.total_scraped} tweets")

        except Exception as e:
            error_msg = str(e)
            result.error = f"Scraping error: {error_msg}"
            print(f"Error scraping @{username}: {error_msg}")
            
            # Check if it's a rate limit or not found error
            if "not found" in error_msg.lower() or "doesn't exist" in error_msg.lower():
                result.error = f"User @{username} not found or account is private"
            elif "rate" in error_msg.lower() or "429" in error_msg:
                result.rate_limited = True
                result.error = "Rate limited by Twitter"

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
        compiled = compiled[:max_chars]
        compiled += "\n\n[... truncated due to length ...]"

    return compiled



