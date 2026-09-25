"""Tests for the hardened code sandbox."""

from __future__ import annotations

import platform

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


def test_local_runner_is_runner() -> None:
    """LocalPythonRunner implements the Runner protocol."""
    lr = LocalPythonRunner()
    assert isinstance(lr, Runner)
