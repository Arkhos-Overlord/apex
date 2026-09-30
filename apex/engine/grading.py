"""Static answer grading for non-code exercise kinds.

``mcq``, ``recall`` and ``numeric`` exercises do not need the sandbox:
the answer is checked against the exercise's own answer key.  Keeping
these graders in one module lets :meth:`LearningSession.submit` dispatch
on ``Exercise.kind`` without importing the sandbox for a vocabulary quiz,
which is the whole point of having non-code kinds.
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Callable

GradeResult = dict[str, Any]
"""Keys: passed (int), total (int), score (float), details (list)."""

Case = dict[str, str]
"""Grader case: ``description``, ``passed``, ``expected``, ``got``."""


def _case(description: str, passed: bool, expected: str, got: str) -> Case:
    return {
        "description": description,
        "passed": passed,
        "expected": expected if not passed else got,
        "got": got,
    }


def _fold(text: str) -> str:
    """Casefold + strip accents so 'Bogotá' matches 'bogota'.

    NFKD decomposes accented characters into base letter + combining mark;
    the mark must then be *removed*, not just decomposed.
    """
    decomposed = unicodedata.normalize("NFKD", text.strip().casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def grade_mcq(response: str, options: list[str], answer: str) -> GradeResult:
    """Grade a multiple-choice response.

    Accepts either the exact option text or its 1-based position, so both
    a dropdown UI and a CLI "type 2" flow work with one grader.
    """
    response = response.strip()
    by_position = False
    if response.isdigit() and 1 <= int(response) <= len(options):
        chosen = options[int(response) - 1]
        by_position = True
    else:
        chosen = response

    # Exact option-text match (case-insensitive) — no prefix matching, so
    # "B" does not accidentally match "Bogotá" when both are options.
    matched_option = next((o for o in options if _fold(o) == _fold(chosen)), None)
    if matched_option is None and not by_position:
        # fall through: compare raw response against the answer directly
        matched_option = chosen

    passed = _fold(matched_option or chosen) == _fold(answer)
    display = chosen if not by_position else f"#{response} ({options[int(response) - 1]})"
    return {
        "passed": 1 if passed else 0,
        "total": 1,
        "score": 1.0 if passed else 0.0,
        "details": [_case("multiple choice", passed, answer, display)],
    }


def grade_recall(response: str, answer: str, accept: list[str]) -> GradeResult:
    """Grade a short free-text answer, case/accent-insensitively.

    ``accept`` lists alternative correct spellings (e.g. inflected forms).
    Every alternative must independently match.
    """
    accepted = [answer, *accept]
    passed = any(_fold(response) == _fold(a) for a in accepted if a.strip())
    return {
        "passed": 1 if passed else 0,
        "total": 1,
        "score": 1.0 if passed else 0.1,  # effort credit: an attempt still evidences study
        "details": [_case("short answer", passed, answer, response)],
    }


def grade_numeric(response: str, answer: str, tolerance: float = 0.0) -> GradeResult:
    """Grade a numeric response within an absolute *tolerance*.

    Accepts ``1,000``/``1 000`` thousand separators, trailing ``%``, and
    simple fractions like ``1/2``.  ``tolerance`` is absolute, not
    relative, so content authors know exactly what counts.
    """
    cleaned = response.strip().replace(",", "").replace(" ", "")
    cleaned = cleaned.rstrip("%")

    def _to_float(text: str) -> float | None:
        if "/" in text:
            try:
                num, den = text.split("/", 1)
                if float(den) == 0:
                    return None
                return float(num) / float(den)
            except ValueError:
                return None
        try:
            return float(text)
        except ValueError:
            return None

    value = _to_float(cleaned)
    target = _to_float(answer.strip().replace(",", "").replace(" ", "").rstrip("%"))
    if value is None or target is None:
        return {
            "passed": 0,
            "total": 1,
            "score": 0.0,
            "details": [_case("numeric", False, answer, response)],
        }

    delta = abs(value - target)
    ok = delta <= max(tolerance, 0.0) + 1e-9
    return {
        "passed": 1 if ok else 0,
        "total": 1,
        "score": 1.0 if ok else 0.0,
        "details": [
            {
                "description": "numeric answer",
                "passed": ok,
                "expected": answer,
                "got": repr(value),
            }
        ],
    }


def grade_static(exercise: Any, response: str) -> GradeResult:
    """Dispatch to the right static grader for *exercise*.

    Args:
        exercise: An :class:`~apex.content.Exercise` with ``kind`` in
            ``{"mcq", "recall", "numeric"}``.
        response: The learner's raw answer.

    Raises:
        ValueError: For an unknown kind, so a typo in a YAML kind never
            silently grades as correct.
    """
    graders: dict[str, Callable[..., GradeResult]] = {
        "mcq": lambda: grade_mcq(response, list(exercise.options), exercise.answer),
        "recall": lambda: grade_recall(response, exercise.answer, list(exercise.accept)),
        "numeric": lambda: grade_numeric(response, exercise.answer, exercise.tolerance),
    }
    if exercise.kind not in graders:
        raise ValueError(f"no static grader for exercise kind {exercise.kind!r}")
    return graders[exercise.kind]()
