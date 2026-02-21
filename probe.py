"""
Probe script to test NextRequest API endpoints.
"""
import requests
import json
from bs4 import BeautifulSoup

s = requests.Session()
s.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
s.headers['Accept'] = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'

# Init session
print("Initializing session...")
r = s.get('https://shastacountyca.nextrequest.com/requests')
print(f"Page load: {r.status_code}")
print(f"Content-Type: {r.headers.get('content-type')}")
print(f"HTML length: {len(r.text)}")

# Show first 1000 chars so we can see what came back
print(f"\n=== FIRST 1000 CHARS OF HTML ===")
print(r.text[:1000])

# Try to find CSRF token
soup = BeautifulSoup(r.text, 'html.parser')
meta = soup.find('meta', {'name': 'csrf-token'})
if meta:
    token = meta['content']
    s.headers['X-CSRF-Token'] = token
    print(f"\nCSRF token: {token[:30]}...")
else:
    print("\nNo CSRF meta tag found. Listing all meta tags:")
    for m in soup.find_all('meta'):
        print(f"  {m}")
    token = None

# Show all cookies we got
print(f"\n=== COOKIES ===")
for cookie in s.cookies:
    print(f"  {cookie.name} = {cookie.value[:50]}...")

# Switch to JSON accept for API calls
s.headers['Accept'] = 'application/json, text/plain, */*'
s.headers['X-Requested-With'] = 'XMLHttpRequest'

# 1. Try request listing
print('\n=== TEST: /client/requests ===')
r1 = s.get('https://shastacountyca.nextrequest.com/client/requests',
           params={'page_number': 1, 'per_page': 2})
print(f'Status: {r1.status_code}')
print(f'Content-Type: {r1.headers.get("content-type")}')
try:
    data = r1.json()
    print(json.dumps(data, indent=2)[:2000])
except:
    print(r1.text[:1000])

# 2. Try request detail
print('\n=== TEST: /client/requests/26-309 ===')
r2 = s.get('https://shastacountyca.nextrequest.com/client/requests/26-309')
print(f'Status: {r2.status_code}')
print(f'Content-Type: {r2.headers.get("content-type")}')
try:
    data = r2.json()
    print(json.dumps(data, indent=2)[:2000])
except:
    print(r2.text[:1000])

# 3. Try timeline
print('\n=== TEST: /client/requests/26-309/timeline ===')
r3 = s.get('https://shastacountyca.nextrequest.com/client/requests/26-309/timeline',
           params={'page_number': 1})
print(f'Status: {r3.status_code}')
print(f'Content-Type: {r3.headers.get("content-type")}')
try:
    data = r3.json()
    print(json.dumps(data, indent=2)[:2000])
except:
    print(r3.text[:1000])

# 4. Try departments
print('\n=== TEST: /client/departments ===')
r4 = s.get('https://shastacountyca.nextrequest.com/client/departments')
print(f'Status: {r4.status_code}')
try:
    data = r4.json()
    print(json.dumps(data, indent=2)[:1000])
except:
    print(r4.text[:500])

print('\n=== DONE ===')