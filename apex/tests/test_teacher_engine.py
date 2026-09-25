"""Tests for the APEX teacher persona system."""

from __future__ import annotations

import pytest

from apex.core import LearnerState
from apex.teachers import (
    TEACHER_PROFILES,
    LessonContent,
    TeacherProfile,
    diagnose_errors,
    generate_socratic_questions,
    get_teacher,
    get_tts_voice,
    instruct,
    list_teachers,
)

# ── Teacher lookup tests ──────────────────────────────────────────────────────


class TestGetTeacher:
    def test_get_mentor(self) -> None:
        teacher = get_teacher("The Mentor")
        assert teacher.name == "The Mentor"
        assert teacher.teaching_style == "socratic"
        assert teacher.patience_level == "high"

    def test_get_drill_sergeant(self) -> None:
        teacher = get_teacher("the drill sergeant")
        assert teacher.name == "The Drill Sergeant"
        assert teacher.teaching_style == "direct"
        assert teacher.patience_level == "low"

    def test_get_guide(self) -> None:
        teacher = get_teacher("THE GUIDE")
        assert teacher.name == "The Guide"
        assert teacher.teaching_style == "inquiry"
        assert teacher.patience_level == "medium"

    def test_get_storyteller(self) -> None:
        teacher = get_teacher("the storyteller")
        assert teacher.name == "The Storyteller"
        assert teacher.teaching_style == "narrative"
        assert teacher.patience_level == "high"

    def test_case_insensitive_lookup(self) -> None:
        t1 = get_teacher("The Mentor")
        t2 = get_teacher("the mentor")
        t3 = get_teacher("THE MENTOR")
        assert t1 is t2 is t3

    def test_unknown_teacher_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown teacher"):
            get_teacher("NonExistent Teacher")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown teacher"):
            get_teacher("")

    def test_whitespace_trimmed(self) -> None:
        teacher = get_teacher("  The Mentor  ")
        assert teacher.name == "The Mentor"


class TestListTeachers:
    def test_returns_all_four(self) -> None:
        names = list_teachers()
        assert len(names) == 4

    def test_contains_all_expected_names(self) -> None:
        names = list_teachers()
        expected = {"The Mentor", "The Drill Sergeant", "The Guide", "The Storyteller"}
        assert set(names) == expected

    def test_sorted_order(self) -> None:
        names = list_teachers()
        assert names == sorted(names)


class TestTeacherProfilesDict:
    def test_all_profiles_present(self) -> None:
        assert len(TEACHER_PROFILES) == 4

    def test_keys_are_lowercase(self) -> None:
        for key in TEACHER_PROFILES:
            assert key == key.lower()

    def test_profiles_are_immutable(self) -> None:
        for profile in TEACHER_PROFILES.values():
            assert isinstance(profile, TeacherProfile)
            # Frozen dataclass should not allow attribute setting
            with pytest.raises(Exception):  # AttributeError or similar
                profile.name = "New Name"


# ── Instruction engine tests ──────────────────────────────────────────────────


