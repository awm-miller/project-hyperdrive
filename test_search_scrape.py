"""
Test script for search-based scraping with VPN rotation.
Scraping all of 2024 for @elonmusk.
"""
import asyncio
from datetime import datetime
from app.scraper_search import NitterSearchScraper


async def main():
    print("="*60)
    print("SCRAPING @elonmusk - ALL OF 2024")
    print("="*60)
    print("VPN rotation + Nitter restart on rate limit")
    print("="*60)
    print()

    async with NitterSearchScraper(
        nitter_url='http://localhost:8080',
        delay_seconds=0.5,        # Fast - we reset on rate limit
        max_tweets=50000,         # High limit
        chunk_days=30,            # 30-day chunks
        max_restarts=50,          # Allow many restarts
        docker_compose_path='C:\\Users\\Alex\\GitHub\\project-hyperdrive',
    ) as scraper:
        result = await scraper.scrape_user(
            username="elonmusk",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 12, 31),
            include_retweets=True,
            include_replies=True,
        )
        
        print()
        print("="*60)
        print("FINAL RESULTS")
        print("="*60)
        print(f"Total tweets collected: {len(result.tweets)}")
        print(f"Date ranges processed: {result.date_ranges_processed}")
        print(f"Rate limited: {result.rate_limited}")
        print(f"Error: {result.error}")
        if result.tweets:
            print(f"Oldest tweet: {result.tweets[-1].timestamp}")
            print(f"Newest tweet: {result.tweets[0].timestamp}")
        print("="*60)
        
        # Save to file
        with open("elonmusk_2024_tweets.txt", "w", encoding="utf-8") as f:
            f.write(f"@elonmusk tweets from 2024\n")
            f.write(f"Total: {len(result.tweets)}\n")
            f.write("="*60 + "\n\n")
            for tweet in result.tweets:
                f.write(f"[{tweet.timestamp}] {tweet.content}\n")
                f.write(f"  Likes: {tweet.likes} | RTs: {tweet.retweets} | Replies: {tweet.replies}\n")
                f.write("-"*40 + "\n")
        print(f"\nSaved to elonmusk_2024_tweets.txt")


if __name__ == "__main__":
    asyncio.run(main())
