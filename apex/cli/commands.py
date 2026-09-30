"""CLI commands for the Apex learning tool.

A thin rendering layer. Every figure printed here comes from a
:class:`~apex.session.LearningSession` reading the real content library
and the learner's real store -- the previous version of this file printed
a hardcoded table listing "Introduction to Python 3/10" regardless of
anything that had actually happened.
"""

from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from apex.cli.config import Config, load_config, save_config
from apex.cli.dashboard import DEFAULT_PORT, serve_in_background
from apex.core.bkt import MASTERED
from apex.graph import Relation
from apex.session import LearningSession
from apex.store import Store, StoreError
from apex.teachers import get_teacher, instruct, list_teachers

console = Console()


# ── helpers ──────────────────────────────────────────────────────────────


def _session(config: Config) -> LearningSession:
    """Build a session from config, reporting failures as CLI errors.

    Precedence is environment, then config file, then defaults -- the same
    order :mod:`apex.session` uses for itself, so a script and the CLI
    cannot disagree about whose progress they are reading.  Without this
    a subprocess pointed at a throwaway database would still read the
    developer's real one.

    Content and database problems are the two things a new user hits
    first, so they get a specific message rather than a traceback.
    """
    content_dir = os.environ.get("APEX_CONTENT_DIR") or config.content_dir
    if content_dir:
        # default_content_root() reads the environment, so a configured
        # value has to be published there before the session is built.
        os.environ["APEX_CONTENT_DIR"] = content_dir
    db_path = os.environ.get("APEX_DB_PATH") or config.db_path
    try:
        return LearningSession(
            learner=os.environ.get("APEX_LEARNER") or config.learner,
            store=Store(db_path) if db_path else None,
        )
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    except StoreError as exc:
        raise click.ClickException(f"Cannot open the learner database: {exc}") from exc


def _bar(fraction: float, width: int = 12) -> str:
    """A simple text meter, so progress is visible without a TTY.

    The brackets are backslash-escaped because rich treats ``[`` as the
    start of a markup tag: an unescaped ``[###.......]`` is swallowed
    whole and the meter renders as an empty cell.
    """
    filled = max(0, min(width, round(fraction * width)))
    return "\\[" + "#" * filled + "." * (width - filled) + "]"


def _mastery_pct(value: float) -> str:
    return f"{value * 100:.0f}%"


# ── courses ──────────────────────────────────────────────────────────────


@click.command(name="courses")
def courses() -> None:
    """List the available courses and how far through each one you are."""
    session = _session(load_config())

    if not session.library.courses:
        console.print("[yellow]No courses are defined in the content library.[/yellow]")
        return

    table = Table(title="Courses", show_lines=False)
    table.add_column("Course", style="cyan")
    table.add_column("Skills", justify="right")
    table.add_column("Done", justify="right")
    table.add_column("Mastery")
    table.add_column("Level", style="green")

    for progress in session.all_course_progress():
        table.add_row(
            progress.course.title,
            str(len(progress.course.skills)),
            f"{progress.solved}/{progress.total}",
            _bar(progress.mastery),
            progress.level,
        )

    console.print()
    console.print(table)
    console.print(
        f"\n[dim]Learner:[/dim] {session.learner}   "
        f"[dim]next skill:[/dim] {session.next_skill() or 'nothing left to unlock'}"
    )
    console.print("[dim]Start one with:[/dim] [bold]apex practice --course <id>[/bold]")


# ── course ───────────────────────────────────────────────────────────────


