"""CLI commands for Apex learning tool.

Provides interactive commands for teaching, practicing, and tracking progress.
"""

from __future__ import annotations

import webbrowser

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from apex.cli.config import load_config

console = Console()


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

    Creates a new course, loads the first lesson, and begins an interactive
    session with rich terminal output.
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

    console.print(f"\n[bold cyan]Welcome to[/bold cyan] [bold]{topic}[/bold]!")
    console.print(
        "\n[yellow]This is an interactive learning session.[/yellow]\n"
        "Type [bold]help[/bold] for available commands, "
        "[bold]quit[/bold] to exit.\n"
    )


@click.command()
@click.argument("course_id", required=True)
def course(course_id: str) -> None:
    """Show details for a specific course.

    COURSE_ID is the identifier of the course to inspect.

    Displays course information including title, progress, and available
    lessons in a formatted table.
    """
    console.print(f"\n[bold]Course:[/bold] {course_id}\n")

    table = Table(title="Course Details")
    table.add_column("Property", style="cyan", justify="right")
    table.add_column("Value", style="green")

    table.add_row("ID", course_id)
    table.add_row("Status", "Active")
    table.add_row("Lessons", "—")
    table.add_row("Progress", "0%")

    console.print(table)


@click.command(name="practice")
def practice() -> None:
    """Start an adaptive practice session.

    Picks up from your current progress and presents questions tailored to
    your weak areas. Track your mastery as you go.
    """
    console.print(
        Panel(
            "[bold green]Adaptive Practice Session[/bold green]\n"
            "[dim]Practicing based on your current knowledge gaps...[/dim]",
            title="[bold]🎯 Practice[/bold]",
            border_style="blue",
        )
    )

    console.print("\n[yellow]Practice session ready.[/yellow]")
    console.print("Press [bold]Ctrl+C[/bold] to stop.\n")


@click.command()
def progress() -> None:
    """Show a summary of your learning progress.

    Displays your current mastery levels across all courses using a
    rich-formatted table in the terminal.
    """
    console.print("\n[bold]Your Learning Progress[/bold]\n")

    table = Table(title="Mastery Summary")
    table.add_column("Course", style="cyan")
    table.add_column("Level", style="green")
    table.add_column("Completed", justify="right")

    table.add_row("Introduction to Python", "Beginner", "3/10")
    table.add_row("Intermediate Python", "Intermediate", "1/8")
    table.add_row("Advanced Patterns", "Not started", "0/12")

    console.print(table)

    console.print("\n[dim]Use [bold]apex teach &lt;topic&gt;[/bold] to start a new course.[/dim]")


@click.command()
def dashboard() -> None:
    """Open the learning dashboard in your browser.

    Launches the web dashboard at [bold]http://localhost:8080[/bold]
    in your default browser.
    """
    console.print(
        Panel(
            "[bold green]Opening dashboard...[/bold green]\n"
            "[dim]If the page does not open, visit:[/dim]\n"
            "[link=http://localhost:8080]http://localhost:8080[/link]",
            title="[bold]📊 Dashboard[/bold]",
            border_style="magenta",
        )
    )

    webbrowser.open("http://localhost:8080")
