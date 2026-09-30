"""Tests for static answer grading (mcq, recall, numeric)."""

from __future__ import annotations

import pytest

from apex.engine.grading import grade_mcq, grade_numeric, grade_recall, grade_static


class TestGradeMcq:
    def test_exact_option_text(self) -> None:
        assert grade_mcq("Bogotá", ["Lima", "Bogotá", "Quito"], "Bogotá")["passed"] == 1

    def test_position_accepted(self) -> None:
        assert grade_mcq("2", ["Lima", "Bogotá", "Quito"], "Bogotá")["passed"] == 1

    def test_wrong_option(self) -> None:
        result = grade_mcq("Lima", ["Lima", "Bogotá", "Quito"], "Bogotá")
        assert result["passed"] == 0
        assert result["score"] == 0.0

    def test_case_insensitive(self) -> None:
        assert grade_mcq("bogotá", ["Lima", "Bogotá"], "Bogotá")["passed"] == 1

    def test_out_of_range_position_is_wrong_not_crash(self) -> None:
        assert grade_mcq("9", ["Lima", "Bogotá"], "Bogotá")["passed"] == 0


class TestGradeRecall:
    def test_exact(self) -> None:
        assert grade_recall("hablar", "hablar", [])["passed"] == 1

    def test_case_insensitive(self) -> None:
        assert grade_recall("HABLAR", "hablar", [])["passed"] == 1

    def test_accent_insensitive_both_ways(self) -> None:
        assert grade_recall("bogota", "Bogotá", [])["passed"] == 1
        assert grade_recall("Bogotá", "bogota", [])["passed"] == 1

    def test_accept_alternatives(self) -> None:
        assert grade_recall("hablo", "hablar", ["hablo"])["passed"] == 1

    def test_wrong_gets_effort_credit_not_full(self) -> None:
        result = grade_recall("lima", "Bogotá", [])
        assert result["passed"] == 0
        assert 0 < result["score"] < 0.5


class TestGradeNumeric:
    def test_plain_integer(self) -> None:
        assert grade_numeric("14", "14")["passed"] == 1

    def test_thousands_separator(self) -> None:
        assert grade_numeric("1,000", "1000")["passed"] == 1

    def test_fraction_answer_key(self) -> None:
        assert grade_numeric("5/6", "5/6", tolerance=0.001)["passed"] == 1

    def test_decimal_equivalent_within_tolerance(self) -> None:
        assert grade_numeric("0.8333", "5/6", tolerance=0.001)["passed"] == 1

    def test_percent_sign_stripped(self) -> None:
        assert grade_numeric("25%", "25")["passed"] == 1

    def test_tolerance_boundary(self) -> None:
        assert grade_numeric("3.1416", "3.14159", tolerance=0.0001)["passed"] == 1
        assert grade_numeric("3.15", "3.14159", tolerance=0.0001)["passed"] == 0

    def test_non_numeric_response_fails_cleanly(self) -> None:
        result = grade_numeric("banana", "14")
        assert result["passed"] == 0
        assert result["score"] == 0.0


class TestGradeStaticDispatch:
    class _Ex:
        kind = "mcq"
        options = ["a", "b"]
        answer = "a"
        accept: list[str] = []
        tolerance = 0.0

    def test_dispatch_mcq(self) -> None:
        ex = self._Ex()
        assert grade_static(ex, "a")["passed"] == 1

    def test_unknown_kind_raises(self) -> None:
        class Broken(self._Ex):
            kind = "poem"

        with pytest.raises(ValueError):
            grade_static(Broken(), "roses are red")
