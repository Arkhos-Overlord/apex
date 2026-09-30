"""Tests for the hardened code sandbox."""

from __future__ import annotations

import platform
from pathlib import Path

import pytest

from apex.sandbox import (
    DockerRunner,
    Limits,
    LocalPythonRunner,
    Runner,
    RunResult,
)


@pytest.fixture
def runner() -> LocalPythonRunner:
    return LocalPythonRunner(Limits(timeout_s=3.0, memory_mb=96))


@pytest.mark.asyncio
@pytest.mark.skipif(platform.system() == "Windows", reason="Windows tempfile limitation")
async def test_echo(runner: LocalPythonRunner) -> None:
    """Runner can execute simple print."""
    result = await runner.run("print('hello')")
    assert result.ok
    assert "hello" in result.stdout


@pytest.mark.asyncio
@pytest.mark.skipif(platform.system() == "Windows", reason="Windows tempfile limitation")
async def test_timeout_kills_infinite_loop(runner: LocalPythonRunner) -> None:
    """Runner kills infinite loops within timeout."""
    result = await runner.run("while True: pass")
    assert result.timed_out


@pytest.mark.asyncio
@pytest.mark.skipif(platform.system() == "Windows", reason="Windows tempfile limitation")
async def test_reverse_string(runner: LocalPythonRunner) -> None:
    """Runner processes stdin correctly."""
    result = await runner.run("print(input()[::-1])", "abc\n")
    assert result.ok
    assert result.stdout.strip() == "cba"


@pytest.mark.asyncio
@pytest.mark.skipif(platform.system() == "Windows", reason="Windows tempfile limitation")
async def test_syntax_error(runner: LocalPythonRunner) -> None:
    """Runner returns error for syntax errors."""
    result = await runner.run("print(")
    assert not result.ok
    assert result.exit_code != 0


@pytest.mark.asyncio
@pytest.mark.skipif(platform.system() == "Windows", reason="Windows tempfile limitation")
async def test_env_is_scrubbed(runner: LocalPythonRunner) -> None:
    """Runner strips sensitive environment variables."""
    result = await runner.run("import os; print(sorted(os.environ.keys()))")
    assert result.ok
    # PATH should not be present in scrubbed env
    assert "PATH" not in result.stdout


@pytest.mark.asyncio
@pytest.mark.skipif(platform.system() == "Windows", reason="Windows tempfile limitation")
@pytest.mark.skipif(platform.system() != "Windows" and __import__("os").geteuid() == 0, reason="the kernel does not enforce RLIMIT_NPROC for uid 0")
async def test_cannot_fork_processes(runner: LocalPythonRunner) -> None:
    """Runner prevents process spawning via RLIMIT_NPROC."""
    result = await runner.run("import subprocess; subprocess.run(['echo', 'hi'])")
    assert not result.ok


@pytest.mark.asyncio
@pytest.mark.skipif(platform.system() == "Windows", reason="Windows tempfile limitation")
async def test_memory_limit(runner: LocalPythonRunner) -> None:
    """Runner enforces memory limits."""
    result = await runner.run("x = bytearray(10**9)")
    assert not result.ok


def test_run_result_ok_property() -> None:
    """RunResult.ok is True when exit_code==0 and not timed_out."""
    ok_result = RunResult(stdout="hi", stderr="", exit_code=0, timed_out=False, duration_ms=100)
    assert ok_result.ok


def test_run_result_not_ok_on_timeout() -> None:
    """RunResult.ok is False when timed_out."""
    timeout_result = RunResult(stdout="", stderr="", exit_code=-1, timed_out=True, duration_ms=5000)
    assert not timeout_result.ok


def test_run_result_not_ok_on_error() -> None:
    """RunResult.ok is False when exit_code != 0."""
    error_result = RunResult(stdout="", stderr="err", exit_code=1, timed_out=False, duration_ms=50)
    assert not error_result.ok


