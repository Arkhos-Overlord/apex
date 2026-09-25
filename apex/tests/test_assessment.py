"""Unit tests for the APEX assessment and spaced-repetition engine."""

from __future__ import annotations

import datetime as dt

import pytest

from apex.engine.assessment import (
    LearnerState,
    MasteryScorer,
    QuizGenerator,
    SpacedRepetition,
    get_due_reviews,
    next_review_date,
    schedule_review,
)

# ===================================================================
# SpacedRepetition
# ===================================================================


class TestSpacedRepetition:
    """Tests for SpacedRepetition — SM-2 scheduling rules."""

    def test_new_card_on_first_review(self) -> None:
        engine = SpacedRepetition()
        now = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
        card = engine.schedule_review("lesson:1", quality=4, now=now)
        assert card["material"] == "lesson:1"
        assert card["repetitions"] == 1
        assert card["interval"] == 1
        assert card["next_date"] == dt.datetime(2024, 1, 2, tzinfo=dt.UTC)

    def test_quality_zero_resets_repetitions(self) -> None:
        engine = SpacedRepetition()
        now = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
        engine.schedule_review("l2", quality=5, now=now)
        card = engine.schedule_review("l2", quality=0, now=now + dt.timedelta(days=1))
        assert card["repetitions"] == 0
        assert card["interval"] == 1

    def test_easiness_factor_floor(self) -> None:
        engine = SpacedRepetition()
        now = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
        engine.schedule_review("l3", quality=0, now=now)
        card = engine.schedule_review("l3", quality=0, now=now + dt.timedelta(days=1))
        assert card["easiness_factor"] >= 1.3

    def test_next_review_date_raises_for_unknown(self) -> None:
        engine = SpacedRepetition()
        with pytest.raises(KeyError, match="No card for material"):
            engine.next_review_date("ghost")

    def test_get_due_reviews_selects_overdue(self) -> None:
        engine = SpacedRepetition()
        now = dt.datetime(2024, 1, 10, tzinfo=dt.UTC)
        engine.schedule_review("a", quality=5, now=now - dt.timedelta(days=3))
        engine.schedule_review("b", quality=5, now=now - dt.timedelta(days=2))
        engine.schedule_review("c", quality=5, now=now + dt.timedelta(days=5))
        due = engine.get_due_reviews({}, now=now)
        assert set(due) == {"a", "b"}

    def test_get_due_reviews_empty_when_nothing_due(self) -> None:
        engine = SpacedRepetition()
        now = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
        engine.schedule_review("future", quality=5, now=now)
        due = engine.get_due_reviews({}, now=now + dt.timedelta(days=1))
        assert "future" in due  # interval=1 so it is due next day

    def test_interval_growth_across_repetitions(self) -> None:
        engine = SpacedRepetition()
        now = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
        for _ in range(4):
            now = now + dt.timedelta(days=1)
            engine.schedule_review("growing", quality=5, now=now)
        card = engine._cards["growing"]
        assert card["repetitions"] == 4
        assert card["interval"] >= 6

    def test_quality_clamped_below_zero(self) -> None:
        engine = SpacedRepetition()
        now = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
        card = engine.schedule_review("clamp-below", quality=-5, now=now)
        assert card["interval"] == 1  # treated as quality 0

    def test_quality_clamped_above_five(self) -> None:
        engine = SpacedRepetition()
        now = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
        card = engine.schedule_review("clamp-above", quality=99, now=now)
        assert card["interval"] == 1  # treated as quality 5


# ===================================================================
# QuizGenerator
# ===================================================================


class TestQuizGenerator:
    """Tests for QuizGenerator — MCQ, fill-blank, coding challenge."""

    def test_mcq_returns_list_within_count(self) -> None:
        g = QuizGenerator(seed=42)
        qs = g.generate_mcq(
            "The quick brown fox jumps over the lazy dog. "
            "Sorting algorithms arrange data in order.",
            count=5,
        )
        assert isinstance(qs, list)
        assert len(qs) <= 5

    def test_mcq_structure(self) -> None:
        g = QuizGenerator(seed=1)
        qs = g.generate_mcq(
            "Photosynthesis converts light energy into chemical energy. "
            "Mitochondria produce ATP through cellular respiration.",
            count=5,
        )
        if qs:
            q = qs[0]
            for key in ("question", "options", "answer", "difficulty", "topic"):
                assert key in q
            assert isinstance(q["options"], list)
            assert len(q["options"]) >= 2
            assert q["answer"] in q["options"]

    def test_fill_blank_structure(self) -> None:
        g = QuizGenerator(seed=7)
        qs = g.generate_fill_blank(
            "The capital of France is Paris. London is the capital of the United Kingdom.",
            count=3,
        )
        if qs:
            q = qs[0]
            assert q["options"] is None
            assert "______" in q["question"]
            assert len(q["answer"]) >= 3

    def test_coding_challenge_structure(self) -> None:
        g = QuizGenerator(seed=3)
        q = g.generate_coding_challenge(
            "Implement a binary search tree with insert and search operations."
        )
        assert isinstance(q, dict)
        assert q["options"] is None
        assert isinstance(q["difficulty"], str)
        assert isinstance(q["topic"], str)
        assert "function" in q["question"].lower()

    def test_empty_content_returns_empty(self) -> None:
        g = QuizGenerator(seed=0)
        assert g.generate_mcq("", count=5) == []
        assert g.generate_fill_blank("", count=3) == []

    def test_deterministic_with_same_seed(self) -> None:
        g1 = QuizGenerator(seed=123)
        g2 = QuizGenerator(seed=123)
        q1 = g1.generate_mcq("Deterministic test content.", count=3)
        q2 = g2.generate_mcq("Deterministic test content.", count=3)
        assert len(q1) == len(q2)
        for a, b in zip(q1, q2):
            assert a == b

    def test_difficulty_values_valid(self) -> None:
        g = QuizGenerator(seed=5)
        qs = g.generate_mcq("Any content here to generate questions.", count=3)
        for q in qs:
            assert q["difficulty"] in ("easy", "medium", "hard")

    def test_topic_non_empty(self) -> None:
        g = QuizGenerator(seed=9)
        qs = g.generate_mcq(
            "Python lists are mutable sequences. Tuples are immutable.",
            count=3,
        )
        for q in qs:
            assert q["topic"]
            assert isinstance(q["topic"], str)


