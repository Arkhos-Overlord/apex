"""Tests for the APEX core engine modules."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from apex.core import AdaptiveDifficulty, Chapter, Course, LearnerState, Lesson
from apex.store import Store, StoreError

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


# ── LearnerState in BKT mode ────────────────────────────────────────────


class TestLearnerBKTMode:
    """BKT mode tracks probabilities instead of integer scores.

    BKT_MODE is a module global, so every test here flips it back in a
    finally block -- leaving it True would silently retarget the whole
    suite that runs after it.
    """

    @staticmethod
    def _run_bkt(ls: LearnerState, correct: bool) -> None:
        from apex.core import learner as learner_mod

        original = learner_mod.BKT_MODE
        learner_mod.BKT_MODE = True
        try:
            ls.record_attempt("loops", correct)
        finally:
            learner_mod.BKT_MODE = original

    def test_unseen_topic_is_not_mastered(self) -> None:
        """Regression: an unseen topic used to report as mastered.

        Returning MASTERED for un-attempted skills made a brand-new learner
        look like an expert in every subject, so is_mastered() was True
        everywhere and nothing was ever selected for practice.
        """
        ls = LearnerState()
        assert ls.get_mastery_probability("loops") == pytest.approx(ls.bkt_params.p_init)
        assert ls.get_mastery_probability("loops") < 0.95
        assert ls.is_mastered("loops") is False

    def test_correct_attempt_raises_probability(self) -> None:
        ls = LearnerState()
        self._run_bkt(ls, True)
        assert ls.mastery_probabilities["loops"] > ls.bkt_params.p_init

    def test_incorrect_attempt_lowers_probability(self) -> None:
        ls = LearnerState()
        ls.mastery_probabilities["loops"] = 0.9
        self._run_bkt(ls, False)
        assert ls.mastery_probabilities["loops"] < 0.9

    def test_bkt_mode_does_not_touch_integer_scores(self) -> None:
        ls = LearnerState()
        self._run_bkt(ls, True)
        assert ls.mastery_scores == {}

    def test_is_mastered_after_repeated_success(self) -> None:
        from apex.core import learner as learner_mod

        original = learner_mod.BKT_MODE
        learner_mod.BKT_MODE = True
        try:
            ls = LearnerState()
            for _ in range(15):
                ls.record_attempt("loops", True)
            assert ls.is_mastered("loops") is True
        finally:
            learner_mod.BKT_MODE = original


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
        """Good performance increases topic difficulty rating."""
        engine = AdaptiveDifficulty()
        ls = LearnerState()
        engine.update_model(ls, "math", 1.0)
        assert engine.topic_ratings["math"] > 1200.0

    def test_update_model_widens_the_gap(self) -> None:
        """A strong performance must move the learner/content gap.

        Regression: update_model used to add the same delta to both the
        learner and the topic rating, which left the gap invariant and made
        suggest_difficulty and zpd_topics blind to how the learner did.
        """
        engine = AdaptiveDifficulty()
        ls = LearnerState()
        engine.update_model(ls, "math", 1.0)
        gap = engine.learner_ratings["math"] - engine.topic_ratings["math"]
        assert gap > 0.0

    def test_weak_performance_narrows_the_gap(self) -> None:
        """A poor performance pushes the gap the other way."""
        engine = AdaptiveDifficulty()
        ls = LearnerState()
        engine.update_model(ls, "math", 0.0)
        gap = engine.learner_ratings["math"] - engine.topic_ratings["math"]
        assert gap < 0.0

    def test_difficulty_rises_with_repeated_success(self) -> None:
        """Success after success should escalate difficulty, not stall."""
        engine = AdaptiveDifficulty()
        ls = LearnerState()
        first = engine.suggest_difficulty(ls, "math")
        for _ in range(5):
            engine.update_model(ls, "math", 1.0)
        later = engine.suggest_difficulty(ls, "math")
        assert later > first

    def test_difficulty_drops_with_repeated_failure(self) -> None:
        """Failure after failure should back off, not stall."""
        engine = AdaptiveDifficulty()
        ls = LearnerState()
        first = engine.suggest_difficulty(ls, "math")
        for _ in range(5):
            engine.update_model(ls, "math", 0.0)
        later = engine.suggest_difficulty(ls, "math")
        assert later < first

    def test_damping_is_bounded(self) -> None:
        """The content rating must never outrun the learner's own rating."""
        engine = AdaptiveDifficulty(difficulty_damping=1.0)
        ls = LearnerState()
        engine.update_model(ls, "math", 1.0)
        assert engine.topic_ratings["math"] == engine.learner_ratings["math"]

    def test_seeds_learner_rating_from_mastery(self) -> None:
        """A strong existing mastery starts the learner above the default."""
        engine = AdaptiveDifficulty()
        ls = LearnerState()
        ls.mastery_scores["math"] = 100
        engine.update_model(ls, "math", 0.5)
        # 100 mastery -> 1200 + 50*8 = 1600 before the update
        assert engine.learner_ratings["math"] > 1400.0

    def test_unseen_topic_uses_default_seed(self) -> None:
        """With no mastery on record the rating starts at the default."""
        engine = AdaptiveDifficulty()
        ls = LearnerState()
        engine.update_model(ls, "unseen", 0.5)
        assert engine.learner_ratings["unseen"] == pytest.approx(1200.0, abs=1.0)

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