class TestInstruct:
    def test_returns_lesson_content(self) -> None:
        result = instruct("The Mentor", "variables")
        assert isinstance(result, LessonContent)

    def test_all_fields_populated(self) -> None:
        result = instruct("The Mentor", "functions")
        assert result.teacher_name == "The Mentor"
        assert result.topic == "functions"
        assert result.greeting
        assert result.explanation
        assert result.example
        assert isinstance(result.questions, list)
        assert len(result.questions) >= 3
        assert isinstance(result.practice_exercises, list)
        assert len(result.practice_exercises) >= 3
        assert result.encouragement
        assert result.tts_voice

    def test_greeting_matches_teacher(self) -> None:
        mentor = instruct("The Mentor", "loops")
        drill = instruct("The Drill Sergeant", "loops")
        assert "Welcome" in mentor.greeting or "welcome" in mentor.greeting.lower()
        assert "Listen up" in drill.greeting or "listen" in drill.greeting.lower()

    def test_explanation_depth_differs_by_teacher(self) -> None:
        mentor = instruct("The Mentor", "recursion")
        drill = instruct("The Drill Sergeant", "recursion")
        guide = instruct("The Guide", "recursion")
        storyteller = instruct("The Storyteller", "recursion")

        # Mentor: step-by-step, detailed
        assert "Let's explore" in mentor.explanation or "together" in mentor.explanation
        # Drill Sergeant: brief, direct
        assert mentor.explanation != drill.explanation
        # Guide: detailed, inquiry-based
        assert "Great, we're looking at" in guide.explanation or "looking at" in guide.explanation
        # Storyteller: narrative, historical
        assert "Ah," in storyteller.explanation or "story" in storyteller.explanation.lower()

    def test_questions_differ_by_teacher(self) -> None:
        mentor_qs = instruct("The Mentor", "arrays").questions
        drill_qs = instruct("The Drill Sergeant", "arrays").questions
        guide_qs = instruct("The Guide", "arrays").questions

        # Different teachers phrase questions differently
        assert mentor_qs != drill_qs
        assert mentor_qs != guide_qs

        # Mentor uses reflective language
        assert any("Reflect" in q or "think" in q.lower() for q in mentor_qs)

        # Drill Sergeant uses direct language
        assert any("Answer" in q or "now" in q.lower() for q in drill_qs)

        # Guide uses exploratory language
        assert any("Explore" in q or "find" in q.lower() for q in guide_qs)

    def test_different_topics_produce_different_content(self) -> None:
        vars_lesson = instruct("The Mentor", "variables")
        func_lesson = instruct("The Mentor", "functions")
        assert vars_lesson.explanation != func_lesson.explanation
        assert vars_lesson.topic == "variables"
        assert func_lesson.topic == "functions"

    def test_tts_voice_matches_teacher(self) -> None:
        mentor = instruct("The Mentor", "classes")
        assert mentor.tts_voice == "alloy"

        drill = instruct("The Drill Sergeant", "classes")
        assert drill.tts_voice == "shimmer"

        guide = instruct("The Guide", "classes")
        assert guide.tts_voice == "nova"

        storyteller = instruct("The Storyteller", "classes")
        assert storyteller.tts_voice == "fable"

    def test_encouragement_matches_teacher_style(self) -> None:
        mentor = instruct("The Mentor", "conditionals")
        drill = instruct("The Drill Sergeant", "conditionals")
        guide = instruct("The Guide", "conditionals")

        # Mentor: curiosity and discovery
        assert (
            "question" in mentor.encouragement.lower() or "explore" in mentor.encouragement.lower()
        )
        # Drill: discipline and practice
        assert "practice" in drill.encouragement.lower() or "drill" in drill.encouragement.lower()
        # Guide: autonomy and resources
        assert "path" in guide.encouragement.lower() or "resource" in guide.encouragement.lower()


class TestInstructWithLearnerState:
    def test_learner_state_with_errors_adds_correction(self) -> None:
        state = LearnerState(
            current_topic="variables",
            errors=["Variable 'x' used before assignment"],
            attempts=3,
            confidence=0.3,
        )
        result = instruct("The Mentor", "variables", learner_state=state)
        # Correction should be included in the explanation
        assert "Variable" in result.explanation
        assert "used before" in result.explanation or "assignment" in result.explanation

    def test_learner_state_empty_errors_no_correction(self) -> None:
        state = LearnerState(current_topic="loops", errors=[])
        result = instruct("The Guide", "loops", learner_state=state)
        # No error-specific content should appear
        assert "Error detected" not in result.explanation

    def test_correction_voice_matches_teacher(self) -> None:
        state = LearnerState(
            errors=["Syntax error: missing colon"],
            attempts=2,
            confidence=0.4,
        )
        mentor_result = instruct("The Mentor", "conditionals", learner_state=state)
        drill_result = instruct("The Drill Sergeant", "conditionals", learner_state=state)

        # Different teachers phrase corrections differently
        assert mentor_result.explanation != drill_result.explanation

        # Mentor: reflective, gentle
        assert (
            "think" in mentor_result.explanation.lower()
            or "expect" in mentor_result.explanation.lower()
        )
        # Drill: direct, firm
        assert (
            "fix" in drill_result.explanation.lower()
            or "correct" in drill_result.explanation.lower()
        )

    def test_learner_state_fields_carried_through(self) -> None:
        state = LearnerState(
            current_topic="recursion",
            errors=["Base case missing"],
            attempts=5,
            confidence=0.2,
            pace="slow",
        )
        result = instruct("The Storyteller", "recursion", learner_state=state)
        # The lesson should reference the topic
        assert result.topic == "recursion"


