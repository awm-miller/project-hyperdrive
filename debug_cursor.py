import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs

# Fetch page 2
url = "http://localhost:8080/elonmusk?cursor=DAAHCgABG75HK3A__-oLAAIAAAATMTk5ODg3NzAzMTU1NjQyNzg2NwgAAwAAAAIAAA"
response = httpx.get(url)
soup = BeautifulSoup(response.text, 'html.parser')

print(f"Response size: {len(response.text)} bytes")

# Find all show-more elements
show_mores = soup.select('.show-more')
print(f"\nFound {len(show_mores)} .show-more elements")

for i, sm in enumerate(show_mores):
    print(f"\n  Element {i}: {sm}")
    link = sm.select_one('a')
    if link:
        href = link.get('href', '')
        print(f"  Link href: {href[:80]}...")
        parsed = urlparse(href)
        params = parse_qs(parsed.query)
        cursor = params.get('cursor', [None])[0]
        print(f"  Cursor: {cursor[:50] if cursor else 'None'}...")

# Also try the selector we use
show_more_a = soup.select_one('.show-more a')
print(f"\n\n.show-more a selector result: {show_more_a}")
if show_more_a:
    print(f"  href: {show_more_a.get('href', '')[:80]}...")

