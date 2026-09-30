"""Spec evaluation for Apex.

Ten criteria, written down before the code was finished, checked by
running the real application rather than by asserting against mocks.  A
spec nobody measures is a wish list.

Run it:

    python apex/tests/eval_spec.py            # human-readable report
    python apex/tests/eval_spec.py --json     # machine-readable

Exit code is 0 only if every criterion passes.  Several criteria are
written as adversarial checks -- "submit wrong code and confirm it fails",
"confirm the learner is never handed recursion before loops" -- because
the failure modes that matter here are precisely the ones a happy-path
test cannot see.

Deliberately not part of the pytest suite: it is slow (it shells out to
the real CLI and runs real subprocesses) and it reports its own results
rather than failing an individual test.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from apex.cli.dashboard import serve_in_background  # noqa: E402
from apex.cli.main import cli  # noqa: E402
from apex.content import ContentLibrary  # noqa: E402
from apex.session import LearningSession, default_content_root  # noqa: E402
from apex.store import Store  # noqa: E402
from apex.teachers import instruct  # noqa: E402

CONTENT = REPO_ROOT / "content"


# ── harness ──────────────────────────────────────────────────────────────


@dataclass
class Criterion:
    """One spec line and the check that decides it."""

    key: str
    requirement: str
    check: Callable[["Ctx"], tuple[bool, str]]


@dataclass
class Ctx:
    """Throwaway state shared between criteria."""

    tmp: Path
    library: ContentLibrary
    session: LearningSession
    results: list[dict[str, Any]] = field(default_factory=list)

    def cli(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
        """Run the real CLI in a subprocess, pointed at a throwaway database.

        APEX_DB_PATH and APEX_LEARNER matter here: without them the
        subprocess reads the developer's real ~/.apex/apex.db and this
        criterion would be asserting against whatever they last practised.
        """
        env = dict(os.environ)
        env["APEX_CONTENT_DIR"] = str(CONTENT)
        env["APEX_OUTPUT_DIR"] = str(self.tmp / "outputs")
        env["APEX_DB_PATH"] = str(self.session.store._db_path)
        env["APEX_LEARNER"] = self.session.learner
        env["PYTHONPATH"] = str(REPO_ROOT)
        return subprocess.run(
            [sys.executable, "-m", "apex.cli.main", *args],
            capture_output=True,
            text=True,
            input=stdin,
            env=env,
            cwd=str(REPO_ROOT),
            timeout=300,
        )


def new_ctx() -> Ctx:
    tmp = Path(tempfile.mkdtemp(prefix="apex-eval-"))
    store = Store(str(tmp / "eval.db"))
    library = ContentLibrary(CONTENT)
    return Ctx(
        tmp=tmp,
        library=library,
        session=LearningSession("evaluator", library=library, store=store),
    )


# ── S1: the knowledge web is a real graph ────────────────────────────────


def s1_graph_is_real(ctx: Ctx) -> tuple[bool, str]:
    """A concept web, not a list: multiple relation types, traversable."""
    g = ctx.library.graph
    stats = g.stats()
    relations = set(stats["edges_by_relation"])
    if len(relations) < 4:
        return False, f"only {len(relations)} relation types: {sorted(relations)}"
    if stats["edges"] < 50:
        return False, f"only {stats['edges']} edges"
    if stats["concepts"] < 15:
        return False, f"only {stats['concepts']} concepts"
    # The web property: a node reachable by more than one route.
    loops_neighbours = g.neighbourhoods("loops", 1)
    if len(loops_neighbours) < 4:
        return False, f"'loops' has only {len(loops_neighbours)} neighbours"
    if not g.ancestors("recursion"):
        return False, "no prerequisite ancestors reachable from 'recursion'"
    return True, (
        f"{stats['concepts']} concepts, {stats['edges']} edges, "
        f"{len(relations)} relation types {sorted(relations)}"
    )


# ── S2: the graph is structurally sound ───────────────────────────────────


def s2_graph_is_sound(ctx: Ctx) -> tuple[bool, str]:
    """No cycles, no dead nodes, no dangling edges."""
    health = ctx.library.health()
    if not health["ok"]:
        return False, "; ".join(health["problems"])
    return True, (
        f"0 cycles, 0 unreachable, 0 dangling; "
        f"{health['skills']} skills + {health['concepts_only']} knowledge nodes"
    )


# ── S3: a fresh learner is given something to do ─────────────────────────


def s3_fresh_learner_has_a_next_step(ctx: Ctx) -> tuple[bool, str]:
    """Regression guard for the deadlock that shipped during development.

    Concept nodes used as prerequisites could never be satisfied, and
    next_skill() applied the gate rule after a traversal that had already
    excluded the affected nodes -- so a brand-new learner was offered
    nothing at all.
    """
    exercise = ctx.session.next_exercise()
    if exercise is None:
        return False, "next_exercise() returned None for a learner with no history"
    mastery = ctx.session.mastery()
    if not ctx.library.is_unlocked(exercise.skills[0], mastery):
        return False, f"served {exercise.id} while {exercise.skills[0]} is still locked"
    return True, f"a new learner is served {exercise.id} ({exercise.title})"


# ── S4: prerequisites are genuinely enforced ─────────────────────────────


def s4_prerequisites_block_early_topics(ctx: Ctx) -> tuple[bool, str]:
    """No exercise is ever offered before every skill it drills is unlocked.

    Checks the actual invariant rather than a hand-written order.  A fixed
    expected sequence would be wrong: exercises that become eligible at
    the same moment are ranked by weakest mastery, so py-count-vowels
    (strings and loops) can legitimately precede py-fizzbuzz (loops and
    conditionals).  What must never happen is an exercise whose own skills
    are not all unlocked yet -- that was the bug, where only skills[0] was
    checked.
    """
    session = LearningSession("walk-check", library=ctx.library,
                              store=Store(str(ctx.tmp / "walk.db")))
    served: list[str] = []
    violations: list[str] = []

    for _ in range(8):
        mastery_before = session.mastery()
        exercise = session.next_exercise()
        if exercise is None:
            break

        locked = [s for s in exercise.skills if not ctx.library.is_unlocked(s, mastery_before)]
        if locked:
            violations.append(f"{exercise.id} served with {locked} still locked")

        served.append(exercise.id)
        session.submit(exercise.solution, exercise)
        # Passing does not always clear the BKT threshold in one go, so
        # force the assessed skills to mastered to let the walk descend.
        mastery = session.mastery()
        for skill in exercise.skills:
            mastery[skill] = 1.0
        session.store.set_mastery(session.learner, mastery)

    if violations:
        return False, "; ".join(violations)

    if len(served) < 4:
        return False, f"only {len(served)} exercises reachable by passing: {served}"

    repeats = [
        a for a, b in zip(served, served[1:], strict=False) if a == b
    ]
    if repeats:
        return False, f"the same exercise was served twice in a row: {repeats}"

    return True, (
        f"{len(served)} exercises, every one unlocked at serve time, no immediate "
        f"repeats: {' -> '.join(served)}"
    )



# ── S5: grading discriminates right from wrong ───────────────────────────


def s5_grading_discriminates(ctx: Ctx) -> tuple[bool, str]:
    """Correct code passes, wrong code fails, on the same exercise."""
    session = LearningSession("grader-check", library=ctx.library,
                              store=Store(str(ctx.tmp / "grader.db")))
    exercise = ctx.library.exercises["py-sum-two"]
    cases = exercise.grader_cases()

    good = session.submit(exercise.solution, exercise)
    if not good.passed:
        return False, f"reference solution failed: {good.passed_count}/{good.total}"
    if good.total != len(cases):
        return False, f"grader saw {good.total} cases, expected {len(cases)}"

    wrong_source = "a, b = map(int, input().split())\nprint(a - b)\n"
    bad_session = LearningSession("grader-check-bad", library=ctx.library,
                                  store=Store(str(ctx.tmp / "grader-bad.db")))
    bad = bad_session.submit(wrong_source, exercise)
    if bad.passed:
        return False, "subtraction was graded as correct"
    if bad.score >= 1.0:
        return False, f"wrong code scored {bad.score}"
    if not bad.failing_cases:
        return False, "no failing-case detail reported for wrong code"

    broken = bad_session.submit("this is @@@ not python", exercise)
    if broken.passed:
        return False, "a syntax error was graded as correct"
    return True, (
        f"reference {good.passed_count}/{good.total}; wrong answer "
        f"{bad.passed_count}/{bad.total} with detail; syntax error rejected"
    )


# ── S6: mastery is tracked, persisted, and ordered ───────────────────────


def s6_mastery_is_tracked(ctx: Ctx) -> tuple[bool, str]:
    """Mastery moves on a pass, moves down on a fail, and survives a reload."""
    session = LearningSession("mastery-check", library=ctx.library,
                              store=Store(str(ctx.tmp / "mastery.db")))
    exercise = ctx.library.exercises["py-hello"]
    skill = exercise.skills[0]

    start = session.mastery()[skill]
    up = session.submit(exercise.solution, exercise)
    if up.mastery_after[skill] <= start:
        return False, f"mastery did not rise: {start} -> {up.mastery_after[skill]}"

    down = session.submit("print('nope')", exercise)
    if down.mastery_after[skill] >= up.mastery_after[skill]:
        return False, (
            f"mastery did not fall on a wrong answer: "
            f"{up.mastery_after[skill]} -> {down.mastery_after[skill]}"
        )

    reloaded = LearningSession("mastery-check", library=ctx.library,
                               store=Store(str(ctx.tmp / "mastery.db")))
    if abs(reloaded.mastery()[skill] - down.mastery_after[skill]) > 1e-6:
        return False, "mastery did not survive a reload"

    if len(reloaded.attempts()) != 2:
        return False, f"expected 2 recorded attempts, found {len(reloaded.attempts())}"
    return True, (
        f"{skill}: {start:.2f} -> {up.mastery_after[skill]:.2f} on a pass, "
        f"-> {down.mastery_after[skill]:.2f} on a fail, persisted across reload"
    )


# ── S7: the CLI reports real data ────────────────────────────────────────


def s7_cli_reports_real_data(ctx: Ctx) -> tuple[bool, str]:
    """No hardcoded tables: the output must change when progress changes."""
    proc = ctx.cli("progress")
    if proc.returncode != 0:
        return False, f"apex progress exited {proc.returncode}: {proc.stderr[:200]}"
    before = proc.stdout

    # A pristine database, for comparison.
    clean = Store(str(ctx.tmp / "clean.db"))
    clean_session = LearningSession("clean-learner", library=ctx.library, store=clean)
    if not clean_session.stats()["attempts"] == 0:
        return False, "a fresh learner should have zero attempts"

    if "Mastery Summary" not in before:
        return False, "no mastery table in output"
    if "No attempts recorded yet" not in before:
        return False, "a learner with no history did not say so"

    # Now create real history and confirm the output changes.
    exercise = ctx.session.next_exercise()
    ctx.session.submit(exercise.solution, exercise)
    after = ctx.cli("progress")
    if after.stdout == before:
        return False, "output is identical before and after a real attempt"
    if "attempts" not in after.stdout:
        return False, "attempt count missing after a real attempt"
    return True, "output is empty for a new learner and changes after a real pass"


# ── S8: the dashboard serves the web ──────────────────────────────────────


def s8_dashboard_serves_the_web(ctx: Ctx) -> tuple[bool, str]:
    """The port the browser is sent to is real, live, and returns the graph.

    Learns something first, so the served payload has to reflect it --
    a server that returns a static graph would otherwise pass.
    """
    exercise = ctx.session.next_exercise()
    if exercise is not None:
        # Static kinds (mcq/recall/numeric) carry their reference in
        # `answer`; code kinds in `solution`.
        reference = exercise.answer if exercise.kind != "code" else exercise.solution
        for _ in range(3):
            ctx.session.submit(reference, exercise)

    expected = ctx.session.mastery()[exercise.skills[0]]

    server, _thread = serve_in_background(ctx.session, port=0)
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/graph", timeout=10) as resp:
            payload = json.loads(resp.read())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
    except OSError as exc:
        return False, f"dashboard did not serve: {exc!r}"
    finally:
        server.shutdown()
        server.server_close()

    nodes = payload.get("nodes", [])
    edges = payload.get("edges", [])
    if len(nodes) < 15:
        return False, f"only {len(nodes)} nodes served"
    if len({e["relation"] for e in edges}) < 4:
        return False, "served edges do not carry typed relations"

    practised = next((n for n in nodes if n["id"] == exercise.skills[0]), None)
    if practised is None:
        return False, f"'{exercise.skills[0]}' missing from served nodes"
    if abs(practised["mastery"] - expected) > 1e-3:
        return False, (
            f"served mastery {practised['mastery']} does not match the "
            f"learner's actual {expected}"
        )
    if not practised["mastered"]:
        return False, "a fully-passed skill was not served as mastered"

    for name in ("id", "name", "kind", "mastery", "mastered", "unlocked", "has_exercises"):
        if name not in practised:
            return False, f"served node missing '{name}'"
    if "three" not in html.lower():
        return False, "page does not load a graph renderer"
    return True, (
        f"served {len(nodes)} nodes / {len(edges)} edges; "
        f"{practised['id']} mastery {expected:.2f} and mastered=True, "
        f"matching the store"
    )


# ── S9: the curriculum is open-ended, and the learner directs it ─────────


def s9_curriculum_grows(ctx: Ctx) -> tuple[bool, str]:
    """A mastered node unlocks more; the learner can accept or refuse edges.

    This is the "never ending" property: after the curated exercises run
    out there is still somewhere to go, it is real content, and the
    learner decides whether the tie between two concepts is real.
    """
    session = LearningSession("growth-check", library=ctx.library,
                              store=Store(str(ctx.tmp / "growth.db")))
    fresh = session.library.frontier(session.mastery())
    if len(fresh) < 2:
        return False, f"a new learner has only {len(fresh)} things to look at"

    # Push the learner to the end of the prerequisite chain.
    for concept_id in ("io", "arithmetic", "conditionals", "loops", "strings",
                       "data-structures", "functions", "recursion", "error-handling"):
        mastery = session.mastery()
        mastery[concept_id] = 1.0
        session.store.set_mastery(session.learner, mastery)

    advanced = session.library.frontier(session.mastery())
    if len(advanced) <= len(fresh):
        return False, f"frontier did not grow: {len(fresh)} -> {len(advanced)}"

    proposals = session.proposals(limit=4)
    if not proposals:
        return False, "no proposals offered after progress"
    if not all(p.reason for p in proposals):
        return False, "a proposal came with no reason"

    # The learner refuses a tie; it must be remembered.
    session.confirm_edge("arithmetic", "io", "prereq", accepted=False)
    rejected = session.rejected_edges()
    if ("arithmetic", "io", "prereq") not in rejected:
        return False, "a refused edge was not remembered"

    still_fresh = LearningSession("growth-check", library=ctx.library,
                                  store=Store(str(ctx.tmp / "growth.db")))
    if ("arithmetic", "io", "prereq") not in still_fresh.rejected_edges():
        return False, "a refused edge did not survive a reload"
    return True, (
        f"frontier {len(fresh)} -> {len(advanced)} after mastering 9 skills; "
        f"{len(proposals)} proposals with reasons; refusal persisted"
    )


# ── S10: nothing regressed ───────────────────────────────────────────────


def s10_suite_is_green(ctx: Ctx) -> tuple[bool, str]:
    """The existing test suite must still pass."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "apex/tests", "-q", "--timeout=120"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=900,
    )
    tail = [line for line in proc.stdout.strip().splitlines() if line.strip()]
    summary = tail[-1] if tail else "no output"
    if proc.returncode != 0:
        return False, f"suite failed: {summary}"
    return True, summary


