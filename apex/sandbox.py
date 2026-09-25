"""Protocol-based code runner architecture for APEX sandbox.

Defines a ``Runner`` protocol and two implementations:

* ``LocalPythonRunner`` — runs user code in an isolated Python subprocess
  on the host (POSIX: resource limits + setsid; env scrubbing).
* ``DockerRunner`` — runs user code inside a Docker container with network,
  read-only rootfs, and UID/GID isolation.

Both satisfy ``Runner`` so that callers can swap implementations without
changing the rest of the codebase.
"""

from __future__ import annotations

import asyncio
import os
import platform
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunResult:
    """Outcome of a single code-execution run."""

    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    duration_ms: float

    @property
    def ok(self) -> bool:
        """True when the process exited cleanly with code 0."""
        return self.exit_code == 0


@dataclass(frozen=True)
class Limits:
    """Resource limits applied to a single run.

    ``None`` / unset fields mean "no limit" for that axis.
    """

    timeout_s: float = 3.0
    memory_mb: float = 128.0
    cpu_s: float = 2.0
    max_output_bytes: int = 64_000

    def __post_init__(self) -> None:
        if self.timeout_s is not None and self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if self.memory_mb is not None and self.memory_mb <= 0:
            raise ValueError("memory_mb must be positive")
        if self.cpu_s is not None and self.cpu_s <= 0:
            raise ValueError("cpu_s must be positive")


# ---------------------------------------------------------------------------
# Runner Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Runner(Protocol):
    """Something that can execute user code and return a :class:`RunResult`."""

    async def run(self, code: str, stdin: str = "") -> RunResult: ...


# ---------------------------------------------------------------------------
# Environment scrubbing helpers
# ---------------------------------------------------------------------------

_SAFE_ENV_KEYS = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "PYTHONIOENCODING",
        "PYTHONUNBUFFERED",
        "TERM",
    }
)


def _scrub_env() -> dict[str, str]:
    """Return a minimal, audited environment dict for subprocess execution."""
    env = {k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS}
    # Ensure a deterministic encoding
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


# ---------------------------------------------------------------------------
# LocalPythonRunner
# ---------------------------------------------------------------------------


@dataclass
class LocalPythonRunner:
    """Execute code in a restricted Python subprocess on the host machine.

    On POSIX this applies `RLIMIT_AS` (address-space / memory), `RLIMIT_CPU`
    (CPU time), `RLIMIT_NPROC` (process count), `RLIMIT_FSIZE` (file size),
    and starts the child in its own session via `setsid` so it cannot reclaim
    the terminal or signal the parent.

    On Windows resource limits are not available; the runner still applies
    timeouts and env scrubbing.
    """

    python_exe: str = field(default_factory=lambda: sys.executable)
    limits: Limits = field(default_factory=Limits)

    def __post_init__(self) -> None:
        # dataclass frozen workaround — we only need this for type-checking
        if not os.path.isfile(self.python_exe):
            raise FileNotFoundError(f"python_exe not found: {self.python_exe}")

    async def run(self, code: str, stdin: str = "") -> RunResult:
        t0 = asyncio.get_event_loop().time()
        timed_out = False
        proc: subprocess.CompletedProcess | None = None

        script_fd, script_path = tempfile.mkstemp(suffix=".py", prefix="apex_sandbox_")
        with os.fdopen(script_fd, "w", encoding="utf-8") as fh:
            fh.write(code)

        try:
            cmd = self._build_cmd(script_path)
            env = _scrub_env()

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE if stdin else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                start_new_session=_start_new_session(),
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(
                        input=stdin.encode() if stdin else None,
                    ),
                    timeout=self.limits.timeout_s,
                )
            except TimeoutError:
                timed_out = True
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()
                stdout_bytes = b""
                stderr_bytes = b""

            stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

            if timed_out:
                stderr = f"Execution timed out after {self.limits.timeout_s}s.\n" + stderr

            # Truncate output if needed
            max_out = self.limits.max_output_bytes
            if max_out and len(stdout) > max_out:
                stdout = stdout[:max_out] + "\n[… output truncated …]"
            if max_out and len(stderr) > max_out:
                stderr = stderr[:max_out] + "\n[… output truncated …]"

            exit_code = proc.returncode if proc.returncode is not None else -1
            duration_ms = (asyncio.get_event_loop().time() - t0) * 1000
            return RunResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                timed_out=timed_out,
                duration_ms=duration_ms,
            )
        except OSError as exc:
            duration_ms = (asyncio.get_event_loop().time() - t0) * 1000
            return RunResult(
                stdout="",
                stderr=f"Failed to spawn process: {exc}",
                exit_code=-1,
                timed_out=False,
                duration_ms=duration_ms,
            )
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_cmd(self, script_path: str) -> list[str]:
        """Return the argv that launches the script under the restricted flags."""
        base = [
            self.python_exe,
            "-I",  # isolated mode (no user-site, no environment imports)
            "-S",  # no site.py import
            "-B",  # no .pyc files written
            script_path,
        ]
        if platform.system() != "Windows":
            # POSIX: resource-limit wrapper
            wrapper = _resource_wrapper_path()
            if wrapper:
                limits = self.limits
                args: list[str] = []
                if limits.memory_mb:
                    args.extend(["-m", str(int(limits.memory_mb))])
                if limits.cpu_s:
                    args.extend(["-c", str(int(limits.cpu_s))])
                if limits.cpu_s or limits.memory_mb:
                    return [self.python_exe, wrapper, *args, script_path]
        return base


