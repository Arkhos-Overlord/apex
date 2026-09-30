"""Entry point for Apex CLI.

Provides the main click group and registers all subcommands.
"""

from __future__ import annotations

import click

from apex.cli.commands import course, dashboard, practice, progress, teach
from apex.cli.docker import docker_group


@click.group()
@click.version_option(version="0.2.0", prog_name="apex")
def cli() -> None:
    """Apex CLI - AI-powered learning tool.

    Use subcommands to teach, practice, and track your progress.
    """


cli.add_command(teach)
cli.add_command(course)
cli.add_command(practice)
cli.add_command(progress)
cli.add_command(dashboard)
cli.add_command(docker_group)


if __name__ == "__main__":
    cli()


def main() -> None:
    """Entry point for apex CLI."""
    cli()
