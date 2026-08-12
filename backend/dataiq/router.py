"""
dataiq/router.py
----------------
Router node: classifies queries as "simple" (direct pandas op, no LLM needed)
or "complex" (code-gen required). Implements the left branch of the
architecture diagram.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class QueryType(Enum):
    COUNT = auto()
    SUM = auto()
    MEAN = auto()
    MAX = auto()
    MIN = auto()
    TOP_N = auto()
    BOTTOM_N = auto()
    UNIQUE = auto()
    DESCRIBE = auto()       # summary statistics
    HEAD = auto()           # show first N rows
    COMPLEX = auto()        # requires code-gen LLM


@dataclass
class RouteDecision:
    query_type: QueryType
    is_simple: bool
    column_hints: list[str]   # column names mentioned in the query
    n_hint: Optional[int]     # e.g., "top 5" → 5
    filter_hint: Optional[str]
    raw_query: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def route(query: str, schema: dict) -> RouteDecision:
    """
    Classify a natural-language query and extract key parameters.

    Parameters
    ----------
    query : str
        The user's plain-English question.
    schema : dict
        Output of loader.infer_schema(), used for column matching.

    Returns
    -------
    RouteDecision
    """
    q = query.strip().lower()
    columns = [c.lower() for c in schema.get("columns", [])]

    col_hits = _find_columns(q, schema.get("columns", []))
    n_hint = _extract_n(q)
    filter_hint = _extract_filter(q)

    _complex_filter_kw = r"\b(by|per|group|where|filter|which|for|in|highest|lowest|most|least|returned|plot|chart|graph|bar|line|visualize|draw)\b"

    # --- Simple patterns (no LLM needed) ---
    if _matches(q, r"\b(how many|count|number of|total count)\b") and not _matches(q, r"\b(unique|distinct|different)\b") and not _matches(q, _complex_filter_kw):
        return RouteDecision(QueryType.COUNT, True, col_hits, n_hint, filter_hint, query)

    if _matches(q, r"\b(total|sum of|sum)\b") and not _matches(q, _complex_filter_kw):
        return RouteDecision(QueryType.SUM, True, col_hits, n_hint, filter_hint, query)

    if _matches(q, r"\b(average|mean|avg)\b") and not _matches(q, _complex_filter_kw):
        return RouteDecision(QueryType.MEAN, True, col_hits, n_hint, filter_hint, query)

    if _matches(q, r"\b(maximum|max)\b") and not _matches(q, _complex_filter_kw):
        return RouteDecision(QueryType.MAX, True, col_hits, n_hint, filter_hint, query)

    if _matches(q, r"\b(minimum|min)\b") and not _matches(q, _complex_filter_kw):
        return RouteDecision(QueryType.MIN, True, col_hits, n_hint, filter_hint, query)

    if _matches(q, r"\btop\s*\d*\b") and not _matches(q, r"\bgroup\b|\bmonth\b|\byear\b|\btrend\b|\bcategory\b|\bregion\b"):
        return RouteDecision(QueryType.TOP_N, True, col_hits, n_hint, filter_hint, query)

    if _matches(q, r"\bbottom\s*\d*\b") and not _matches(q, r"\bgroup\b|\bmonth\b|\byear\b|\btrend\b|\bcategory\b|\bregion\b"):
        return RouteDecision(QueryType.BOTTOM_N, True, col_hits, n_hint, filter_hint, query)

    if _matches(q, r"\b(unique|distinct|different)\b") and not _matches(q, _complex_filter_kw):
        return RouteDecision(QueryType.UNIQUE, True, col_hits, n_hint, filter_hint, query)

    if _matches(q, r"\b(describe|summary|statistics|stats|overview|profile)\b"):
        return RouteDecision(QueryType.DESCRIBE, True, col_hits, n_hint, filter_hint, query)

    if _matches(q, r"\b(show|display|list|first|head|preview|sample)\b") and not _matches(
        q, _complex_filter_kw
    ):
        return RouteDecision(QueryType.HEAD, True, col_hits, n_hint, filter_hint, query)

    # --- Complex: send to code-gen ---
    return RouteDecision(QueryType.COMPLEX, False, col_hits, n_hint, filter_hint, query)


# ---------------------------------------------------------------------------
# Direct pandas execution for simple queries
# ---------------------------------------------------------------------------

def execute_simple(decision: RouteDecision, df) -> dict:
    """
    Execute a simple pandas operation without LLM involvement.
    Returns a dict with keys: result, code, methodology.
    """
    import pandas as pd

    qt = decision.query_type
    n = decision.n_hint or 10

    # Pick best column from hints
    col = decision.column_hints[0] if decision.column_hints else None

    # Helper to find first numeric column among hints or fallback
    def _get_numeric_col() -> str:
        num_cols = list(df.select_dtypes(include="number").columns)
        for h in decision.column_hints:
            matches = [c for c in df.columns if c.lower() == h.lower()]
            c = matches[0] if matches else None
            if c in num_cols:
                return c
        return num_cols[0] if num_cols else (col or df.columns[0])

    # For TOP_N/BOTTOM_N: extract the 'by <column>' if present and set it as primary column
    if qt in (QueryType.TOP_N, QueryType.BOTTOM_N):
        m = re.search(r'\bby\s+([\w\s]+?)(?:\s*$|\?)', decision.raw_query, re.IGNORECASE)
        if m:
            by_col_hint = m.group(1).strip()
            matched = [c for c in df.columns if c.lower() == by_col_hint.lower()]
            if not matched:
                matched = [c for c in df.columns if by_col_hint.lower() in c.lower()]
            if matched:
                col = matched[0]

    # Validate column exists
    if col and col not in df.columns:
        matches = [c for c in df.columns if c.lower() == col.lower()]
        col = matches[0] if matches else None

    if qt == QueryType.COUNT:
        if col:
            result = df[col].count()
            code = f"result = df['{col}'].count()"
            method = f"Non-null count of column '{col}'."
        else:
            result = len(df)
            code = "result = len(df)"
            method = "Total row count of the dataset."

    elif qt == QueryType.SUM:
        col = _get_numeric_col()
        result = df[col].sum()
        code = f"result = df['{col}'].sum()"
        method = f"Sum of column '{col}'; NaN values skipped (pandas default)."

    elif qt == QueryType.MEAN:
        col = _get_numeric_col()
        result = df[col].mean()
        code = f"result = df['{col}'].mean()"
        method = f"Arithmetic mean of column '{col}'; NaN values excluded."

    elif qt == QueryType.MAX:
        col = _get_numeric_col()
        result = df[col].max()
        code = f"result = df['{col}'].max()"
        method = f"Maximum value in column '{col}'."

    elif qt == QueryType.MIN:
        col = _get_numeric_col()
        result = df[col].min()
        code = f"result = df['{col}'].min()"
        method = f"Minimum value in column '{col}'."

    elif qt == QueryType.TOP_N:
        num_col = col if (col and col in df.select_dtypes(include="number").columns) else _get_numeric_col()
        result = df.nlargest(n, num_col)
        code = f"result = df.nlargest({n}, '{num_col}')"
        method = f"Top {n} rows by column '{num_col}' (descending order)."

    elif qt == QueryType.BOTTOM_N:
        num_col = col if (col and col in df.select_dtypes(include="number").columns) else _get_numeric_col()
        result = df.nsmallest(n, num_col)
        code = f"result = df.nsmallest({n}, '{num_col}')"
        method = f"Bottom {n} rows by column '{num_col}' (ascending order)."

    elif qt == QueryType.UNIQUE:
        col = col or df.columns[0]
        result = df[col].nunique()
        code = f"result = df['{col}'].nunique()"
        method = f"Count of distinct non-null values in column '{col}'."

    elif qt == QueryType.DESCRIBE:
        result = df.describe(include="all")
        code = "result = df.describe(include='all')"
        method = "Descriptive statistics for all columns (numeric + categorical)."

    elif qt == QueryType.HEAD:
        result = df.head(n)
        code = f"result = df.head({n})"
        method = f"First {n} rows of the dataset."

    else:
        return execute_complex_fallback(decision.raw_query, df)

    return {"result": result, "code": code, "methodology": method}


def execute_complex_fallback(query: str, df) -> dict:
    """
    Local fallback execution for complex queries when LLM is unavailable or out of quota.
    Analyzes column types, filter terms, and groupby keys to produce valid pandas output.
    """
    import pandas as pd
    q = query.lower()
    cat_cols = list(df.select_dtypes(include=["object", "category"]).columns)
    num_cols = list(df.select_dtypes(include="number").columns)

    num_col = num_cols[0] if num_cols else None
    for c in num_cols:
        if c.lower() in q or any(tok in q for tok in c.lower().split("_") if len(tok) > 3):
            num_col = c
            break

    group_col = None
    for c in cat_cols:
        if c.lower() in q or any(tok in q for tok in c.lower().split("_") if len(tok) > 3):
            group_col = c
            break

    # 0. Chart / Plot requests
    if any(kw in q for kw in ["plot", "chart", "bar", "graph", "line", "pie", "histogram", "hist", "scatter", "visualize", "draw", "distribution"]):
        g_col = group_col or (cat_cols[0] if cat_cols else df.columns[0])
        n_col = num_col or (num_cols[0] if num_cols else df.columns[-1])
        plot_type = "pie" if "pie" in q else "line" if "line" in q else "scatter" if "scatter" in q else "bar"
        
        if plot_type == "pie":
            code = f"""grouped = df.groupby('{g_col}')['{n_col}'].sum().head(7)
