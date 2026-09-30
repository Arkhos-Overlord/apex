"""APEX Code Execution Engine — safe sandboxed code runner with auto-grading.

Provides isolated execution of Python and JavaScript source via subprocess,
test-case grading, and automated test-case generation from concept descriptions.

Python execution delegates to :class:`apex.sandbox.LocalPythonRunner` (POSIX
rlimits, env scrubbing, session isolation); JavaScript runs under Node with a
V8 heap cap. Every path enforces a wall-clock timeout.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from typing import Any

try:  # Optional: keeps the module importable if sandbox deps are missing.
    from apex.sandbox import Limits, LocalPythonRunner
except ImportError:  # pragma: no cover
    Limits = None  # type: ignore[assignment,misc]
    LocalPythonRunner = None  # type: ignore[assignment,misc]

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

_TIMEOUT_EXIT_CODE = 124  # conventional timeout exit status


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
        ``RLIMIT_AS`` in the child process; for JavaScript it maps to the
        V8 ``--max-old-space-size`` flag.  On Windows the parameter is
        accepted but not enforced (documented limitation).

    Returns
    -------
    ExecutionResult
        ``{success, output, error, exit_code, execution_time}``.  A timed-out
        run reports ``exit_code == 124``.
    """
    lang = language.lower()
    if lang not in ("python", "javascript"):
        return _failure(
            f"Unsupported language: {language!r}. Supported: python, javascript.",
            exit_code=-1,
        )

    if lang == "python":
        return _run_python(source, timeout, memory_limit_mb)
    return _run_javascript(source, timeout, memory_limit_mb)


def _run_python(source: str, timeout: int, memory_limit_mb: int) -> ExecutionResult:
    """Run Python *source* through the hardened LocalPythonRunner."""
    if LocalPythonRunner is not None:
        limits = Limits(
            timeout_s=float(timeout),
            memory_mb=float(memory_limit_mb) if memory_limit_mb else None,
        )
        runner = LocalPythonRunner(limits=limits)
        try:
            import asyncio

            result = asyncio.run(runner.run(source))
        except (RuntimeError, OSError, ValueError) as exc:
            return _failure(f"Runner error: {exc}", exit_code=-1)
        exit_code = _TIMEOUT_EXIT_CODE if result.timed_out else result.exit_code
        return {
            "success": result.ok,
            "output": result.stdout,
            "error": result.stderr,
            "exit_code": exit_code,
            "execution_time": round(result.duration_ms / 1000, 4),
        }

    # Fallback path when the sandbox module is unavailable.
    cmd = _write_and_build_cmd(source, ".py", [_python_exe()])
    return _run_subprocess(cmd, stdin="", timeout=timeout)


def _run_javascript(source: str, timeout: int, memory_limit_mb: int) -> ExecutionResult:
    """Run JavaScript *source* under Node with a V8 heap cap (MiB)."""
    cmd = _write_and_build_cmd(
        source,
        ".js",
        ["node", f"--max-old-space-size={max(16, int(memory_limit_mb))}"],
    )
    return _run_subprocess(cmd, stdin="", timeout=timeout)


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
    ``{input, expected_output, description}`` triples. Generated cases
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


def _write_and_build_cmd(source: str, suffix: str, prefix_argv: list[str]) -> list[str]:
    """Write *source* to a temp file and return the full argv to run it."""
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="apex_run_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(source)
    except BaseException:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    # The temp file is cleaned up by _run_subprocess after execution.
    return [*prefix_argv, path]


def _run_subprocess(
    cmd: list[str],
    stdin: str,
    timeout: float,
) -> ExecutionResult:
    """Run *cmd*, always cleaning up its trailing temp script path."""
    script_path = cmd[-1] if cmd and os.path.isfile(cmd[-1]) else None
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL if not stdin else None,
            input=stdin if stdin else None,
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
            f"Execution timed out after {timeout:g}s.",
            exit_code=_TIMEOUT_EXIT_CODE,
            elapsed=elapsed,
        )
    except OSError as exc:
        elapsed = time.perf_counter() - t0
        return _failure(
            f"Failed to spawn process: {exc}",
            exit_code=-1,
            elapsed=elapsed,
        )
    finally:
        if script_path:
            try:
                os.unlink(script_path)
            except OSError:
                pass


def _run_with_stdin(
    source: str,
    stdin_input: str,
    language: str,
) -> ExecutionResult:
    """Run *source* with *stdin_input* piped in, under the hardened sandbox."""
    lang = language.lower()

    if lang == "python" and LocalPythonRunner is not None:
        import asyncio

        runner = LocalPythonRunner(limits=Limits(timeout_s=30.0))
        try:
            result = asyncio.run(runner.run(source, stdin_input))
        except (RuntimeError, OSError, ValueError) as exc:
            return _failure(f"Runner error: {exc}", exit_code=-1)
        return {
            "success": result.ok,
            "output": result.stdout,
            "error": result.stderr,
            "exit_code": _TIMEOUT_EXIT_CODE if result.timed_out else result.exit_code,
            "execution_time": round(result.duration_ms / 1000, 4),
        }

    suffix = ".py" if lang == "python" else ".js"
    base = [_python_exe()] if lang == "python" else ["node"]
    cmd = _write_and_build_cmd(source, suffix, base)
    return _run_subprocess(cmd, stdin=stdin_input, timeout=30)


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