@click.command()
@click.argument("course_id", required=True)
def course(course_id: str) -> None:
    """Show a course: its skills, its exercises, and your progress.

    COURSE_ID is the identifier from [bold]apex courses[/bold].
    """
    config = load_config()
    session = _session(config)

    progress = session.course_progress(course_id)
    if progress is None:
        known = ", ".join(session.library.courses) or "none defined"
        raise click.ClickException(f"Unknown course {course_id!r}. Available: {known}")

    mastery = session.mastery()
    solved = session.solved_ids()

    console.print()
    console.print(
        Panel(
            f"[bold]{progress.course.title}[/bold]\n"
            f"[dim]{progress.course.description}[/dim]\n\n"
            f"{progress.solved}/{progress.total} exercises passed   "
            f"{_bar(progress.mastery)} {_mastery_pct(progress.mastery)}   "
            f"{progress.level}",
            title="Course",
            border_style="cyan",
        )
    )

    skill_table = Table(title="Skills")
    skill_table.add_column("Skill", style="cyan")
    skill_table.add_column("Mastery")
    skill_table.add_column("Exercises", justify="right")
    skill_table.add_column("State", style="green")
    for skill_id in progress.course.skills:
        skill = session.library.skills.get(skill_id)
        if skill is None:
            continue
        value = mastery.get(skill_id, 0.0)
        if value >= MASTERED:
            state = "mastered"
        elif session.library.is_unlocked(skill_id, mastery):
            state = "unlocked"
        else:
            state = "locked"
        skill_table.add_row(
            skill.name,
            _bar(value),
            str(len(session.library.exercises_for_skill(skill_id))),
            state,
        )
    console.print(skill_table)

    exercises = session.exercises_for(course_id)
    if exercises:
        ex_table = Table(title="Exercises")
        ex_table.add_column("ID", style="magenta")
        ex_table.add_column("Exercise")
        ex_table.add_column("Difficulty", justify="right")
        ex_table.add_column("Status", style="green")
        for ex in exercises:
            ex_table.add_row(
                ex.id,
                ex.title,
                str(ex.difficulty),
                "passed" if ex.id in solved else "not yet",
            )
        console.print(ex_table)

    console.print(
        f"\n[dim]Practise it with:[/dim] [bold]apex practice --course {course_id}[/bold]"
    )


# ── progress ─────────────────────────────────────────────────────────────


@click.command()
def progress() -> None:
    """Show mastery across the whole knowledge web."""
    session = _session(load_config())
    mastery = session.mastery()
    stats = session.stats()

    if not mastery:
        console.print("[yellow]The content library declares no skills.[/yellow]")
        return

    console.print(f"\n[bold]Your Learning Progress[/bold]  [dim]learner: {session.learner}[/dim]\n")

    table = Table(title="Mastery Summary")
    table.add_column("Concept", style="cyan")
    table.add_column("Kind")
    table.add_column("Mastery")
    table.add_column("State", style="green")

    for concept_id, value in sorted(mastery.items(), key=lambda kv: (-kv[1], kv[0])):
        concept = session.library.skills.get(concept_id)
        name = concept.name if concept else concept_id
        if value >= MASTERED:
            state = "mastered"
        elif session.library.is_unlocked(concept_id, mastery):
            state = "unlocked"
        else:
            state = "locked"
        table.add_row(
            name,
            concept.kind if concept else "?",
            _bar(value),
            state,
        )
    console.print(table)

    attempts = stats["attempts"]
    if attempts:
        console.print(
            f"\n[bold]{attempts}[/bold] attempts | "
            f"[bold]{stats['passed']}[/bold] passed | "
            f"accuracy [bold]{_mastery_pct(stats['accuracy'])}[/bold] | "
            f"[bold]{stats['mastered']}[/bold]/{stats['concepts']} concepts mastered | "
            f"[bold]{stats['graph_concepts']}[/bold] nodes / "
            f"[bold]{stats['graph_edges']}[/bold] edges in the web"
        )
    else:
        console.print("\n[dim]No attempts recorded yet. Start with:[/dim] [bold]apex practice[/bold]")

    next_skill = session.next_skill()
    if next_skill:
        concept = session.library.skills[next_skill]
        console.print(f"[dim]Next up:[/dim] [bold]{concept.name}[/bold] [dim]({next_skill})[/dim]")

    console.print("[dim]Explore the web with:[/dim] [bold]apex graph[/bold]")


