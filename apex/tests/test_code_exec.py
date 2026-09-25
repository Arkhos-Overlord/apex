"""Unit tests for the APEX code execution engine."""

from __future__ import annotations

import pytest

from apex.engine.code_exec import generate_test_cases, grade_code, run_code


# ---------------------------------------------------------------------------
# run_code
# ---------------------------------------------------------------------------


class TestRunCode:
    """Tests for run_code — execution, timeout, error capture, parameters."""

    def test_python_hello_world(self) -> None:
        result = run_code("print('hello from apex')")
        assert result["success"] is True
        assert "hello from apex" in result["output"]
        assert result["exit_code"] == 0
        assert result["execution_time"] >= 0

    def test_python_computation(self) -> None:
        src = "x = 10\ny = 20\nprint(x + y)"
        result = run_code(src)
        assert result["success"] is True
        assert "30" in result["output"]

    def test_python_syntax_error(self) -> None:
        result = run_code("this is @@@ not valid python")
        assert result["success"] is False
        assert result["exit_code"] != 0
        assert result["error"]

    def test_python_timeout(self) -> None:
        src = "import time; time.sleep(10)"
        result = run_code(src, timeout=1)
        assert result["success"] is False
        assert "timed out" in result["error"].lower()
        assert result["exit_code"] == 124

    def test_python_quiet_success(self) -> None:
        result = run_code("x = 42")
        assert result["success"] is True
        assert result["output"] == ""
        assert result["exit_code"] == 0

    def test_unsupported_language(self) -> None:
        result = run_code("print(1)", language="rust")
        assert result["success"] is False
        assert "Unsupported language" in result["error"]

    def test_execution_time_recorded(self) -> None:
        result = run_code("print('tick')", timeout=30)
        assert isinstance(result["execution_time"], float)
        assert result["execution_time"] >= 0.0

    def test_memory_limit_parameter_accepted(self) -> None:
        result = run_code("print(1)", memory_limit_mb=64)
        assert result["success"] is True

    def test_python_multiline(self) -> None:
        src = "total = 0\nfor i in range(1, 6):\n    total += i\nprint(total)"
        result = run_code(src)
        assert result["success"] is True
        assert result["output"].strip() == "15"


# ---------------------------------------------------------------------------
# grade_code
# ---------------------------------------------------------------------------


class TestGradeCode:
    """Tests for grade_code — test-case execution and scoring."""

    @staticmethod
    def _adder_source() -> str:
        return (
            "import sys\n"
            "data = sys.stdin.read().strip()\n"
            "a, b = map(int, data.split())\n"
            "print(a + b)\n"
        )

    def test_perfect_score(self) -> None:
        src = self._adder_source()
        cases = [
            {"input": "2 3\n", "expected_output": "5", "description": "2+3"},
            {"input": "10 20\n", "expected_output": "30", "description": "10+20"},
            {"input": "-5 5\n", "expected_output": "0", "description": "-5+5"},
        ]
        result = grade_code(src, cases)
        assert result["passed"] == 3
        assert result["total"] == 3
        assert result["score"] == 1.0
        assert all(d["passed"] for d in result["details"])

    def test_partial_score(self) -> None:
        src = (
            "import sys\n"
            "data = sys.stdin.read().strip()\n"
            "a, b = map(int, data.split())\n"
            "print(a + b + 1)\n"  # deliberate bug
        )
        cases = [
            {"input": "2 3\n", "expected_output": "5", "description": "2+3"},
            {"input": "1 1\n", "expected_output": "2", "description": "1+1"},
            {"input": "0 0\n", "expected_output": "0", "description": "0+0"},
        ]
        result = grade_code(src, cases)
        assert result["passed"] == 0
        assert result["total"] == 3
        assert result["score"] == 0.0

    def test_empty_test_cases(self) -> None:
        result = grade_code("print(1)", [])
        assert result["passed"] == 0
        assert result["total"] == 0
        assert result["score"] == 1.0
        assert result["details"] == []

    def test_detail_fields_present(self) -> None:
        src = self._adder_source()
        result = grade_code(
            src,
            [
                {"input": "7 8\n", "expected_output": "15", "description": "7+8"},
            ],
        )
        d = result["details"][0]
        for key in ("description", "passed", "expected", "got", "input"):
            assert key in d
        assert d["passed"] is True
        assert d["got"] == "15"

    def test_single_failing_case(self) -> None:
        src = self._adder_source()
        result = grade_code(
            src,
            [
                {"input": "1 2\n", "expected_output": "4", "description": "wrong expected"},
            ],
        )
        assert result["passed"] == 0
        assert result["score"] == 0.0
        assert result["details"][0]["passed"] is False


# ---------------------------------------------------------------------------
# generate_test_cases
# ---------------------------------------------------------------------------


class TestGenerateTestCases:
    """Tests for generate_test_cases — heuristic test-case generation."""

    def test_factorial_concept(self) -> None:
        cases = generate_test_cases("factorial recursion")
        assert len(cases) >= 3
        descs = {c["description"] for c in cases}
        assert any("factorial" in d.lower() for d in descs)

    def test_sorting_concept(self) -> None:
        cases = generate_test_cases("bubble sort algorithm")
        assert len(cases) >= 3
        descs = {c["description"] for c in cases}
        assert any("sort" in d.lower() for d in descs)

    def test_string_reverse_concept(self) -> None:
        cases = generate_test_cases("reverse a string")
        assert len(cases) >= 2
        descs = {c["description"] for c in cases}
        assert any("reverse" in d.lower() for d in descs)

    def test_arithmetic_concept(self) -> None:
        cases = generate_test_cases("add two numbers together")
        assert len(cases) >= 3
        descs = {c["description"] for c in cases}
        assert any("addition" in d.lower() or "add" in d.lower() for d in descs)

    def test_unknown_concept_fallback(self) -> None:
        cases = generate_test_cases("quantum entanglement nanotubes")
        assert len(cases) == 1
        assert cases[0]["description"].startswith("Sample case for:")

    def test_returns_list_of_dicts(self) -> None:
        cases = generate_test_cases("fibonacci recursion")
        for c in cases:
            assert isinstance(c, dict)
            for key in ("input", "expected_output", "description"):
                assert key in c

    def test_language_parameter_accepted(self) -> None:
        cases = generate_test_cases("sort an array", language="javascript")
        assert len(cases) >= 1