# ---------------------------------------------------------------------------
# DockerRunner
# ---------------------------------------------------------------------------


@dataclass
class DockerRunner:
    """Execute code inside a Docker container with network, filesystem, and
    process-count isolation.

    Requires Docker to be installed and the current user to have permission
    to run ``docker`` commands.
    """

    image: str = "python:3.11-slim"
    limits: Limits = field(default_factory=Limits)

    async def run(self, code: str, stdin: str = "") -> RunResult:
        t0 = asyncio.get_event_loop().time()
        timed_out = False

        script_fd, script_path = tempfile.mkstemp(suffix=".py", prefix="apex_docker_")
        with os.fdopen(script_fd, "w", encoding="utf-8") as fh:
            fh.write(code)

        try:
            cmd = self._build_cmd(script_path)
            env = _scrub_env()
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE if stdin else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(
                        input=stdin.encode() if stdin else None,
                    ),
                    timeout=self.limits.timeout_s,
                )
            except TimeoutError:
                timed_out = True
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()
                stdout_bytes = b""
                stderr_bytes = b""

            stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

            if timed_out:
                stderr = f"Execution timed out after {self.limits.timeout_s}s.\n" + stderr

            max_out = self.limits.max_output_bytes
            if max_out and len(stdout) > max_out:
                stdout = stdout[:max_out] + "\n[… output truncated …]"
            if max_out and len(stderr) > max_out:
                stderr = stderr[:max_out] + "\n[… output truncated …]"

            exit_code = proc.returncode if proc.returncode is not None else -1
            duration_ms = (asyncio.get_event_loop().time() - t0) * 1000
            return RunResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                timed_out=timed_out,
                duration_ms=duration_ms,
            )
        except OSError as exc:
            duration_ms = (asyncio.get_event_loop().time() - t0) * 1000
            return RunResult(
                stdout="",
                stderr=f"Failed to spawn container: {exc}",
                exit_code=-1,
                timed_out=False,
                duration_ms=duration_ms,
            )
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_cmd(self, script_path: str) -> list[str]:
        limits = self.limits
        args: list[str] = [
            "docker",
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--user=65534:65534",
            "--pids-limit=16",
            "--memory=" + (f"{int(limits.memory_mb)}m" if limits.memory_mb else "128m"),
        ]
        if limits.cpu_s:
            # Docker CPU quota: period=100000, quota = cpu_s * 100000
            quota_ns = int(limits.cpu_s * 1_000_000)
            args.extend(["--cpu-period=100000", f"--cpu-quota={quota_ns}"])
        args.extend(
            [
                "--cap-drop=ALL",
                self.image,
                "python",
                "-I",
                "-S",
                "-B",
                "/tmp/code.py",
            ]
        )
        return args


# ---------------------------------------------------------------------------
# POSIX resource-limit wrapper (bundled, written at import time)
# ---------------------------------------------------------------------------

_RESOURCE_WRAPPER_PATH: str = ""

if platform.system() != "Windows":
    _WRAPPER_SRC = r"""
import resource
import sys
import runpy

def _set_limits(memory_mb: int | None, cpu_s: int | None) -> None:
    if memory_mb:
        soft = memory_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (soft, soft))
        except (ValueError, resource.error):
            pass
    if cpu_s:
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
        except (ValueError, resource.error):
            pass
    # Restrict process count and file size as a safety net
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    except (ValueError, resource.error):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))  # 1 MiB max file
    except (ValueError, resource.error):
        pass

if __name__ == "__main__":
    memory = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
    cpu = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else None
    _set_limits(memory, cpu)
    # Remove our own args so the child sees only the script path
    sys.argv = sys.argv[-1:]
    runpy.run_path(sys.argv[0], run_name="__apex__")
"""

    _MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
    _WRAPPER_PATH = os.path.join(_MODULE_DIR, "_resource_wrapper.py")
    try:
        with open(_WRAPPER_PATH, "w", encoding="utf-8") as fh:
            fh.write(_WRAPPER_SRC)
        _RESOURCE_WRAPPER_PATH = _WRAPPER_PATH
    except OSError:
        _RESOURCE_WRAPPER_PATH = ""


def _resource_wrapper_path() -> str:
    return _RESOURCE_WRAPPER_PATH


def _start_new_session() -> bool:
    """Return True on POSIX where setsid-style session isolation is available."""
    return platform.system() != "Windows"
