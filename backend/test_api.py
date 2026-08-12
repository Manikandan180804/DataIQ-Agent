"""Final verification test for DataIQ API."""
import sys, urllib.request, json
sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:5000/api"

def post(url, body):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

# Load sample dataset
d = post(f"{BASE}/load_sample", {})
sid = d["session_id"]
print(f"Loaded dataset: {d['schema']['shape']}")
print(f"Columns: {d['schema']['columns']}\n")

tests = [
    ("How many rows are in the dataset?",     "row"),
    ("What is the total revenue?",            "14,403"),
    ("Show me the top 5 rows by revenue",     "top"),
    ("What is the average unit price?",       "285"),
    ("How many unique customers are there?",  "unique"),
    ("Describe the dataset",                  "[Answer]"),
    ("What will revenue be next quarter?",    "Out of Scope"),
]

passed = failed = 0
for q, expect in tests:
    a = post(f"{BASE}/ask", {"session_id": sid, "query": q})
    ans = a.get("answer", "")
    ok = expect.lower() in ans.lower()
    status = "PASS" if ok else "FAIL"
    if ok: passed += 1
    else: failed += 1
    snippet = " ".join(ans.split())[:100]
    print(f"  [{status}] {q[:48]:<48} => {snippet[:90]}")

print(f"\nResult: {passed}/{passed+failed} tests passed")

# Check DB endpoints
def get(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())

hist = get(f"{BASE}/history?session_id={sid}")
print(f"\n[SQLite Verification]")
print(f"History count for session: {hist.get('count')}")

sess = get(f"{BASE}/sessions")
print(f"Sessions count in DB: {len(sess.get('sessions', []))}")

stats = get(f"{BASE}/db/stats")
print(f"DB Stats: {stats}")

# Check Notebook export endpoint
nb_resp = post(f"{BASE}/export/notebook", {"session_id": sid})
print(f"\n[Notebook Export Verification]")
print(f"Notebook cells count: {len(nb_resp.get('cells', []))}")
print(f"Notebook nbformat: {nb_resp.get('nbformat')}")


