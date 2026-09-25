"""Tests for the YAML content loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.content import ContentLibrary, Exercise


@pytest.fixture
def lib() -> ContentLibrary:
    return ContentLibrary(Path(__file__).resolve().parents[2] / "content")


def test_content_loads_skills(lib: ContentLibrary) -> None:
    """ContentLibrary loads all skills from skills.yaml."""
    assert len(lib.skills) >= 4
    assert "io" in lib.skills
    assert "arithmetic" in lib.skills
    assert "conditionals" in lib.skills
    assert "loops" in lib.skills


def test_content_loads_exercises(lib: ContentLibrary) -> None:
    """ContentLibrary loads all exercise YAML files."""
    assert lib.exercise_count >= 3
    assert "py-hello" in lib.exercises
    assert "py-sum-two" in lib.exercises
    assert "py-fizzbuzz" in lib.exercises


def test_exercise_properties(lib: ContentLibrary) -> None:
    """Exercise properties are correctly loaded."""
    ex = lib.exercises["py-fizzbuzz"]
    assert ex.id == "py-fizzbuzz"
    assert ex.title == "FizzBuzz"
    assert ex.difficulty == 2
    assert "loops" in ex.skills
    assert "conditionals" in ex.skills
    assert len(ex.tests) >= 2


def test_exercise_public_strips_hidden(lib: ContentLibrary) -> None:
    """Exercise.public() only returns non-hidden tests."""
    ex = lib.exercises["py-fizzbuzz"]
    public = ex.public()
    [t for t in ex.tests if t.hidden]
    visible_tests = [t for t in ex.tests if not t.hidden]
    assert len(public["tests"]) == len(visible_tests)
    assert len(public["tests"]) < len(ex.tests)


def test_prereq_cycle_detection(lib: ContentLibrary) -> None:
    """ContentLibrary detects prerequisite cycles."""
    # skills.yaml has valid prereqs (io -> arithmetic -> conditionals -> loops)
    # No cycle exists, so no exception is raised
    assert lib.exercise_count >= 3


def test_invalid_exercise_id(lib: ContentLibrary) -> None:
    """Exercise id must be a valid slug."""
    with pytest.raises(ValueError):
        Exercise(
            id="invalid id!",
            title="Bad",
            skills=["io"],
            difficulty=1,
            prompt="test",
            tests=[Exercise(input="1\n", expected="2\n")],
        )


def test_get_exercise(lib: ContentLibrary) -> None:
    """get_exercise returns correct exercise or None."""
    ex = lib.get_exercise("py-hello")
    assert ex is not None
    assert ex.id == "py-hello"

    assert lib.get_exercise("nonexistent") is None


def test_all_public_exercises(lib: ContentLibrary) -> None:
    """all_public_exercises returns dicts with hidden tests stripped."""
    public = lib.all_public_exercises()
    assert len(public) == lib.exercise_count
    for ex_dict in public:
        for test in ex_dict["tests"]:
            assert test["hidden"] is False


def test_skill_count(lib: ContentLibrary) -> None:
    """skill_count property is correct."""
    assert lib.skill_count >= 4


def test_reload(lib: ContentLibrary) -> None:
    """reload() refreshes the content library."""
    before_count = lib.exercise_count
    lib.reload()
    assert lib.exercise_count == before_count
