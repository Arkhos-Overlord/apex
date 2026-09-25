"""YAML content loader for APEX exercises and skills."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class TestItem(BaseModel):
    """A single test case for an exercise."""

    input: str = ""
    expected: str
    hidden: bool = True


class Exercise(BaseModel):
    """A coding exercise with prompt, starter code, and tests."""

    id: str
    title: str
    skills: list[str] = Field(min_length=1)
    difficulty: int = Field(ge=1, le=5)
    prompt: str
    starter: str = ""
    tests: list[TestItem] = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("exercise id must be a slug")
        return v

    def public(self) -> dict[str, Any]:
        """Everything a learner may see — hidden test expectations stripped."""
        d = self.model_dump()
        d["tests"] = [t.model_dump() for t in self.tests if not t.hidden]
        return d


class Skill(BaseModel):
    """A skill with prerequisite skills."""

    id: str
    name: str
    prereqs: list[str] = []


class ContentLibrary:
    """Loads and validates skills and exercises from YAML files."""

    def __init__(self, root: Path):
        self.root = root
        self.skills: dict[str, Skill] = {}
        self.exercises: dict[str, Exercise] = {}
        self.reload()

    def reload(self) -> None:
        """Load all YAML files from the content directory."""
        skills_raw = yaml.safe_load((self.root / "skills.yaml").read_text()) or []
        self.skills = {s["id"]: Skill(**s) for s in skills_raw}
        self.exercises = {}
        for path in sorted((self.root / "exercises").glob("*.yaml")):
            ex = Exercise(**yaml.safe_load(path.read_text()))
            unknown = set(ex.skills) - self.skills.keys()
            if unknown:
                raise ValueError(f"{path.name}: unknown skills {unknown}")
            self.exercises[ex.id] = ex
        self._check_prereq_cycles()

    def _check_prereq_cycles(self) -> None:
        """Detect prerequisite cycles using DFS."""
        seen: set[str] = set()

        def visit(sid: str, stack: tuple[str, ...]) -> None:
            if sid in stack:
                raise ValueError(f"prerequisite cycle: {' -> '.join(stack + (sid,))}")
            if sid in seen:
                return
            seen.add(sid)
            for p in self.skills[sid].prereqs:
                visit(p, stack + (sid,))

        for sid in self.skills:
            visit(sid, ())

    def get_exercise(self, exercise_id: str) -> Exercise | None:
        return self.exercises.get(exercise_id)

    def all_public_exercises(self) -> list[dict[str, Any]]:
        return [ex.public() for ex in self.exercises.values()]

    @property
    def exercise_count(self) -> int:
        return len(self.exercises)

    @property
    def skill_count(self) -> int:
        return len(self.skills)
