import asyncio
from app.scraper import NitterScraper

async def test():
    print('Starting MAX scrape of @elonmusk (up to 2000 tweets, WITH replies and RTs)...\n')
    async with NitterScraper(nitter_url='http://localhost:8080', delay_seconds=1.5, max_tweets=2000) as scraper:
        result = await scraper.scrape_user('elonmusk', include_retweets=True, include_replies=True)
    
    print(f'\n\nFinal Results:')
    print(f'  Total tweets collected: {result.total_scraped}')
    print(f'  Rate limited: {result.rate_limited}')
    print(f'  Error: {result.error}')

asyncio.run(test())

