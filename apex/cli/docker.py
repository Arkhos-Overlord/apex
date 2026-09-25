"""Docker management commands for APEX."""
from __future__ import annotations
import click


@click.group(name="docker")
def docker_group() -> None:
    """Build, run, and manage the APEX Docker container."""
    pass


@docker_group.command()
def build() -> None:
    """Build the Docker image."""
    click.echo("Building APEX Docker image...")
    click.echo("Run: docker compose build")


@docker_group.command()
def up() -> None:
    """Start APEX in Docker."""
    click.echo("Starting APEX container...")
    click.echo("Run: docker compose up -d")
    click.echo("Dashboard: http://localhost:8080")


@docker_group.command()
def down() -> None:
    """Stop APEX container."""
    click.echo("Stopping APEX container...")
    click.echo("Run: docker compose down")


@docker_group.command()
def logs() -> None:
    """View container logs."""
    click.echo("Run: docker compose logs -f")


def main() -> None:
    """Entry point for apex-docker CLI."""
    pass
