import httpx
from bs4 import BeautifulSoup
from urllib.parse import quote

# Test different search queries
queries = [
    "from:elonmusk",
    "from:elonmusk since:2024-01-01",
    "from:elonmusk until:2024-12-01",
    "from:elonmusk since:2024-06-01 until:2024-12-01",
]

for q in queries:
    url = f"http://localhost:8080/search?f=tweets&q={quote(q)}"
    print(f"\nQuery: {q}")
    print(f"URL: {url}")
    
    response = httpx.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Count tweets
    tweets = soup.select('.timeline-item .tweet-body')
    print(f"Tweets found: {len(tweets)}")
    
    # Check for errors
    error = soup.select_one('.error-panel')
    if error:
        print(f"ERROR: {error.get_text(strip=True)}")
    
    # Check for cursor (pagination)
    cursor_links = soup.select('.show-more a[href*="cursor"]')
    print(f"Has pagination: {len(cursor_links) > 0}")
    
    # Show first tweet if any
    if tweets:
        content = tweets[0].select_one('.tweet-content')
        if content:
            print(f"First tweet: {content.get_text(strip=True)[:80]}...")

