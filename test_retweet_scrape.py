"""
Test script for timeline retweet scraping.
Scrapes all retweets from @elonmusk's timeline.
"""
import asyncio
from app.scraper_timeline import NitterTimelineScraper


async def main():
    print("="*60)
    print("SCRAPING @elonmusk RETWEETS FROM TIMELINE")
    print("="*60)
    print("VPN rotation + Redis flush + Nitter restart on rate limit")
    print("="*60)
    print()

    async with NitterTimelineScraper(
        nitter_url='http://localhost:8080',
        delay_seconds=0.5,
        max_retweets=50000,
        max_restarts=100,
        docker_compose_path='C:\\Users\\Alex\\GitHub\\project-hyperdrive',
    ) as scraper:
        result = await scraper.scrape_retweets(username="elonmusk")
        
        print()
        print("="*60)
        print("FINAL RESULTS")
        print("="*60)
        print(f"Total retweets collected: {len(result.tweets)}")
        print(f"Pages processed: {result.pages_processed}")
        print(f"Rate limited: {result.rate_limited}")
        print(f"Error: {result.error}")
        if result.tweets:
            print(f"Oldest retweet: {result.tweets[-1].timestamp}")
            print(f"Newest retweet: {result.tweets[0].timestamp}")
            print(f"\nSample retweets:")
            for i, tweet in enumerate(result.tweets[:5]):
                print(f"  {i+1}. RT @{tweet.original_author}: {tweet.content[:60]}...")
        print("="*60)
        
        # Save to file
        with open("elonmusk_retweets.txt", "w", encoding="utf-8") as f:
            f.write(f"@elonmusk retweets\n")
            f.write(f"Total: {len(result.tweets)}\n")
            f.write("="*60 + "\n\n")
            for tweet in result.tweets:
                f.write(f"[{tweet.timestamp}] RT @{tweet.original_author}\n")
                f.write(f"{tweet.content}\n")
                f.write(f"  Likes: {tweet.likes} | RTs: {tweet.retweets} | Replies: {tweet.replies}\n")
                f.write("-"*40 + "\n")
        print(f"\nSaved to elonmusk_retweets.txt")


if __name__ == "__main__":
    asyncio.run(main())

