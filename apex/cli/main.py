"""Entry point for Apex CLI.

Provides the main click group and registers all subcommands.
"""

from __future__ import annotations

import click

from apex.cli.commands import course, dashboard, practice, progress, teach


@click.group()
@click.version_option(version="0.1.0", prog_name="apex")
def cli() -> None:
    """Apex CLI - AI-powered learning tool.

    Use subcommands to teach, practice, and track your progress.
    """


cli.add_command(teach)
cli.add_command(course)
cli.add_command(practice)
cli.add_command(progress)
cli.add_command(dashboard)


if __name__ == "__main__":
    cli()

def main() -> None:
    """Entry point for apex CLI."""
    cli()

