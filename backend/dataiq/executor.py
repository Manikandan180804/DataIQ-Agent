"""
dataiq/executor.py
------------------
Sandbox executor: runs LLM-generated pandas code in a restricted namespace.
Implements the "Sandbox executor → Error? → Retry" flow from the architecture.
"""

from __future__ import annotations

import contextlib
import io
import re
import traceback
from typing import Any


import base64
import matplotlib
matplotlib.use('Agg')  # Headless non-GUI backend
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


# Dangerous patterns to block in generated code
_BLOCKED_PATTERNS = [
    r"\bimport\s+os\b",
    r"\bimport\s+sys\b",
    r"\bimport\s+subprocess\b",
    r"\bimport\s+socket\b",
    r"\bimport\s+requests\b",
    r"\bimport\s+urllib\b",
    r"\bimport\s+http\b",
    r"\b__import__\b",
    r"\bopen\s*\(",           # file access
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bgetattr\s*\(",
    r"\bsetattr\s*\(",
    r"\bdelattr\s*\(",
    r"\b__builtins__\b",
    r"\bshutil\b",
    r"\bpathlib\b",
    r"\bglob\b",
]


class ExecutionResult:
    """Container for the result of a sandbox execution."""

    def __init__(
        self,
        ok: bool,
        result: Any = None,
        stdout: str = "",
        error: str = "",
        code: str = "",
        plot_base64: str = "",
    ):
        self.ok = ok
        self.result = result
        self.stdout = stdout
        self.error = error
        self.code = code
        self.plot_base64 = plot_base64

    def __repr__(self) -> str:
        status = "✅ OK" if self.ok else "❌ ERROR"
        return f"ExecutionResult({status})"


def validate_code(code: str) -> tuple[bool, str]:
    """
    Check generated code against the blocked-patterns blocklist.
    Returns (is_safe, reason).
    """
    for pattern in _BLOCKED_PATTERNS:
        if re.search(pattern, code, re.IGNORECASE):
            return False, f"Blocked pattern detected: `{pattern}`"
    return True, ""


def safe_exec(code: str, df, extra_imports: bool = True) -> ExecutionResult:
    """
    Execute pandas code in a sandboxed namespace.

    The namespace provides:
      - df          : the loaded DataFrame
      - pd          : pandas
      - np          : numpy
      - plt         : matplotlib.pyplot (non-GUI Agg backend)
      - result      : variable the code should assign its final output to
    """
    # Clear any leftover figures
    plt.close('all')

    # Security check
    safe, reason = validate_code(code)
    if not safe:
        return ExecutionResult(
            ok=False,
            error=f"Security violation: {reason}\nGenerated code was blocked.",
            code=code,
        )

    # Build restricted namespace
    namespace: dict[str, Any] = {
        "df": df,
        "pd": pd,
        "np": np,
        "plt": plt,
        "result": None,
    }

    if extra_imports:
        import math, datetime, re as _re
        namespace.update({"math": math, "datetime": datetime, "re": _re})

    # Capture stdout
    stdout_buf = io.StringIO()

    try:
        with contextlib.redirect_stdout(stdout_buf):
            exec(compile(code, "<dataiq_sandbox>", "exec"), namespace)  # noqa: S102

        stdout_text = stdout_buf.getvalue()
        result = namespace.get("result")

        # Capture plot if generated
        plot_b64 = ""
        try:
            if plt.get_fignums():
                img_buf = io.BytesIO()
                plt.savefig(img_buf, format="png", bbox_inches="tight", dpi=150)
                img_buf.seek(0)
                plot_b64 = base64.b64encode(img_buf.read()).decode("utf-8")
        except Exception as exc:
            print(f"[DataIQ] Plot capture exception: {exc}")
        finally:
            plt.close("all")

        # If result not set but something was printed, use stdout
        if result is None and stdout_text.strip():
            result = stdout_text.strip()

        return ExecutionResult(
            ok=True,
            result=result,
            stdout=stdout_text,
            code=code,
            plot_base64=plot_b64,
        )

    except Exception:
        plt.close("all")
        tb = traceback.format_exc()
        return ExecutionResult(ok=False, error=tb, code=code)


def strip_code_fences(code: str) -> str:
    """
    Remove markdown code fences (```python ... ```) from LLM output.
    """
    code = code.strip()
    # Remove opening fence
    code = re.sub(r"^```(?:python)?\s*\n?", "", code, flags=re.IGNORECASE)
    # Remove closing fence
    code = re.sub(r"\n?```\s*$", "", code)
    return code.strip()
