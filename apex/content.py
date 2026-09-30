"""YAML content loader for APEX exercises, skills, and courses."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from apex.core.bkt import MASTERED as MASTERED_THRESHOLD
from apex.graph import Concept, KnowledgeGraph, Relation


class TestItem(BaseModel):
    """A single test case for an exercise."""

    input: str = ""
    expected: str
    hidden: bool = True


class Exercise(BaseModel):
    """A coding exercise with prompt, starter code, and tests.

    Attributes:
        solution: Reference implementation.  Never included in
            :meth:`public` -- it is only revealed on request after an
            unsuccessful attempt.
        hints: Progressive hints, ordered easiest-first.
    """

    id: str
    title: str
    skills: list[str] = Field(min_length=1)
    difficulty: int = Field(ge=1, le=5)
    prompt: str
    starter: str = ""
    solution: str = ""
    hints: list[str] = Field(default_factory=list)
    tests: list[TestItem] = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("exercise id must be a slug")
        return v

    def public(self) -> dict[str, Any]:
        """Everything a learner may see.

        Strips two things: the hidden test expectations, and the reference
        solution.  Hints are kept -- they are scaffolding, not the answer --
        but the first hint only helps if the tests are visible.
        """
        d = self.model_dump()
        d["tests"] = [t.model_dump() for t in self.tests if not t.hidden]
        d["solution"] = ""
        return d

    def grader_cases(self) -> list[dict[str, str]]:
        """Render the tests in the shape :func:`apex.engine.code_exec.grade_code` wants.

        The content schema and the grader schema disagree on purpose:
        ``TestItem`` uses ``expected`` and carries a ``hidden`` flag for
        presentation, while the grader wants ``expected_output`` and a
        ``description`` to report back.  This is the single place that
        translation happens.
        """
        return [
            {
                "input": t.input,
                "expected_output": t.expected,
                "description": f"case {i + 1}" + (" (hidden)" if t.hidden else ""),
            }
            for i, t in enumerate(self.tests)
        ]



class Skill(BaseModel):
    """A node in the knowledge web, and optionally a source of exercises.

    The five relation lists are what turn a prerequisite ladder into a web.
    ``prereqs`` orders learning; the rest give the learner somewhere to go
    when they are not ready to advance -- adjacent material, easy
    confusions, the larger subject a concept belongs to.

    A node with ``kind: concept`` has no exercises and no mastery. Those
    are the frontier the curriculum grows into, which is what keeps it
    open-ended.

    Attributes:
        id: Slug, unique in the graph.
        name: Display name.
        kind: ``"skill"`` (default) or ``"concept"``.
        summary: One-line description.
        prereqs: Concepts required before this one.
        related: Adjacent concepts that illuminate this one.
        contrasts: Concepts learners commonly mix up with this one.
        part_of: Broader subjects containing this concept.
        applies_to: Contexts this concept gets used in.
    """

    id: str
    name: str
    kind: str = "skill"
    summary: str = ""
    prereqs: list[str] = []
    related: list[str] = []
    contrasts: list[str] = []
    part_of: list[str] = []
    applies_to: list[str] = []

    def to_concept(self) -> Concept:
        """Project onto the graph's node type."""
        return Concept(
            id=self.id,
            name=self.name,
            kind=self.kind,
            summary=self.summary,
            prereqs=tuple(self.prereqs),
            related=tuple(self.related),
            contrasts=tuple(self.contrasts),
            part_of=tuple(self.part_of),
            applies_to=tuple(self.applies_to),
        )


class CourseDef(BaseModel):
    """An ordered path through the skill graph.

    Distinct from :class:`apex.core.course.Course`, which models lesson
    prose.  This is the practice-facing view: a titled sequence of skills.

    Attributes:
        id: Slug used on the command line.
        title: Display name.
        description: One-line blurb.
        skills: Skill ids in the order they should be attempted.
    """

    id: str
    title: str
    description: str = ""
    skills: list[str] = Field(min_length=1)


