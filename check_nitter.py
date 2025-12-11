import httpx
import re

response = httpx.get('http://localhost:8080/elonmusk')
html = response.text

print(f"Response size: {len(html)} bytes")

# Check for show-more links
if 'show-more' in html:
    print('\nFound show-more in HTML')
    matches = re.findall(r'class="show-more"[^>]*>.*?</a>', html, re.DOTALL)
    for m in matches[:3]:
        print(f'  {m[:200]}')
else:
    print('\nNO show-more found in HTML')

# Check for cursor
if 'cursor=' in html:
    print('\nFound cursor in HTML')
    cursors = re.findall(r'cursor=([^"&]+)', html)
    for c in cursors[:2]:
        print(f'  Cursor: {c[:50]}...')
else:
    print('\nNO cursor found in HTML')

# Check for error messages
if 'error-panel' in html:
    print('\nFound error-panel in HTML')
    errors = re.findall(r'error-panel[^>]*>([^<]+)', html)
    for e in errors:
        print(f'  Error: {e.strip()}')

# Check timeline items
timeline_items = re.findall(r'timeline-item', html)
print(f'\nTimeline items found: {len(timeline_items)}')