def test_limits_default() -> None:
    """Limits dataclass has sensible defaults."""
    limits = Limits(timeout_s=3.0, memory_mb=128)
    assert limits.timeout_s == pytest.approx(3.0)
    assert limits.memory_mb == 128
    assert limits.cpu_s == 2
    assert limits.max_output_bytes == 64_000


def test_docker_runner_is_runner() -> None:
    """DockerRunner implements the Runner protocol."""
    dr = DockerRunner()
    assert isinstance(dr, Runner)


# ── DockerRunner isolation flags ────────────────────────────────────────
#
# Regression: _build_cmd named /tmp/code.py while the caller's script sat
# in a host temp directory and was never mounted or copied in, so every
# run failed with a file-not-found from the interpreter. The command is
# checked directly rather than by running Docker, which is not available
# in the test environment.


def _mount_parts(cmd: list[str]) -> tuple[str, str, str]:
    """Return ``(host, container, mode)`` for the single volume in *cmd*.

    Split from the right: a Windows host path starts with a drive letter, so
    ``split(":")`` would return the tail of the host path, not the mount
    point.
    """
    mounts = [a for a in cmd if a.startswith("--volume=")]
    assert len(mounts) == 1, f"expected one volume, found {len(mounts)}"
    host, container, mode = mounts[0].removeprefix("--volume=").rsplit(":", 2)
    return host, container, mode


def test_docker_cmd_mounts_the_script(tmp_path: Path) -> None:
    """The script must reach the container, or nothing can run."""
    script = tmp_path / "learner.py"
    script.write_text("print('hi')", encoding="utf-8")
    cmd = DockerRunner()._build_cmd(str(script))

    host, container, mode = _mount_parts(cmd)
    assert Path(host) == script.resolve()
    assert container == "/sandbox/apex_run.py"
    assert mode == "ro", "the script must be mounted read-only"


def test_docker_cmd_runs_the_mounted_path(tmp_path: Path) -> None:
    """The interpreter must be pointed at the mount, not a path that is absent."""
    script = tmp_path / "learner.py"
    script.write_text("print('hi')", encoding="utf-8")
    cmd = DockerRunner()._build_cmd(str(script))

    _host, container, _mode = _mount_parts(cmd)
    assert cmd[-1] == container, (
        f"container runs {cmd[-1]!r} but the script is mounted at {container!r}"
    )



def test_docker_cmd_keeps_stdin_free_for_the_program(tmp_path: Path) -> None:
    """Test input is piped to the learner's program, so the script cannot
    be delivered over stdin."""
    script = tmp_path / "learner.py"
    script.write_text("print(input())", encoding="utf-8")
    cmd = DockerRunner()._build_cmd(str(script))
    assert not any(a == "-" for a in cmd), "python must not be reading the script from stdin"


def test_docker_cmd_is_isolated(tmp_path: Path) -> None:
    """Network, filesystem, process count and capabilities are all capped."""
    script = tmp_path / "learner.py"
    script.write_text("print('hi')", encoding="utf-8")
    cmd = DockerRunner()._build_cmd(str(script))
    joined = " ".join(cmd)

    for flag in (
        "--network=none",
        "--read-only",
        "--pids-limit=16",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
    ):
        assert flag in joined, f"missing isolation flag: {flag}"
    assert any(a.startswith("--memory=") for a in cmd)
    assert any(a.startswith("--cpu-quota=") for a in cmd)


def test_docker_cmd_respects_limits(tmp_path: Path) -> None:
    """A smaller memory limit reaches the docker command line."""
    script = tmp_path / "learner.py"
    script.write_text("print('hi')", encoding="utf-8")
    cmd = DockerRunner(limits=Limits(memory_mb=32, cpu_s=3))._build_cmd(str(script))
    joined = " ".join(cmd)
    assert "--memory=32m" in joined
    assert "--cpu-quota=300000" in joined



def test_local_runner_is_runner() -> None:
    """LocalPythonRunner implements the Runner protocol."""
    lr = LocalPythonRunner()
    assert isinstance(lr, Runner)