plt.figure(figsize=(7, 4.5))
plt.pie(grouped, labels=grouped.index, autopct='%1.1f%%', colors=['#7c3aed', '#06b6d4', '#3b82f6', '#10b981', '#f59e0b', '#ec4899', '#8b5cf6'])
plt.title('{n_col.replace("_", " ").title()} by {g_col.replace("_", " ").title()}', fontsize=12, fontweight='bold')
plt.tight_layout()
result = grouped.reset_index()"""
        elif plot_type == "scatter" and len(num_cols) >= 2:
            n_col2 = num_cols[1] if num_cols[1] != n_col else num_cols[0]
            code = f"""plt.figure(figsize=(8, 4.5))
plt.scatter(df['{n_col}'], df['{n_col2}'], color='#7c3aed', alpha=0.75, edgecolors='none', s=50)
plt.title('{n_col.replace("_", " ").title()} vs {n_col2.replace("_", " ").title()}', fontsize=12, fontweight='bold')
plt.xlabel('{n_col.replace("_", " ").title()}')
plt.ylabel('{n_col2.replace("_", " ").title()}')
plt.grid(True, linestyle='--', alpha=0.5)
plt.tight_layout()
result = df[['{n_col}', '{n_col2}']].describe()"""
        else:
            code = f"""grouped = df.groupby('{g_col}')['{n_col}'].sum()