class ContentLibrary:
    """Loads and validates skills, courses, and exercises from YAML files.

    Parameters:
        root: Directory holding ``skills.yaml``, ``courses.yaml`` and the
            ``exercises/`` folder.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.skills: dict[str, Skill] = {}
        self.courses: dict[str, CourseDef] = {}
        self.exercises: dict[str, Exercise] = {}
        self.graph = KnowledgeGraph()
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
        self._build_graph()
        self._load_courses()

    def _build_graph(self) -> None:
        """Project every skill onto a node, then add all typed edges.

        Runs after the cycle check so a malformed graph never reaches the
        traversal code, and before courses load so course validation can
        report against a graph that exists.
        """
        graph = KnowledgeGraph()
        for skill in self.skills.values():
            graph.add_concept(skill.to_concept())
        for skill in self.skills.values():
            for relation, target in skill.to_concept().edges():
                graph.add_edge(skill.id, target, relation)
        self.graph = graph

    def dangling_references(self) -> list[str]:
        """Relation targets that name a concept which does not exist.

        A missing target raises during :meth:`_build_graph`, so this exists
        for the health check to report *which* files to fix, rather than
        only that something is wrong.
        """
        known = set(self.skills)
        missing: list[str] = []
        for skill in self.skills.values():
            for _, target in skill.to_concept().edges():
                if target not in known:
                    missing.append(f"{skill.id} -> {target}")
        return sorted(missing)

    def _load_courses(self) -> None:
        """Load courses.yaml, which is optional.

        A library with skills and exercises but no courses is still usable --
        only the course-aware helpers degrade.
        """
        path = self.root / "courses.yaml"
        if not path.exists():
            self.courses = {}
            return
        raw = yaml.safe_load(path.read_text()) or {}
        self.courses = {}
        for entry in raw.get("courses", []):
            course = CourseDef(**entry)
            unknown = set(course.skills) - self.skills.keys()
            if unknown:
                raise ValueError(f"courses.yaml: {course.id} references unknown skills {unknown}")
            self.courses[course.id] = course

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

    # ── graph queries ────────────────────────────────────────────────────

    def exercises_for_skill(self, skill: str) -> list[Exercise]:
        """Every exercise that assesses *skill*, easiest first."""
        return sorted(
            (ex for ex in self.exercises.values() if skill in ex.skills),
            key=lambda ex: (ex.difficulty, ex.id),
        )

    def is_gate(self, concept_id: str) -> bool:
        """Whether mastery of *concept_id* must be earned before moving on.

        The rule is: **you only need to pass what has tests.**  A concept
        with no exercises is orientation, not a gate -- you are expected to
        read it, not to be examined on it.  Gating on such nodes would
        deadlock the graph, because mastery only ever accrues to skills,
        so nothing downstream of an unmasterable node could ever unlock.

        This is also what makes the graph grow: writing the first exercise
        for a concept promotes it from orientation to gate, and everything
        downstream of it immediately becomes reachable.
        """
        return bool(self.exercises_for_skill(concept_id))

    def gates_for(self, concept_id: str) -> list[str]:
        """The prerequisites of *concept_id* that actually block it."""
        return [p for p in self.graph.prereqs_of(concept_id) if self.is_gate(p)]

    def is_unlocked(self, skill: str, mastery: dict[str, float]) -> bool:
        """Whether *skill* is available given the learner's *mastery* map.

        A skill unlocks when every *gating* prerequisite is already
        mastered -- see :meth:`is_gate` for why not every prerequisite
        counts.  Using the learner's real map is the point: without it a
        learner can be handed a recursion exercise before they can write a
        loop.

        Args:
            skill: Skill id to test.
            mastery: Mapping of skill id to mastery in [0, 1].
        """
        if skill not in self.skills:
            return False
        mastered = [s for s, p in mastery.items() if p >= MASTERED_THRESHOLD]
        return self.graph.is_unlocked(skill, mastered, self.gates_for)

    def mastered_ids(self, mastery: dict[str, float]) -> list[str]:
        """Ids whose mastery clears the threshold."""
        return [s for s, p in mastery.items() if p >= MASTERED_THRESHOLD]

    def unlocked_skills(self, mastery: dict[str, float]) -> list[str]:
        """Skills whose gating prerequisites are all met, in declaration order."""
        return [sid for sid in self.skills if self.is_unlocked(sid, mastery)]

    def next_skill(self, mastery: dict[str, float]) -> str | None:
        """The next skill worth working on, or ``None`` when all are mastered.

        Only ever returns a node that has at least one exercise, so the
        learner is never pointed at something they cannot practise.
        """
        for sid in self.frontier(mastery):
            if self.exercises_for_skill(sid):
                return sid
        return None

    def frontier(self, mastery: dict[str, float]) -> list[str]:
        """Every unlocked concept, skills and knowledge nodes alike."""
        return self.graph.frontier(self.mastered_ids(mastery), self.gates_for)

    def health(self) -> dict[str, Any]:
        """Structural checks over the whole library.

        Returns a report the ``apex doctor`` command prints and the eval
        harness asserts against.  ``ok`` is true only when every check
        passes.
        """
        cycles = self.graph.find_cycles()
        unreachable = self.graph.unreachable()
        dangling = self.dangling_references()
        untestable = sorted(
            sid
            for sid, skill in self.skills.items()
            if skill.kind == "skill" and not self.exercises_for_skill(sid)
        )
        problems: list[str] = []
        if cycles:
            problems.append(f"prerequisite cycles: {cycles}")
        if unreachable:
            problems.append(f"unreachable concepts: {unreachable}")
        if dangling:
            problems.append(f"dangling relations: {dangling}")
        if untestable:
            problems.append(
                "declared as skills but have no exercises, so they can never be "
                f"mastered: {untestable}"
            )
        return {
            "ok": not problems,
            "problems": problems,
            "cycles": cycles,
            "unreachable": unreachable,
            "dangling": dangling,
            "untestable_skills": untestable,
            **self.graph.stats(),
        }

    def course_exercises(self, course_id: str) -> list[Exercise]:
        """Exercises belonging to a course, in course order then difficulty.

        Returns an empty list for an unknown course id rather than raising,
        so a stale ``default_course`` in the CLI config cannot crash startup.
        """
        course = self.courses.get(course_id)
        if course is None:
            return []
        ordered: list[Exercise] = []
        for skill in course.skills:
            ordered.extend(self.exercises_for_skill(skill))
        return ordered

    def course_for_skill(self, skill: str) -> str | None:
        """The id of the first course that teaches *skill*, if any."""
        for cid, course in self.courses.items():
            if skill in course.skills:
                return cid
        return None

    @property
    def exercise_count(self) -> int:
        return len(self.exercises)

    @property
    def skill_count(self) -> int:
        return len(self.skills)

    @property
    def course_count(self) -> int:
        return len(self.courses)
