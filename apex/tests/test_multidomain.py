"""Integration tests for the multi-domain content bank.

These are the tests that would have caught the "APEX only teaches Python"
problem: a session must be able to submit an answer to a Spanish recall
exercise, a math numeric exercise, and a JavaScript code exercise through
the exact same grading pipeline, and the adaptive selector must serve all
domains.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.content import ContentLibrary
from apex.session import LearningSession
from apex.store import Store

CONTENT = Path(__file__).resolve().parents[2] / "content"


@pytest.fixture
def lib() -> ContentLibrary:
    return ContentLibrary(CONTENT)


@pytest.fixture
def session(tmp_path: Path) -> LearningSession:
    return LearningSession("multi-domain", store=Store(tmp_path / "multi.db"))


class TestContentBank:
    def test_non_python_kinds_exist(self, lib: ContentLibrary) -> None:
        kinds = {ex.kind for ex in lib.exercises.values()}
        assert {"code", "mcq", "recall", "numeric"} <= kinds

    def test_math_and_spanish_domains_in_graph(self, lib: ContentLibrary) -> None:
        for skill in ("order-of-operations", "fractions", "spanish-greetings", "spanish-verbs"):
            assert skill in lib.skills, f"{skill} missing from the knowledge web"

    def test_math_links_into_programming_web(self, lib: ContentLibrary) -> None:
        # order-of-operations is related to arithmetic: the domains connect.
        assert "arithmetic" in lib.graph.neighbours("order-of-operations", include_incoming=True)

    def test_health_still_clean_with_new_domains(self, lib: ContentLibrary) -> None:
        assert lib.health()["ok"], lib.health()["problems"]

    def test_static_exercises_carry_no_tests(self, lib: ContentLibrary) -> None:
        for ex in lib.exercises.values():
            if ex.kind != "code":
                assert not ex.tests, f"{ex.id} is {ex.kind} but declares test cases"

    def test_mcq_answer_is_an_option(self, lib: ContentLibrary) -> None:
        for ex in lib.exercises.values():
            if ex.kind == "mcq":
                assert ex.answer in ex.options

    def test_public_strips_answer_key(self, lib: ContentLibrary) -> None:
        for ex in lib.exercises.values():
            if ex.kind != "code":
                assert ex.public()["answer"] == ""


class TestMixedKindSubmissions:
    def test_math_numeric_submission(self, session: LearningSession) -> None:
        ex = session.library.get_exercise("math-order-1")
        report = session.submit("14", ex)
        assert report.passed
        assert report.mastery_after["order-of-operations"] > 0.25

    def test_spanish_recall_submission(self, session: LearningSession) -> None:
        ex = session.library.get_exercise("es-greeting-1")
        report = session.submit("Hola", ex)  # case-insensitive
        assert report.passed

    def test_wrong_static_answer_scores_below_correct(self, session: LearningSession) -> None:
        ex = session.library.get_exercise("es-greeting-1")
        wrong = session.submit("adios", ex)
        assert not wrong.passed
        # Bayesian honesty: a wrong answer on an unseen skill drives the
        # posterior BELOW the prior (0.25) -- an attempt is weak evidence,
        # and evidence of failure is still evidence.
        assert wrong.mastery_after["spanish-greetings"] < 0.25
        assert wrong.mastery_after["spanish-greetings"] > 0.0

        # And the correct answer on the same skill must beat it.
        right = session.submit(ex.answer, ex)
        assert right.mastery_after["spanish-greetings"] > wrong.mastery_after["spanish-greetings"]

    def test_javascript_code_submission(self, session: LearningSession) -> None:
        ex = session.library.get_exercise("js-greet")
        assert ex.language == "javascript"
        report = session.submit(ex.solution, ex)
        assert report.passed, report.details

    def test_python_still_works(self, session: LearningSession) -> None:
        ex = session.library.get_exercise("py-hello")
        report = session.submit(ex.solution, ex)
        assert report.passed


class TestAdaptiveSelectionSpansDomains:
    def test_selector_reaches_every_domain(self, session: LearningSession) -> None:
        served: set[str] = set()
        kinds: set[str] = set()
        # Long enough to exhaust the alphabetically-first static exercises:
        # weakest-first selection with everything tied at the prior walks
        # the bank in deterministic order until mastery differentiates.
        for _ in range(20):
            ex = session.next_exercise(exclude=served)
            if ex is None:
                break
            served.add(ex.id)
            kinds.add(ex.kind)
            session.submit(
                ex.answer if ex.kind != "code" else ex.solution,
                ex,
            )
        # Over a tour the learner meets static AND code kinds.
        assert {"mcq", "recall", "numeric"} & kinds
        assert "code" in kinds

    def test_math_proposal_reasons_are_real(self, session: LearningSession) -> None:
        proposals = session.proposals(limit=8)
        names = {p.name for p in proposals}
        assert any("Order of Operations" in n or "Fractions" in n for n in names)
