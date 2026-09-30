"""Tests for Apex CLI commands.

Mocks click and rich where needed to keep tests fast and isolated.
"""

from __future__ import annotations

import sys
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure the project root is on sys.path so cli.* imports resolve.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from apex.cli.config import Config, _get_config_path, load_config, save_config

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
        """teach loads the library and lists skills for a basic topic."""
        from click.testing import CliRunner

        from apex.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["teach", "Python"])
        assert result.exit_code == 0
        assert "Python" in result.output
        assert "Creating course" in result.output
        assert "exercises loaded" in result.output

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
        """course prints a table with matching exercises."""
        from click.testing import CliRunner

        from apex.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["course", "py"])
        assert result.exit_code == 0
        assert "Course Details" in result.output
        assert "py-hello" in result.output

    def test_course_unknown_id_lists_all(self) -> None:
        """course with a non-matching id lists available exercises."""
        from click.testing import CliRunner

        from apex.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["course", "no-such-course"])
        assert result.exit_code == 0
        assert "No exercises match" in result.output
        assert "py-hello" in result.output


class TestPracticeCommand:
    """Behaviour of the practice command."""

    def test_practice_runs_and_updates_store(self, tmp_path, monkeypatch) -> None:
        """practice grades exercises and persists attempts + mastery."""
        from click.testing import CliRunner

        from apex.cli.main import cli
        from apex.store import Store

        monkeypatch.setenv("APEX_DB", str(tmp_path / "practice.db"))
        monkeypatch.setenv("APEX_CONTENT_DIR", str(Path(__file__).resolve().parents[2] / "content"))
        monkeypatch.setenv("APEX_LEARNER", "cli-test-learner")

        runner = CliRunner()
        result = runner.invoke(cli, ["practice", "--rounds", "2"])
        assert result.exit_code == 0
        assert "Adaptive Practice Session" in result.output
        assert "Session complete" in result.output

        store = Store(str(tmp_path / "practice.db"))
        attempts = store.attempts("cli-test-learner")
        assert len(attempts) == 2
        mastery = store.get_mastery("cli-test-learner")
        assert mastery, "expected mastery updates after practice"


class TestProgressCommand:
    """Behaviour of the progress command."""

    def test_progress_shows_store_data(self, tmp_path, monkeypatch) -> None:
        """progress reads the real store and prints a mastery summary."""
        from click.testing import CliRunner

        from apex.cli.main import cli
        from apex.store import Store

        db = str(tmp_path / "progress.db")
        monkeypatch.setenv("APEX_DB", db)
        monkeypatch.setenv("APEX_LEARNER", "progress-learner")
        Store(db).set_mastery("progress-learner", {"io": 0.5, "loops": 0.9})

        runner = CliRunner()
        result = runner.invoke(cli, ["progress"])
        assert result.exit_code == 0
        assert "Mastery Summary" in result.output
        assert "io" in result.output
        assert "loops" in result.output

    def test_progress_empty_store(self, tmp_path, monkeypatch) -> None:
        """progress on a fresh store shows the empty hint."""
        from click.testing import CliRunner

        from apex.cli.main import cli

        monkeypatch.setenv("APEX_DB", str(tmp_path / "empty.db"))
        monkeypatch.setenv("APEX_LEARNER", "nobody")

        runner = CliRunner()
        result = runner.invoke(cli, ["progress"])
        assert result.exit_code == 0
        assert "no data yet" in result.output


class TestDashboardCommand:
    """Behaviour of the dashboard command."""

    def test_dashboard_serves_then_shuts_down(self) -> None:
        """dashboard starts uvicorn and exits cleanly on shutdown."""
        from unittest.mock import MagicMock

        from apex.cli.main import cli
        from click.testing import CliRunner

        fake_uvicorn = MagicMock()
        with patch("apex.cli.commands.uvicorn.run", fake_uvicorn):
            runner = CliRunner()
            result = runner.invoke(cli, ["dashboard", "--no-browser", "--port", "18080"])
            assert result.exit_code == 0
            assert "Starting dashboard" in result.output
            fake_uvicorn.assert_called_once()
            _, kwargs = fake_uvicorn.call_args
            assert kwargs.get("port") == 18080


class TestCLIHelp:
    """Top-level help and invocation."""

    def test_help_text(self) -> None:
        """apex --help describes the tool."""
        from apex.cli.main import cli
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Apex CLI" in result.output
        assert "teach" in result.output
        assert "dashboard" in result.output

    def test_version(self) -> None:
        """apex --version returns the package version."""
        from apex.cli.main import cli
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.2.0" in result.output
