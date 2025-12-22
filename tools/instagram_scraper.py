"""
Instagram Scraper + Gemini Vision Analyzer
Standalone script to scrape public Instagram profiles and analyze with AI
"""

import os
import sys
import json
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional
import google.generativeai as genai

# Check for instaloader
try:
    import instaloader
except ImportError:
    print("Installing instaloader...")
    os.system("pip install instaloader")
    import instaloader


@dataclass
class InstagramPost:
    """Represents a single Instagram post"""
    id: str
    url: str
    caption: str
    date: str
    likes: int
    comments: int
    image_path: str
    is_video: bool
    flagged: bool = False
    flag_reason: str = ""
    image_description: str = ""


def scrape_instagram(
    username: str,
    max_posts: int = 50,
    days_back: Optional[int] = None,
    download_dir: str = "instagram_downloads"
) -> List[InstagramPost]:
    """
    Scrape public Instagram profile
    
    Args:
        username: Instagram username (without @)
        max_posts: Maximum number of posts to scrape
        days_back: Only get posts from last N days (None = all)
        download_dir: Directory to save images
    
    Returns:
        List of InstagramPost objects
    """
    print(f"\n{'='*60}")
    print(f"INSTAGRAM SCRAPE: @{username}")
    print(f"{'='*60}")
    
    # Setup instaloader
    L = instaloader.Instaloader(
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        post_metadata_txt_pattern="",
    )
    
    # Create download directory
    save_dir = Path(download_dir) / username
    save_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # Get profile
        print(f"  Fetching profile @{username}...")
        profile = instaloader.Profile.from_username(L.context, username)
        
        print(f"  Followers: {profile.followers:,}")
        print(f"  Posts: {profile.mediacount:,}")
        try:
            bio = profile.biography[:100] + "..." if len(profile.biography) > 100 else profile.biography
            print(f"  Bio: {bio}")
        except:
            print(f"  Bio: [contains special characters]")
        
        # Calculate date cutoff
        cutoff_date = None
        if days_back:
            cutoff_date = datetime.now() - timedelta(days=days_back)
            print(f"  Date filter: Posts since {cutoff_date.strftime('%Y-%m-%d')}")
        
        posts: List[InstagramPost] = []
        
        print(f"\n  Scraping posts (max {max_posts})...")
        
        for i, post in enumerate(profile.get_posts()):
            # Check max posts
            if len(posts) >= max_posts:
                print(f"  Reached max posts limit ({max_posts})")
                break
            
            # Check date cutoff
            if cutoff_date and post.date_local < cutoff_date:
                print(f"  Reached date cutoff ({cutoff_date.strftime('%Y-%m-%d')})")
                break
            
            # Skip videos for now (can add later)
            if post.is_video:
                print(f"  [{i+1}] Skipping video post")
                continue
            
            # Download image directly from URL
            image_filename = f"{post.shortcode}.jpg"
            image_path = save_dir / image_filename
            
            try:
                if not image_path.exists():
                    import requests
                    # Get the actual image URL from the post
                    img_url = post.url  # This is actually the display_url for images
                    
                    # For sidecar posts (multiple images), get first image
                    if post.typename == "GraphSidecar":
                        try:
                            first_node = next(post.get_sidecar_nodes())
                            img_url = first_node.display_url
                        except:
                            pass
                    else:
                        img_url = post.url
                    
                    # Download the image
                    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                    response = requests.get(img_url, headers=headers, timeout=30)
                    
                    if response.status_code == 200 and len(response.content) > 1000:
                        with open(image_path, 'wb') as f:
                            f.write(response.content)
                    else:
                        # Fallback: try to get display_url directly
                        try:
                            response = requests.get(post.url, headers=headers, timeout=30)
                            if response.status_code == 200:
                                with open(image_path, 'wb') as f:
                                    f.write(response.content)
                        except:
                            pass
                            
            except Exception as e:
                # Silently continue - we can still analyze captions
                pass
            
            # Create post object
            ig_post = InstagramPost(
                id=post.shortcode,
                url=f"https://instagram.com/p/{post.shortcode}/",
                caption=post.caption or "",
                date=post.date_local.strftime("%Y-%m-%d %H:%M"),
                likes=post.likes,
                comments=post.comments,
                image_path=str(image_path) if image_path.exists() else "",
                is_video=post.is_video,
            )
            
            posts.append(ig_post)
            print(f"  [{len(posts)}] {ig_post.date} - {ig_post.likes:,} likes - {len(ig_post.caption)} chars")
            
            # Small delay to avoid rate limits
            if i > 0 and i % 10 == 0:
                print(f"  ... pausing to avoid rate limit ...")
                asyncio.get_event_loop().run_until_complete(asyncio.sleep(2))
        
        print(f"\n  Scraped {len(posts)} posts")
        return posts
        
    except instaloader.exceptions.ProfileNotExistsException:
        print(f"  ERROR: Profile @{username} does not exist")
        return []
    except instaloader.exceptions.PrivateProfileNotFollowedException:
        print(f"  ERROR: Profile @{username} is private")
        return []
    except Exception as e:
        print(f"  ERROR: {e}")
        return []