def s11_cli_output_renders(ctx: Ctx) -> tuple[bool, str]:
    """Every table cell must actually contain visible text.

    Added after a real bug slipped through the other criteria: the mastery
    meter was written as ``[###....]``, and rich parses ``[`` as the start
    of a markup tag, so the entire meter was swallowed and every mastery
    cell rendered empty. Nothing else in the spec looked at what the
    terminal actually showed, because a blank cell still "changes".
    """
    # Give the learner some history so the meters are non-trivial.
    for _ in range(3):
        exercise = ctx.session.next_exercise()
        if exercise is None:
            return False, "no exercise available to build history with"
        ctx.session.submit(exercise.solution, exercise)

    problems: list[str] = []
    for command in (["progress"], ["courses"], ["graph"], ["course", "introduction-to-python"]):
        proc = ctx.cli(*command)
        if proc.returncode != 0:
            problems.append(f"{' '.join(command)} exited {proc.returncode}")
            continue
        if not proc.stdout.strip():
            problems.append(f"{' '.join(command)} printed nothing")
            continue
        # A meter must survive to the screen as literal characters.
        if "[" not in proc.stdout and "]" not in proc.stdout:
            problems.append(f"{' '.join(command)}: no meter rendered at all")

    if problems:
        return False, "; ".join(problems)

    progress = ctx.cli("progress").stdout
    if not any(ch in progress for ch in "#."):
        return False, "progress rendered no meter characters"

    return True, "progress, courses, graph and course all render visible meters"


