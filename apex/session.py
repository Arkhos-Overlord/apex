"""The learning session: everything the CLI and dashboard need, in one place.

The engine modules are each independently testable but none of them knows
about the others -- ``content.py`` cannot grade code, ``code_exec`` knows
nothing about mastery, ``store`` knows nothing about either. This module is
the seam: it loads the library, opens the store, applies Bayesian
Knowledge Tracing to real graded attempts, and grows the knowledge web as
the learner advances.

Keeping this out of ``cli/`` is deliberate. The CLI should be a thin
rendering layer so the interesting behaviour is testable without a
terminal.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from apex.content import ContentLibrary, CourseDef, Exercise
from apex.core.adaptive import AdaptiveDifficulty
from apex.core.bkt import DEFAULT, MASTERED, apply_attempt
from apex.core.learner import LearnerState
from apex.engine.code_exec import grade_code
from apex.engine.grading import grade_static
from apex.graph import Relation
from apex.store import LEARNING_STATES, Store

DEFAULT_LEARNER = "default"

#: Priors seeded when a learner *declares* intent on a concept they have
#: never attempted. Declaring "I want to learn this" is evidence — weaker
#: than passing a test, stronger than silence — so it moves the BKT prior
#: a little above :data:`~apex.core.bkt.DEFAULT.p_init`, and committing to
#: actively learning it moves it further. The engine's own updates then
#: take over from whatever evidence arrives.
INTENT_PRIORS: dict[str, float] = {
    "wantToLearn": 0.30,
    "learning": 0.40,
    # ``learned`` is honoured, not seeded: the learner asserts it, and the
    # CLI/dashboard command records it — but a claimed mastery never
    # becomes exercise-eligible mastery. Gating still requires the real
    # BKT posterior to cross the threshold.
}
#: Concepts actively being learned get first pick in selection — the flag
#: is a sort key, not a bonus (see :meth:`LearningSession.next_exercise`).


def default_content_root() -> Path:
    """Locate the ``content/`` directory.

    Checked in order: ``APEX_CONTENT_DIR``, then a walk up from this file
    looking for ``content/skills.yaml``.  The walk matters because the
    package sits inside a larger repository rather than being installed
    alongside its data, and hardcoding one layout would break the other.
    """
    override = os.environ.get("APEX_CONTENT_DIR")
    if override:
        return Path(override)

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "content"
        if (candidate / "skills.yaml").is_file():
            return candidate

    raise FileNotFoundError(
        "Could not find the content directory. Set APEX_CONTENT_DIR to the "
        "folder holding skills.yaml and exercises/."
    )


def default_learner() -> str:
    """Which learner profile to use when none is given.

    ``APEX_LEARNER`` overrides the default, matching what the CLI does, so
    a script and ``apex progress`` cannot silently disagree about whose
    progress they are reading.
    """
    return os.environ.get("APEX_LEARNER") or DEFAULT_LEARNER


def default_db_path() -> str:
    """Default location of the learner database.

    ``APEX_DB_PATH`` wins if set.  Otherwise ``~/.apex/apex.db`` -- under
    the home directory rather than the working directory, so progress is
    found again from any directory and is not accidentally committed.
    """
    override = os.environ.get("APEX_DB_PATH")
    if override:
        return override
    return str(Path.home() / ".apex" / "apex.db")


@dataclass
class AttemptReport:
    """Outcome of submitting code for one exercise.

    Attributes:
        exercise: The exercise that was attempted.
        passed: Whether every test case passed.
        passed_count: Number of test cases that passed.
        total: Total number of test cases.
        score: Fraction of test cases passed, in [0, 1].
        details: Per-case results from the grader.
        duration_s: Wall-clock seconds the submission took to grade.
        mastery_before: Skill mastery probabilities before the update.
        mastery_after: Skill mastery probabilities after the update.
    """

    exercise: Exercise
    passed: bool
    passed_count: int
    total: int
    score: float
    details: list[dict[str, Any]] = field(default_factory=list)
    duration_s: float = 0.0
    mastery_before: dict[str, float] = field(default_factory=dict)
    mastery_after: dict[str, float] = field(default_factory=dict)
    promoted: list[str] = field(default_factory=list)
    """Skills whose ``learning`` intent became ``learned`` this attempt."""

    @property
    def newly_mastered(self) -> list[str]:
        """Skills that crossed the mastery threshold on this attempt."""
        return [
            skill
            for skill, after in self.mastery_after.items()
            if after >= MASTERED and self.mastery_before.get(skill, 0.0) < MASTERED
        ]

    @property
    def failing_cases(self) -> list[dict[str, Any]]:
        """Only the cases that did not pass, for a readable failure report."""
        return [d for d in self.details if not d["passed"]]


@dataclass
class CourseProgress:
    """A learner's standing in one course.

    Attributes:
        course: The course definition.
        solved: Exercises passed at least once.
        total: Exercises the course contains.
        mastery: Average mastery across the course's skills, in [0, 1].
        complete: Whether every exercise has been passed.
    """

    course: CourseDef
    solved: int
    total: int
    mastery: float
    complete: bool

    @property
    def level(self) -> str:
        """A short label for how far along the learner is."""
        if self.total == 0:
            return "No exercises"
        if self.complete:
            return "Complete"
        if self.mastery >= 0.7:
            return "Advanced"
        if self.mastery >= 0.35:
            return "Intermediate"
        if self.solved:
            return "Beginner"
        return "Not started"


@dataclass
class FrontierProposal:
    """A suggested next node, with the reason it is being suggested.

    Attributes:
        concept_id: The node being proposed.
        name: Its display name.
        summary: Its one-line description.
        kind: ``"skill"`` (has exercises) or ``"concept"`` (reading only).
        reason: Why the app thinks this is a good next step.
        has_exercises: Whether there is anything to actually attempt.
        neighbours: Adjacent concepts, so the learner can see the context
            the proposal came from.
    """

    concept_id: str
    name: str
    summary: str
    kind: str
    reason: str
    has_exercises: bool
    neighbours: list[str] = field(default_factory=list)


class LearningSession:
    """A learner's progress through the knowledge web, with grading built in.

    Defaults are resolved from the environment before falling back, so a
    script and the CLI agree on which database and which learner they are
    talking about: ``APEX_LEARNER``, ``APEX_DB_PATH`` and
    ``APEX_CONTENT_DIR``.

    Parameters:
        learner: Identifier used to key the store.  ``None`` means
            :func:`default_learner`.
        library: The content library to draw from.  Loaded from
            :func:`default_content_root` when omitted.
        store: Where progress is persisted.  ``None`` means a
            :class:`~apex.store.Store` at :func:`default_db_path`.
    """

    def __init__(
        self,
        learner: str | None = None,
        library: ContentLibrary | None = None,
        store: Store | None = None,
    ) -> None:
        self.learner = learner if learner is not None else default_learner()
        self.library = library if library is not None else ContentLibrary(default_content_root())
        self.store = store if store is not None else Store(default_db_path())
        self.adaptive = AdaptiveDifficulty()

    @property
    def graph(self) -> Any:
        """The knowledge web."""
        return self.library.graph

    # ── mastery ──────────────────────────────────────────────────────────

    def mastery(self) -> dict[str, float]:
        """Every known concept's mastery probability, in [0, 1].

        Concepts with no record are included at the BKT prior, so callers
        get a complete picture rather than having to guess which exist.
        """
        """Every known concept's mastery probability, in [0, 1].

        Concepts with no record are included at the BKT prior, so callers
        get a complete picture rather than having to guess which exist.
        """
        stored = self.store.get_mastery(self.learner)
        return {cid: stored.get(cid, DEFAULT.p_init) for cid in self.library.skills}

    def mastered_ids(self) -> list[str]:
        """Concepts whose mastery has cleared the threshold."""
        return self.library.mastered_ids(self.mastery())

    def next_skill(self) -> str | None:
        """The next skill worth practising, or ``None`` if there is none."""
        return self.library.next_skill(self.mastery())

    def solved_ids(self) -> set[str]:
        """Exercise ids this learner has passed at least once."""
        return {row["exercise"] for row in self.store.solved(self.learner)}

    # ── learning intent ──────────────────────────────────────────────

    def set_learning_state(self, concept_id: str, state: str) -> dict[str, Any]:
        """Declare what the learner wants to learn / is learning / has learned.

        This is the learner steering the engine, not the engine steering
        the learner — the learn-anything intent model, wired into mastery
        tracing. Three things happen:

        1. The declaration is persisted.
        2. For an unattempted concept, the declaration seeds the BKT
           prior (:data:`INTENT_PRIORS`) — declaring interest is weak
           evidence of knowledge, but it is evidence.
        3. Promotions to ``learning`` (and ``learned``) bump the mastery
           of *neighbouring* concepts slightly, because intent on a node
           implies willingness to reach its prerequisites.

        Moving to ``learned`` does **not** fabricate mastery: gating keeps
        requiring the real BKT posterior to cross the threshold.

        Args:
            concept_id: Concept to set the state for. Must exist.
            state: One of :data:`~apex.store.LEARNING_STATES`.

        Returns:
            ``{"concept", "state", "mastery"}`` after the update.

        Raises:
            KeyError: If the concept is not in the knowledge web.
            StoreError: On an invalid state value.
        """
        graph = self.library.graph
        if concept_id not in graph.concepts:
            raise KeyError(f"unknown concept '{concept_id}'")
        if state not in LEARNING_STATES:
            raise ValueError(f"invalid learning state '{state}'")

        mastery = self.mastery()

        def _seed(ids: set[str], prior: float) -> dict[str, float]:
            """Set unseen concepts to *prior* without a (dis)confirmation update.

            Deliberately *not* ``apply_attempt``: that models an
            observation, and a declaration is not an observation of
            ability — treating ``score=0.4`` as evidence would run the
            "incorrect" branch and drag mastery *down*. A seed just says
            "act as if this is slightly more plausible than the cold
            prior", and the learner's real attempts move it from there.
            """
            return {
                cid: max(prior, p) if cid in ids and p <= DEFAULT.p_init else p
                for cid, p in mastery.items()
            }

        if state in INTENT_PRIORS:
            mastery = _seed({concept_id}, INTENT_PRIORS[state])

        # Intent radiates one hop: adjacent concepts get a nudge, so the
        # neighbourhood of a declared interest becomes the natural next
        # frontier rather than a random corner of the web.
        if state in ("learning", "learned"):
            mastery = _seed(
                set(graph.neighbourhoods(concept_id, 1)) - {concept_id},
                INTENT_PRIORS["wantToLearn"],
            )

        self.store.set_mastery(self.learner, mastery)
        self.store.set_learning_state(self.learner, concept_id, state)
        return {"concept": concept_id, "state": state, "mastery": round(mastery.get(concept_id, DEFAULT.p_init), 4)}

    def learning_states(self) -> dict[str, str]:
        """Declared intents: concept id -> state, excluding archived."""
        return self.store.learning_states(self.learner)

    def intent_board(self) -> dict[str, list[dict[str, Any]]]:
        """The three intent buckets with mastery attached, for CLI/dashboard.

        ``learned`` is split into the *declared* set and the *earned* set
        (BKT posterior over the threshold) — the gap between claiming and
        proving is the whole point of tracking mastery at all.
        """
        states = self.learning_states()
        mastery = self.mastery()
        board: dict[str, list[dict[str, Any]]] = {
            "wantToLearn": [],
            "learning": [],
            "learned": [],
        }
        for cid, state in states.items():
            node = self.library.graph.concepts.get(cid)
            if node is None:
                continue
            p = mastery.get(cid, DEFAULT.p_init)
            if state in board:
                board[state].append(
                    {
                        "id": cid,
                        "name": node.name,
                        "kind": node.kind,
                        "mastery": round(p, 4),
                        "earned": p >= MASTERED,
                        "has_exercises": bool(self.library.exercises_for_skill(cid)),
                    }
                )
        for bucket in board.values():
            bucket.sort(key=lambda item: -item["mastery"])
        return board

    def archived_ids(self) -> set[str]:
        """Concepts the learner has parked; excluded from proposals/pool."""
        return self.store.archived_concepts(self.learner)

    # ── the web ──────────────────────────────────────────────────────────

    def graph_payload(self) -> dict[str, Any]:
        """The whole web, annotated with this learner's progress.

        This is what the dashboard renders.  Every node carries the
        learner's mastery and whether it is currently reachable, and every
        edge carries its relation type so the UI can draw them
        differently.
        """
        mastery = self.mastery()
        mastered = set(self.mastered_ids())
        frontier = set(self.library.frontier(mastery))
        graph = self.library.graph
        verdicts = self.store.edge_verdicts(self.learner)
        states = self.learning_states()

        nodes: list[dict[str, Any]] = []
        for concept in graph.concepts.values():
            nodes.append(
                {
                    "id": concept.id,
                    "name": concept.name,
                    "kind": concept.kind,
                    "summary": concept.summary,
                    "mastery": round(mastery.get(concept.id, DEFAULT.p_init), 4),
                    "mastered": concept.id in mastered,
                    "unlocked": concept.id in frontier,
                    "has_exercises": bool(self.library.exercises_for_skill(concept.id)),
                    "intent": states.get(concept.id),
                }
            )

        edges: list[dict[str, Any]] = []
        for edge in graph.edges.values():
            edges.append(
                {
                    "source": edge.source,
                    "target": edge.target,
                    "relation": edge.relation.value,
                    "confirmed": verdicts.get((edge.source, edge.target, edge.relation.value)),
                }
            )

        return {
            "learner": self.learner,
            "nodes": nodes,
            "edges": edges,
            "stats": self.stats(),
        }

    def proposals(self, limit: int = 5) -> list[FrontierProposal]:
        """Suggest what to learn next, with reasons.

        Two kinds of suggestion, because they answer different questions:

        * **frontier** -- unlocked nodes with exercises. These are what the
          learner can actually attempt now.
        * **adjacent** -- unmastered nodes one non-blocking hop from
          something they have mastered. These are the "never ending" part:
          the web keeps offering somewhere to go even once every exercise
          in the curriculum is done, and none of it is invented, it is all
          real curated content the learner has not reached yet.
        """
        mastery = self.mastery()
        mastered = set(self.mastered_ids())
        out: list[FrontierProposal] = []
        seen: set[str] = set()

        for cid in self.library.frontier(mastery):
            if len(out) >= limit:
                break
            node = self.library.skills.get(cid)
            if node is None:
                continue
            has_ex = bool(self.library.exercises_for_skill(cid))
            out.append(
                FrontierProposal(
                    concept_id=cid,
                    name=node.name,
                    summary=node.summary,
                    kind=node.kind,
                    reason=(
                        "unlocked, and you can practise it now"
                        if has_ex
                        else "unlocked, and worth reading first"
                    ),
                    has_exercises=has_ex,
                    neighbours=self.library.graph.neighbourhoods(cid, 1)[:5],
                )
            )
            seen.add(cid)

        # Adjacent-but-not-yet-unlocked: the long tail of the web.
        for anchor in sorted(mastered):
            for cid in self.library.graph.neighbourhoods(anchor, 1):
                if cid in seen or cid in mastered:
                    continue
                node = self.library.skills.get(cid)
                if node is None:
                    continue
                if len(out) >= limit + 4:
                    break
                out.append(
                    FrontierProposal(
                        concept_id=cid,
                        name=node.name,
                        summary=node.summary,
                        kind=node.kind,
                        reason=f"connects to {anchor}, which you have mastered",
                        has_exercises=bool(self.library.exercises_for_skill(cid)),
                        neighbours=self.library.graph.neighbourhoods(cid, 1)[:5],
                    )
                )
                seen.add(cid)
        return out

    def confirm_edge(
        self,
        source: str,
        target: str,
        relation: Relation | str,
        accepted: bool,
    ) -> None:
        """Record the learner's verdict on a relation between two concepts.

        Rejecting a ``prereq`` edge is a claim that this learner does not
        need that ordering, and the store keeps it so the edge stops being
        proposed.

        Raises:
            GraphError: If the edge does not exist in the graph.
        """
        rel = relation if isinstance(relation, Relation) else Relation(str(relation))
        self.library.graph.set_confirmed(source, target, rel, accepted)
        self.store.set_edge_verdict(self.learner, source, target, rel.value, accepted)

    def rejected_edges(self) -> set[tuple[str, str, str]]:
        """Edges this learner has refused, for suppressing re-proposals."""
        return self.store.rejected_relations(self.learner)

    # ── exercise selection ───────────────────────────────────────────────

    def next_exercise(
        self,
        course_id: str | None = None,
        exclude: set[str] | None = None,
    ) -> Exercise | None:
        """Choose the next exercise to attempt.

        Candidates are restricted to *gating* prerequisites being met, so a
        learner is never handed recursion before loops.  Among those, the
        exercise with the weakest minimum skill mastery wins; already-solved
        exercises are only offered when nothing unsolved is available, so
        revisiting weak material stays possible.

        Args:
            course_id: Restrict to one course when given.
            exclude: Exercise ids to skip.  The practice loop passes the ids
                it has already served this run, because a learner who has
                just been handed py-hello should not be handed py-hello
                again while they are still building mastery on it.

        Returns:
            An :class:`~apex.content.Exercise`, or ``None`` when there is
            nothing left to attempt.
        """
        mastery = self.mastery()
        solved = self.solved_ids()
        skip = exclude or set()
        parked = self.archived_ids()
        learning = {
            cid for cid, s in self.learning_states().items() if s == "learning"
        }
        pool = (
            self.library.course_exercises(course_id)
            if course_id
            else list(self.library.exercises.values())
        )
        if not pool:
            return None

        # "learning" intent outranks the raw mastery scan: an exercise for a
        # skill the learner declared they are learning beats an equally weak
        # skill they never mentioned, so the flag is the *primary* sort key
        # (0 beats 1), not a sub-1.0 bonus that an alphabetical id tiebreak
        # can override. Archived skills are dropped entirely — parking a
        # topic must actually park it.
        def weakest(ex: Exercise) -> float:
            return min(mastery.get(skill, DEFAULT.p_init) for skill in ex.skills)

        def priority(ex: Exercise) -> tuple[int, float, int, str]:
            not_learning = 0 if learning & set(ex.skills) else 1
            return (not_learning, weakest(ex), ex.difficulty, ex.id)

        pool = [ex for ex in pool if not (parked & set(ex.skills))]

        # Every skill the exercise assesses must be unlocked, not just the
        # first one. Checking only skills[0] served py-count-vowels -- which
        # drills strings *and* loops -- to a learner who could not yet write
        # a loop, which is the exact failure the prerequisite graph exists
        # to prevent.
        eligible = [
            ex
            for ex in pool
            if ex.skills and all(self.library.is_unlocked(s, mastery) for s in ex.skills)
        ]

        if not eligible:
            # Nothing is unlocked (e.g. a brand-new learner on a fully gated
            # course): fall back to the weakest exercise in the pool so the
            # learner is still shown *something* actionable. Honour the
            # caller's exclude set so a practice loop never sees repeats.
            fresh = [ex for ex in pool if ex.id not in skip]
            if not fresh:
                return None
            return min(fresh, key=priority)

        unseen = [ex for ex in eligible if ex.id not in solved and ex.id not in skip]
        if unseen:
            return min(unseen, key=priority)
        unserved = [ex for ex in eligible if ex.id not in skip]
        if unserved:
            return min(unserved, key=priority)
        # Everything eligible has been served this run: stop rather than
        # repeat, which is what the exclude contract promises.
        return None

    def exercises_for(self, course_id: str) -> list[Exercise]:
        """Every exercise in a course, in course order."""
        return self.library.course_exercises(course_id)

    # ── grading ──────────────────────────────────────────────────────────

    def submit(self, source: str, exercise: Exercise) -> AttemptReport:
        """Grade *source* against *exercise* and record the attempt.

        Dispatch is on the exercise kind: ``code`` runs against every test
        case (hidden ones included) in the sandbox for the exercise's
        language; ``mcq``/``recall``/``numeric`` are graded statically
        against the answer key with no sandbox at all.  Mastery is updated
        for every skill the exercise assesses either way, so a Spanish
        vocabulary quiz moves the same BKT machinery as a Python exercise.

        Args:
            source: The learner's code, or their raw answer for static kinds.
            exercise: The exercise being attempted.

        Returns:
            An :class:`AttemptReport` describing the result.
        """
        before = self.mastery()
        start = time.perf_counter()
        if exercise.kind == "code":
            grade = grade_code(source, exercise.grader_cases(), language=exercise.language)
        else:
            grade = grade_static(exercise, source)
        duration = time.perf_counter() - start

        score = float(grade["score"])
        passed = bool(grade["total"] > 0 and grade["passed"] == grade["total"])

        after = apply_attempt(dict(before), set(exercise.skills), score, DEFAULT)

        self.store.set_mastery(self.learner, after)
        self.store.add_attempt(
            learner=self.learner,
            exercise=exercise.id,
            passed=passed,
            score=score * 100.0,
            duration_ms=int(duration * 1000),
        )
        # A fresh LearnerState each time: seeding Elo from the already
        # BKT-updated mastery would double-count the same evidence.
        for skill in exercise.skills:
            self.adaptive.update_model(LearnerState(), skill, score)

        # Proof completes intent: a skill declared ``learning`` whose BKT
        # posterior just crossed the threshold is now ``learned``. The
        # learner said they were learning it; the engine records that the
        # evidence arrived. Nothing here fabricates mastery — the flag
        # follows the posterior, never leads it.
        promoted = [
            skill
            for skill in exercise.skills
            if after.get(skill, 0.0) >= MASTERED
            and self.learning_states().get(skill) == "learning"
        ]
        for skill in promoted:
            self.store.set_learning_state(self.learner, skill, "learned")

        return AttemptReport(
            exercise=exercise,
            passed=passed,
            passed_count=int(grade["passed"]),
            total=int(grade["total"]),
            score=score,
            details=list(grade["details"]),
            duration_s=duration,
            mastery_before=before,
            mastery_after=after,
            promoted=sorted(promoted),
        )

    # ── reporting ────────────────────────────────────────────────────────

    def course_progress(self, course_id: str) -> CourseProgress | None:
        """Summarise the learner's standing in one course.

        Returns ``None`` for an unknown course id so a stale
        ``default_course`` setting cannot crash a report.
        """
        course = self.library.courses.get(course_id)
        if course is None:
            return None

        exercises = self.library.course_exercises(course_id)
        solved = self.solved_ids()
        mastery = self.mastery()
        skills = course.skills

        average = (
            sum(mastery.get(skill, DEFAULT.p_init) for skill in skills) / len(skills)
            if skills
            else 0.0
        )
        done = sum(1 for ex in exercises if ex.id in solved)
        return CourseProgress(
            course=course,
            solved=done,
            total=len(exercises),
            mastery=average,
            complete=bool(exercises) and done == len(exercises),
        )

    def all_course_progress(self) -> list[CourseProgress]:
        """Progress for every course, in declaration order."""
        return [
            progress
            for progress in (self.course_progress(cid) for cid in self.library.courses)
            if progress is not None
        ]

    def attempts(self) -> list[dict[str, Any]]:
        """Every attempt this learner has made, oldest first."""
        return self.store.attempts(self.learner)

    def stats(self) -> dict[str, Any]:
        """Headline numbers for the dashboard."""
        attempts = self.attempts()
        passed = sum(1 for row in attempts if row["passed"])
        mastery = self.mastery()
        mastered = [cid for cid, p in mastery.items() if p >= MASTERED]
        graph_stats = self.library.graph.stats()
        return {
            "learner": self.learner,
            "attempts": len(attempts),
            "passed": passed,
            "accuracy": (passed / len(attempts)) if attempts else 0.0,
            "concepts": len(mastery),
            "mastered": len(mastered),
            "mastered_concepts": mastered,
            "courses": self.library.course_count,
            "exercises": self.library.exercise_count,
            "graph_concepts": graph_stats["concepts"],
            "graph_edges": graph_stats["edges"],
            "relations": graph_stats["edges_by_relation"],
            "frontier_size": len(self.library.frontier(mastery)),
        }
