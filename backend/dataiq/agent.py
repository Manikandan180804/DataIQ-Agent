"""
dataiq/agent.py
---------------
DataIQ agent core: orchestrates the full pipeline:
  load → schema → route → execute/codegen → format → respond

This module is LLM-provider-agnostic; it calls a `code_gen_fn` callable
that you inject (OpenAI, Anthropic, local Ollama, etc.).
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

from .executor import ExecutionResult, safe_exec, strip_code_fences
from .formatter import (
    build_error_response,
    build_out_of_scope_response,
    build_response,
    format_scalar,
)
from .loader import infer_schema, load_dataset, list_sheets, schema_to_text
from .router import RouteDecision, QueryType, execute_simple, execute_complex_fallback, route


# ---------------------------------------------------------------------------
# Out-of-scope detection
# ---------------------------------------------------------------------------

_OUT_OF_SCOPE_PATTERNS = [
    "predict", "forecast", "future", "next quarter", "next year",
    "will happen", "projection", "stock price", "trading signal",
    "sentiment", "emotion", "translate", "write a poem",
]


def _is_out_of_scope(query: str) -> bool:
    q = query.lower()
    return any(kw in q for kw in _OUT_OF_SCOPE_PATTERNS)


# ---------------------------------------------------------------------------
# DataIQ Agent class
# ---------------------------------------------------------------------------

class DataIQAgent:
    """
    The main DataIQ agent.

    Parameters
    ----------
    code_gen_fn : Callable[[str, str], str] | None
        A function that takes (system_prompt, user_prompt) and returns
        a Python code string. If None, the agent only handles simple
        queries via the direct pandas router.
    max_retries : int
        Number of retry attempts for code execution errors.
    """

    def __init__(
        self,
        code_gen_fn: Optional[Callable[[str, str], str]] = None,
        max_retries: int = 1,
    ):
        self.code_gen_fn = code_gen_fn
        self.max_retries = max_retries
        self.df: Optional[pd.DataFrame] = None
        self.schema: Optional[dict] = None
        self.history: list[dict] = []

    # ------------------------------------------------------------------
    # Data management
    # ------------------------------------------------------------------

    def load(self, path: str, sheet_name: Any = 0) -> str:
        """
        Load a CSV or Excel file. Returns a human-readable summary.
        """
        self.df = load_dataset(path, sheet_name=sheet_name)
        self.schema = infer_schema(self.df)
        summary = schema_to_text(self.schema)
        return f"✅ Dataset loaded successfully.\n\n{summary}"

    def list_sheets(self, path: str) -> list[str]:
        """List all sheets in an Excel file."""
        return list_sheets(path)

    def reset(self):
        """Clear the loaded dataset and conversation history."""
        self.df = None
        self.schema = None
        self.history = []

    # ------------------------------------------------------------------
    # Query answering
    # ------------------------------------------------------------------

    def ask(self, query: str) -> str:
        """
        Main entry point: answer a natural-language question about the data.

        Returns a formatted DataIQ response string.
        """
        if self.df is None or self.schema is None:
            return (
                "⚠️ No dataset loaded. Use `load <path>` to load a CSV or Excel file first."
            )

        # Out-of-scope guard
        if _is_out_of_scope(query):
            response = build_out_of_scope_response(
                query,
                "This query requires prediction or external data, which DataIQ does not support.",
            )
            self._record(query, response)
            return response

        # Route the query
        decision = route(query, self.schema)

        if decision.is_simple:
            response = self._handle_simple(query, decision)
        else:
            response = self._handle_complex(query, decision)

        self._record(query, response)
        return response

    # ------------------------------------------------------------------
    # Internal: simple path
    # ------------------------------------------------------------------

    def _handle_simple(self, query: str, decision: RouteDecision) -> str:
        try:
            exec_data = execute_simple(decision, self.df)
            result = exec_data["result"]
            code = exec_data["code"]
            method = exec_data["methodology"]

            plot_base64 = ""
            if "plt." in code or "plot(" in code or "plot." in code or any(k in query.lower() for k in ["plot", "plots", "chart", "charts", "graph", "graphs", "bar", "line", "hist", "histogram", "scatter", "pie", "draw", "visualize", "figure", "diagram"]):
                plot_type = 'pie' if 'pie' in query.lower() else 'line' if 'line' in query.lower() else 'bar'
                plot_code = code + "\n" + textwrap.dedent(f"""
                    import matplotlib.pyplot as plt
                    plt.figure(figsize=(8, 4.5))
                    if isinstance(result, pd.DataFrame):
                        num_c = list(result.select_dtypes(include=['number']).columns)
                        cat_c = [c for c in result.columns if c not in num_c]
                        x_c = cat_c[0] if cat_c else result.columns[0]
                        y_c = num_c[0] if num_c else (result.columns[1] if len(result.columns)>1 else result.columns[0])
                        result.plot(kind='{plot_type}', x=x_c, y=y_c, color='#7c3aed', ax=plt.gca())
                    elif isinstance(result, pd.Series):
                        result.plot(kind='{plot_type}', color='#7c3aed', ax=plt.gca())
                    else:
                        cat_cols = list(df.select_dtypes(include=['object', 'category']).columns)
                        num_cols = list(df.select_dtypes(include=['number']).columns)
                        if cat_cols and num_cols:
                            g = df.groupby(cat_cols[0])[num_cols[0]].sum()
                            g.plot(kind='{plot_type}', color='#7c3aed', ax=plt.gca())
                    plt.title('DataIQ Visualization', fontsize=12, fontweight='bold')
                    plt.grid(True, linestyle='--', alpha=0.5)
                    plt.tight_layout()
                """)
                exec_res = safe_exec(plot_code, self.df)
                if exec_res.ok and exec_res.plot_base64:
                    result = exec_res.result if exec_res.result is not None else result
                    plot_base64 = exec_res.plot_base64
                    code = plot_code

            answer = self._narrate_simple(result, decision, query)
            return build_response(answer, code, result, method, query, plot_base64=plot_base64)

        except Exception as exc:
            return build_error_response(query, str(exc), "Try specifying the column name explicitly.")

    def _narrate_simple(self, result: Any, decision: RouteDecision, query: str) -> str:
        """Convert a simple result to a natural-language sentence."""
        qt = decision.query_type
        col = decision.column_hints[0] if decision.column_hints else "the dataset"
        n = decision.n_hint or 10

        if qt == QueryType.COUNT:
            if isinstance(result, (int, float)):
                col_label = decision.column_hints[0] if decision.column_hints else None
                return f"There are **{format_scalar(result)}** records" + (
                    f" in column `{col_label}`." if col_label else " in the dataset."
                )
        if qt == QueryType.SUM:
            return f"The total sum of `{col}` is **{format_scalar(result)}**."
        if qt == QueryType.MEAN:
            return f"The average (mean) of `{col}` is **{format_scalar(result)}**."
        if qt == QueryType.MAX:
            return f"The maximum value in `{col}` is **{format_scalar(result)}**."
        if qt == QueryType.MIN:
            return f"The minimum value in `{col}` is **{format_scalar(result)}**."
        if qt == QueryType.UNIQUE:
            col_label = decision.column_hints[0] if decision.column_hints else "(column)"
            return f"There are **{format_scalar(result)}** unique values in `{col_label}`."
        if qt == QueryType.TOP_N:
            col_label = decision.column_hints[0] if decision.column_hints else col
            return f"Here are the top **{n}** rows by `{col_label}`:"
        if qt == QueryType.BOTTOM_N:
            col_label = decision.column_hints[0] if decision.column_hints else col
            return f"Here are the bottom **{n}** rows by `{col_label}`:"
        if qt == QueryType.DESCRIBE:
            return "Here is the statistical summary of the dataset:"
        if qt == QueryType.HEAD:
            return f"Here are the first **{n}** rows of the dataset:"

        return "Computed result:"

    # ------------------------------------------------------------------
    # Internal: complex path (code-gen)
    # ------------------------------------------------------------------

    def _handle_complex(self, query: str, decision: RouteDecision) -> str:
        if self.code_gen_fn is None:
            # Run local fallback router execution
            try:
                fallback_res = execute_complex_fallback(query, self.df)
                exec_res = safe_exec(fallback_res["code"], self.df)
                plot_b64 = exec_res.plot_base64 if exec_res.ok else ""
                res_val = exec_res.result if (exec_res.ok and exec_res.result is not None) else fallback_res["result"]
                answer = self._narrate_complex(res_val, query)
                return build_response(answer, fallback_res["code"], res_val, fallback_res["methodology"], query, plot_base64=plot_b64)
            except Exception as exc:
                return build_error_response(query, f"Analysis failed: {exc}", "Provide a simpler question or connect an OpenAI API key.")

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_codegen_prompt(query, decision)

        attempt = 0
        last_error = ""

        while attempt <= self.max_retries:
            if attempt > 0:
                user_prompt = self._build_retry_prompt(query, decision, last_error)

            try:
                raw_code = self.code_gen_fn(system_prompt, user_prompt)
                code = strip_code_fences(raw_code)
            except Exception as exc:
                try:
                    fallback_res = execute_complex_fallback(query, self.df)
                    exec_res = safe_exec(fallback_res["code"], self.df)
                    plot_b64 = exec_res.plot_base64 if exec_res.ok else ""
                    res_val = exec_res.result if (exec_res.ok and exec_res.result is not None) else fallback_res["result"]
                    answer = self._narrate_complex(res_val, query)
                    return build_response(answer, fallback_res["code"], res_val, fallback_res["methodology"], query, plot_base64=plot_b64)
                except Exception:
                    return build_error_response(query, f"Code generation failed: {exc}")

            exec_result: ExecutionResult = safe_exec(code, self.df)

            if exec_result.ok:
                plot_b64 = exec_result.plot_base64
                if not plot_b64 and any(k in query.lower() for k in ["plot", "plots", "plotting", "chart", "charts", "graph", "graphs", "bar", "line", "hist", "histogram", "scatter", "pie", "draw", "visualize", "visualise", "visualization", "figure", "diagram"]):
                    plot_type = 'pie' if 'pie' in query.lower() else 'line' if 'line' in query.lower() else 'scatter' if 'scatter' in query.lower() else 'bar'
                    plot_code = code + "\n" + textwrap.dedent(f"""
                        import matplotlib.pyplot as plt
                        plt.figure(figsize=(8, 4.5))
                        if isinstance(result, pd.DataFrame):
                            num_c = list(result.select_dtypes(include=['number']).columns)
                            cat_c = [c for c in result.columns if c not in num_c]
                            x_c = cat_c[0] if cat_c else result.columns[0]
                            y_c = num_c[0] if num_c else (result.columns[1] if len(result.columns)>1 else result.columns[0])
                            if '{plot_type}' == 'pie':
                                plt.pie(result[y_c].head(8), labels=result[x_c].head(8), autopct='%1.1f%%')
                            else:
                                result.plot(kind='{plot_type}', x=x_c, y=y_c, color='#7c3aed', ax=plt.gca())
                        elif isinstance(result, pd.Series):
                            if '{plot_type}' == 'pie':
                                plt.pie(result.head(8), labels=result.index[:8], autopct='%1.1f%%')
                            else:
                                result.plot(kind='{plot_type}', color='#7c3aed', ax=plt.gca())
                        else:
                            cat_cols = list(df.select_dtypes(include=['object', 'category']).columns)
                            num_cols = list(df.select_dtypes(include=['number']).columns)
                            if cat_cols and num_cols:
                                g = df.groupby(cat_cols[0])[num_cols[0]].sum()
                                g.plot(kind='{plot_type}', color='#7c3aed', ax=plt.gca())
                        plt.title('DataIQ Visualization', fontsize=12, fontweight='bold')
                        plt.grid(True, linestyle='--', alpha=0.5)
                        plt.tight_layout()
                    """)
                    plot_exec = safe_exec(plot_code, self.df)
                    if plot_exec.ok and plot_exec.plot_base64:
                        plot_b64 = plot_exec.plot_base64
                        code = plot_code

                answer = self._narrate_complex(exec_result.result, query)
                method = self._extract_methodology(code, decision)
                return build_response(
                    answer,
                    code,
                    exec_result.result,
                    method,
                    query,
                    plot_base64=plot_b64,
                )

            last_error = exec_result.error
            attempt += 1

        # All retries exhausted
        return build_error_response(
            query,
            f"Execution failed after {self.max_retries + 1} attempt(s).\n\nLast error:\n{last_error}",
            "Try rephrasing with explicit column names, or break into smaller sub-questions.",
        )

    def _narrate_complex(self, result: Any, query: str) -> str:
        """Generate a natural-language answer for a complex query result."""
        if isinstance(result, pd.DataFrame):
            return f"Here are the results for your query ({len(result):,} rows returned):"
        if isinstance(result, pd.Series):
            return f"Here is the computed series ({len(result):,} values):"
        if isinstance(result, (int, float)):
            return f"The computed result is **{format_scalar(result)}**."
        return "Here is the computed result:"

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        schema_text = schema_to_text(self.schema)
        return textwrap.dedent(f"""
            You are DataIQ, a deterministic data-analysis code generator.
            Your job is to write a single self-contained Python (pandas) code snippet
            that answers the user's question about a DataFrame named `df`.

            AVAILABLE VARIABLES in the execution namespace:
            - df   : pandas DataFrame (the user's dataset)
            - pd   : pandas
            - np   : numpy
            - plt  : matplotlib.pyplot
            - math : Python math module
            - datetime : Python datetime module

            RULES:
            1. Assign the final answer to a variable named `result`.
            2. Do NOT import os, sys, subprocess, requests, or any network library.
            3. Do NOT read or write any files.
            4. Use only the columns listed in the schema below.
            5. Handle NaN/null values gracefully (use skipna=True, dropna(), or fillna()).
            6. Output only valid Python code — no explanations, no markdown fences.
            7. If you need to parse dates, use pd.to_datetime(..., errors='coerce').
            8. If the user asks for a plot, chart, bar, graph, or visualization, generate a Matplotlib figure using plt (e.g. plt.figure(figsize=(8,4)), df.groupby(...).plot(kind='bar', color='#7c3aed'), plt.title(...), plt.tight_layout()) AND set `result` to the aggregated DataFrame or Series.

            DATASET SCHEMA:
            {schema_text}
        """).strip()

    def _build_codegen_prompt(self, query: str, decision: RouteDecision) -> str:
        hints = ""
        if decision.column_hints:
            hints = f"\nColumn hints from query: {', '.join(decision.column_hints)}"
        if decision.filter_hint:
            hints += f"\nFilter hint: {decision.filter_hint}"
        return f"Question: {query}{hints}\n\nWrite the pandas code:"

    def _build_retry_prompt(self, query: str, decision: RouteDecision, error: str) -> str:
        base = self._build_codegen_prompt(query, decision)
        return (
            f"{base}\n\n"
            f"Your previous attempt failed with this error:\n```\n{error[:800]}\n```\n"
            f"Fix the error and try again. Output only valid Python code."
        )

    def _extract_methodology(self, code: str, decision: RouteDecision) -> str:
        lines = [
            "- Code generated by LLM and executed in a sandboxed namespace.",
            "- NaN values handled per pandas defaults (skipna=True for aggregations).",
        ]
        if decision.column_hints:
            lines.append(f"- Columns referenced: {', '.join(decision.column_hints)}.")
        if decision.filter_hint:
            lines.append(f"- Filter applied: '{decision.filter_hint}'.")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def _record(self, query: str, response: str):
        self.history.append({"query": query, "response": response})
