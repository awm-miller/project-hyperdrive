import httpx

cursor = "DAAHCgABG75KBvv__HwLAAIAAAATMTk5Mjk3MTYyNzE1NjM2OTY5OQgAAwAAAAIAAA"
url = f"http://localhost:8080/elonmusk?cursor={cursor}"

response = httpx.get(url)
html = response.text

# Save raw HTML
with open('page44_raw.html', 'w', encoding='utf-8') as f:
    f.write(html)

print(f"Saved {len(html)} bytes to page44_raw.html")

# Look for the timeline section
from bs4 import BeautifulSoup
soup = BeautifulSoup(html, 'html.parser')

# Find timeline
timeline = soup.select_one('.timeline')
if timeline:
    print(f"\nTimeline section found:")
    print(timeline.prettify()[:2000])
else:
    print("\nNo .timeline element found")

# Find any error or notice
for cls in ['error-panel', 'timeline-end', 'timeline-none', 'show-more']:
    elem = soup.select_one(f'.{cls}')
    if elem:
        print(f"\nFound .{cls}:")
        print(f"  {elem.get_text(strip=True)[:200]}")