# ── teach ────────────────────────────────────────────────────────────────


@click.command()
@click.argument("topic", required=True)
@click.option(
    "--course-id",
    default=None,
    help="Course to teach from. Defaults to matching the topic against the library.",
)
@click.option("--teacher", default="The Mentor", help="Which teacher persona to use.")
def teach(topic: str, course_id: str | None = None, teacher: str | None = None) -> None:
    """Teach a topic, then hand over to practice.

    TOPIC is a concept id, a skill name, or any word in one.
    """
    config = load_config()
    session = _session(config)

    resolved = course_id or _match_course(session, topic) or "introduction-to-python"
    teacher_name = teacher or config.teacher or "The Mentor"

    subject = _match_concept(session, topic) or topic

    # get_teacher does the case-insensitive lookup and raises on an unknown
    # name, so there is no need to re-implement the check here.
    try:
        get_teacher(teacher_name)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    lesson = instruct(teacher_name, subject)
    skill = session.library.skills.get(subject)
    heading = f"{skill.name} [dim]({subject})[/dim]" if skill else subject
    console.print()
    console.print(Panel(lesson.greeting, title=f"[bold]{lesson.teacher_name}[/bold]",
                        border_style="magenta"))
    console.print(f"\n[bold cyan]{heading}[/bold cyan]\n")
    console.print(lesson.explanation)
    console.print(f"\n[dim]{lesson.example}[/dim]\n")

    if lesson.questions:
        console.print("[bold]Think about these:[/bold]")
        for question in lesson.questions:
            console.print(f"  [cyan]?[/cyan] {question}")
        console.print()

    if lesson.practice_exercises:
        console.print("[bold]Try these:[/bold]")
        for item in lesson.practice_exercises:
            console.print(f"  [green]-[/green] {item}")
        console.print()

    console.print(Panel(lesson.encouragement, border_style="magenta", title="[dim]encouragement[/dim]"))

    console.print(
        f"\n[dim]Course:[/dim] [bold]{resolved}[/bold]   "
        f"[dim]Practise it with:[/dim] [bold]apex practice --course {resolved}[/bold]\n"
    )


def _match_course(session: LearningSession, topic: str) -> str | None:
    """Find the course id that best matches *topic*."""
    needle = topic.lower()
    if needle in session.library.courses:
        return needle
    for cid, definition in session.library.courses.items():
        haystack = " ".join([definition.title, definition.description, *definition.skills])
        if needle in haystack.lower():
            return cid
    return None


def _match_concept(session: LearningSession, topic: str) -> str | None:
    """Find the concept id that best matches *topic*."""
    needle = topic.lower()
    if needle in session.library.skills:
        return needle
    for concept_id, skill in session.library.skills.items():
        if needle in skill.name.lower() or needle in concept_id:
            return concept_id
    return None


# ── practice ─────────────────────────────────────────────────────────────


