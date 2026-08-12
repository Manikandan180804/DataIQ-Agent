"""
dataiq/loader.py
----------------
Handles loading CSV/Excel files and inferring their schema.
Sends only df.head() + dtypes to LLM context — never raw full data.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Union

import pandas as pd


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_dataset(path: Union[str, Path], sheet_name: Union[int, str] = 0) -> pd.DataFrame:
    """
    Load a CSV or Excel file into a pandas DataFrame.

    - CSV: delimiter auto-detected via csv.Sniffer; falls back to comma.
    - Excel: reads the specified sheet (default: first sheet, index 0).
    - Post-load cleanup: drops fully-empty rows.

    Parameters
    ----------
    path : str | Path
        Absolute or relative path to the file.
    sheet_name : int | str
        Sheet index or name for Excel files (ignored for CSV).

    Returns
    -------
    pd.DataFrame
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()

    if suffix in {".xls", ".xlsx", ".xlsm", ".xlsb"}:
        df = _load_excel(path, sheet_name)
    elif suffix in {".csv", ".tsv", ".txt"}:
        df = _load_csv(path)
    else:
        raise ValueError(
            f"Unsupported file type '{suffix}'. Accepted: .csv, .tsv, .txt, .xls, .xlsx, .xlsm"
        )

    # Drop rows that are entirely NaN
    original_len = len(df)
    df = df.dropna(how="all").reset_index(drop=True)
    dropped = original_len - len(df)

    # Attempt datetime coercion on object columns that look like dates
    df = _coerce_datetimes(df)

    df.attrs["source_path"] = str(path)
    df.attrs["dropped_empty_rows"] = dropped
    return df


def list_sheets(path: Union[str, Path]) -> list[str]:
    """Return all sheet names for an Excel file."""
    path = Path(path)
    xf = pd.ExcelFile(path)
    return xf.sheet_names


def infer_schema(df: pd.DataFrame) -> dict:
    """
    Build a lightweight schema summary suitable for the LLM context window.
    Returns dtypes, null counts, and the first 5 rows — never the full data.
    """
    numeric_cols = list(df.select_dtypes(include="number").columns)
    categorical_cols = list(df.select_dtypes(include=["object", "category"]).columns)
    datetime_cols = list(df.select_dtypes(include=["datetime", "datetimetz"]).columns)
    bool_cols = list(df.select_dtypes(include="bool").columns)

    null_counts = df.isnull().sum()
    cols_with_nulls = {col: int(cnt) for col, cnt in null_counts.items() if cnt > 0}

    return {
        "shape": {"rows": df.shape[0], "cols": df.shape[1]},
        "columns": list(df.columns),
        "dtypes": df.dtypes.astype(str).to_dict(),
        "numeric_cols": numeric_cols,
        "categorical_cols": categorical_cols,
        "datetime_cols": datetime_cols,
        "bool_cols": bool_cols,
        "null_counts": cols_with_nulls,
        "total_nulls": int(null_counts.sum()),
        "sample": df.head(5).to_dict(orient="records"),
        "source_path": df.attrs.get("source_path", "unknown"),
        "dropped_empty_rows": df.attrs.get("dropped_empty_rows", 0),
    }


def schema_to_text(schema: dict) -> str:
    """Render schema as a compact text block for the LLM system message."""
    lines = [
        f"Dataset: {schema['source_path']}",
        f"Shape: {schema['shape']['rows']:,} rows × {schema['shape']['cols']} columns",
        "",
        "Columns and dtypes:",
    ]
    for col, dtype in schema["dtypes"].items():
        null_note = ""
        if col in schema["null_counts"]:
            null_note = f"  [⚠ {schema['null_counts'][col]:,} nulls]"
        lines.append(f"  • {col} ({dtype}){null_note}")

    lines += [
        "",
        f"Numeric  : {', '.join(schema['numeric_cols']) or 'none'}",
        f"Category : {', '.join(schema['categorical_cols']) or 'none'}",
        f"Datetime : {', '.join(schema['datetime_cols']) or 'none'}",
        "",
        "First 5 rows (sample):",
    ]
    sample_df = pd.DataFrame(schema["sample"])
    lines.append(sample_df.to_string(index=False))

    if schema["dropped_empty_rows"]:
        lines.append(f"\n[Note: {schema['dropped_empty_rows']} fully-empty rows were dropped at load time.]")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_csv(path: Path) -> pd.DataFrame:
    """Auto-detect delimiter and load CSV."""
    raw = path.read_bytes()
    # Try to sniff delimiter from first 4 KB
    try:
        sample = raw[:4096].decode("utf-8", errors="replace")
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t|;")
        sep = dialect.delimiter
    except csv.Error:
        sep = ","

    return pd.read_csv(
        io.BytesIO(raw),
        sep=sep,
        encoding="utf-8-sig",  # handles BOM
        low_memory=False,
    )


def _load_excel(path: Path, sheet_name: Union[int, str]) -> pd.DataFrame:
    """Load a single Excel sheet."""
    return pd.read_excel(path, sheet_name=sheet_name)


def _coerce_datetimes(df: pd.DataFrame) -> pd.DataFrame:
    """
    Try to convert object columns whose name contains common date keywords
    to datetime. Silently skips columns that cannot be converted.
    """
    date_keywords = {"date", "time", "dt", "timestamp", "created", "updated", "period"}
    for col in df.select_dtypes(include="object").columns:
        if any(kw in col.lower() for kw in date_keywords):
            try:
                df[col] = pd.to_datetime(df[col], infer_datetime_format=True, errors="coerce")
            except Exception:
                pass  # leave as object if conversion fails
    return df
