"""Entry point for the Apex CLI.

Registers every subcommand. Kept as a plain list of imports so the command
surface is readable in one place.
"""

from __future__ import annotations

import click

from apex import __version__
from apex.cli.commands import (
    config_group,
    course,
    courses,
    dashboard,
    doctor,
    graph,
    learn,
    practice,
    progress,
    relations,
    teach,
)
from apex.cli.docker import docker_group


@click.group()
@click.version_option(version=__version__, prog_name="apex")
def cli() -> None:
    """Apex CLI - an adaptive learning engine.

    Every number this prints comes from your real progress. Work through a
    course with 'apex practice', inspect what you know with 'apex progress',
    and see the knowledge web itself with 'apex graph' or 'apex dashboard'.
    """


cli.add_command(teach)
cli.add_command(learn)
cli.add_command(courses)
cli.add_command(course)
cli.add_command(practice)
cli.add_command(progress)
cli.add_command(graph)
cli.add_command(dashboard)
cli.add_command(doctor)
cli.add_command(relations)
cli.add_command(config_group)
cli.add_command(docker_group)


if __name__ == "__main__":
    cli()


def main() -> None:
    """Console-script entry point."""
    cli()
