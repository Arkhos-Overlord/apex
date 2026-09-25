"""APEX Code Execution Engine — safe sandboxed code runner with auto-grading.

Provides isolated execution of Python and JavaScript source via subprocess,
test-case grading, and automated test-case generation from concept descriptions.
"""

from __future__ import annotations

import asyncio
import os
import platform
import subprocess
import tempfile
import time
from typing import Any

# Optional: Protocol-based runner (imported lazily to keep existing API working
# even if sandbox.py is not present).
try:
    from apex.sandbox import Limits, LocalPythonRunner
except ImportError:
    Limits = None
    LocalPythonRunner = None

# ---------------------------------------------------------------------------
# Result type aliases
# ---------------------------------------------------------------------------

ExecutionResult = dict[str, Any]
"""Keys: success (bool), output (str), error (str), exit_code (int),
execution_time (float)."""

GradeResult = dict[str, Any]
"""Keys: passed (int), total (int), score (float), details (list[TestCaseResult])."""

TestCase = dict[str, str]
"""Keys: input, expected_output, description."""

TestCaseResult = dict[str, Any]
"""Keys: description, passed (bool), expected, got, input."""


# ---------------------------------------------------------------------------
# run_code
# ---------------------------------------------------------------------------


def run_code(
    source: str,
    language: str = "python",
    timeout: int = 30,
    memory_limit_mb: int = 128,
) -> ExecutionResult:
    """Execute *source* in an isolated subprocess and return the result.

    Parameters
    ----------
    source:
        Program text to run.
    language:
        ``"python"`` or ``"javascript"`` (Node.js).  Case-insensitive.
    timeout:
        Wall-clock timeout in seconds before the process is killed.
        Defaults to 30.
    memory_limit_mb:
        Soft memory limit in MiB.  On POSIX this is enforced via
        ``resource.setrlimit(RLIMIT_AS)`` through a wrapper script; on
        Windows the parameter is accepted but not enforced (documented
        limitation).

    Returns
    -------
    ExecutionResult
        ``{success, output, error, exit_code, execution_time}``.
    """
    lang = language.lower()
    if lang not in ("python", "javascript"):
        return _failure(
            f"Unsupported language: {language!r}. Supported: python, javascript.",
            exit_code=-1,
        )

    # ---- Use the Protocol-based LocalPythonRunner when available ----
    if LocalPythonRunner is not None and lang == "python":
        limits = Limits(
            timeout_s=float(timeout),
            memory_mb=float(memory_limit_mb) if memory_limit_mb else None,
        )
        runner = LocalPythonRunner(limits=limits)
        try:
            result = asyncio.run(runner.run(source))
            return {
                "success": result.ok,
                "output": result.stdout,
                "error": result.stderr,
                "exit_code": result.exit_code,
                "execution_time": round(result.duration_ms / 1000, 4),
            }
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            return _failure(f"Runner error: {exc}", exit_code=-1)

    cmd = _build_command(source, lang, memory_limit_mb)
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        elapsed = time.perf_counter() - t0
        return {
            "success": proc.returncode == 0,
            "output": proc.stdout,
            "error": proc.stderr,
            "exit_code": proc.returncode,
            "execution_time": round(elapsed, 4),
        }
    except subprocess.TimeoutExpired:
        elapsed = time.perf_counter() - t0
        return _failure(
            f"Execution timed out after {timeout}s.",
            exit_code=124,
            elapsed=elapsed,
        )
    except OSError as exc:
        elapsed = time.perf_counter() - t0
        return _failure(
            f"Failed to spawn process: {exc}",
            exit_code=-1,
            elapsed=elapsed,
        )


# ---------------------------------------------------------------------------
# grade_code
# ---------------------------------------------------------------------------