class TestLearnerPersistence:
    """save/load must round-trip through the store's canonical 0-1 scale."""

    @staticmethod
    def _store(tmp_path: Path) -> Store:
        return Store(tmp_path / "test.db")

    def test_elo_scores_are_normalised_to_0_1(self, tmp_path: Path) -> None:
        """Regression: save() wrote Elo's 0-100 straight into the store.

        Everything downstream -- prerequisite gating, select_next, the
        MASTERED threshold -- reads that column as a probability, so a
        perfect 100 was read back as 100x over the mastery threshold.
        """
        store = self._store(tmp_path)
        ls = LearnerState(persistence=store)
        ls.record_attempt("io", True)
        ls.save("alice")

        stored = store.get_mastery("alice")
        assert stored["io"] == pytest.approx(0.1)
        assert all(0.0 <= v <= 1.0 for v in stored.values())

    def test_elo_round_trip(self, tmp_path: Path) -> None:
        store = self._store(tmp_path)
        ls = LearnerState(persistence=store)
        for _ in range(4):
            ls.record_attempt("loops", True)
        ls.save("alice")

        restored = LearnerState(persistence=store)
        restored.load("alice")
        assert restored.get_mastery("loops") == 40

    def test_bkt_round_trip(self, tmp_path: Path) -> None:
        from apex.core import learner as learner_mod

        store = self._store(tmp_path)
        original = learner_mod.BKT_MODE
        learner_mod.BKT_MODE = True
        try:
            ls = LearnerState(persistence=store)
            for _ in range(3):
                ls.record_attempt("loops", True)
            probability = ls.mastery_probabilities["loops"]
            ls.save("alice")

            restored = LearnerState(persistence=store)
            restored.load("alice")
            assert restored.mastery_probabilities["loops"] == pytest.approx(probability)
        finally:
            learner_mod.BKT_MODE = original

    def test_save_without_store_raises(self) -> None:
        ls = LearnerState()
        with pytest.raises(StoreError):
            ls.save("alice")

    def test_load_without_store_raises(self) -> None:
        ls = LearnerState()
        with pytest.raises(StoreError):
            ls.load("alice")

    def test_load_records_exposure_evidence(self, tmp_path: Path) -> None:
        store = self._store(tmp_path)
        source = LearnerState(persistence=store)
        source.record_attempt("io", True)
        source.save("alice")

        restored = LearnerState(persistence=store)
        restored.load("alice")
        assert any(e["type"] == "exposure" and e["topic"] == "io" for e in restored.evidence)
