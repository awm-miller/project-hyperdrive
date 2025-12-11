import httpx

# The cursor from page 43 that led to page 44
cursor = "DAAHCgABG75KBvv__HwLAAIAAAATMTk5Mjk3MTYyNzE1NjM2OTY5OQgAAwAAAAIAAA"
url = f"http://localhost:8080/elonmusk?cursor={cursor}"

print(f"Fetching: {url}\n")
response = httpx.get(url)
html = response.text

print(f"Response status: {response.status_code}")
print(f"Response size: {len(html)} bytes")

# Check for error panel
if 'error-panel' in html:
    import re
    errors = re.findall(r'class="error-panel[^"]*"[^>]*>([^<]+)', html)
    print(f"\nERROR PANEL FOUND:")
    for e in errors:
        print(f"  {e.strip()}")

# Check for timeline items
import re
timeline_count = len(re.findall(r'timeline-item', html))
print(f"\nTimeline items in HTML: {timeline_count}")

# Check for show-more / cursor
if 'show-more' in html:
    cursors = re.findall(r'cursor=([^"&\s]+)', html)
    print(f"\nCursors found: {len(cursors)}")
    for c in cursors[:3]:
        print(f"  {c[:50]}...")
else:
    print("\nNO show-more element found")

# Check for any rate limit or error messages
rate_keywords = ['rate', 'limit', 'error', 'blocked', 'unavailable', 'try again']
for kw in rate_keywords:
    if kw.lower() in html.lower():
        # Find context
        idx = html.lower().find(kw.lower())
        context = html[max(0,idx-50):idx+100]
        print(f"\nFound '{kw}' in HTML:")
        print(f"  ...{context}...")