@click.command()
@click.option("--course", "course_id", default=None, help="Restrict to one course.")
@click.option("--count", default=1, show_default=True, help="How many exercises to attempt.")
@click.option("--file", "source_file", default=None, help="Read the solution from this file.")
@click.option("--solution", is_flag=True, help="Submit the reference solution (for testing).")
def practice(
    course_id: str | None = None,
    count: int = 1,
    source_file: str | None = None,
    solution: bool = False,
) -> None:
    """Attempt an exercise and get it graded against every test case.

    Code is read from --file, or from stdin. With --solution the reference
    implementation is submitted, which is how you check the grader is
    working.
    """
    session = _session(load_config())

    console.print(
        Panel(
            "[bold green]Adaptive Practice Session[/bold green]\n"
            f"[dim]Learner {session.learner} | "
            f"{stats_line(session)}[/dim]",
            title="[bold]Practice[/bold]",
            border_style="blue",
        )
    )

    served: set[str] = set()
    for index in range(1, max(1, count) + 1):
        exercise = session.next_exercise(course_id, exclude=served)
        if exercise is None:
            console.print("\n[green]Nothing left to attempt in this course.[/green]")
            return
        served.add(exercise.id)

        console.print(
            Panel(
                f"[bold]{exercise.title}[/bold]  [dim]difficulty {exercise.difficulty}/5[/dim]\n"
                f"[dim]{exercise.id} | skills: {', '.join(exercise.skills)}[/dim]\n\n"
                f"{exercise.prompt}",
                title=f"[bold]Exercise {index}[/bold]",
                border_style="cyan",
            )
        )
        if exercise.starter:
            console.print("[dim]Starter:[/dim]")
            console.print(Syntax(exercise.starter.rstrip(), "python", theme="monokai", padding=(0, 2)))

        visible = [t for t in exercise.tests if not t.hidden]
        if visible:
            console.print("[dim]Visible test cases:[/dim]")
            for test in visible:
                console.print(f"  stdin [cyan]{test.input.strip()!r}[/cyan] -> stdout {test.expected.strip()!r}")
        hidden_count = sum(1 for t in exercise.tests if t.hidden)
        if hidden_count:
            console.print(f"  [dim]+ {hidden_count} hidden test case(s); you need all of them[/dim]")

        if solution:
            source = exercise.solution
        elif source_file:
            source = Path(source_file).read_text(encoding="utf-8")
        else:
            console.print("\n[dim]Paste your code, then Ctrl-Z / Ctrl-D to end input:[/dim]")
            try:
                source = sys.stdin.read()
            except KeyboardInterrupt:
                console.print("\n[yellow]Cancelled.[/yellow]")
                return

        if not source.strip():
            console.print("[yellow]No code submitted.[/yellow]")
            return

        report = session.submit(source, exercise)
        _print_report(session, report)

    nxt = session.next_skill()
    if nxt:
        console.print(f"\n[dim]Next skill:[/dim] [bold]{nxt}[/bold] | [dim]apex graph[/dim]\n")


def _print_report(session: LearningSession, report: object) -> None:
    """Render an :class:`AttemptReport`."""
    passed = report.passed  # type: ignore[attr-defined]
    style = "green" if passed else "red"
    verdict = "PASSED" if passed else "NOT YET"
    console.print(
        Panel(
            f"[bold {style}]{verdict}[/bold {style}]  "
            f"{report.passed_count}/{report.total} cases  "  # type: ignore[attr-defined]
            f"[dim]in {report.duration_s:.2f}s[/dim]",  # type: ignore[attr-defined]
            border_style=style,
        )
    )
    for detail in report.failing_cases:  # type: ignore[attr-defined]
        console.print(
            f"  [red]x[/red] {detail['description']}  "
            f"[dim]input[/dim] {detail['input'].strip()!r}  "
            f"[dim]expected[/dim] {detail['expected']!r}  [dim]got[/dim] {detail['got']!r}"
        )
    if report.newly_mastered:  # type: ignore[attr-defined]
        console.print(
            f"  [green]mastered:[/green] {', '.join(report.newly_mastered)}"  # type: ignore[attr-defined]
        )
    moved = [
        skill
        for skill, after in report.mastery_after.items()  # type: ignore[attr-defined]
        if abs(after - report.mastery_before.get(skill, after)) > 1e-9  # type: ignore[attr-defined]
    ]
    if moved:
        console.print(
            "  [dim]mastery:[/dim] "
            + ", ".join(
                f"{s} {report.mastery_before.get(s, 0):.2f}->{report.mastery_after[s]:.2f}"  # type: ignore[attr-defined]
                for s in moved
            )
        )
    if not passed:
        exercise = report.exercise  # type: ignore[attr-defined]
        console.print(f"\n  [dim]hint:[/dim] {exercise.hints[0]}" if exercise.hints else "")
        console.print("  [dim]apex practice --solution[/dim] runs the reference implementation.")


