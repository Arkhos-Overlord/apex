"""Tests for Apex CLI commands.

Mocks click and rich where needed to keep tests fast and isolated.
"""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure the project root is on sys.path so cli.* imports resolve.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from apex.cli.config import Config, _get_config_path, load_config, save_config

# ── CLI test isolation ───────────────────────────────────────────────────
#
# Without this the command tests read the developer's real
# ~/.apex/config.json and write to the real ~/.apex/apex.db, so `apex
# progress` reports whatever the person running the suite happens to have
# been practising. Every test that builds a session gets a tmp database
# instead, and HOME is redirected so the config file is not touched either.

_TEST_HOME: Path | None = None


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path_factory) -> Generator[None, None, None]:
    """Point HOME and the apex config at a throwaway directory."""
    global _TEST_HOME
    home = tmp_path_factory.mktemp("apex_home")
    _TEST_HOME = home
    with patch("pathlib.Path.home", return_value=home):
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        yield


def _session_for_tests(learner: str = "cli-test"):
    """A LearningSession backed by a throwaway database and no config."""
    from apex.session import LearningSession
    from apex.store import Store

    assert _TEST_HOME is not None
    return LearningSession(learner, store=Store(str(_TEST_HOME / f"{learner}.db")))


def _write_test_config(**kwargs) -> None:
    """Write a config pointing at the throwaway database.

    Keyword arguments override the defaults rather than colliding with
    them, so a test can supply its own ``db_path``.
    """
    from apex.cli.config import Config

    assert _TEST_HOME is not None
    defaults = {"db_path": str(_TEST_HOME / "cmd.db"), "learner": "cli-test"}
    defaults.update(kwargs)
    save_config(Config(**defaults))


@pytest.fixture
def cli_config() -> Generator[None, None, None]:
    """Give CLI command tests a known, isolated configuration."""
    _write_test_config()
    yield


# ── environment overrides ───────────────────────────────────────────────
#
# The CLI and a plain Python script must agree about whose progress they
# are reading. APEX_DB_PATH and APEX_LEARNER used to be honoured only by
# the CLI, so LearningSession() in a script silently read a different
# database than `apex progress` on the same machine.


