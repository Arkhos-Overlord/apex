"""Configuration management for Apex CLI.

Provides Config model and file-based persistence for user settings.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel


class Config(BaseModel):
    """User configuration for the Apex CLI.

    Attributes:
        api_key: Optional API key for external services.
        default_course: Optional default course identifier.
        log_level: Logging level string, defaults to 'INFO'.
        learner: Which learner profile the store is keyed by.
        teacher: Default teacher persona for ``apex teach``.
        db_path: Explicit path to the learner database, or ``None`` to use
            ``~/.apex/apex.db``.
        content_dir: Explicit path to the content library, or ``None`` to
            auto-detect it by walking up from the package.
    """

    api_key: str | None = None
    default_course: str | None = None
    log_level: str = "INFO"
    learner: str = "default"
    teacher: str | None = None
    db_path: str | None = None
    content_dir: str | None = None


def load_config() -> Config:
    """Load configuration from ~/.apex/config.json.

    Returns:
        Config: The loaded configuration, or a default Config if the file
            does not exist or cannot be parsed.
    """
    config_path = _get_config_path()
    if not config_path.exists():
        return Config()

    try:
        raw = config_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return Config(**data)
    except (json.JSONDecodeError, OSError):
        return Config()


def save_config(config: Config) -> None:
    """Save configuration to ~/.apex/config.json.

    Creates the ~/.apex directory if it does not exist.

    Args:
        config: The Config instance to persist.
    """
    config_path = _get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        config.model_dump_json(indent=2),
        encoding="utf-8",
    )


def _get_config_path() -> Path:
    """Return the path to the configuration file.

    Returns:
        Path: Absolute path to ~/.apex/config.json.
    """
    home = Path.home()
    return home / ".apex" / "config.json"