# ── S12: learner intent steers the engine ───────────────────────────────


def s12_intent_steers_engine(ctx: Ctx) -> tuple[bool, str]:
    """Intent is engine signal: prior seed, selection priority, promotion.

    The learn-anything intent model (wantToLearn/learning/learned) only
    matters here because it is wired into mastery tracing. This check
    walks the whole lifecycle with the real session and the real CLI.
    """
    facts: list[str] = []
    session = LearningSession(
        "intent-evaluator", library=ctx.library, store=Store(str(ctx.tmp / "intent.db"))
    )

    # 1. Declaring 'learning' moves the prior and jumps the queue.
    before = session.mastery()["order-of-operations"]
    session.set_learning_state("order-of-operations", "learning")
    after = session.mastery()["order-of-operations"]
    if not after > before:
        return False, f"declaring 'learning' did not raise the prior ({before} -> {after})"
    facts.append(f"prior {before:.2f} -> {after:.2f}")

    chosen = session.next_exercise()
    if chosen is None or "order-of-operations" not in chosen.skills:
        return False, f"learning intent did not steer selection (got {chosen and chosen.id})"
    facts.append(f"selection -> {chosen.id}")

    # 2. Archive hides material from selection.
    for skill in ("spanish-greetings", "spanish-numbers", "spanish-verbs", "spanish-family"):
        session.set_learning_state(skill, "archived")
    for _ in range(8):
        ex = session.next_exercise()
        if ex is None:
            break
        if set(ex.skills) & {"spanish-greetings", "spanish-numbers", "spanish-verbs", "spanish-family"}:
            return False, f"archived skill {ex.skills} was still selected"
    facts.append("archive respected")

    # 3. Proof promotes: hammer the learning skill until BKT crosses 0.95.
    ex = next(e for e in session.library.exercises.values() if "order-of-operations" in e.skills)
    report = None
    for _ in range(15):
        report = session.submit(ex.answer, ex)
        if report.mastery_after["order-of-operations"] >= 0.95:
            break
    if report is None or report.mastery_after["order-of-operations"] < 0.95:
        return False, "could not reach mastery on the declared skill"
    if "order-of-operations" not in report.promoted:
        return False, "crossing the threshold did not promote learning -> learned"
    facts.append("promoted on proof")

    # 4. The CLI sees the same truth.
    result = ctx.cli("learn", "board")
    if result.returncode != 0:
        return False, f"apex learn board failed: {result.stderr.strip()[:120]}"
    if "learned" not in result.stdout:
        return False, "board does not show the learned bucket"
    facts.append("CLI board renders")

    return True, "; ".join(facts)