def grade_code(
    source: str,
    test_cases: list[TestCase],
    language: str = "python",
) -> GradeResult:
    """Run *source* against every *test_case* and return a grade summary.

    Each test case's ``input`` string is fed to the subprocess via stdin;
    stdout is compared (after ``strip()``) to ``expected_output``.  A case
    passes only when the process exits cleanly **and** output matches.

    Parameters
    ----------
    source:
        Program source text.
    test_cases:
        List of ``{input, expected_output, description}`` dicts.
    language:
        ``"python"`` or ``"javascript"``.

    Returns
    -------
    GradeResult
        ``{passed, total, score, details}``.  *score* is ``passed/total``
        rounded to 4 decimal places (1.0 when *total* is zero).
    """
    if not test_cases:
        return {"passed": 0, "total": 0, "score": 1.0, "details": []}

    details: list[TestCaseResult] = []
    passed = 0
    for tc in test_cases:
        result = _run_with_stdin(source, tc["input"], language)
        got = result["output"].strip()
        expected = tc["expected_output"].strip()
        case_passed = result["success"] and got == expected
        if case_passed:
            passed += 1
        details.append(
            {
                "description": tc["description"],
                "passed": case_passed,
                "expected": expected,
                "got": got,
                "input": tc["input"],
            }
        )

    total = len(test_cases)
    score = round(passed / total, 4) if total else 1.0
    return {"passed": passed, "total": total, "score": score, "details": details}


# ---------------------------------------------------------------------------
# generate_test_cases
# ---------------------------------------------------------------------------


def generate_test_cases(
    concept: str,
    language: str = "python",
) -> list[TestCase]:
    """Produce a starter set of test cases from a concept description.

    Uses keyword heuristics to generate simple, reviewable
    ``{input, expected_output, description}`` triples.  Generated cases
    should be checked and extended by the instructor before being used in
    high-stakes assessment.

    Parameters
    ----------
    concept:
        Natural-language description of the function / concept being tested.
    language:
        Used only to prefix placeholder input text in the fallback case.

    Returns
    -------
    list[TestCase]
    """
    concept_lower = concept.lower()
    cases: list[TestCase] = []

    # -- Arithmetic / numeric -------------------------------------------------
    if any(
        k in concept_lower
        for k in (
            "add",
            "sum",
            "plus",
            "addition",
            "subtract",
            "difference",
            "multiply",
            "product",
            "divide",
            "arithmetic",
        )
    ):
        cases.extend(
            [
                {
                    "input": "2 3\n",
                    "expected_output": "5\n",
                    "description": "Basic positive-integer addition",
                },
                {
                    "input": "-1 1\n",
                    "expected_output": "0\n",
                    "description": "Additive-inverse cancellation",
                },
                {
                    "input": "0 0\n",
                    "expected_output": "0\n",
                    "description": "Zero plus zero identity",
                },
            ]
        )

    # -- Factorial / recursion -------------------------------------------------
    if any(
        k in concept_lower
        for k in (
            "factorial",
            "recursion",
            "fibonacci",
            "recursive",
            "recurrence",
        )
    ):
        cases.extend(
            [
                {
                    "input": "0\n",
                    "expected_output": "1\n",
                    "description": "Factorial of 0 (base case)",
                },
                {"input": "5\n", "expected_output": "120\n", "description": "Factorial of 5"},
                {"input": "1\n", "expected_output": "1\n", "description": "Factorial of 1"},
            ]
        )

    # -- Sorting ---------------------------------------------------------------
    if any(
        k in concept_lower
        for k in (
            "sort",
            "sorted",
            "bubble",
            "merge sort",
            "quick sort",
            "insertion sort",
            "selection sort",
        )
    ):
        cases.extend(
            [
                {
                    "input": "3 1 2\n",
                    "expected_output": "1 2 3\n",
                    "description": "Sort a small unsorted list",
                },
                {"input": "\n", "expected_output": "\n", "description": "Sort an empty input"},
                {
                    "input": "42\n",
                    "expected_output": "42\n",
                    "description": "Sort a single-element input",
                },
            ]
        )

    # -- String manipulation --------------------------------------------------
    if any(
        k in concept_lower
        for k in (
            "string",
            "reverse",
            "palindrome",
            "upper",
            "lower",
            "strip",
            "substring",
            "concatenate",
        )
    ):
        cases.extend(
            [
                {
                    "input": "hello\n",
                    "expected_output": "olleh\n",
                    "description": "Reverse a simple word",
                },
                {"input": "\n", "expected_output": "\n", "description": "Reverse an empty string"},
            ]
        )

    # -- Search / contains -----------------------------------------------------
    if any(
        k in concept_lower
        for k in (
            "search",
            "find",
            "contains",
            "binary search",
            "linear search",
        )
    ):
        cases.extend(
            [
                {
                    "input": "1 3 5 7\n5\n",
                    "expected_output": "True\n",
                    "description": "Search for a present element",
                },
                {
                    "input": "1 3 5 7\n4\n",
                    "expected_output": "False\n",
                    "description": "Search for an absent element",
                },
            ]
        )

    # -- Default fallback ------------------------------------------------------
    if not cases:
        cases.append(
            {
                "input": f"<{language} sample input>\n",
                "expected_output": "<expected output>\n",
                "description": f"Sample case for: {concept[:80]}",
            }
        )

    return cases


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_command(
    source: str,
    lang: str,
    memory_limit_mb: int,
) -> list[str]:
    """Return the argv list that runs *source* under the appropriate interpreter."""
    if lang == "python":
        py_exe = _python_exe()
        wrapper = _python_wrapper_path()
        fd, path = tempfile.mkstemp(suffix=".py", prefix="apex_run_")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(source)
        if wrapper and os.path.exists(wrapper):
            return [py_exe, wrapper, str(memory_limit_mb), path]
        return [py_exe, path]

    # JavaScript — Node.js
    fd, path = tempfile.mkstemp(suffix=".js", prefix="apex_run_")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(source)
    os.close(fd)
    return [
        "node",
        f"--max-old-space-size={memory_limit_mb * 1024}",
        path,
    ]


