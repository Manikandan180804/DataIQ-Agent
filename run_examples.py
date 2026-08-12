"""
run_examples.py
---------------
Executes 10 real example queries against the DataIQ agent on `sample_data.csv`.
Saves full structured output to `run_results.json` and `run_results.md`.
"""

import json
import os
import sys
import time
from pathlib import Path

# Ensure root package is in import path
sys.path.insert(0, str(Path(__file__).parent))

from dataiq.agent import DataIQAgent
from dataiq.db import get_db

# Load API key from environment or .env if present
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

openai_key = os.environ.get("OPENAI_API_KEY")
model = os.environ.get("OPENAI_MODEL", "gpt-4o")

code_gen_fn = None
if openai_key and openai_key.startswith("sk-"):
    try:
        import openai
        client = openai.OpenAI(api_key=openai_key)
        def code_gen_fn(system_prompt: str, user_prompt: str) -> str:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
            )
            return resp.choices[0].message.content or ""
        print(f"[Run Examples] Using OpenAI LLM ({model})")
    except Exception as e:
        print(f"[Run Examples] LLM setup failed: {e}. Running with local direct ops only.")
else:
    print("[Run Examples] No OpenAI key found. Running with direct pandas ops.")

# Initialize Agent & DB
db = get_db()
agent = DataIQAgent(code_gen_fn=code_gen_fn)

sample_csv = Path(__file__).parent / "sample_data.csv"
agent.load(str(sample_csv))
schema = agent.schema
session_id = "real_run_demo_" + str(int(time.time()))

db.save_session(session_id, "sample_data.csv", schema, llm_backend=model if code_gen_fn else "Local-Only")

queries = [
    "How many total orders are in the dataset?",
    "What is the total revenue generated across all sales?",
    "Which product category generated the highest total revenue?",
    "What is the average unit price of products sold?",
    "List the top 5 highest revenue orders.",
    "How many unique customers made purchases?",
    "What is the total revenue for the North region?",
    "Which product has the highest total quantity sold?",
    "How many orders were returned?",
    "What will the total sales be next quarter?",
]

results = []
markdown_output = [
    "# DataIQ Real-Run Execution Results",
    f"- **Dataset:** `sample_data.csv` ({schema['shape']['rows']} rows, {schema['shape']['cols']} columns)",
    f"- **Execution Timestamp:** {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
    f"- **LLM Backend:** {model if code_gen_fn else 'Direct Pandas Operations'}",
    "\n---\n",
]

print("\nRunning 10 Real Examples...")
print("=" * 60)

for idx, q in enumerate(queries, 1):
    t0 = time.monotonic()
    answer = agent.ask(q)
    duration_ms = int((time.monotonic() - t0) * 1000)

    q_type = "out_of_scope" if "Out of Scope" in answer else \
             "error"       if "[Error]" in answer else \
             "simple"

    db.save_qa(session_id, q, answer, q_type, duration_ms)

    item = {
        "id": idx,
        "query": q,
        "answer_markdown": answer,
        "query_type": q_type,
        "duration_ms": duration_ms,
    }
    results.append(item)

    print(f"[{idx}/10] Query: {q}")
    print(f"       Duration: {duration_ms} ms | Type: {q_type}")

    markdown_output.append(f"## Example {idx}: {q}\n")
    markdown_output.append(f"**Execution Time:** {duration_ms} ms\n")
    markdown_output.append(answer)
    markdown_output.append("\n---\n")

# Save JSON results
json_file = Path(__file__).parent / "run_results.json"
with open(json_file, "w", encoding="utf-8") as f:
    json.dump({"session_id": session_id, "results": results}, f, indent=2)

# Save Markdown results
md_file = Path(__file__).parent / "run_results.md"
with open(md_file, "w", encoding="utf-8") as f:
    f.write("\n".join(markdown_output))

# Reconfigure stdout for utf-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

print("=" * 60)
print(f"Saved results to:\n  - {json_file}\n  - {md_file}")
print(f"Saved to SQLite DB: {db.db_path} (Session: {session_id})")
