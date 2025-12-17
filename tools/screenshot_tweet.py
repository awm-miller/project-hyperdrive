"""
Tweet Screenshot Tool - Uses Twitter embed (no login required)

Only supports regular tweets, not retweets.
"""

import asyncio
import os
import tempfile
from playwright.async_api import async_playwright


async def screenshot_tweet(
    tweet_id: str,
    username: str,
    tweet_text: str = "",
    is_retweet: bool = False,
    retweeted_by: str = None,
    nitter_url: str = None,  # Ignored - kept for API compatibility
) -> bytes:
    """
    Screenshot a tweet using Twitter's embed widget.
    
    Args:
        tweet_id: The tweet's status ID
        username: The tweet author's username
        tweet_text: Ignored (kept for API compatibility)
        is_retweet: If True, returns None (retweets not supported)
        retweeted_by: Ignored
        nitter_url: Ignored
    
    Returns:
        PNG image bytes, or None if retweet
    """
    # Skip retweets
    if is_retweet:
        raise ValueError("Retweet screenshots not supported")
    
    # Clean username
    username = username.lstrip('@') if username else ''
    
    # Create HTML with Twitter embed
    html_content = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{
            margin: 0;
            padding: 20px;
            background: #000;
            display: flex;
            justify-content: center;
        }}
        .tweet-container {{
            max-width: 550px;
        }}
    </style>
</head>
<body>
    <div class="tweet-container">
        <blockquote class="twitter-tweet" data-theme="dark" data-conversation="none">
            <a href="https://twitter.com/{username}/status/{tweet_id}"></a>
        </blockquote>
        <script async src="https://platform.twitter.com/widgets.js" charset="utf-8"></script>
    </div>
</body>
</html>'''
    
    # Write to temp file
    temp_file = os.path.join(tempfile.gettempdir(), f"tweet_embed_{tweet_id}.html")
    with open(temp_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 600, "height": 1200})
            
            await page.goto(f"file://{temp_file}", wait_until="networkidle")
            
            # Wait for Twitter widget to load
            try:
                await page.wait_for_selector('iframe.twitter-tweet-rendered', timeout=15000)
            except:
                await asyncio.sleep(5)
            
            # Screenshot the container
            container = await page.query_selector('.tweet-container')
            
            if container:
                screenshot = await container.screenshot()
            else:
                screenshot = await page.screenshot()
            
            await browser.close()
            
            return screenshot
    finally:
        # Cleanup temp file
        try:
            os.remove(temp_file)
        except:
            pass


async def screenshot_tweet_to_file(
    tweet_id: str,
    username: str,
    output_path: str,
    **kwargs
) -> str:
    """Screenshot a tweet and save to file."""
    png_bytes = await screenshot_tweet(
        tweet_id=tweet_id,
        username=username,
        **kwargs
    )
    
    with open(output_path, 'wb') as f:
        f.write(png_bytes)
    
    return output_path


# CLI for testing
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Screenshot a tweet using Twitter embed")
    parser.add_argument("--tweet-id", required=True, help="Tweet status ID")
    parser.add_argument("--username", required=True, help="Tweet author username")
    parser.add_argument("--output", default="tweet_screenshot.png", help="Output file path")
    
    args = parser.parse_args()
    
    asyncio.run(screenshot_tweet_to_file(
        tweet_id=args.tweet_id,
        username=args.username,
        output_path=args.output,
    ))
    
    print(f"Saved to: {args.output}")