def analyze_with_gemini(
    posts: List[InstagramPost],
    api_key: str,
    username: str
) -> tuple[str, List[InstagramPost]]:
    """
    Analyze Instagram posts with Gemini Vision
    
    Args:
        posts: List of InstagramPost objects with downloaded images
        api_key: Gemini API key
        username: Instagram username for context
    
    Returns:
        Tuple of (summary, posts_with_flags)
    """
    print(f"\n{'='*60}")
    print(f"GEMINI VISION ANALYSIS")
    print(f"{'='*60}")
    
    if not posts:
        return "No posts to analyze", posts
    
    # Configure Gemini
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')
    
    # First, describe each image
    print(f"\n  Analyzing {len(posts)} images...")
    
    for i, post in enumerate(posts):
        if not post.image_path or not Path(post.image_path).exists():
            print(f"  [{i+1}] No image file, skipping")
            continue
        
        try:
            # Load image
            import PIL.Image
            image = PIL.Image.open(post.image_path)
            
            # Get image description
            describe_prompt = """Describe this Instagram image in 2-3 sentences. 
            Focus on: people, symbols, text overlays, gestures, locations, and any potentially controversial elements."""
            
            response = model.generate_content([describe_prompt, image])
            post.image_description = response.text.strip()
            
            print(f"  [{i+1}] Described: {post.image_description[:80]}...")
            
        except Exception as e:
            print(f"  [{i+1}] Failed to analyze image: {e}")
            post.image_description = "[Analysis failed]"
    
    # Now do overall analysis with all content
    print(f"\n  Running comprehensive analysis...")
    
    # Build content for analysis
    content_for_analysis = []
    for i, post in enumerate(posts):
        content_for_analysis.append({
            "index": i,
            "date": post.date,
            "caption": post.caption[:500] if post.caption else "[No caption]",
            "image_description": post.image_description,
            "likes": post.likes,
            "url": post.url
        })
    
    analysis_prompt = f"""You are analyzing the Instagram profile of @{username}.

Below is data from {len(posts)} Instagram posts, including captions and AI-generated image descriptions.

POSTS DATA:
{json.dumps(content_for_analysis, indent=2)}

YOUR TASK:
1. Write a 4-6 sentence clinical summary of this person's Instagram presence, themes, and any concerning patterns.
2. Identify the TOP 20 MOST controversial or potentially problematic posts (if any exist).

Consider as controversial:
- Hate speech, discrimination, extremist content
- Misinformation or conspiracy theories
- Harassment or threatening behavior
- Inappropriate imagery or gestures
- Association with problematic individuals/groups
- Content that could damage professional reputation

Return ONLY valid JSON in this exact format:
{{
  "summary": "Your 4-6 sentence summary here",
  "flagged": [
    {{"index": 0, "reason": "Brief reason why this post is problematic"}},
    ...
  ]
}}

If no posts are controversial, return an empty flagged array.
Return ONLY the JSON, no other text."""

    try:
        response = model.generate_content(
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
        print(f"\n  Analysis complete: {flagged_count} posts flagged")
        
        return summary, posts
        
    except Exception as e:
        print(f"  ERROR in analysis: {e}")
        return f"Analysis failed: {e}", posts


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Instagram Scraper + Gemini Vision Analyzer")
    parser.add_argument("username", help="Instagram username to analyze (without @)")
    parser.add_argument("--max-posts", type=int, default=30, help="Maximum posts to scrape (default: 30)")
    parser.add_argument("--days", type=int, default=None, help="Only get posts from last N days")
    parser.add_argument("--output", default="instagram_results.json", help="Output JSON file")
    
    args = parser.parse_args()
    
    # Get API key
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY environment variable not set")
        sys.exit(1)
    
    # Scrape
    posts = scrape_instagram(
        username=args.username,
        max_posts=args.max_posts,
        days_back=args.days
    )
    
    if not posts:
        print("\nNo posts found. Exiting.")
        sys.exit(1)
    
    # Analyze
    summary, analyzed_posts = analyze_with_gemini(posts, api_key, args.username)
    
    # Output results
    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}")
    print(f"\nSUMMARY:\n{summary}")
    
    flagged_posts = [p for p in analyzed_posts if p.flagged]
    if flagged_posts:
        print(f"\nFLAGGED POSTS ({len(flagged_posts)}):")
        for p in flagged_posts:
            print(f"\n  [{p.date}] {p.url}")
            try:
                caption_preview = p.caption[:100] + "..." if len(p.caption) > 100 else p.caption
                print(f"  Caption: {caption_preview.encode('ascii', 'replace').decode()}")
            except:
                print(f"  Caption: [contains special characters]")
            try:
                img_preview = p.image_description[:100] + "..."
                print(f"  Image: {img_preview.encode('ascii', 'replace').decode()}")
            except:
                print(f"  Image: [description available in JSON]")
            print(f"  REASON: {p.flag_reason}")
    else:
        print("\nNo posts flagged as controversial.")
    
    # Save to JSON
    output = {
        "username": args.username,
        "scraped_at": datetime.now().isoformat(),
        "total_posts": len(analyzed_posts),
        "flagged_count": len(flagged_posts),
        "summary": summary,
        "posts": [asdict(p) for p in analyzed_posts]
    }
    
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()

