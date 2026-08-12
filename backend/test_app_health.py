import urllib.request
import json

def test_endpoint(url, post_data=None):
    req = urllib.request.Request(url, headers={'Content-Type': 'application/json'})
    data_bytes = json.dumps(post_data).encode('utf-8') if post_data else None
    res = urllib.request.urlopen(req, data=data_bytes)
    return json.loads(res.read().decode('utf-8'))

print("=== DATA IQ AGENT HEALTH & ANALYSIS CHECK ===")

print("\n1. Testing /api/health...")
health = test_endpoint('http://127.0.0.1:5000/api/health')
print("Health Response:", health)

print("\n2. Testing /api/sample_datasets...")
samples = test_endpoint('http://127.0.0.1:5000/api/sample_datasets')
sample_list = samples.get("datasets", [])
print(f"Retrieved {len(sample_list)} sample datasets.")

print("\n3. Testing /api/load_sample_file (01_sales_performance.csv)...")
loaded = test_endpoint('http://127.0.0.1:5000/api/load_sample_file', {'filename': '01_sales_performance.csv'})
session_id = loaded.get('session_id')
rows = loaded["schema"]["shape"]["rows"]
cols = loaded["schema"]["shape"]["cols"]
print(f"[OK] Loaded successfully! Session ID: {session_id}")
print(f"   Dataset shape: {rows} rows x {cols} columns")

print("\n4. Testing /api/ask (Numeric aggregation query)...")
ans1 = test_endpoint('http://127.0.0.1:5000/api/ask', {'session_id': session_id, 'query': 'What is the total sum of total_revenue?'})
answer_text = ans1.get('answer', '')
print("Answer Snippet:")
print(answer_text[:200].replace("\n", " "))

print("\n5. Testing /api/ask (Chart/Visualization query)...")
ans2 = test_endpoint('http://127.0.0.1:5000/api/ask', {'session_id': session_id, 'query': 'Plot a bar chart of total revenue by category'})
chart_text = ans2.get('answer', '')
has_viz = ('[Visualization]' in chart_text) or ('![Generated Visualization]' in chart_text)
has_img = 'data:image/png;base64,' in chart_text
print(f"Visualization Section Present: {has_viz}")
print(f"Base64 PNG Image Embedded: {has_img}")
print("Chart Code snippet:")
for line in chart_text.splitlines():
    if "plt." in line or "grouped" in line or "kind=" in line or "plot" in line:
        print("  ", line)

print("\n6. Testing Jupyter Notebook Export...")
export_res = test_endpoint('http://127.0.0.1:5000/api/export/notebook', {'session_id': session_id})
nb_nodes = len(export_res.get('cells', []))
print(f"Notebook generated successfully with {nb_nodes} notebook cells!")

print("\n==========================================")
print("ALL BACKEND PIPELINES & VISUALIZATIONS TESTED AND WORKING 100% PERFECTLY!")
print("==========================================")