class TestGenerateSocraticQuestions:
    def test_returns_correct_count(self) -> None:
        teacher = get_teacher("The Mentor")
        questions = generate_socratic_questions(teacher, "variables", count=3)
        assert len(questions) == 3

    def test_default_count_is_three(self) -> None:
        teacher = get_teacher("The Guide")
        questions = generate_socratic_questions(teacher, "functions")
        assert len(questions) == 3

    def test_questions_for_known_topic(self) -> None:
        teacher = get_teacher("The Mentor")
        questions = generate_socratic_questions(teacher, "loops", count=5)
        assert len(questions) == 5
        assert all(isinstance(q, str) and q for q in questions)

    def test_questions_for_unknown_topic_fallback(self) -> None:
        teacher = get_teacher("The Storyteller")
        questions = generate_socratic_questions(teacher, "quantum_entanglement", count=2)
        assert len(questions) == 2
        # Should use generic fallback questions
        assert "quantum_entanglement" in questions[0].lower() or "this" in questions[0].lower()

    def test_questions_reflect_teacher_style(self) -> None:
        mentor = get_teacher("The Mentor")
        drill = get_teacher("The Drill Sergeant")
        guide = get_teacher("The Guide")

        mentor_qs = generate_socratic_questions(mentor, "arrays", count=2)
        drill_qs = generate_socratic_questions(drill, "arrays", count=2)
        guide_qs = generate_socratic_questions(guide, "arrays", count=2)

        # Mentor: reflective phrasing
        assert any(q.startswith("Reflect") for q in mentor_qs)
        # Drill: direct phrasing
        assert any(q.startswith("Answer") for q in drill_qs)
        # Guide: exploratory phrasing
        assert any(q.startswith("Explore") for q in guide_qs)

    def test_questions_for_storyteller_use_imagery(self) -> None:
        storyteller = get_teacher("The Storyteller")
        questions = generate_socratic_questions(storyteller, "functions", count=2)
        assert any("Imagine" in q for q in questions)


class TestDiagnoseErrors:
    def test_empty_error_list_returns_encouragement(self) -> None:
        teacher = get_teacher("The Mentor")
        result = diagnose_errors(teacher, [])
        assert "No errors" in result or "excellent" in result.lower()
        assert "work" in result.lower()

    def test_single_error_returns_correction(self) -> None:
        teacher = get_teacher("The Drill Sergeant")
        result = diagnose_errors(teacher, ["Undefined variable 'count'"])
        assert "Undefined variable" in result or "count" in result
        assert "Error" in result or "error" in result.lower()

    def test_multiple_errors_acknowledges_all(self) -> None:
        teacher = get_teacher("The Guide")
        result = diagnose_errors(
            teacher,
            [
                "Variable 'x' used before assignment",
                "Missing semicolon on line 5",
            ],
        )
        assert "Variable" in result
        assert "semicolon" in result

    def test_correction_voice_is_teacher_specific(self) -> None:
        errors = ["Missing return statement"]
        mentor_result = diagnose_errors(get_teacher("The Mentor"), errors)
        drill_result = diagnose_errors(get_teacher("The Drill Sergeant"), errors)
        guide_result = diagnose_errors(get_teacher("The Guide"), errors)
        storyteller_result = diagnose_errors(get_teacher("The Storyteller"), errors)

        # All should address the error but differently
        assert mentor_result != drill_result
        assert guide_result != storyteller_result

        # Mentor: reflective
        assert "think" in mentor_result.lower() or "expect" in mentor_result.lower()
        # Drill: direct command
        assert "fix" in drill_result.lower() or "repeat" in drill_result.lower()
        # Guide: resource suggestion
        assert "resource" in guide_result.lower() or "check" in guide_result.lower()
        # Storyteller: narrative
        assert (
            "story" in storyteller_result.lower()
            or "twist" in storyteller_result.lower()
            or "chapter" in storyteller_result.lower()
        )

    def test_mentor_error_correction_is_patient(self) -> None:
        teacher = get_teacher("The Mentor")
        result = diagnose_errors(teacher, ["Division by zero"])
        # Mentor should be gentle and guiding
        assert (
            "challenge" in result.lower()
            or "learning" in result.lower()
            or "moment" in result.lower()
        )

    def test_drill_sergeant_is_confrontational(self) -> None:
        teacher = get_teacher("The Drill Sergeant")
        result = diagnose_errors(teacher, ["Wrong loop condition"])
        # Should be direct and demanding
        assert "fix" in result.lower() or "correct" in result.lower() or "right" in result.lower()