def stats_line(session: LearningSession) -> str:
    stats = session.stats()
    return (
        f"{stats['passed']}/{stats['attempts']} passed | "
        f"{stats['mastered']}/{stats['concepts']} mastered"
    )


# ── graph ────────────────────────────────────────────────────────────────


@click.command()
@click.option("--depth", default=2, show_default=True, help="Neighbourhood depth to show.")
@click.option("--json", "as_json", is_flag=True, help="Emit the raw graph payload.")
def graph(depth: int = 2, as_json: bool = False) -> None:
    """Show the knowledge web: what you know, and what it connects to."""
    session = _session(load_config())
    payload = session.graph_payload()

    if as_json:
        import json as _json

        console.print_json(_json.dumps(payload))
        return

    mastery = session.mastery()
    mastered = set(session.mastered_ids())
    table = Table(title=f"Knowledge web for {session.learner}")
    table.add_column("Concept", style="cyan")
    table.add_column("Kind")
    table.add_column("Mastery")
    table.add_column("Unlocks", justify="right")
    table.add_column("Related", justify="right")

    for node in sorted(payload["nodes"], key=lambda n: (-n["mastery"], n["id"])):
        concept_id = node["id"]
        unlocks = len(session.library.graph.dependents_of(concept_id))
        related = len(session.library.graph.neighbourhoods(concept_id, 1))
        table.add_row(
            node["name"],
            node["kind"],
            _bar(node["mastery"]),
            str(unlocks) if unlocks else "-",
            str(related),
        )
    console.print()
    console.print(table)

    proposals = session.proposals()
    if proposals:
        console.print("\n[bold]Where the web grows next:[/bold]")
        for proposal in proposals:
            mark = "[green]o[/green]" if proposal.has_exercises else "[yellow]~[/yellow]"
            console.print(f"  {mark} [bold]{proposal.name}[/bold] [dim]({proposal.concept_id})[/dim]")
            console.print(f"      {proposal.reason}")

    console.print("\n[dim]See it as a picture:[/dim] [bold]apex dashboard[/bold]\n")
    _ = (mastery, mastered, depth)


# ── doctor ───────────────────────────────────────────────────────────────


@click.command()
def doctor() -> None:
    """Check the content library and the learner database for problems."""
    config = load_config()
    session = _session(config)
    health = session.library.health()

    table = Table(title="Content library")
    table.add_column("Check", style="cyan")
    table.add_column("Result", style="green")
    table.add_row("Concepts", str(health["concepts"]))
    table.add_row("Skills with exercises", str(health["skills"]))
    table.add_row("Knowledge nodes", str(health["concepts_only"]))
    table.add_row("Edges", str(health["edges"]))
    for relation, count in sorted(health["edges_by_relation"].items()):
        table.add_row(f"  {relation}", str(count))
    table.add_row("Prerequisite cycles", str(len(health["cycles"])) or "0")
    table.add_row("Unreachable concepts", str(len(health["unreachable"])))
    table.add_row("Dangling relations", str(len(health["dangling"])))
    console.print()
    console.print(table)

    if health["ok"]:
        console.print("\n[green]Content library is healthy.[/green]\n")
    else:
        console.print("\n[red]Problems found:[/red]")
        for problem in health["problems"]:
            console.print(f"  [red]-[/red] {problem}")
        console.print()

    console.print(
        f"[dim]database:[/dim] {config.db_path or '~/.apex/apex.db'}   "
        f"[dim]learner:[/dim] {session.learner}   "
        f"[dim]content:[/dim] {session.library.root}\n"
    )


# ── dashboard ────────────────────────────────────────────────────────────


