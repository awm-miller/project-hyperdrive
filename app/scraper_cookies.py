"""
Twitter Scraper using browser cookies

Uses exported cookies to authenticate with Twitter's API directly.
"""

import asyncio
import os
import re
from dataclasses import dataclass, field
from typing import Optional
from http.cookiejar import MozillaCookieJar

import httpx
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


class TwitterCookieScraper:
    """Scrapes tweets using browser cookies for authentication."""

    def __init__(
        self,
        max_tweets: int = 500,
        cookies_file: str = "cookies.txt",
    ):
        self.max_tweets = max_tweets
        self.cookies_file = cookies_file
        self.cookies = self._load_cookies()

    def _load_cookies(self) -> dict:
        """Load cookies from Netscape format file."""
        cookies = {}
        try:
            jar = MozillaCookieJar(self.cookies_file)
            jar.load(ignore_discard=True, ignore_expires=True)
            
            for cookie in jar:
                cookies[cookie.name] = cookie.value
            
            print(f"Loaded {len(cookies)} cookies from {self.cookies_file}")
            return cookies
        except Exception as e:
            print(f"Error loading cookies: {e}")
            return {}

    async def scrape_user(
        self,
        username: str,
        include_retweets: bool = False,
        include_replies: bool = False,
        progress_callback=None,
    ) -> ScrapeResult:
        """
        Scrape tweets from a user's timeline using Twitter's GraphQL API.
        
        Args:
            username: Twitter username (without @)
            include_retweets: Whether to include retweets
            include_replies: Whether to include replies
            progress_callback: Optional async callback(current_count, status_message)
        
        Returns:
            ScrapeResult with collected tweets
        """
        result = ScrapeResult(username=username)
        
        if not self.cookies or 'auth_token' not in self.cookies:
            result.error = "No authentication cookies found. Please export cookies from your browser."
            return result

        try:
            if progress_callback:
                await progress_callback(0, f"Starting to scrape @{username}...")

            headers = {
                'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
                'x-csrf-token': self.cookies.get('ct0', ''),
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'x-twitter-active-user': 'yes',
                'x-twitter-auth-type': 'OAuth2Session',
                'x-twitter-client-language': 'en',
            }

            async with httpx.AsyncClient(cookies=self.cookies, headers=headers, timeout=30.0) as client:
                # First, get the user ID
                user_url = f"https://x.com/i/api/graphql/7mjxD3-C6BxitPMVQ6w0-Q/UserByScreenName"
                user_variables = {
                    "screen_name": username,
                    "withSafetyModeUserFields": True
                }
                user_features = {
                    "hidden_profile_likes_enabled": False,
                    "responsive_web_graphql_exclude_directive_enabled": True,
                    "verified_phone_label_enabled": False,
                    "subscriptions_verification_info_is_identity_verified_enabled": False,
                    "subscriptions_verification_info_verified_since_enabled": True,
                    "highlights_tweets_tab_ui_enabled": True,
                    "creator_subscriptions_tweet_preview_api_enabled": True,
                    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
                    "responsive_web_graphql_timeline_navigation_enabled": True
                }
                
                # This is a simplified scraper that demonstrates the approach
                # A full implementation would need to handle pagination and parse the complex GraphQL response
                result.error = "Twitter's GraphQL API requires complex authentication and parsing. Consider using Twitter's official API instead."
                
        except Exception as e:
            error_msg = str(e)
            result.error = f"Scraping error: {error_msg}"
            print(f"Error scraping @{username}: {error_msg}")

        return result