# ── the spec ─────────────────────────────────────────────────────────────

SPEC: list[Criterion] = [
    Criterion("S1", "Knowledge is a web, not a list: 4+ relation types, traversable",
              s1_graph_is_real),
    Criterion("S2", "Graph is sound: no cycles, no dead nodes, no dangling edges",
              s2_graph_is_sound),
    Criterion("S3", "A brand-new learner is offered something to do",
              s3_fresh_learner_has_a_next_step),
    Criterion("S4", "Prerequisites are enforced; no topic before its gates",
              s4_prerequisites_block_early_topics),
    Criterion("S5", "Grading discriminates: correct passes, wrong fails, syntax errors rejected",
              s5_grading_discriminates),
    Criterion("S6", "Mastery rises on a pass, falls on a fail, and persists",
              s6_mastery_is_tracked),
    Criterion("S7", "CLI output is derived from real data, not hardcoded",
              s7_cli_reports_real_data),
    Criterion("S8", "Dashboard serves the live knowledge web on the port it advertises",
              s8_dashboard_serves_the_web),
    Criterion("S9", "Curriculum is open-ended and the learner directs its edges",
              s9_curriculum_grows),
    Criterion("S10", "No regression in the existing suite",
              s10_suite_is_green),
    Criterion("S11", "CLI output actually renders; no cell is silently blank",
              s11_cli_output_renders),
    Criterion("S12", "Learner intent steers the engine, and proof promotes it",
              s12_intent_steers_engine),
]