class TestGetTtsVoice:
    def test_mentor_voice(self) -> None:
        teacher = get_teacher("The Mentor")
        assert get_tts_voice(teacher) == "alloy"

    def test_drill_sergeant_voice(self) -> None:
        teacher = get_teacher("The Drill Sergeant")
        assert get_tts_voice(teacher) == "shimmer"

    def test_guide_voice(self) -> None:
        teacher = get_teacher("The Guide")
        assert get_tts_voice(teacher) == "nova"

    def test_storyteller_voice(self) -> None:
        teacher = get_teacher("The Storyteller")
        assert get_tts_voice(teacher) == "fable"

    def test_unknown_voice_defaults_to_alloy(self) -> None:
        # Create a profile with an unknown voice
        unknown = TeacherProfile(
            name="Test",
            voice="nonexistent_voice",
            teaching_style="direct",
            greeting="Hi",
            correction_pattern="fix it",
            motivation_style="push",
            explanation_depth="brief",
            patience_level="low",
            preferred_question_type="direct",
        )
        assert get_tts_voice(unknown) == "alloy"


class TestLearnerState:
    def test_default_values(self) -> None:
        state = LearnerState()
        assert state.current_topic == ""
        assert state.errors == []
        assert state.attempts == 0
        assert state.confidence == 0.5
        assert state.pace == "normal"
        assert state.preferred_teacher is None

    def test_custom_values(self) -> None:
        state = LearnerState(
            current_topic="recursion",
            errors=["No base case"],
            attempts=10,
            confidence=0.7,
            pace="slow",
            preferred_teacher="The Mentor",
        )
        assert state.current_topic == "recursion"
        assert state.errors == ["No base case"]
        assert state.attempts == 10
        assert state.confidence == 0.7
        assert state.pace == "slow"
        assert state.preferred_teacher == "The Mentor"

    def test_errors_is_mutable_list(self) -> None:
        state = LearnerState()
        state.errors.append("New error")
        assert len(state.errors) == 1
        assert state.errors[0] == "New error"


class TestLessonContent:
    def test_fields_are_accessible(self) -> None:
        content = LessonContent(
            teacher_name="Test Teacher",
            topic="test",
            greeting="Hello",
            explanation="Explanation here",
            example="Example here",
            questions=["Q1", "Q2"],
            practice_exercises=["E1", "E2"],
            encouragement="Keep going",
            tts_voice="alloy",
        )
        assert content.teacher_name == "Test Teacher"
        assert content.topic == "test"
        assert content.greeting == "Hello"
        assert content.explanation == "Explanation here"
        assert content.example == "Example here"
        assert content.questions == ["Q1", "Q2"]
        assert content.practice_exercises == ["E1", "E2"]
        assert content.encouragement == "Keep going"
        assert content.tts_voice == "alloy"

    def test_questions_and_exercises_are_lists(self) -> None:
        content = LessonContent(
            teacher_name="T",
            topic="X",
            greeting="G",
            explanation="E",
            example="Ex",
            questions=[],
            practice_exercises=[],
            encouragement="C",
            tts_voice="alloy",
        )
        assert isinstance(content.questions, list)
        assert isinstance(content.practice_exercises, list)
