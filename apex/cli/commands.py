"""CLI commands for Apex learning tool.

Real implementations backed by the APEX engine: adaptive practice sessions
grade sandboxed exercises, progress is read from the SQLite store, and the
dashboard command launches uvicorn.
"""

from __future__ import annotations

import time

import click
import uvicorn
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from apex.cli.config import load_config
from apex.content import ContentLibrary
from apex.core.bkt import DEFAULT, apply_attempt, select_next
from apex.engine.code_exec import grade_code
from apex.store import Store

console = Console()

_DEFAULT_CONTENT_DIR = "content"


def _content_root() -> str:
    """Resolve the content directory (APEX_CONTENT_DIR or ./content)."""
    import os

    return os.environ.get("APEX_CONTENT_DIR", _DEFAULT_CONTENT_DIR)


def _db_path() -> str:
    """Resolve the database path (APEX_DB or ./apex.db)."""
    import os

    return os.environ.get("APEX_DB", "apex.db")


def _learner_id() -> str:
    """Resolve the active learner id (APEX_LEARNER or 'default')."""
    import os

    return os.environ.get("APEX_LEARNER", "default")


@click.command()
@click.argument("topic", required=True)
@click.option(
    "--course-id",
    default=None,
    help="Optional course identifier to use instead of generating one from the topic.",
)
def teach(topic: str, course_id: str | None = None) -> None:
    """Create a course on a topic and start an interactive learning session.

    TOPIC is the subject you want to learn about.

    Loads the exercise library, reports what skills are available, and
    prints the next recommended exercise for this learner.
    """
    config = load_config()
    resolved_course_id = course_id or topic.lower().replace(" ", "-")

    console.print(
        Panel(
            f"[bold green]Creating course:[/bold green] {topic}\n"
            f"[bold]Course ID:[/bold] {resolved_course_id}\n"
            f"[dim]Using API key:[/dim] {config.api_key is not None}",
            title="[bold]📚 Apex Teach[/bold]",
            border_style="green",
        )
    )

    try:
        lib = ContentLibrary(_content_root())
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean CLI error
        raise click.ClickException(
            f"Could not load exercises from '{_content_root()}': {exc}"
        ) from exc

    table = Table(title="Available Skills")
    table.add_column("Skill", style="cyan")
    table.add_column("Prerequisites", style="dim")
    for skill in lib.skills.values():
        table.add_row(skill.name, ", ".join(skill.prereqs) or "—")
    console.print(table)

    console.print(f"\n{lib.exercise_count} exercises loaded. Starting session for [bold]{topic}[/bold]!")
    console.print(
        "\n[yellow]Run [bold]apex practice[/bold] to work through exercises, "
        "[bold]apex progress[/bold] to see mastery.[/yellow]\n"
    )