# ===================================================================
# MasteryScorer
# ===================================================================


class TestMasteryScorer:
    """Tests for MasteryScorer — scoring, mastery tracking, confidence."""

    def test_all_correct_quick(self) -> None:
        scorer = MasteryScorer()
        score = scorer.calculate_score(attempts=1, accuracy=1.0, time_spent=10.0)
        assert 90.0 <= score <= 100.0

    def test_half_correct(self) -> None:
        scorer = MasteryScorer()
        score = scorer.calculate_score(attempts=1, accuracy=0.5, time_spent=10.0)
        assert 40.0 <= score <= 60.0

    def test_zero_attempts_returns_zero(self) -> None:
        scorer = MasteryScorer()
        assert scorer.calculate_score(attempts=0, accuracy=1.0, time_spent=0.0) == 0.0

    def test_invalid_accuracy_returns_zero(self) -> None:
        scorer = MasteryScorer()
        assert scorer.calculate_score(attempts=1, accuracy=-0.1, time_spent=0.0) == 0.0
        assert scorer.calculate_score(attempts=1, accuracy=1.5, time_spent=0.0) == 0.0

    def test_update_mastery_increases_exposure(self) -> None:
        scorer = MasteryScorer()
        snap1 = scorer.update_mastery("algebra", 85.0)
        assert snap1["exposure_count"] == 1
        assert snap1["scores"] == [85.0]
        snap2 = scorer.update_mastery("algebra", 90.0)
        assert snap2["exposure_count"] == 2

    def test_update_mastery_classification(self) -> None:
        scorer = MasteryScorer()
        scorer.update_mastery("geo", 90.0)  # independent
        scorer.update_mastery("geo", 60.0)  # assisted
        scorer.update_mastery("geo", 30.0)  # neither
        snap = scorer.update_mastery("geo", 0.0)
        assert snap["independent_success"] == 1
        assert snap["assisted_success"] == 1

    def test_record_recall_successful(self) -> None:
        scorer = MasteryScorer()
        snap = scorer.record_recall("history", successful=True)
        assert snap["delayed_recall"] == 1

    def test_record_recall_unsuccessful_no_increment(self) -> None:
        scorer = MasteryScorer()
        scorer.record_recall("history", successful=True)
        snap = scorer.record_recall("history", successful=False)
        assert snap["delayed_recall"] == 1

    def test_get_confidence_no_data(self) -> None:
        scorer = MasteryScorer()
        conf = scorer.get_confidence({}, "nonexistent")
        assert conf["score"] == 0.0
        assert conf["half_width"] == 50.0
        assert conf["lower"] == 0.0
        assert conf["upper"] == 0.0

    def test_get_confidence_narrows_with_data(self) -> None:
        scorer = MasteryScorer()
        for _ in range(5):
            scorer.update_mastery("physics", 80.0)
        conf = scorer.get_confidence({}, "physics")
        assert conf["score"] == pytest.approx(80.0, abs=0.01)
        assert conf["half_width"] < 50.0

    def test_get_confidence_bounds_clamped(self) -> None:
        scorer = MasteryScorer()
        for _ in range(10):
            scorer.update_mastery("chem", 100.0)
        conf = scorer.get_confidence({}, "chem")
        assert conf["upper"] <= 100.0
        assert conf["lower"] >= 0.0

    def test_get_confidence_respects_learner_state_override(self) -> None:
        scorer = MasteryScorer()
        state: LearnerState = {
            "custom_topic": {"scores": [50.0, 60.0, 70.0]},
        }
        conf = scorer.get_confidence(state, "custom_topic")
        assert conf["score"] == pytest.approx(60.0, abs=0.01)
        assert conf["half_width"] < 50.0

    def test_score_boundary_80_independent(self) -> None:
        scorer = MasteryScorer()
        snap = scorer.update_mastery("bio", 80.0)
        assert snap["independent_success"] == 1
        snap2 = scorer.update_mastery("bio", 79.9)
        assert snap2["independent_success"] == 1
        assert snap2["assisted_success"] == 1  # 79.9 >= 50


# ===================================================================
# Convenience wrappers
# ===================================================================


class TestConvenienceWrappers:
    """Sanity checks for module-level convenience functions."""

    def test_schedule_review_wrapper(self) -> None:
        card = schedule_review("mock_material", 4)
        assert card["material"] == "mock_material"
        assert card["repetitions"] == 1

    def test_next_review_date_wrapper(self) -> None:
        d = next_review_date("wrapper_test")
        assert isinstance(d, dt.datetime)

    def test_get_due_reviews_wrapper_empty(self) -> None:
        due = get_due_reviews({})
        assert isinstance(due, list)
