import asyncio
from app.scraper import NitterScraper

async def test():
    print('Starting scrape of @elonmusk (max 100 tweets, WITH retweets)...\n')
    async with NitterScraper(nitter_url='http://localhost:8080', delay_seconds=1.0, max_tweets=100) as scraper:
        result = await scraper.scrape_user('elonmusk', include_retweets=True, include_replies=False)
    
    print(f'\n{"="*60}')
    print(f'RESULTS')
    print(f'{"="*60}')
    print(f'Total tweets: {result.total_scraped}')
    print(f'Error: {result.error}')
    print(f'Rate limited: {result.rate_limited}')
    
    if result.tweets:
        print(f'\nFirst 5 tweets:')
        for i, t in enumerate(result.tweets[:5], 1):
            print(f'{i}. [{t.timestamp[:20]}] {t.content[:80]}...')

asyncio.run(test())