@click.command()
@click.argument("course_id", required=True)
def course(course_id: str) -> None:
    """Show details for a specific course.

    COURSE_ID is the identifier of the course to inspect.

    Displays the exercises registered in the content library for this
    course prefix, with difficulty and skill mappings.
    """
    console.print(f"\n[bold]Course:[/bold] {course_id}\n")

    try:
        lib = ContentLibrary(_content_root())
    except Exception as exc:  # noqa: BLE001
        raise click.ClickException(
            f"Could not load exercises from '{_content_root()}': {exc}"
        ) from exc

    matching = [ex for ex in lib.exercises.values() if ex.id.startswith(course_id)]
    if not matching:
        console.print("[yellow]No exercises match this course id.[/yellow]")
        console.print("Available exercises:")
        for ex in sorted(lib.exercises.values(), key=lambda e: e.id):
            console.print(f"  • [cyan]{ex.id}[/cyan] — {ex.title}")
        return

    table = Table(title="Course Details")
    table.add_column("Exercise", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Difficulty", justify="right")
    table.add_column("Skills", style="dim")
    for ex in sorted(matching, key=lambda e: e.id):
        table.add_row(ex.id, ex.title, str(ex.difficulty), ", ".join(ex.skills))
    console.print(table)


@click.command(name="practice")
@click.option("--learner", default=None, help="Learner id (defaults to APEX_LEARNER or 'default').")
@click.option("--rounds", default=3, show_default=True, help="Number of exercises to attempt.")
def practice(learner: str | None, rounds: int) -> None:
    """Start an adaptive practice session.

    Picks the next exercise using Bayesian Knowledge Tracing, runs your
    solution in the sandbox against its tests, and updates mastery.
    """
    lid = learner or _learner_id()
    console.print(
        Panel(
            "[bold green]Adaptive Practice Session[/bold green]\n"
            f"[dim]Learner: {lid} · Engine: BKT · Grading: sandboxed[/dim]",
            title="[bold]🎯 Practice[/bold]",
            border_style="blue",
        )
    )

    try:
        lib = ContentLibrary(_content_root())
        store = Store(_db_path())
    except Exception as exc:  # noqa: BLE001
        raise click.ClickException(
            f"Could not initialise practice session: {exc}"
        ) from exc

    mastery = store.get_mastery(lid)
    solved = {a["exercise"] for a in store.solved(lid)}
    exercises = list(lib.exercises.values())

    if not exercises:
        console.print("[yellow]No exercises found in the content library.[/yellow]")
        return

    done = 0
    attempted_this_session: set[str] = set()
    for _ in range(max(1, rounds)):
        ex = select_next(mastery, solved | attempted_this_session, exercises, DEFAULT)
        if ex is None:
            console.print("[green]🎉 All exercises solved — nothing left to practice![/green]")
            break

        console.print(f"\n[bold cyan]→ {ex.id}:[/bold cyan] {ex.title} [dim]({', '.join(ex.skills)})[/dim]")
        console.print(ex.prompt)
        if ex.starter:
            console.print(f"[dim]Starter:[/dim]\n{ex.starter}")
        attempted_this_session.add(ex.id)

        # Grade the learner's saved submission if one exists; otherwise run
        # the starter code so the session demonstrates the grading loop.
        submission = store.get_submission(lid, ex.id)
        source = submission if submission is not None else ex.starter
        t0 = time.perf_counter()
        result = grade_code(source, [{"input": t.input, "expected_output": t.expected, "description": "test"} for t in ex.tests])
        duration_ms = int((time.perf_counter() - t0) * 1000)

        passed_all = result["passed"] == result["total"] and result["total"] > 0
        if passed_all:
            console.print(f"  [green]✓ Passed {result['passed']}/{result['total']} tests[/green]")
            solved.add(ex.id)
        else:
            console.print(f"  [red]✗ {result['passed']}/{result['total']} tests passing[/red]")
            for d in result["details"]:
                if not d["passed"]:
                    console.print(f"    [dim]{d['description']}: expected {d['expected']!r}, got {d['got']!r}[/dim]")

        score = result["score"]
        store.add_attempt(lid, ex.id, passed_all, score, duration_ms)
        mastery = apply_attempt(mastery, set(ex.skills), score, DEFAULT)
        store.set_mastery(lid, mastery)
        done += 1

    if done == 0:
        console.print("[yellow]No practice rounds completed.[/yellow]")
    else:
        console.print(f"\n[bold]Session complete:[/bold] {done} exercise(s), mastery updated. [dim]Run apex progress to review.[/dim]")


@click.command()
@click.option("--learner", default=None, help="Learner id (defaults to APEX_LEARNER or 'default').")
def progress(learner: str | None) -> None:
    """Show a summary of your learning progress.

    Reads mastery scores and attempt history from the APEX store and
    renders a mastery summary table.
    """
    lid = learner or _learner_id()
    store = Store(_db_path())
    mastery = store.get_mastery(lid)
    attempts = store.attempts(lid)

    console.print(f"\n[bold]Your Learning Progress[/bold] [dim]({lid})[/dim]\n")

    table = Table(title="Mastery Summary")
    table.add_column("Skill", style="cyan")
    table.add_column("Mastery", style="green", justify="right")

    if mastery:
        for skill, score in sorted(mastery.items()):
            table.add_row(skill, f"{score:.0%}")
    else:
        table.add_row("(no data yet — run apex practice)", "—")

    console.print(table)

    if attempts:
        solved_count = len(store.solved(lid))
        console.print(
            f"\n[bold]Attempts:[/bold] {len(attempts)} · [green]Solved exercises: {solved_count}[/green]"
        )

    console.print("\n[dim]Use [bold]apex practice[/bold] to keep learning.[/dim]")


@click.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind address.")
@click.option("--port", default=8080, show_default=True, type=int, help="Port.")
@click.option("--no-browser", is_flag=True, help="Do not open a browser tab.")
def dashboard(host: str, port: int, no_browser: bool) -> None:
    """Launch the web dashboard server.

    Serves the FastAPI dashboard and opens it in your browser.
    """
    url = f"http://{'localhost' if host in ('0.0.0.0', '127.0.0.1') else host}:{port}"
    console.print(
        Panel(
            f"[bold green]Starting dashboard...[/bold green]\n"
            f"[dim]Serving on[/dim] [link={url}]{url}[/link]",
            title="[bold]📊 Dashboard[/bold]",
            border_style="magenta",
        )
    )

    if not no_browser:
        import threading

        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run("dashboard.server:app", host=host, port=port, reload=False)
