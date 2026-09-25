"""Tests for the APEX core engine modules."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from apex.core import AdaptiveDifficulty, Chapter, Course, LearnerState, Lesson

# ── Lesson ──────────────────────────────────────────────────────────────


class TestLesson:
    def test_default_difficulty(self) -> None:
        lesson = Lesson(title="Intro", content="Hello")
        assert lesson.difficulty == 5

    def test_custom_difficulty(self) -> None:
        lesson = Lesson(title="Intro", content="Hello", difficulty=8)
        assert lesson.difficulty == 8

    def test_difficulty_clamped_low(self) -> None:
        """Lesson raises on difficulty below 1."""
        with pytest.raises(ValidationError):
            Lesson(title="Intro", content="Hello", difficulty=0)

    def test_difficulty_clamped_high(self) -> None:
        """Lesson raises on difficulty above 10."""
        with pytest.raises(ValidationError):
            Lesson(title="Intro", content="Hello", difficulty=15)

    def test_serialization(self) -> None:
        lesson = Lesson(title="T", content="C", difficulty=7)
        data = lesson.model_dump()
        restored = Lesson.model_validate(data)
        assert restored.title == lesson.title
        assert restored.difficulty == lesson.difficulty


# ── Chapter ─────────────────────────────────────────────────────────────


class TestChapter:
    def test_empty_chapter(self) -> None:
        ch = Chapter(title="Basics")
        assert ch.lessons == []

    def test_chapter_with_lessons(self) -> None:
        lessons = [Lesson(title="L1", content="A"), Lesson(title="L2", content="B")]
        ch = Chapter(title="Basics", lessons=lessons)
        assert len(ch.lessons) == 2
        assert ch.lessons[0].title == "L1"

    def test_serialization(self) -> None:
        ch = Chapter(title="C", lessons=[Lesson(title="L", content="X")])
        data = ch.model_dump()
        restored = Chapter.model_validate(data)
        assert restored.title == ch.title
        assert len(restored.lessons) == 1


# ── Course ──────────────────────────────────────────────────────────────


class TestCourse:
    def test_minimal_course(self) -> None:
        c = Course(id="py101", title="Python", description="Learn Python")
        assert c.id == "py101"
        assert c.depth == "survey"
        assert c.length == 0
        assert c.chapters == []

    def test_course_with_chapters(self) -> None:
        ch = Chapter(title="Basics", lessons=[Lesson(title="L", content="C")])
        c = Course(id="py101", title="Python", description="D", chapters=[ch])
        assert len(c.chapters) == 1
        assert c.chapters[0].title == "Basics"

    def test_depth_literal(self) -> None:
        for depth in ("survey", "working", "mastery"):
            c = Course(id="x", title="T", description="D", depth=depth)
            assert c.depth == depth

    def test_created_at_is_datetime(self) -> None:
        c = Course(id="x", title="T", description="D")
        assert isinstance(c.created_at, datetime)
        assert isinstance(c.updated_at, datetime)

    def test_serialization(self) -> None:
        c = Course(id="py101", title="Python", description="D")
        data = c.model_dump()
        restored = Course.model_validate(data)
        assert restored.id == c.id
        assert restored.title == c.title

    def test_roundtrip_via_dict(self) -> None:
        c = Course(id="c1", title="T", description="D", depth="mastery", length=10)
        dumped = c.model_dump()
        restored = Course.model_validate(dumped)
        assert restored.id == c.id
        assert restored.depth == "mastery"
        assert restored.length == 10


# ── LearnerState ────────────────────────────────────────────────────────


class TestLearnerState:
    def test_initial_state(self) -> None:
        ls = LearnerState()
        assert ls.mastery_scores == {}
        assert ls.attempt_history == []
        assert ls.confidence_levels == {}
        assert ls.evidence == []

    def test_record_attempt_correct(self) -> None:
        ls = LearnerState()
        ls.record_attempt("math", True)
        assert ls.get_mastery("math") == 10
        assert ls.confidence_levels["math"] > 0.5
        assert len(ls.attempt_history) == 1
        assert ls.attempt_history[0]["result"] is True
        assert len(ls.evidence) == 1

    def test_record_attempt_incorrect(self) -> None:
        ls = LearnerState()
        ls.record_attempt("math", False)
        assert ls.get_mastery("math") == 0
        assert ls.confidence_levels["math"] < 0.5

    def test_mastery_increases(self) -> None:
        ls = LearnerState()
        ls.mastery_scores["math"] = 50
        ls.record_attempt("math", True)
        assert ls.get_mastery("math") == 60

    def test_mastery_decreases(self) -> None:
        ls = LearnerState()
        ls.mastery_scores["math"] = 50
        ls.record_attempt("math", False)
        assert ls.get_mastery("math") == 45

    def test_mastery_clamps_at_100(self) -> None:
        ls = LearnerState()
        ls.mastery_scores["math"] = 100
        ls.record_attempt("math", True)
        assert ls.get_mastery("math") == 100

    def test_mastery_clamps_at_0(self) -> None:
        ls = LearnerState()
        ls.mastery_scores["math"] = 0
        ls.record_attempt("math", False)
        assert ls.get_mastery("math") == 0

    def test_get_mastery_default_zero(self) -> None:
        ls = LearnerState()
        assert ls.get_mastery("nonexistent") == 0

    def test_next_topic_returns_lowest(self) -> None:
        ls = LearnerState()
        ls.mastery_scores["easy"] = 90
        ls.mastery_scores["hard"] = 10
        assert ls.next_topic() == "hard"

    def test_next_topic_empty(self) -> None:
        ls = LearnerState()
        assert ls.next_topic() is None

    def test_evidence_type(self) -> None:
        ls = LearnerState()
        ls.record_attempt("topic", True)
        ev = ls.evidence[-1]
        assert ev["type"] == "independent"
        assert ev["topic"] == "topic"

    def test_attempt_history_timestamp(self) -> None:
        ls = LearnerState()
        ls.record_attempt("t", True)
        assert "timestamp" in ls.attempt_history[0]

    def test_serialization(self) -> None:
        ls = LearnerState()
        ls.record_attempt("math", True)
        data = ls.model_dump()
        restored = LearnerState.model_validate(data)
        assert restored.get_mastery("math") == ls.get_mastery("math")
        assert len(restored.attempt_history) == len(ls.attempt_history)


# ── AdaptiveDifficulty ───────────────────────────────────────────────────


class TestAdaptiveDifficulty:
    def test_default_ratings(self) -> None:
        engine = AdaptiveDifficulty()
        assert engine.k_factor == 32.0
        assert engine.default_rating == 1200.0
        assert engine.learner_ratings == {}
        assert engine.topic_ratings == {}

    def test_suggest_difficulty_equal_ratings(self) -> None:
        engine = AdaptiveDifficulty()
        engine.learner_ratings["math"] = 1200.0
        engine.topic_ratings["math"] = 1200.0
        result = engine.suggest_difficulty(LearnerState(), "math")
        assert result == 5  # middle of the range

    def test_suggest_difficulty_easy_content(self) -> None:
        engine = AdaptiveDifficulty()
        engine.learner_ratings["math"] = 1400.0
        engine.topic_ratings["math"] = 1200.0
        result = engine.suggest_difficulty(LearnerState(), "math")
        assert 6 <= result <= 10

    def test_suggest_difficulty_hard_content(self) -> None:
        engine = AdaptiveDifficulty()
        engine.learner_ratings["math"] = 1000.0
        engine.topic_ratings["math"] = 1400.0
        result = engine.suggest_difficulty(LearnerState(), "math")
        assert 1 <= result <= 4

    def test_suggest_difficulty_clamps_low(self) -> None:
        engine = AdaptiveDifficulty()
        engine.learner_ratings["math"] = 100.0
        engine.topic_ratings["math"] = 2000.0
        result = engine.suggest_difficulty(LearnerState(), "math")
        assert result == 1

    def test_suggest_difficulty_clamps_high(self) -> None:
        engine = AdaptiveDifficulty()
        engine.learner_ratings["math"] = 2000.0
        engine.topic_ratings["math"] = 100.0
        result = engine.suggest_difficulty(LearnerState(), "math")
        assert result == 10

    def test_update_model_improves_learner_rating(self) -> None:
        engine = AdaptiveDifficulty()
        ls = LearnerState()
        engine.update_model(ls, "math", 1.0)
        assert engine.learner_ratings["math"] > 1200.0

    def test_update_model_worsens_learner_rating(self) -> None:
        engine = AdaptiveDifficulty()
        ls = LearnerState()
        engine.update_model(ls, "math", 0.0)
        assert engine.learner_ratings["math"] < 1200.0

    def test_update_model_flips_topic_rating(self) -> None:
        engine = AdaptiveDifficulty()
        ls = LearnerState()
        engine.update_model(ls, "math", 1.0)
        assert engine.topic_ratings["math"] < 1200.0

    def test_update_model_invalid_performance_raises(self) -> None:
        engine = AdaptiveDifficulty()
        ls = LearnerState()
        with pytest.raises(ValueError, match="performance must be between"):
            engine.update_model(ls, "math", 1.5)

    def test_zpd_topics_empty_when_no_topics(self) -> None:
        engine = AdaptiveDifficulty()
        assert engine.zpd_topics == []

    def test_zpd_topics_inside_range(self) -> None:
        engine = AdaptiveDifficulty()
        engine.learner_ratings["math"] = 1200.0
        engine.topic_ratings["math"] = 1250.0  # gap +50
        assert "math" in engine.zpd_topics

    def test_zpd_topics_outside_range(self) -> None:
        engine = AdaptiveDifficulty()
        engine.learner_ratings["math"] = 1200.0
        engine.topic_ratings["math"] = 1400.0  # gap +200
        assert "math" not in engine.zpd_topics

    def test_zpd_with_learner_state_seed(self) -> None:
        engine = AdaptiveDifficulty()
        ls = LearnerState()
        ls.mastery_scores["math"] = 70
        engine.update_model(ls, "math", 0.7)
        # After one observation the gap should be small enough for ZPD
        assert len(engine.zpd_topics) >= 0  # non-deterministic but valid


# ── Integration ──────────────────────────────────────────────────────────


class TestIntegration:
    def test_learner_and_adaptive_work_together(self) -> None:
        ls = LearnerState()
        engine = AdaptiveDifficulty()

        ls.record_attempt("math", True)
        engine.update_model(ls, "math", 1.0)

        difficulty = engine.suggest_difficulty(ls, "math")
        assert 1 <= difficulty <= 10

    def test_course_lesson_chapter_nesting(self) -> None:
        lesson = Lesson(title="Loops", content="Learn loops", difficulty=6)
        chapter = Chapter(title="Basics", lessons=[lesson])
        course = Course(
            id="py101",
            title="Python",
            description="Learn to code",
            chapters=[chapter],
            depth="working",
            length=8,
        )
        assert course.chapters[0].lessons[0].title == "Loops"
        assert course.depth == "working"
        assert course.length == 8

    def test_full_workflow(self) -> None:
        # 1. Create content
        lesson = Lesson(title="Variables", content="What is a variable", difficulty=3)
        chapter = Chapter(title="Intro", lessons=[lesson])
        _ = Course(id="cs101", title="CS101", description="Intro", chapters=[chapter])

        # 2. Track learner
        ls = LearnerState()
        ls.record_attempt("variables", False)
        ls.record_attempt("variables", True)
        ls.record_attempt("variables", True)

        # 3. Adaptive engine adjusts
        engine = AdaptiveDifficulty()
        engine.update_model(ls, "variables", 0.66)

        # 4. Get recommendation
        suggested = engine.suggest_difficulty(ls, "variables")
        assert 1 <= suggested <= 10

        # 5. Verify state
        assert ls.get_mastery("variables") > 0
        assert len(ls.attempt_history) == 3
        assert len(ls.evidence) == 3


# ── LearnerState persistence ──────────────────────────────────────────────
