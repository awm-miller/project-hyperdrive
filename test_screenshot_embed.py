"""
Twitter embed screenshot - uses Twitter's embed feature (no login needed!)
For retweets, adds a header showing who retweeted.

Usage:
  python test_screenshot_embed.py                              # Default test tweet
  python test_screenshot_embed.py elonmusk 123456              # Specific tweet
  python test_screenshot_embed.py elonmusk 123456 --rt-by someone  # Retweet
"""

import asyncio
import sys
import tempfile
import os
from playwright.async_api import async_playwright


async def screenshot_twitter_embed(
    username: str, 
    tweet_id: str, 
    retweeted_by: str = None,
    theme: str = "dark"
):
    print(f"Screenshotting Twitter embed...")
    print(f"Tweet: {username}/status/{tweet_id}")
    if retweeted_by:
        print(f"Retweeted by: @{retweeted_by}")
    
    # Build retweet header if needed
    retweet_header = ""
    if retweeted_by:
        retweet_header = f'''
        <div class="retweet-header">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="#71767b">
                <path d="M4.5 3.88l4.432 4.14-1.364 1.46L5.5 7.55V16c0 1.1.896 2 2 2H13v2H7.5c-2.209 0-4-1.79-4-4V7.55L1.432 9.48.068 8.02 4.5 3.88zM16.5 6H11V4h5.5c2.209 0 4 1.79 4 4v8.45l2.068-1.93 1.364 1.46-4.432 4.14-4.432-4.14 1.364-1.46 2.068 1.93V8c0-1.1-.896-2-2-2z"/>
            </svg>
            <span>@{retweeted_by} retweeted</span>
        </div>
        '''
    
    # Create HTML with Twitter embed
    html_content = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{
            margin: 0;
            padding: 20px;
            background: {"#000" if theme == "dark" else "#fff"};
            display: flex;
            justify-content: center;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }}
        .tweet-container {{
            max-width: 550px;
        }}
        .retweet-header {{
            display: flex;
            align-items: center;
            gap: 8px;
            color: #71767b;
            font-size: 13px;
            margin-bottom: 8px;
            padding-left: 4px;
        }}
        .retweet-header svg {{
            flex-shrink: 0;
        }}
    </style>
</head>
<body>
    <div class="tweet-container">
        {retweet_header}
        <blockquote class="twitter-tweet" data-theme="{theme}" data-conversation="none">
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
    
    async with async_playwright() as p:
        print("Launching browser...")
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page(viewport={"width": 600, "height": 1200})
        
        print(f"Loading embed HTML...")
        await page.goto(f"file://{temp_file}", wait_until="networkidle")
        
        # Wait for Twitter widget to load
        print("Waiting for Twitter widget to load...")
        try:
            await page.wait_for_selector('iframe.twitter-tweet-rendered', timeout=15000)
            print("Twitter iframe loaded!")
        except:
            print("Iframe not found, waiting longer...")
            await asyncio.sleep(5)
        
        # Screenshot the whole container (includes retweet header)
        output_file = f"test_embed_{tweet_id}.png"
        container = await page.query_selector('.tweet-container')
        
        if container:
            await container.screenshot(path=output_file)
            print(f"Saved to: {output_file}")
        else:
            await page.screenshot(path=output_file)
            print(f"Saved full page to: {output_file}")
        
        print("Waiting 2 seconds...")
        await asyncio.sleep(2)
        
        await browser.close()
    
    # Cleanup
    try:
        os.remove(temp_file)
    except:
        pass
    
    print("Done!")
    return output_file


if __name__ == "__main__":
    # Parse args
    username = "elonmusk"
    tweet_id = "2001020623863341268"
    retweeted_by = None
    
    args = sys.argv[1:]
    if len(args) >= 2:
        username = args[0].lstrip('@')
        tweet_id = args[1]
    
    # Check for --rt-by flag
    if '--rt-by' in args:
        idx = args.index('--rt-by')
        if idx + 1 < len(args):
            retweeted_by = args[idx + 1].lstrip('@')
    
    asyncio.run(screenshot_twitter_embed(username, tweet_id, retweeted_by))
