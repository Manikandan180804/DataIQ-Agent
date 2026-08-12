"""
server.py
---------
Flask REST API server for the DataIQ web UI.

API key priority order:
  1. Per-request header:  X-OpenAI-Key  (from UI settings panel)
  2. .env file:           OPENAI_API_KEY
  3. System env var:      OPENAI_API_KEY

Endpoints:
  GET  /api/health              — health + LLM status
  POST /api/load                — upload CSV/Excel file
  POST /api/load_sample         — load bundled sample_data.csv
  POST /api/ask                 — ask a question
  POST /api/configure           — update API key/model live (no restart)
  POST /api/reset               — clear session

Run:
  pip install flask flask-cors python-dotenv openai
  python server.py
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

# ── Load .env FIRST before anything reads os.environ ─────────────────────
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent.parent / ".env"
    if not _env_path.exists():
        _env_path = Path(__file__).parent / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path, override=False)  # env vars take priority
        print(f"[DataIQ] Loaded .env from {_env_path}")
except ImportError:
    print("[DataIQ] python-dotenv not installed; skipping .env load. Run: pip install python-dotenv")

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import sys
sys.path.insert(0, str(Path(__file__).parent))
from dataiq.agent import DataIQAgent
from dataiq.db import get_db

frontend_dir = Path(__file__).parent.parent / "frontend"
if not frontend_dir.exists():
    frontend_dir = Path(__file__).parent / "frontend"
if not frontend_dir.exists():
    frontend_dir = Path(__file__).parent

app = Flask(__name__, static_folder=str(frontend_dir), static_url_path="")
CORS(app, expose_headers=["X-LLM-Name"])

# ── SQLite DB ─────────────────────────────────────────────────────────────
db = get_db()
print(f"[DataIQ] SQLite DB  : {db.db_path}")

# ── Session store ─────────────────────────────────────────────────────────
_sessions: dict[str, DataIQAgent] = {}

UPLOAD_FOLDER = Path(__file__).parent / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)
ALLOWED_EXT = {".csv", ".tsv", ".txt", ".xls", ".xlsx", ".xlsm"}

# ── Runtime-mutable config (can be updated via /api/configure) ────────────
_runtime_config: dict = {
    "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
    "openai_model":   os.environ.get("OPENAI_MODEL", "gpt-4o"),
    "ollama_model":   os.environ.get("OLLAMA_MODEL", ""),
}


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------

def _build_openai_fn(api_key: str, model: str):
    """Build an OpenAI code-gen callable."""
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)

        def fn(sys_p: str, usr_p: str) -> str:
            r = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": sys_p},
                    {"role": "user",   "content": usr_p},
                ],
                temperature=0,
                max_tokens=1024,
            )
            return r.choices[0].message.content

        return fn, f"OpenAI {model}"
    except ImportError:
        raise RuntimeError("openai package not installed. Run: pip install openai")


def _build_ollama_fn(model: str):
    """Build an Ollama local code-gen callable."""
    import requests as req

    def fn(sys_p: str, usr_p: str) -> str:
        r = req.post(
            "http://localhost:11434/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_p},
                    {"role": "user",   "content": usr_p},
                ],
                "stream": False,
                "options": {"temperature": 0},
            },
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["message"]["content"]

    return fn, f"Ollama {model}"


def _resolve_code_gen_fn(request_api_key: str | None = None):
    """
    Resolve the best available code-gen function.
    Priority: per-request key → runtime config key → env var.
    Returns (fn, llm_name).
    """
    # Per-request API key overrides everything
    api_key = request_api_key or _runtime_config.get("openai_api_key") or ""
    model   = _runtime_config.get("openai_model", "gpt-4o-mini")

    if api_key and api_key not in ("", "sk-...paste-your-key-here..."):
        try:
            return _build_openai_fn(api_key.strip(), model)
        except RuntimeError as e:
            app.logger.warning(str(e))

    # Ollama fallback
    ollama_model = _runtime_config.get("ollama_model", "")
    if ollama_model:
        try:
            return _build_ollama_fn(ollama_model)
        except Exception:
            pass

    return None, "None (simple queries only)"


# Initial LLM name for health endpoint
def _current_llm_name() -> str:
    _, name = _resolve_code_gen_fn()
    return name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_create_session(session_id: str | None, request_api_key: str | None = None) -> tuple[str, DataIQAgent]:
    if session_id and session_id in _sessions:
        agent = _sessions[session_id]
        # Hot-swap LLM if a new key is provided
        if request_api_key:
            fn, _ = _resolve_code_gen_fn(request_api_key)
            agent.code_gen_fn = fn
        return session_id, agent
    sid = str(uuid.uuid4())
    fn, _ = _resolve_code_gen_fn(request_api_key)
    agent = DataIQAgent(code_gen_fn=fn, max_retries=1)
    _sessions[sid] = agent
    return sid, agent


def _allowed(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXT


def _schema_payload(schema: dict) -> dict:
    return {
        "shape":            schema.get("shape"),
        "columns":          schema.get("columns"),
        "dtypes":           schema.get("dtypes"),
        "numeric_cols":     schema.get("numeric_cols"),
        "categorical_cols": schema.get("categorical_cols"),
        "datetime_cols":    schema.get("datetime_cols"),
        "null_counts":      schema.get("null_counts"),
        "total_nulls":      schema.get("total_nulls"),
        "sample":           schema.get("sample"),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "llm":    _current_llm_name(),
        "sessions": len(_sessions),
        "key_configured": bool(
            _runtime_config.get("openai_api_key", "")
            and _runtime_config["openai_api_key"] not in ("", "sk-...paste-your-key-here...")
        ),
    })


@app.route("/api/configure", methods=["POST"])
def configure():
    """
    Update LLM config at runtime — no server restart required.
    Body: { api_key, model, session_id? }
    """
    body      = request.get_json(force=True) or {}
    api_key   = (body.get("api_key") or "").strip()
    model     = (body.get("model") or "gpt-4o-mini").strip()
    session_id = body.get("session_id")

    if not api_key:
        return jsonify({"error": "api_key is required"}), 400

    # Validate key format (basic check)
    if not api_key.startswith("sk-"):
        return jsonify({"error": "Invalid API key format. OpenAI keys start with 'sk-'"}), 400

    # Update runtime config
    _runtime_config["openai_api_key"] = api_key
    _runtime_config["openai_model"]   = model

    # Hot-swap existing session if provided
    if session_id and session_id in _sessions:
        fn, llm_name = _resolve_code_gen_fn(api_key)
        _sessions[session_id].code_gen_fn = fn
    else:
        fn, llm_name = _resolve_code_gen_fn(api_key)

    print(f"[DataIQ] LLM config updated: {llm_name}")
    return jsonify({"ok": True, "llm": llm_name, "model": model})


@app.route("/api/load", methods=["POST"])
def load_file():
    if "file" not in request.files:
        return jsonify({"error": "No file in request"}), 400

    file = request.files["file"]
    if not file.filename or not _allowed(file.filename):
        return jsonify({"error": "Unsupported file type. Use CSV or Excel."}), 400

    safe_name = uuid.uuid4().hex + Path(file.filename).suffix.lower()
    save_path = UPLOAD_FOLDER / safe_name
    file.save(str(save_path))

    session_id      = request.form.get("session_id")
    request_api_key = request.headers.get("X-OpenAI-Key") or request.form.get("api_key")
    sid, agent      = _get_or_create_session(session_id, request_api_key)

    try:
        sheet = request.form.get("sheet", 0)
        try:
            sheet = int(sheet)
        except (ValueError, TypeError):
            pass
        agent.load(str(save_path), sheet_name=sheet)
        _, llm_name = _resolve_code_gen_fn(request_api_key)
        # ── Persist session to SQLite ─────────────────────────
        db.save_session(sid, file.filename, agent.schema, llm_name)
        return jsonify({"session_id": sid, "llm": llm_name, "schema": _schema_payload(agent.schema)})
    except Exception as exc:
        save_path.unlink(missing_ok=True)
        return jsonify({"error": str(exc)}), 500


SAMPLE_DATASETS_META = [
    {
        "filename": "01_sales_performance.csv",
        "title": "Sales Performance & Revenue",
        "type": "CSV",
        "icon": "📊",
        "description": "25 retail sales transactions with order status, category, units, price, and total revenue.",
        "questions": ["Total revenue by region?", "Which category has highest sales?", "Show top 5 orders by revenue"]
    },
    {
        "filename": "02_employee_payroll.csv",
        "title": "HR & Employee Payroll",
        "type": "CSV",
        "icon": "👥",
        "description": "Employee demographics, departments, salary, bonus %, performance score, and remote status.",
        "questions": ["Average salary by department?", "How many remote employees?", "Highest bonus percentage?"]
    },
    {
        "filename": "03_ecommerce_orders.csv",
        "title": "E-Commerce Order Fulfillment",
        "type": "CSV",
        "icon": "🛒",
        "description": "Customer order data with countries, payment methods, shipping fees, and fulfillment status.",
        "questions": ["Total orders by country?", "Most popular payment method?", "Average order subtotal?"]
    },
    {
        "filename": "04_financial_transactions.csv",
        "title": "Banking & Financial Audit",
        "type": "CSV",
        "icon": "💳",
        "description": "Financial ledger of wire transfers, payroll, vendor payments, amounts, and risk ratings.",
        "questions": ["Sum of positive transactions?", "Count of high risk transactions?", "Total vendor payments?"]
    },
    {
        "filename": "05_customer_churn_analytics.csv",
        "title": "SaaS Customer Churn",
        "type": "CSV",
        "icon": "📈",
        "description": "Subscription plans, tenure months, monthly fees, support tickets, and churn flags.",
        "questions": ["Churn rate by subscription plan?", "Average tenure of churned customers?", "Monthly revenue by plan?"]
    },
    {
        "filename": "06_real_estate_listings.xlsx",
        "title": "Real Estate Property Market",
        "type": "Excel",
        "icon": "🏠",
        "description": "Housing listings with city, property type, bedrooms, sq ft, year built, and listing prices.",
        "questions": ["Average price per square foot by city?", "Highest price property details?", "Average bedrooms per city?"]
    },
    {
        "filename": "07_marketing_campaigns.xlsx",
        "title": "Digital Marketing Campaigns ROI",
        "type": "Excel",
        "icon": "🎯",
        "description": "Ad campaign performance metrics: budget, impressions, clicks, conversions, and revenue.",
        "questions": ["Channel with highest ROI/Revenue?", "Total budget spent across channels?", "Average CTR by channel?"]
    },
    {
        "filename": "08_student_academic_performance.xlsx",
        "title": "Student Academic Scores",
        "type": "Excel",
        "icon": "🎓",
        "description": "Student grades in Math, Science, English, attendance percentage, study hours, and GPA.",
        "questions": ["Average GPA by grade level?", "Correlation between study hours and GPA?", "Top 3 students by math score"]
    },
    {
        "filename": "09_inventory_warehouse_stock.xlsx",
        "title": "Warehouse Inventory Stock",
        "type": "Excel",
        "icon": "📦",
        "description": "SKU catalog, stock quantities, reorder thresholds, unit costs, and warehouse zones.",
        "questions": ["Which items need reordering (Stock < Threshold)?", "Total inventory valuation (Stock * Cost)?", "Stock quantity by zone?"]
    },
    {
        "filename": "10_healthcare_patient_records.xlsx",
        "title": "Healthcare & Patient Billing",
        "type": "Excel",
        "icon": "🏥",
        "description": "Hospital patient admissions, age, blood type, diagnosis, stay duration, and billing amounts.",
        "questions": ["Average hospital stay by diagnosis?", "Total billing amount by diagnosis?", "Patient age distribution?"]
    }
]

@app.route("/api/sample_datasets", methods=["GET"])
def list_sample_datasets():
    return jsonify({"datasets": SAMPLE_DATASETS_META})


@app.route("/api/load_sample_file", methods=["POST"])
def load_sample_file():
    body = request.get_json(force=True, silent=True) or {}
    filename = body.get("filename") or "01_sales_performance.csv"
    
    safe_fn = Path(filename).name
    sample_path = Path(__file__).parent / "sample_datasets" / safe_fn
    if not sample_path.exists():
        sample_path = Path(__file__).parent / "sample_data.csv"
        if not sample_path.exists():
            return jsonify({"error": f"Sample dataset {safe_fn} not found"}), 404
        safe_fn = "sample_data.csv"

    session_id = body.get("session_id")
    request_api_key = request.headers.get("X-OpenAI-Key") or body.get("api_key")
    sid, agent = _get_or_create_session(session_id, request_api_key)

    try:
        agent.load(str(sample_path))
        _, llm_name = _resolve_code_gen_fn(request_api_key)
        db.save_session(sid, safe_fn, agent.schema, llm_name)
        
        meta = next((item for item in SAMPLE_DATASETS_META if item["filename"] == safe_fn), None)
        questions = meta["questions"] if meta else []

        return jsonify({
            "session_id": sid,
            "llm": llm_name,
            "schema": _schema_payload(agent.schema),
            "filename": safe_fn,
            "questions": questions,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/load_sample", methods=["POST"])
def load_sample():
    sample_path = Path(__file__).parent / "sample_data.csv"
    if not sample_path.exists():
        return jsonify({"error": "sample_data.csv not found"}), 404

    body           = request.get_json(force=True, silent=True) or {}
    session_id     = body.get("session_id")
    request_api_key = request.headers.get("X-OpenAI-Key") or body.get("api_key")
    sid, agent     = _get_or_create_session(session_id, request_api_key)

    try:
        agent.load(str(sample_path))
        _, llm_name = _resolve_code_gen_fn(request_api_key)
        # ── Persist session to SQLite ─────────────────────────
        db.save_session(sid, "sample_data.csv", agent.schema, llm_name)
        return jsonify({
            "session_id": sid,
            "llm": llm_name,
            "schema": _schema_payload(agent.schema),
            "filename": "sample_data.csv",
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/ask", methods=["POST"])
def ask():
    import time
    body            = request.get_json(force=True) or {}
    query           = (body.get("query") or "").strip()
    session_id      = body.get("session_id")
    request_api_key = request.headers.get("X-OpenAI-Key") or body.get("api_key")

    if not query:
        return jsonify({"error": "Empty query"}), 400
    if not session_id or session_id not in _sessions:
        return jsonify({"error": "Session not found. Please reload your dataset."}), 404

    agent = _sessions[session_id]
    if request_api_key:
        fn, llm_name = _resolve_code_gen_fn(request_api_key)
        agent.code_gen_fn = fn
    else:
        _, llm_name = _resolve_code_gen_fn()

    try:
        t0     = time.monotonic()
        answer = agent.ask(query)
        ms     = int((time.monotonic() - t0) * 1000)

        # Detect query type from answer prefix for DB tagging
        q_type = "out_of_scope" if "Out of Scope" in answer else \
                 "error"       if "[Error]" in answer else \
                 "simple"

        # ── Persist Q&A to SQLite ────────────────────────────
        db.save_qa(session_id, query, answer, q_type, ms)

        return jsonify({"answer": answer, "session_id": session_id, "llm": llm_name, "duration_ms": ms})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/history", methods=["GET"])
def get_history():
    """GET /api/history?session_id=<id>&limit=50&offset=0"""
    session_id = request.args.get("session_id")
    limit  = int(request.args.get("limit",  50))
    offset = int(request.args.get("offset",  0))
    keyword = request.args.get("q", "").strip()

    if keyword:
        rows = db.search_history(keyword, session_id, limit)
    elif session_id:
        rows = db.get_history(session_id, limit, offset)
    else:
        rows = db.get_all_history(limit)

    return jsonify({"history": rows, "count": len(rows)})


@app.route("/api/sessions", methods=["GET"])
def list_sessions():
    """GET /api/sessions — list recent sessions from DB."""
    limit = int(request.args.get("limit", 20))
    sessions = db.list_sessions(limit)
    # Decode columns_json for convenience
    for s in sessions:
        try:
            s["columns"] = json.loads(s.get("columns_json") or "[]")
        except Exception:
            s["columns"] = []
    return jsonify({"sessions": sessions})


@app.route("/api/db/stats", methods=["GET"])
def db_stats():
    """GET /api/db/stats — database size and counts."""
    return jsonify(db.stats())


@app.route("/api/reset", methods=["POST"])
def reset_session():
    body = request.get_json(force=True) or {}
    sid  = body.get("session_id")
    if sid and sid in _sessions:
        _sessions[sid].reset()
        del _sessions[sid]
    return jsonify({"ok": True})


@app.route("/api/export/notebook", methods=["POST"])
def export_notebook():
    """
    POST /api/export/notebook — Export session Q&A history to a Jupyter Notebook (.ipynb).
    Body: { "session_id": "..." }
    """
    body = request.get_json(force=True) or {}
    session_id = body.get("session_id")

    if not session_id or session_id not in _sessions:
        return jsonify({"error": "Session not found or invalid"}), 404

    agent = _sessions[session_id]
    history = agent.history

    cells = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# DataIQ Automated Analysis Notebook\n",
                "Generated reproducibly by DataIQ CSV Agent.\n",
                "\n",
                "```python\n",
                "import pandas as pd\n",
                "import numpy as np\n",
                "import matplotlib.pyplot as plt\n",
                "# Load dataset:\n",
                "# df = pd.read_csv('sample_data.csv')\n",
                "```",
            ],
        }
    ]

    for item in history:
        query = item.get("query", "")
        response_md = item.get("response", "")

        # Extract code block if present
        code = ""
        if "```python" in response_md:
            code = response_md.split("```python")[1].split("```")[0].strip()

        cells.append({
            "cell_type": "markdown",
            "metadata": {},
            "source": [f"### Query: {query}\n\n", response_md],
        })

        if code:
            cells.append({
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [code],
            })

    notebook = {
        "cells": cells,
        "metadata": {
            "language_info": {"name": "python", "version": "3.10"}
        },
        "nbformat": 4,
        "nbformat_minor": 2,
    }

    from flask import Response
    return Response(
        json.dumps(notebook, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment;filename=dataiq_analysis.ipynb"},
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    _, llm_name = _resolve_code_gen_fn()
    print(f"\n[DataIQ] Server starting on http://127.0.0.1:{port}")
    print(f"[DataIQ] LLM backend : {llm_name}")
    if llm_name.startswith("None"):
        print("[DataIQ] TIP: Add your OpenAI key to .env or use the Settings panel in the UI")
    print(f"[DataIQ] Open http://127.0.0.1:{port} in your browser\n")
    app.run(debug=True, port=port, use_reloader=False)
