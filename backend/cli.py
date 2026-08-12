"""
cli.py
------
DataIQ CLI — interactive REPL for CSV/Excel data question-answering.

Usage:
  python cli.py                        # starts interactive REPL
  python cli.py --file data.csv        # load file on startup
  python cli.py --file data.csv --ask "What is the total revenue?"

Optional LLM backend (set env vars):
  OPENAI_API_KEY   → uses OpenAI gpt-4o-mini for code-gen
  OLLAMA_MODEL     → uses local Ollama (e.g. llama3) for code-gen
  (no env vars)    → simple queries only (no code-gen)
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from pathlib import Path

# Ensure the package is importable when running from the project root
sys.path.insert(0, str(Path(__file__).parent))

from dataiq.agent import DataIQAgent


# ---------------------------------------------------------------------------
# LLM backend factory
# ---------------------------------------------------------------------------

def _build_code_gen_fn():
    """
    Build a code_gen_fn based on available API keys/configuration.
    Returns None if no LLM backend is configured (simple queries only).
    """
    # --- OpenAI ---
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        try:
            import openai
            client = openai.OpenAI(api_key=openai_key)
            model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

            def openai_codegen(system_prompt: str, user_prompt: str) -> str:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0,
                    max_tokens=1024,
                )
                return resp.choices[0].message.content

            print(f"[DataIQ] Using OpenAI backend: {model}")
            return openai_codegen
        except ImportError:
            print("[DataIQ] openai package not installed. Run: pip install openai")

    # --- Ollama (local) ---
    ollama_model = os.environ.get("OLLAMA_MODEL")
    if ollama_model:
        try:
            import requests

            def ollama_codegen(system_prompt: str, user_prompt: str) -> str:
                payload = {
                    "model": ollama_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                    "options": {"temperature": 0},
                }
                resp = requests.post(
                    "http://localhost:11434/api/chat", json=payload, timeout=120
                )
                resp.raise_for_status()
                return resp.json()["message"]["content"]

            print(f"[DataIQ] Using Ollama backend: {ollama_model}")
            return ollama_codegen
        except ImportError:
            print("[DataIQ] requests package not installed. Run: pip install requests")

    print("[DataIQ] No LLM backend configured. Simple queries only.")
    print("[DataIQ] Set OPENAI_API_KEY or OLLAMA_MODEL to enable complex queries.\n")
    return None


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

BANNER = r"""
╔══════════════════════════════════════════════════════════╗
║   ██████╗  █████╗ ████████╗ █████╗   ██╗ ██████╗       ║
║   ██╔══██╗██╔══██╗╚══██╔══╝██╔══██╗  ██║██╔═══██╗      ║
║   ██║  ██║███████║   ██║   ███████║  ██║██║   ██║      ║
║   ██║  ██║██╔══██║   ██║   ██╔══██║  ██║██║▄▄ ██║      ║
║   ██████╔╝██║  ██║   ██║   ██║  ██║  ██║╚██████╔╝      ║
║   ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝  ╚═╝ ╚══▀▀═╝       ║
║                                                          ║
║   CSV / Excel Q&A Agent   v1.0.0                        ║
║   Type 'help' for commands, 'quit' to exit              ║
╚══════════════════════════════════════════════════════════╝
"""

HELP_TEXT = """
Available commands:
  load <path>              Load a CSV or Excel file
  load <path> <sheet>      Load a specific Excel sheet (name or index)
  sheets <path>            List all sheets in an Excel file
  schema                   Show schema of the loaded dataset
  ask <question>           Ask a question about the data
  history                  Show Q&A history for this session
  reset                    Clear loaded data and history
  help                     Show this help message
  quit / exit              Exit DataIQ

Examples:
  load sales_data.csv
  load report.xlsx Revenue
  ask How many rows are in the dataset?
  ask What is the average order value?
  ask Show me total revenue by product category
  ask What are the top 5 customers by sales?
"""


def repl(agent: DataIQAgent):
    """Run the interactive DataIQ REPL."""
    print(BANNER)

    while True:
        try:
            raw = input("DataIQ> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Goodbye!")
            break

        if not raw:
            continue

        cmd_lower = raw.lower()

        # --- Built-in commands ---
        if cmd_lower in ("quit", "exit", "q"):
            print("👋 Goodbye!")
            break

        if cmd_lower in ("help", "?", "h"):
            print(HELP_TEXT)
            continue

        if cmd_lower == "history":
            if not agent.history:
                print("No Q&A history yet.")
            else:
                for i, item in enumerate(agent.history, 1):
                    print(f"\n{'─'*60}")
                    print(f"[{i}] Q: {item['query']}")
                    print(f"    A: {item['response'][:200]}...")
            continue

        if cmd_lower == "schema":
            if agent.schema is None:
                print("⚠️  No dataset loaded. Use: load <path>")
            else:
                from dataiq.loader import schema_to_text
                print(schema_to_text(agent.schema))
            continue

        if cmd_lower == "reset":
            agent.reset()
            print("✅ Session reset. Dataset and history cleared.")
            continue

        # --- load command ---
        if cmd_lower.startswith("load "):
            parts = raw.split(None, 2)
            path = parts[1] if len(parts) > 1 else ""
            sheet = parts[2] if len(parts) > 2 else 0
            # Try int conversion for sheet
            try:
                sheet = int(sheet)
            except (ValueError, TypeError):
                pass
            result = agent.load(path, sheet_name=sheet)
            print(result)
            continue

        # --- sheets command ---
        if cmd_lower.startswith("sheets "):
            parts = raw.split(None, 1)
            path = parts[1] if len(parts) > 1 else ""
            try:
                sheets = agent.list_sheets(path)
                print(f"Sheets in {path}:")
                for i, s in enumerate(sheets):
                    print(f"  [{i}] {s}")
            except Exception as e:
                print(f"❌ Error: {e}")
            continue

        # --- ask command ---
        if cmd_lower.startswith("ask "):
            query = raw[4:].strip()
        else:
            # Treat bare text as a question
            query = raw

        if query:
            print("\n" + "─" * 60)
            response = agent.ask(query)
            print(response)
            print("─" * 60 + "\n")


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="dataiq",
        description="DataIQ — CSV/Excel Q&A Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Environment variables:
              OPENAI_API_KEY   Enable OpenAI code-gen backend
              OPENAI_MODEL     Override model (default: gpt-4o-mini)
              OLLAMA_MODEL     Enable Ollama local code-gen backend
        """),
    )
    parser.add_argument("--file", "-f", help="CSV or Excel file to load on startup")
    parser.add_argument("--sheet", "-s", default=0, help="Excel sheet name or index (default: 0)")
    parser.add_argument("--ask", "-q", help="Single question to ask (non-interactive mode)")
    parser.add_argument("--no-llm", action="store_true", help="Disable LLM code-gen (simple queries only)")
    args = parser.parse_args()

    code_gen_fn = None if args.no_llm else _build_code_gen_fn()
    agent = DataIQAgent(code_gen_fn=code_gen_fn)

    # Load file if provided
    if args.file:
        sheet = args.sheet
        try:
            sheet = int(sheet)
        except (ValueError, TypeError):
            pass
        print(agent.load(args.file, sheet_name=sheet))

    # Non-interactive single-question mode
    if args.ask:
        print(agent.ask(args.ask))
        sys.exit(0)

    # Interactive REPL
    repl(agent)


if __name__ == "__main__":
    main()
