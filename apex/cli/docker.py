"""Docker management commands for APEX.

Thin wrappers around ``docker compose`` so learners can build, start, stop,
and inspect the containerized dashboard without remembering compose syntax.
"""

from __future__ import annotations

import shutil
import subprocess

import click


def _compose() -> str:
    """Return the compose command to use, or raise a clean error."""
    if shutil.which("docker") is None:
        raise click.ClickException("docker is not installed or not on PATH.")
    return "docker"


def _run(args: list[str]) -> None:
    """Run a docker compose command, streaming output."""
    try:
        result = subprocess.run(
            ["docker", "compose", *args],
            check=False,
        )
        if result.returncode != 0:
            raise click.ClickException(f"docker compose {' '.join(args)} failed (exit {result.returncode}).")
    except FileNotFoundError as exc:
        raise click.ClickException(f"Could not execute docker: {exc}") from exc


@click.group(name="docker")
def docker_group() -> None:
    """Build, run, and manage the APEX Docker container."""


@docker_group.command()
def build() -> None:
    """Build the Docker image."""
    click.echo("Building APEX Docker image...")
    _run(["build"])


@docker_group.command()
def up() -> None:
    """Start APEX in Docker (detached)."""
    click.echo("Starting APEX container...")
    _run(["up", "-d"])
    click.echo("Dashboard: http://localhost:8080")


@docker_group.command()
def down() -> None:
    """Stop and remove the APEX container."""
    click.echo("Stopping APEX container...")
    _run(["down"])


@docker_group.command()
def logs() -> None:
    """Stream container logs."""
    _run(["logs", "-f"])


def main() -> None:
    """Entry point for the apex-docker CLI."""
    docker_group()