@click.command()
@click.option("--port", default=DEFAULT_PORT, show_default=True, help="Port to serve on.")
@click.option("--no-open", is_flag=True, help="Do not launch a browser.")
@click.option(
    "--no-wait",
    is_flag=True,
    help="Start the server, open the browser, and return instead of blocking.",
)
def dashboard(port: int = DEFAULT_PORT, no_open: bool = False, no_wait: bool = False) -> None:
    """Serve the knowledge web in your browser.

    Starts a local server, then opens it. Press Ctrl-C to stop. Use
    --no-wait to start it in the background and carry on.
    """
    session = _session(load_config())

    try:
        server, thread = serve_in_background(session, port)
    except OSError as exc:
        console.print(
            f"[red]Could not bind port {port}:[/red] {exc}\n"
            f"[dim]Something else may be using it. Try:[/dim] apex dashboard --port {port + 1}\n"
        )
        return

    url = f"http://localhost:{port}"
    console.print(
        Panel(
            f"[bold green]Knowledge web serving on[/bold green] [link={url}]{url}[/link]\n"
            f"[dim]Learner {session.learner} | "
            f"{session.stats()['graph_concepts']} nodes, "
            f"{session.stats()['graph_edges']} edges[/dim]\n"
            "[dim]Ctrl-C to stop.[/dim]",
            title="[bold]Dashboard[/bold]",
            border_style="magenta",
        )
    )
    if not no_open:
        webbrowser.open(url)

    if no_wait:
        # The caller carries on; the server lives on a daemon thread and
        # dies with the process. Used by the test suite, which must not
        # block on serve_forever.
        return

    try:
        thread.join()
    except KeyboardInterrupt:
        console.print("\n[dim]Shutting down.[/dim]")
    finally:
        server.shutdown()
        server.server_close()


# ── config ───────────────────────────────────────────────────────────────


@click.group(name="config")
def config_group() -> None:
    """Read and write settings stored in ~/.apex/config.json."""


@config_group.command(name="show")
def config_show() -> None:
    """Print the current configuration."""
    cfg = load_config()
    table = Table(title="apex configuration")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("learner", cfg.learner)
    table.add_row("teacher", cfg.teacher)
    table.add_row("default_course", cfg.default_course or "-")
    table.add_row("db_path", cfg.db_path or "~/.apex/apex.db")
    table.add_row("content_dir", cfg.content_dir or "auto-detected")
    table.add_row("log_level", cfg.log_level)
    table.add_row("api_key", "set" if cfg.api_key else "-")
    console.print()
    console.print(table)
    console.print()


@config_group.command(name="set")
@click.argument("key", required=True)
@click.argument("value", required=True)
def config_set(key: str, value: str) -> None:
    """Set one configuration value."""
    cfg = load_config()
    allowed = {"learner", "teacher", "default_course", "db_path", "content_dir", "log_level", "api_key"}
    if key not in allowed:
        raise click.ClickException(f"Unknown key {key!r}. Choose from: {', '.join(sorted(allowed))}")
    setattr(cfg, key, value or None)
    save_config(cfg)
    console.print(f"[green]set[/green] {key} = {value or '(cleared)'}")


# ── relation vocabulary ──────────────────────────────────────────────────


@click.command(name="relations")
def relations() -> None:
    """Explain the edge types used in the knowledge web."""
    table = Table(title="Relation types")
    table.add_column("Type", style="cyan")
    table.add_column("Meaning")
    descriptions = {
        Relation.PREREQ: "hard dependency - you cannot read B before A",
        Relation.RELATED: "adjacent material; neither requires the other",
        Relation.CONTRASTS: "commonly confused; the edge is the warning",
        Relation.PART_OF: "containment, e.g. sorting is part-of algorithms",
        Relation.APPLIES_TO: "a context the concept gets used in",
    }
    for relation, text in descriptions.items():
        table.add_row(relation.value, text)
    console.print()
    console.print(table)
    console.print("\n[dim]Only[/dim] prereq [dim]blocks progress. The rest are for navigation.[/dim]\n")