def _run_with_stdin(
    source: str,
    stdin_input: str,
    language: str,
) -> ExecutionResult:
    """Run *source* with *stdin_input* piped to stdin; no memory limit applied."""
    lang = language.lower()
    py_exe = _python_exe()

    fd, path = tempfile.mkstemp(suffix=".py" if lang == "python" else ".js", prefix="apex_grade_")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(source)

    try:
        proc = subprocess.run(
            [py_exe, path] if lang == "python" else ["node", path],
            check=False,
            input=stdin_input,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "success": proc.returncode == 0,
            "output": proc.stdout,
            "error": proc.stderr,
            "exit_code": proc.returncode,
            "execution_time": 0.0,
        }
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _failure(
    message: str,
    exit_code: int = -1,
    elapsed: float = 0.0,
) -> ExecutionResult:
    """Build a failure result dict."""
    return {
        "success": False,
        "output": "",
        "error": message,
        "exit_code": exit_code,
        "execution_time": round(elapsed, 4),
    }


def _python_exe() -> str:
    """Return the path to the Python interpreter used for subprocess calls."""
    import sys as _sys

    return _sys.executable or "python"


def _python_wrapper_path() -> str:
    """Path to the RLIMIT_AS wrapper script (POSIX only; empty on Windows)."""
    return _PYTHON_WRAPPER_PATH


# ---------------------------------------------------------------------------
# POSIX memory-limit wrapper  (created once at import time)
# ---------------------------------------------------------------------------

_PYTHON_WRAPPER_PATH: str = ""

if platform.system() != "Windows":
    _MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
    _PYWRAP_PATH = os.path.join(_MODULE_DIR, "_memory_wrapper.py")
    _WRAPPER_SRC = (
        "import resource\n"
        "import sys\n"
        "import runpy\n"
        "\n"
        "def _set_memory_soft(limit_mb: int) -> None:\n"
        "    soft = limit_mb * 1024 * 1024\n"
        "    try:\n"
        "        resource.setrlimit(resource.RLIMIT_AS, (soft, soft))\n"
        "    except (ValueError, resource.error):\n"
        "        pass  # leave default if we can't set it\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    _set_memory_soft(int(sys.argv[1]))\n"
        "    runpy.run_path(sys.argv[2], run_name='__apex__')\n"
    )
    try:
        with open(_PYWRAP_PATH, "w", encoding="utf-8") as fh:
            fh.write(_WRAPPER_SRC)
        _PYTHON_WRAPPER_PATH = _PYWRAP_PATH
    except OSError:
        _PYTHON_WRAPPER_PATH = ""
