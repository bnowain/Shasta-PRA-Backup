"""
Probe script - tests document listing and download endpoints.
Run after probe.py confirms the basic API works.
"""
import requests
import json
from bs4 import BeautifulSoup

s = requests.Session()
s.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'

# Init session
print("Initializing session...")
r = s.get('https://shastacountyca.nextrequest.com/requests')
soup = BeautifulSoup(r.text, 'lxml')
token = soup.find('meta', {'name': 'csrf-token'})['content']
s.headers['X-CSRF-Token'] = token
s.headers['Accept'] = 'application/json, text/plain, */*'
s.headers['X-Requested-With'] = 'XMLHttpRequest'
print(f"Session ready. CSRF: {token[:20]}...")

# Step 1: Get a request that has documents (25-389 = Sinner case, 557 docs)
# We need the NUMERIC id, not the pretty_id. Let's check what the detail gives us.
print("\n=== DETAIL FOR 25-389 ===")
r1 = s.get('https://shastacountyca.nextrequest.com/client/requests/25-389')
print(f"Status: {r1.status_code}")
detail = r1.json()
# Print all top-level keys so we can find the numeric ID
print(f"Top-level keys: {list(detail.keys())}")
print(json.dumps(detail, indent=2)[:1500])

# Step 2: Try request_documents with the pretty_id directly
print("\n=== DOCUMENTS: request_id=25-389 ===")
r2 = s.get('https://shastacountyca.nextrequest.com/client/request_documents',
           params={'request_id': '25-389', 'page': 1, 'per_page': 3})
print(f"Status: {r2.status_code}")
print(f"Content-Type: {r2.headers.get('content-type')}")
try:
    data = r2.json()
    print(json.dumps(data, indent=2)[:2000])
except:
    print(r2.text[:1000])

# Step 3: Try folders
print("\n=== FOLDERS: 25-389 ===")
r3 = s.get('https://shastacountyca.nextrequest.com/client/requests/25-389/folders')
print(f"Status: {r3.status_code}")
try:
    data = r3.json()
    print(json.dumps(data, indent=2)[:1000])
except:
    print(r3.text[:500])

# Step 4: If documents returned, try getting S3 download URL
print("\n=== TRYING TO GET DOWNLOAD URLs ===")
try:
    docs_data = r2.json()
    # Try to find the document list in whatever structure came back
    if isinstance(docs_data, list):
        doc_list = docs_data
    elif isinstance(docs_data, dict):
        doc_list = (docs_data.get('data') or docs_data.get('documents') or
                   docs_data.get('records') or docs_data.get('request_documents') or [])
        # Print all keys to see structure
        print(f"Response keys: {list(docs_data.keys())}")
    else:
        doc_list = []

    if doc_list:
        first = doc_list[0]
        print(f"\nFirst document keys: {list(first.keys())}")
        print(f"First document: {json.dumps(first, indent=2)[:1000]}")

        doc_id = first.get('id') or first.get('document_id')
        print(f"\nDoc ID: {doc_id}")

        # Try s3_url endpoint
        print(f"\n--- /s3_url?document_id={doc_id} ---")
        r4 = s.get('https://shastacountyca.nextrequest.com/s3_url',
                   params={'document_id': doc_id})
        print(f"Status: {r4.status_code}")
        print(f"Content-Type: {r4.headers.get('content-type')}")
        try:
            print(json.dumps(r4.json(), indent=2)[:500])
        except:
            print(r4.text[:500])

        # Try /client/documents/download endpoint
        print(f"\n--- /client/documents/download ---")
        r5 = s.get('https://shastacountyca.nextrequest.com/client/documents/download',
                   params={'document_ids[]': doc_id})
        print(f"Status: {r5.status_code}")
        print(f"Content-Type: {r5.headers.get('content-type')}")
        try:
            print(json.dumps(r5.json(), indent=2)[:500])
        except:
            # Might be binary or redirect
            print(f"Response length: {len(r5.content)}")
            print(f"Headers: {dict(r5.headers)}")
            print(r5.text[:500])

        # Try direct document URL patterns
        print(f"\n--- Direct URL patterns ---")
        for pattern in [
            f"/client/documents/{doc_id}",
            f"/documents/{doc_id}/download",
            f"/documents/{doc_id}",
        ]:
            r6 = s.get(f'https://shastacountyca.nextrequest.com{pattern}',
                      allow_redirects=False)
            print(f"  {pattern} -> {r6.status_code} (Content-Type: {r6.headers.get('content-type', '?')}, Location: {r6.headers.get('location', 'none')})")

    else:
        print("No documents found in response")
except Exception as e:
    print(f"Error: {e}")

# Step 5: Also try a request with fewer docs for a simpler test
print("\n=== SMALLER TEST: request 26-301 ===")
r7 = s.get('https://shastacountyca.nextrequest.com/client/request_documents',
           params={'request_id': '26-301', 'page': 1, 'per_page': 10})
print(f"Status: {r7.status_code}")
try:
    data = r7.json()
    print(json.dumps(data, indent=2)[:1500])
except:
    print(r7.text[:500])

print('\n=== DONE ===')