plt.figure(figsize=(8, 4.5))
ax = grouped.plot(kind='{plot_type}', color='#7c3aed', grid=True)
plt.title('{n_col.replace("_", " ").title()} by {g_col.replace("_", " ").title()}', fontsize=12, fontweight='bold')
plt.xlabel('{g_col.replace("_", " ").title()}')
plt.ylabel('{n_col.replace("_", " ").title()}')
plt.xticks(rotation=45 if len(grouped) > 5 else 0)
plt.tight_layout()
result = grouped.reset_index()"""
        
        res = df.groupby(g_col)[n_col].sum().reset_index() if plot_type != "scatter" else df.describe()
        return {
            "result": res,
            "code": code,
            "methodology": f"Grouped by '{g_col}', aggregated '{n_col}', and generated a {plot_type} chart with Matplotlib.",
        }

    # 1. Filter checks (e.g. 'north', 'returned', 'completed')
    for c in cat_cols:
        unique_vals = [str(v) for v in df[c].dropna().unique()]
        for val in unique_vals:
            if val.lower() in q:
                filtered_df = df[df[c].astype(str).str.lower() == val.lower()]
                if num_col and ("revenue" in q or "total" in q or "sum" in q or "sales" in q):
                    res = filtered_df[num_col].sum()
                    return {
                        "result": res,
                        "code": f"result = df[df['{c}'] == '{val}']['{num_col}'].sum()",
                        "methodology": f"Filtered dataframe where {c} == '{val}', summed '{num_col}'.",
                    }
                elif "how many" in q or "count" in q or "orders" in q:
                    res = len(filtered_df)
                    return {
                        "result": res,
                        "code": f"result = len(df[df['{c}'] == '{val}'])",
                        "methodology": f"Filtered dataframe where {c} == '{val}', counted rows.",
                    }
                return {
                    "result": filtered_df,
                    "code": f"result = df[df['{c}'] == '{val}']",
                    "methodology": f"Filtered dataframe where {c} == '{val}'.",
                }

    # 2. Groupby checks (e.g. 'category', 'region', 'product')
    if group_col and num_col:
        res = df.groupby(group_col)[num_col].sum().reset_index().sort_values(by=num_col, ascending=False)
        return {
            "result": res,
            "code": f"result = df.groupby('{group_col}')['{num_col}'].sum().reset_index().sort_values(by='{num_col}', ascending=False)",
            "methodology": f"Grouped by '{group_col}' and summed '{num_col}' (descending order).",
        }

    # 3. Default fallback
    res = df.describe(include="all")
    return {
        "result": res,
        "code": "result = df.describe(include='all')",
        "methodology": "Fallback statistical overview of dataset.",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _matches(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text, re.IGNORECASE))


def _find_columns(query_lower: str, columns: list[str]) -> list[str]:
    """Return dataset column names mentioned in the query (fuzzy token match)."""
    hits = []
    for col in columns:
        # Match full column name or individual tokens
        tokens = re.split(r"[\s_\-]+", col.lower())
        if col.lower() in query_lower or any(t in query_lower for t in tokens if len(t) > 2):
            hits.append(col)
    return hits


def _extract_n(query: str) -> Optional[int]:
    """Extract numeric N from phrases like 'top 5', 'first 10', 'bottom 3'."""
    m = re.search(r"\b(top|bottom|first|last|head|tail)\s+(\d+)\b", query, re.IGNORECASE)
    if m:
        return int(m.group(2))
    m = re.search(r"\b(\d+)\s+(rows?|records?|entries|items)\b", query, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _extract_filter(query: str) -> Optional[str]:
    """Extract filter phrase for methodology note."""
    m = re.search(r"\b(where|filter|only|for|in)\b.{0,60}", query, re.IGNORECASE)
    return m.group(0) if m else None


def _first_numeric(df) -> str:
    """Return the first numeric column name."""
    nums = df.select_dtypes(include="number").columns
    if len(nums) == 0:
        raise ValueError("No numeric columns found in the dataset.")
    return nums[0]
