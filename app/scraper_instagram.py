"""
Instagram Scraper Module
Scrapes public Instagram profiles and analyzes images/videos with Gemini Vision
Supports: Posts, Stories, Videos with transcription
"""

import os
import shutil
import logging
import time
import http.cookiejar
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
import json

import google.generativeai as genai

try:
    import instaloader
except ImportError:
    instaloader = None

try:
    import PIL.Image
except ImportError:
    PIL = None

logger = logging.getLogger(__name__)

# Default paths
TEMP_DIR = "instagram_downloads"
COOKIES_FILE = "cookies.txt"


@dataclass
class InstagramPost:
    """Represents a single Instagram post or story"""
    id: str
    url: str
    caption: str
    date: str
    likes: int
    comments: int
    image_path: str = ""
    is_video: bool = False
    is_story: bool = False
    flagged: bool = False
    flag_reason: str = ""
    image_description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class InstagramScrapeResult:
    """Result of an Instagram scrape"""
    username: str
    posts: List[InstagramPost] = field(default_factory=list)
    stories: List[InstagramPost] = field(default_factory=list)
    total_scraped: int = 0
    error: Optional[str] = None
    profile_info: Dict[str, Any] = field(default_factory=dict)


class InstagramScraper:
    """Scrapes public Instagram profiles with video and story support"""
    
    def __init__(
        self,
        download_dir: str = TEMP_DIR,
        max_posts: int = 50,
        cookies_file: str = COOKIES_FILE,
    ):
        if instaloader is None:
            raise ImportError("instaloader not installed. Run: pip install instaloader")
        
        self.download_dir = Path(download_dir)
        self.max_posts = max_posts
        self.cookies_file = cookies_file
        self._logged_in = False
        
        # Auth loader for stories
        self.auth_loader = instaloader.Instaloader(
            download_videos=True,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            post_metadata_txt_pattern="",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        
        logger.info(f"InstagramScraper initialized: max_posts={max_posts}")
    
    def login(self) -> bool:
        """Login via cookies.txt (required for stories)"""
        cookies_path = Path(self.cookies_file)
        if not cookies_path.exists():
            logger.warning(f"No cookies file at {self.cookies_file} - stories will be skipped")
            return False
        
        try:
            cookie_jar = http.cookiejar.MozillaCookieJar(str(cookies_path))
            cookie_jar.load(ignore_discard=True, ignore_expires=True)
            
            # Apply cookies to auth loader
            session = self.auth_loader.context._session
            for cookie in cookie_jar:
                if 'instagram' in cookie.domain:
                    session.cookies.set_cookie(cookie)
            
            # Set required headers
            session.headers.update({
                'X-IG-App-ID': '936619743392459',
                'X-IG-WWW-Claim': '0',
                'X-Requested-With': 'XMLHttpRequest',
            })
            
            # Verify sessionid exists
            session_cookies = {c.name: c.value for c in cookie_jar if 'instagram' in c.domain}
            if 'sessionid' not in session_cookies:
                raise ValueError("No sessionid found in cookies")
            
            self._logged_in = True
            logger.info(f"Logged in via cookies.txt")
            return True
            
        except Exception as e:
            logger.error(f"Cookie login failed: {e}")
            return False
    
    def scrape(
        self,
        username: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        include_stories: bool = False,
    ) -> InstagramScrapeResult:
        """
        Scrape a public Instagram profile
        
        Args:
            username: Instagram username (without @)
            start_date: Only get posts after this date
            end_date: Only get posts before this date
            include_stories: Also scrape stories (requires login)
        
        Returns:
            InstagramScrapeResult with posts and metadata
        """
        logger.info(f"")
        logger.info(f"{'='*60}")
        logger.info(f"INSTAGRAM SCRAPE: @{username}")
        logger.info(f"{'='*60}")
        
        result = InstagramScrapeResult(username=username)
        
        # Create download directory
        save_dir = self.download_dir / username
        save_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # Use fresh public loader for posts (avoids rate limits)
            public_loader = instaloader.Instaloader(
                download_videos=True,
                download_video_thumbnails=False,
                download_geotags=False,
                download_comments=False,
                save_metadata=False,
                compress_json=False,
                post_metadata_txt_pattern="",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            
            # Get profile
            logger.info(f"Fetching profile @{username}...")
            profile = instaloader.Profile.from_username(public_loader.context, username)
            
            result.profile_info = {
                "followers": profile.followers,
                "following": profile.followees,
                "posts_count": profile.mediacount,
                "bio": profile.biography[:200] if profile.biography else "",
                "is_private": profile.is_private,
            }
            
            logger.info(f"  Followers: {profile.followers:,}")
            logger.info(f"  Posts: {profile.mediacount:,}")
            
            if profile.is_private:
                result.error = "Profile is private"
                logger.warning(f"  Profile @{username} is private")
                return result
            
            # Date filtering
            if start_date:
                logger.info(f"  Start date: {start_date.strftime('%Y-%m-%d')}")
            if end_date:
                logger.info(f"  End date: {end_date.strftime('%Y-%m-%d')}")
            
            # Scrape posts
            logger.info(f"  Scraping posts (max {self.max_posts})...")
            result.posts = self._scrape_posts(profile, save_dir, start_date, end_date)
            logger.info(f"  Scraped {len(result.posts)} posts")
            
            # Scrape stories if requested
            if include_stories:
                if self._logged_in:
                    try:
                        # Get profile with auth loader for stories
                        auth_profile = instaloader.Profile.from_username(
                            self.auth_loader.context, username
                        )
                        result.stories = self._scrape_stories(auth_profile, save_dir)
                        logger.info(f"  Scraped {len(result.stories)} stories")
                    except Exception as e:
                        logger.warning(f"  Stories failed: {e}")
                else:
                    logger.warning(f"  Skipping stories - not logged in")
            
            result.total_scraped = len(result.posts) + len(result.stories)
            
        except instaloader.exceptions.ProfileNotExistsException:
            result.error = f"Profile @{username} does not exist"
            logger.error(f"  {result.error}")
        except instaloader.exceptions.PrivateProfileNotFollowedException:
            result.error = f"Profile @{username} is private"
            logger.error(f"  {result.error}")
        except Exception as e:
            result.error = str(e)
            logger.error(f"  Scrape error: {e}")
        
        return result
    
    def _scrape_posts(
        self,
        profile,
        save_dir: Path,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
    ) -> List[InstagramPost]:
        """Scrape posts from a profile"""
        posts = []
        
        for i, post in enumerate(profile.get_posts()):
            if len(posts) >= self.max_posts:
                logger.info(f"  Reached max posts limit ({self.max_posts})")
                break
            
            # Date filtering (handle timezone)
            post_date = post.date_local
            if post_date.tzinfo is not None:
                post_date_naive = post_date.replace(tzinfo=None)
            else:
                post_date_naive = post_date
            
            if end_date and post_date_naive > end_date:
                continue  # Too new
            
            if start_date and post_date_naive < start_date:
                logger.info(f"  Reached start date cutoff")
                break  # Too old
            
            # Download media
            media_path = self._download_media(post, save_dir)
            
            ig_post = InstagramPost(
                id=post.shortcode,
                url=f"https://instagram.com/p/{post.shortcode}/",
                caption=post.caption or "",
                date=post_date.strftime("%Y-%m-%d %H:%M"),
                likes=post.likes,
                comments=post.comments,
                image_path=str(media_path) if media_path else "",
                is_video=post.is_video,
            )
            
            posts.append(ig_post)
            media_type = "video" if post.is_video else "image"
            logger.info(f"  [{len(posts)}] {ig_post.date} - {media_type} - {ig_post.likes:,} likes")
        
        return posts
    
    def _scrape_stories(self, profile, save_dir: Path) -> List[InstagramPost]:
        """Scrape active stories from a profile (requires login)"""
        stories = []
        
        try:
            logger.info(f"  Scraping stories...")
            
            for story in self.auth_loader.get_stories(userids=[profile.userid]):
                for item in story.get_items():
                    # Download media
                    media_path = self._download_story_media(item, save_dir)
                    
                    story_post = InstagramPost(
                        id=f"story_{item.mediaid}",
                        url=f"https://instagram.com/stories/{profile.username}/{item.mediaid}/",
                        caption="[Story]",
                        date=item.date_local.strftime("%Y-%m-%d %H:%M"),
                        likes=0,
                        comments=0,
                        image_path=str(media_path) if media_path else "",
                        is_video=item.is_video,
                        is_story=True,
                    )
                    
                    stories.append(story_post)
                    media_type = "video" if item.is_video else "image"
                    logger.info(f"  [Story {len(stories)}] {story_post.date} - {media_type}")
                    
        except Exception as e:
            logger.warning(f"  Story scrape error: {e}")
        
        return stories
    
    def _download_media(self, post, save_dir: Path) -> Optional[Path]:
        """Download image or video from a post"""
        import requests
        
        ext = "mp4" if post.is_video else "jpg"
        media_path = save_dir / f"{post.shortcode}.{ext}"
        
        if media_path.exists():
            return media_path
        
        try:
            if post.is_video:
                url = post.video_url
            else:
                url = post.url
                # For carousel posts, get first item
                if post.typename == "GraphSidecar":
                    try:
                        first_node = next(post.get_sidecar_nodes())
                        url = first_node.display_url
                    except:
                        pass
            
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(url, headers=headers, timeout=60)
            
            if response.status_code == 200 and len(response.content) > 1000:
                with open(media_path, 'wb') as f:
                    f.write(response.content)
                return media_path
                
        except Exception as e:
            logger.debug(f"Failed to download media: {e}")
        
        return None
    
    def _download_story_media(self, item, save_dir: Path) -> Optional[Path]:
        """Download image or video from a story item"""
        import requests
        
        ext = "mp4" if item.is_video else "jpg"
        media_path = save_dir / f"story_{item.mediaid}.{ext}"
        
        if media_path.exists():
            return media_path
        
        try:
            if item.is_video:
                url = item.video_url
            else:
                url = item.url
            
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(url, headers=headers, timeout=60)
            
            if response.status_code == 200 and len(response.content) > 1000:
                with open(media_path, 'wb') as f:
                    f.write(response.content)
                return media_path
                
        except Exception as e:
            logger.debug(f"Failed to download story media: {e}")
        
        return None
    
    def cleanup(self, username: str):
        """Delete downloaded media for a user"""
        user_dir = self.download_dir / username
        if user_dir.exists():
            shutil.rmtree(user_dir)
            logger.info(f"Cleaned up media for @{username}")


class InstagramAnalyzer:
    """Analyzes Instagram posts with Gemini Vision (images + videos)"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not provided")
        
        genai.configure(api_key=self.api_key)
        
        # Use Gemini 2.0 Flash for vision (fast + capable)
        self.vision_model = genai.GenerativeModel('gemini-2.0-flash')
        self.analysis_model = genai.GenerativeModel('gemini-2.0-flash')
        
        logger.info("InstagramAnalyzer initialized with Gemini 2.0 Flash")
    
    def analyze_posts(
        self,
        posts: List[InstagramPost],
        username: str
    ) -> tuple[str, List[InstagramPost]]:
        """
        Analyze Instagram posts with Gemini Vision
        
        Args:
            posts: List of InstagramPost objects with downloaded media
            username: Instagram username for context
        
        Returns:
            Tuple of (summary, posts_with_flags)
        """
        if PIL is None:
            raise ImportError("Pillow not installed. Run: pip install Pillow")
        
        logger.info(f"")
        logger.info(f"{'='*60}")
        logger.info(f"GEMINI VISION ANALYSIS: @{username}")
        logger.info(f"{'='*60}")
        
        if not posts:
            return "No posts to analyze", posts
        
        # Step 1: Describe each media item
        logger.info(f"  Step 1: Analyzing {len(posts)} media items...")
        
        for i, post in enumerate(posts):
            if not post.image_path or not Path(post.image_path).exists():
                logger.debug(f"  [{i+1}] No media file")
                continue
            
            try:
                if post.is_video:
                    post.image_description = self._analyze_video(post.image_path, i+1, len(posts))
                else:
                    post.image_description = self._analyze_image(post.image_path, i+1, len(posts))
                    
            except Exception as e:
                logger.warning(f"  [{i+1}/{len(posts)}] Analysis failed: {e}")
                post.image_description = "[Analysis failed]"
        
        # Step 2: Comprehensive analysis
        logger.info(f"  Step 2: Running comprehensive analysis...")
        
        content_for_analysis = []
        for i, post in enumerate(posts):
            content_for_analysis.append({
                "index": i,
                "date": post.date,
                "caption": post.caption[:500] if post.caption else "[No caption]",
                "media_description": post.image_description,
                "is_video": post.is_video,
                "is_story": post.is_story,
                "likes": post.likes,
                "url": post.url
            })
        
        analysis_prompt = f"""You are a forensic analyst examining the Instagram activity of @{username}.

MATERIAL VOLUME: {len(posts)} total posts are provided below for analysis.
Each post has an INDEX number. Use these indices to identify posts.

TASK 1: Write a ONE PARAGRAPH clinical summary (4-6 sentences max).
Include: volume analyzed, main topics, and any notable patterns.
Be concise and factual.

TASK 2: Identify the MOST CONTROVERSIAL posts by their INDEX number.
Flag only posts that are CLEARLY problematic - not just political opinions. Look for:
- Genuinely inflammatory, offensive, or hateful statements
- Content that could cause serious public backlash
- Statements that are objectively concerning (threats, slurs, etc.)
- Antisemitic, anti-Zionist, or pro-terrorist content
- Support for proscribed terrorist organisations (Hamas, Hezbollah, etc)
- Use of terms like "martyr" in contexts glorifying violence
- Celebration of attacks or violence against civilians
- Dehumanizing language about any ethnic/religious group

Limit to the TOP 50 MOST controversial posts maximum. Do NOT flag normal political opinions or criticism.

POSTS DATA:
{json.dumps(content_for_analysis, indent=2, ensure_ascii=False)}

RESPOND WITH VALID JSON ONLY (no markdown, no extra text):
{{
  "summary": "Your clinical summary here - 4-6 sentences, factual and objective.",
  "flagged": [
    {{"index": 0, "reason": "Short reason why controversial"}},
    {{"index": 5, "reason": "Short reason why controversial"}}
  ]
}}"""

        try:
            response = self.analysis_model.generate_content(
                analysis_prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    max_output_tokens=8192
                )
            )
            
            result = json.loads(response.text)
            summary = result.get("summary", "Analysis complete")
            flagged = result.get("flagged", [])
            
            # Apply flags to posts
            for flag in flagged:
                idx = flag.get("index")
                reason = flag.get("reason", "")
                if idx is not None and 0 <= idx < len(posts):
                    posts[idx].flagged = True
                    posts[idx].flag_reason = reason
            
            flagged_count = sum(1 for p in posts if p.flagged)
            logger.info(f"  Analysis complete: {flagged_count} posts flagged")
            
            return summary, posts
            
        except Exception as e:
            logger.error(f"  Analysis error: {e}")
            return f"Analysis failed: {e}", posts
    
    def _analyze_image(self, image_path: str, current: int, total: int) -> str:
        """Analyze a single image with Gemini Vision"""
        logger.info(f"  [{current}/{total}] Analyzing image...")
        
        image = PIL.Image.open(image_path)
        
        prompt = """Describe this Instagram image in 2-3 sentences.
Focus on: people, symbols, flags, text overlays, gestures, locations.
Specifically highlight any imagery which is antisemitic, anti-Zionist, or in support of proscribed terrorist organisations (Hamas, Hezbollah, etc).
Be factual and objective."""
        
        response = self.vision_model.generate_content([prompt, image])
        return response.text.strip()
    
    def _analyze_video(self, video_path: str, current: int, total: int) -> str:
        """Analyze a video with Gemini - upload, transcribe, and describe"""
        logger.info(f"  [{current}/{total}] Analyzing video...")
        
        # Get file size
        file_size = Path(video_path).stat().st_size / (1024 * 1024)  # MB
        logger.info(f"    Uploading video ({file_size:.1f} MB)...")
        
        # Upload to Gemini
        video_file = genai.upload_file(video_path)
        
        # Wait for processing
        logger.info(f"    Waiting for Gemini to process video...")
        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = genai.get_file(video_file.name)
        
        if video_file.state.name != "ACTIVE":
            raise Exception(f"Video processing failed: {video_file.state.name}")
        
        # Analyze
        logger.info(f"    Analyzing video content...")
        
        prompt = """Analyze this video comprehensively:

1. TRANSCRIBE all speech/audio (include original language if not English)
2. DESCRIBE the visual content: people, locations, symbols, flags, text overlays, gestures
3. FLAG any content that is antisemitic, anti-Zionist, or supportive of proscribed terrorist organisations (Hamas, Hezbollah, etc)

Be thorough but concise. Focus on factual observations."""

        response = self.vision_model.generate_content(
            [video_file, prompt],
            generation_config=genai.GenerationConfig(max_output_tokens=4096)
        )
        
        # Cleanup
        try:
            genai.delete_file(video_file.name)
        except:
            pass
        
        return response.text.strip()
