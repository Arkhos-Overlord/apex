"""Tests for Apex CLI commands.

Mocks click and rich where needed to keep tests fast and isolated.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

# Ensure the project root is on sys.path so cli.* imports resolve.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from apex.cli.config import Config, _get_config_path, load_config, save_config  # noqa: E402


# ---------------------------------------------------------------------------
# config tests
# ---------------------------------------------------------------------------

class TestConfigModel:
    """Tests for the Config pydantic model."""

    def test_default_values(self) -> None:
        """Config() produces sensible defaults."""
        cfg = Config()
        assert cfg.api_key is None
        assert cfg.default_course is None
        assert cfg.log_level == "INFO"

    def test_custom_values(self) -> None:
        """Config accepts custom values."""
        cfg = Config(api_key="abc123", default_course="python-basics", log_level="DEBUG")
        assert cfg.api_key == "abc123"
        assert cfg.default_course == "python-basics"
        assert cfg.log_level == "DEBUG"

    def test_serialization_roundtrip(self) -> None:
        """model_dump_json / model_validate are consistent."""
        original = Config(api_key="key", log_level="WARN")
        data = original.model_dump_json()
        restored = Config.model_validate_json(data)
        assert restored.api_key == original.api_key
        assert restored.log_level == original.log_level


class TestConfigPath:
    """Tests for the internal _get_config_path helper."""

    def test_path_under_home(self) -> None:
        """Path points to ~/.apex/config.json."""
        expected = Path.home() / ".apex" / "config.json"
        assert _get_config_path() == expected


class TestLoadSaveConfig:
    """Tests for load_config / save_config with a real temp directory."""

    @pytest.fixture(autouse=True)
    def _mock_home(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> Generator[None, None, None]:
        """Redirect HOME so ~/.apex lives in the tmp directory."""
        monkeypatch.setenv("HOME", str(tmp_path))
        # Also patch pathlib.Path.home for safety.
        with patch("pathlib.Path.home", return_value=tmp_path):
            yield

    def test_load_missing_file_returns_default(self) -> None:
        """load_config on a clean home returns a default Config."""
        cfg = load_config()
        assert cfg == Config()

    def test_save_and_reload(self) -> None:
        """save_config persists, load_config reads back correctly."""
        original = Config(api_key="secret", default_course="math", log_level="DEBUG")
        save_config(original)

        reloaded = load_config()
        assert reloaded.api_key == "secret"
        assert reloaded.default_course == "math"
        assert reloaded.log_level == "DEBUG"

    def test_malformed_json_returns_default(self, tmp_path: Path) -> None:
        """load_config falls back to default on corrupt file."""
        config_file = tmp_path / ".apex" / "config.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("not json {{{", encoding="utf-8")

        cfg = load_config()
        assert cfg == Config()

    def test_save_creates_directory(self, tmp_path: Path) -> None:
        """save_config creates ~/.apex when it does not exist."""
        config_file = tmp_path / ".apex" / "config.json"
        assert not config_file.parent.exists()
        save_config(Config())
        assert config_file.parent.exists()
        assert config_file.exists()


# ---------------------------------------------------------------------------
# CLI command tests (mocked click + rich)
# ---------------------------------------------------------------------------

class TestTeachCommand:
    """Behaviour of the teach command."""

    def test_teach_runs_without_error(self) -> None:
        """teach exits cleanly for a basic topic."""
        from click.testing import CliRunner

        from apex.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["teach", "Python"])
        assert result.exit_code == 0
        assert "Python" in result.output
        assert "Creating course" in result.output

    def test_teach_with_course_id(self) -> None:
        """teach accepts --course-id."""
        from click.testing import CliRunner

        from apex.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["teach", "Rust", "--course-id", "rust-advance"],
        )
        assert result.exit_code == 0
        assert "rust-advance" in result.output


class TestCourseCommand:
    """Behaviour of the course command."""

    def test_course_shows_details(self) -> None:
        """course prints a table with the given id."""
        from click.testing import CliRunner

        from apex.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["course", "python-basics"])
        assert result.exit_code == 0
        assert "python-basics" in result.output
        assert "Course Details" in result.output


class TestPracticeCommand:
    """Behaviour of the practice command."""

    def test_practice_runs(self) -> None:
        """practice command starts a session."""
        from click.testing import CliRunner

        from cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["practice"])
        assert result.exit_code == 0
        assert "Adaptive Practice Session" in result.output


class TestProgressCommand:
    """Behaviour of the progress command."""

    def test_progress_shows_table(self) -> None:
        """progress prints mastery summary."""
        from click.testing import CliRunner

        from cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["progress"])
        assert result.exit_code == 0
        assert "Mastery Summary" in result.output
        assert "Introduction to Python" in result.output


class TestDashboardCommand:
    """Behaviour of the dashboard command."""

    def test_dashboard_opens_browser(self) -> None:
        """dashboard calls webbrowser.open."""
        from click.testing import CliRunner

        from cli.main import cli

        with patch("cli.commands.webbrowser.open") as mock_open:
            runner = CliRunner()
            result = runner.invoke(cli, ["dashboard"])
            assert result.exit_code == 0
            mock_open.assert_called_once_with("http://localhost:8080")
            assert "Opening dashboard" in result.output


class TestCLIHelp:
    """Top-level help and invocation."""

    def test_help_text(self) -> None:
        """apex --help describes the tool."""
        from click.testing import CliRunner

        from cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Apex CLI" in result.output
        assert "teach" in result.output
        assert "dashboard" in result.output

    def test_version(self) -> None:
        """apex --version returns 0.1.0."""
        from click.testing import CliRunner

        from cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output
