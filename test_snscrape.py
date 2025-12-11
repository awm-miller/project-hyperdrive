"""Quick test of snscrape scraper"""

import asyncio
from app.scraper_snscrape import TwitterScraper

async def test():
    scraper = TwitterScraper(max_tweets=5)
    result = await scraper.scrape_user("elonmusk", include_retweets=False, include_replies=False)
    
    print(f"Scraped {result.total_scraped} tweets from @{result.username}")
    if result.error:
        print(f"Error: {result.error}")
    else:
        for tweet in result.tweets[:3]:
            print(f"\n- {tweet.content[:100]}...")
            print(f"  Likes: {tweet.likes}, Retweets: {tweet.retweets}")

if __name__ == "__main__":
    asyncio.run(test())