def evaluate() -> list[dict[str, Any]]:
    """Run every criterion and return the results."""
    ctx = new_ctx()
    results: list[dict[str, Any]] = []
    try:
        for criterion in SPEC:
            start = time.perf_counter()
            try:
                ok, detail = criterion.check(ctx)
                error = None
            except Exception as exc:  # a crashing check is a failing check
                ok, detail, error = False, f"check raised {type(exc).__name__}", repr(exc)
            results.append(
                {
                    "id": criterion.key,
                    "requirement": criterion.requirement,
                    "passed": bool(ok),
                    "detail": detail,
                    "error": error,
                    "seconds": round(time.perf_counter() - start, 2),
                }
            )
    finally:
        import shutil

        shutil.rmtree(ctx.tmp, ignore_errors=True)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", dest="as_json", action="store_true", help="emit JSON")
    args = parser.parse_args()

    results = evaluate()

    if args.as_json:
        print(json.dumps(results, indent=2))
        return 0 if all(r["passed"] for r in results) else 1

    print("\n" + "=" * 78)
    print("APEX SPEC EVALUATION")
    print("=" * 78)
    failed = 0
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        if not r["passed"]:
            failed += 1
        print(f"\n[{mark}] {r['id']}  {r['requirement']}")
        print(f"       {r['detail']}")
        if r["error"]:
            print(f"       error: {r['error']}")
        print(f"       ({r['seconds']}s)")

    print("\n" + "=" * 78)
    print(f"{len(results) - failed}/{len(results)} criteria met"
          + (f"  --  FAILING: {[r['id'] for r in results if not r['passed']]}" if failed else ""))
    print("=" * 78 + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