class TestEnvironmentOverrides:
    def test_session_uses_apex_db_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from apex.session import LearningSession, default_db_path

        target = tmp_path / "env.db"
        monkeypatch.setenv("APEX_DB_PATH", str(target))
        assert default_db_path() == str(target)

        session = LearningSession("env-learner")
        assert Path(session.store._db_path) == target

    def test_session_uses_apex_learner(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apex.session import LearningSession

        monkeypatch.setenv("APEX_LEARNER", "env-person")
        assert LearningSession().learner == "env-person"

    def test_explicit_learner_beats_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apex.session import LearningSession

        monkeypatch.setenv("APEX_LEARNER", "env-person")
        assert LearningSession("explicit").learner == "explicit"

    def test_env_overrides_config_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An explicit APEX_DB_PATH beats a configured db_path."""
        from click.testing import CliRunner

        from apex.cli.main import cli

        from_env = tmp_path / "from-env.db"
        from_config = tmp_path / "from-config.db"
        _write_test_config(db_path=str(from_config))
        monkeypatch.setenv("APEX_DB_PATH", str(from_env))

        assert CliRunner().invoke(cli, ["doctor"]).exit_code == 0
        assert from_env.exists(), "APEX_DB_PATH was ignored"
        assert not from_config.exists(), "the configured path won over the environment"

    def test_default_db_is_under_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apex.session import default_db_path

        monkeypatch.delenv("APEX_DB_PATH", raising=False)
        assert default_db_path().endswith(str(Path(".apex") / "apex.db"))

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
        """teach produces a real lesson for a real concept."""
        from click.testing import CliRunner

        from apex.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["teach", "loops"])
        assert result.exit_code == 0
        assert "Loops" in result.output
        assert "The Mentor" in result.output

    def test_teach_uses_the_named_teacher(self) -> None:
        from click.testing import CliRunner

        from apex.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["teach", "loops", "--teacher", "The Drill Sergeant"])
        assert result.exit_code == 0
        assert "The Drill Sergeant" in result.output

    def test_teach_rejects_unknown_teacher(self) -> None:
        from click.testing import CliRunner

        from apex.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["teach", "loops", "--teacher", "Nobody"])
        assert result.exit_code != 0
        assert "Unknown teacher" in result.output

    def test_teach_with_course_id(self) -> None:
        """teach accepts --course-id and reports the course it chose."""
        from click.testing import CliRunner

        from apex.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["teach", "Rust", "--course-id", "rust-advance"])
        assert result.exit_code == 0
        assert "rust-advance" in result.output

    def test_teach_lesson_is_about_the_topic(self) -> None:
        """The lesson must discuss the topic, not a fixed placeholder."""
        from click.testing import CliRunner

        from apex.cli.main import cli

        runner = CliRunner()
        recursion = runner.invoke(cli, ["teach", "recursion"])
        loops = runner.invoke(cli, ["teach", "loops"])
        assert recursion.exit_code == 0
        assert loops.exit_code == 0
        assert recursion.output != loops.output
        assert "recursion" in recursion.output.lower()


class TestCourseCommand:
    """Behaviour of the course command."""

    def test_course_shows_real_details(self) -> None:
        from click.testing import CliRunner

        from apex.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["course", "introduction-to-python"])
        assert result.exit_code == 0
        assert "Introduction to Python" in result.output
        assert "Skills" in result.output
        assert "Exercises" in result.output

    def test_course_rejects_unknown_id(self) -> None:
        from click.testing import CliRunner

        from apex.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["course", "no-such-course"])
        assert result.exit_code != 0
        assert "Unknown course" in result.output


class TestProgressCommand:
    """Behaviour of the progress command."""

    def test_progress_shows_table(self) -> None:
        """progress prints a real mastery table."""
        from click.testing import CliRunner

        from apex.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["progress"])
        assert result.exit_code == 0
        assert "Mastery Summary" in result.output
        assert "Loops" in result.output
        assert "mastered" in result.output

    def test_progress_reflects_real_attempts(self) -> None:
        """Regression guard: progress used to print a hardcoded table.

        The old implementation listed "Introduction to Python 3/10"
        regardless of whether anything had been attempted. This asserts
        the output changes once a real exercise is passed.
        """
        from click.testing import CliRunner

        from apex.cli.config import Config, save_config
        from apex.cli.main import cli

        before = CliRunner().invoke(cli, ["progress"])

        session = _session_for_tests()
        exercise = session.next_exercise()
        assert exercise is not None
        session.submit(exercise.solution, exercise)
        save_config(Config(learner=session.learner, db_path=session.store._db_path))

        after = CliRunner().invoke(cli, ["progress"])
        assert after.exit_code == 0
        assert after.output != before.output
        assert "attempts" in after.output


class TestPracticeCommand:
    """Behaviour of the practice command."""

    def test_practice_runs(self) -> None:
        """practice command starts a session."""
        from apex.cli.main import cli
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(cli, ["practice"])
        assert result.exit_code == 0
        assert "Adaptive Practice Session" in result.output


class TestProgressCommand:
    """Behaviour of the progress command."""

class TestDashboardCommand:
    """Behaviour of the dashboard command.

    The command genuinely serves the knowledge web now, so it blocks until
    interrupted. Tests pass --no-wait to start it in the background and
    return; a separate test then talks to the real HTTP server.
    """

    def test_dashboard_opens_browser(self) -> None:
        """dashboard starts a server and calls webbrowser.open."""
        from click.testing import CliRunner

        from apex.cli.main import cli

        with patch("apex.cli.commands.webbrowser.open") as mock_open:
            runner = CliRunner()
            result = runner.invoke(cli, ["dashboard", "--no-wait", "--port", "0"])
            assert result.exit_code == 0
            mock_open.assert_called_once()
            assert mock_open.call_args[0][0].startswith("http://localhost:")
            assert "Opening" in result.output or "serving on" in result.output

    def test_dashboard_no_open_skips_browser(self) -> None:
        from click.testing import CliRunner

        from apex.cli.main import cli

        with patch("apex.cli.commands.webbrowser.open") as mock_open:
            runner = CliRunner()
            result = runner.invoke(cli, ["dashboard", "--no-wait", "--no-open", "--port", "0"])
            assert result.exit_code == 0
            mock_open.assert_not_called()

    def test_dashboard_serves_the_graph(self) -> None:
        """The port the browser is sent to is actually listening."""
        import json
        import urllib.request

        from apex.cli.dashboard import build_server, serve_in_background
        from apex.cli.main import cli
        from apex.cli.config import Config
        from apex.session import LearningSession
        from apex.store import Store

        with tempfile.TemporaryDirectory() as tmp:
            store = Store(str(Path(tmp) / "t.db"))
            session = LearningSession("dash-learner", store=store)
            server, _thread = serve_in_background(session, port=0)
            try:
                port = server.server_address[1]
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/graph") as resp:
                    payload = json.loads(resp.read())
                assert payload["nodes"], "graph had no nodes"
                assert payload["edges"], "graph had no edges"
                assert {n["id"] for n in payload["nodes"]} >= {"io", "loops"}
                relations = {e["relation"] for e in payload["edges"]}
                assert "prereq" in relations
                assert len(relations) > 1, "graph rendered as a single relation type"

                with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:
                    html = resp.read().decode("utf-8")
                assert "<html" in html.lower()
                assert "cytoscape" in html
            finally:
                server.shutdown()
                server.server_close()

    def test_dashboard_reports_bind_failure(self) -> None:
        """A busy port is reported, not silently ignored."""
        import socket

        from click.testing import CliRunner

        from apex.cli.main import cli

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        busy = sock.getsockname()[1]
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["dashboard", "--no-wait", "--port", str(busy)])
            assert result.exit_code == 0
            assert "Could not bind" in result.output
        finally:
            sock.close()
        _ = Config


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
        """apex --version returns 0.1.0."""
        from apex.cli.main import cli
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output
