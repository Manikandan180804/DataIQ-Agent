"""
dataiq/formatter.py
-------------------
Answer formatter: converts raw computation results into the standard
DataIQ output format (Answer → Code → Data View → Methodology).
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd


def format_scalar(value: Any) -> str:
    """Format a scalar result for display."""
    if isinstance(value, float):
        if value == int(value):
            return f"{int(value):,}"
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def format_dataframe(df: pd.DataFrame, max_rows: int = 20) -> str:
    """Convert a DataFrame to a markdown table string (truncated)."""
    if df.empty:
        return "_No data returned._"

    display_df = df.head(max_rows)
    md = display_df.to_markdown(index=False) if hasattr(display_df, "to_markdown") else display_df.to_string(index=False)

    if len(df) > max_rows:
        md += f"\n\n_... and {len(df) - max_rows:,} more rows (showing first {max_rows})._"

    return md


def format_series(series: pd.Series, max_rows: int = 20) -> str:
    """Convert a Series to a readable string."""
    return format_dataframe(series.reset_index(), max_rows)


def build_response(
    answer: str,
    code: str,
    result: Any,
    methodology: str,
    query: str = "",
    error: Optional[str] = None,
    plot_base64: str = "",
) -> str:
    """
    Assemble the canonical DataIQ response block.

    Structure:
    1. 📊 Answer
    2. 📈 Visualization (if plot was generated)
    3. 🐍 Code
    4. 📋 Data View
    5. 📝 Methodology & Assumptions
    """
    parts: list[str] = []

    # --- Answer ---
    parts.append("### [Answer]")
    parts.append(answer)
    parts.append("")

    # --- Visualization ---
    if plot_base64:
        parts.append("---")
        parts.append("### [Visualization]")
        parts.append(f"![Generated Visualization](data:image/png;base64,{plot_base64})")
        parts.append("")

    # --- Error block (if any) ---
    if error:
        parts.append("---")
        parts.append("### [Warning]")
        parts.append("```")
        parts.append(error[:800])  # truncate very long tracebacks
        parts.append("```")
        parts.append("")

    # --- Code ---
    parts.append("---")
    parts.append("### [Code]")
    parts.append("```python")
    parts.append(code.strip())
    parts.append("```")
    parts.append("")

    # --- Data View ---
    parts.append("---")
    parts.append("### [Data View]")
    data_view = _render_result(result)
    parts.append(data_view)
    parts.append("")

    # --- Methodology ---
    parts.append("---")
    parts.append("### [Methodology]")
    parts.append(methodology)
    parts.append("")

    return "\n".join(parts)


def build_error_response(query: str, error: str, suggestion: str = "") -> str:
    """Build a user-friendly error response."""
    parts = [
        "### [Error] Could Not Answer Query",
        "",
        f"**Query:** {query}",
        "",
        "**Error encountered:**",
        "```",
        error[:1000],
        "```",
    ]
    if suggestion:
        parts += ["", f"**Suggestion:** {suggestion}"]
    parts += [
        "",
        "Please try rephrasing your question or check that the column names are correct.",
        "Use `describe` or `schema` to see available columns.",
    ]
    return "\n".join(parts)


def build_out_of_scope_response(query: str, reason: str) -> str:
    """Build a polite out-of-scope message."""
    return (
        f"### ℹ️ Out of Scope\n\n"
        f"**Query:** {query}\n\n"
        f"{reason}\n\n"
        f"DataIQ computes answers from loaded data only. "
        f"If you need forecasting or external data, that requires additional setup.\n\n"
        f"**What I can do:**\n"
        f"- Summarize historical trends\n"
        f"- Compute aggregations (sum, mean, max, min, count)\n"
        f"- Filter and group data by any column\n"
        f"- Show correlations between numeric columns\n"
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _render_result(result: Any) -> str:
    """Dispatch result rendering based on type."""
    if result is None:
        return "_No result returned._"

    if isinstance(result, pd.DataFrame):
        return format_dataframe(result)

    if isinstance(result, pd.Series):
        return format_series(result)

    if isinstance(result, (int, float)):
        return f"**{format_scalar(result)}**"

    if isinstance(result, dict):
        try:
            return format_dataframe(pd.DataFrame([result]))
        except Exception:
            return "\n".join(f"- **{k}**: {v}" for k, v in result.items())

    if isinstance(result, (list, tuple)):
        if len(result) == 0:
            return "_Empty list._"
        try:
            return format_dataframe(pd.DataFrame(result))
        except Exception:
            return "\n".join(f"- {item}" for item in result[:50])

    # Fallback: string representation
    return f"```\n{str(result)[:2000]}\n```"
