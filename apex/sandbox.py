"""Protocol-based code runner architecture for APEX sandbox.

Defines a ``Runner`` protocol and two implementations:

* ``LocalPythonRunner`` — runs user code in an isolated Python subprocess
  on the host (POSIX: resource limits applied in the child via
  ``preexec_fn``; env scrubbing; new session via ``setsid``).
* ``DockerRunner`` — runs user code inside a Docker container with network,
  read-only rootfs, and UID/GID isolation.

Both satisfy ``Runner`` so that callers can swap implementations without
changing the rest of the codebase.
"""

from __future__ import annotations

import asyncio
import os
import platform
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

_IS_POSIX = platform.system() != "Windows"

if _IS_POSIX:
    import resource


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
        return self.exit_code == 0 and not self.timed_out


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
        # Deliberately no PATH: sandboxed code should not exec system binaries,
        # and the interpreter itself is spawned by absolute path.
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
# POSIX child-side resource limits
# ---------------------------------------------------------------------------


def _apply_rlimits(limits: Limits) -> None:  # pragma: no cover - runs in child
    """Install rlimits in the forked child before exec (POSIX only).

    Called via ``preexec_fn``; must never raise (a raise would abort the
    spawn, which is still safe but unhelpful), so every call is guarded.
    """
    if not _IS_POSIX:
        return

    def _set(res: int, value: int) -> None:
        try:
            soft = resource.getrlimit(res)[0]
            # Never lower an existing soft limit below our target —
            # raising the soft limit up to the hard limit is allowed.
            target = value if soft in (-1, resource.RLIM_INFINITY) or value < soft else soft
            hard = resource.getrlimit(res)[1]
            if hard not in (-1, resource.RLIM_INFINITY):
                target = min(target, hard)
            resource.setrlimit(res, (target, target if hard in (-1, resource.RLIM_INFINITY) else hard))
        except (ValueError, OSError):
            pass

    if limits.memory_mb:
        # Address space (covers heap + stack + mmap) — the strongest
        # portable guard against runaway allocation.
        as_bytes = int(limits.memory_mb) * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (as_bytes, as_bytes))
        except (ValueError, OSError):
            pass
    if limits.cpu_s:
        _set(resource.RLIMIT_CPU, int(limits.cpu_s))
    # No new processes from inside the sandbox.
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    except (ValueError, OSError):
        pass
    # Tiny writable-file budget so scripts cannot fill the disk.
    fsize = 1 * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
    except (ValueError, OSError):
        pass
    # No core dumps (they can be large and may leak memory contents).
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ValueError, OSError):
        pass


def _child_setup(limits: Limits) -> None | callable:  # type: ignore[valid-type]
    """Return a ``preexec_fn`` callback, or ``None`` when unsupported."""
    if not _IS_POSIX:
        return None
    return lambda: _apply_rlimits(limits)


def _kill_process_group(proc: subprocess.Popen) -> None:  # pragma: no cover - signal path
    """Best-effort kill of the child and (on POSIX) its whole group."""
    try:
        if _IS_POSIX and proc.pid:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        pass


# ---------------------------------------------------------------------------
# Shared async execution core
# ---------------------------------------------------------------------------


async def _run_argv(
    cmd: list[str],
    stdin: str,
    limits: Limits,
    *,
    new_session: bool = False,
    pre_exec: callable | None = None,  # type: ignore[valid-type]
) -> RunResult:
    """Execute *cmd* asynchronously and package the outcome as a RunResult."""
    t0 = asyncio.get_event_loop().time()
    timed_out = False

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if stdin else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_scrub_env(),
            start_new_session=new_session,
            preexec_fn=pre_exec,
        )
    except OSError as exc:
        return RunResult(
            stdout="",
            stderr=f"Failed to spawn process: {exc}",
            exit_code=-1,
            timed_out=False,
            duration_ms=(asyncio.get_event_loop().time() - t0) * 1000,
        )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=stdin.encode() if stdin else None),
            timeout=limits.timeout_s,
        )
    except asyncio.TimeoutError:
        timed_out = True
        _kill_process_group(proc)
        try:
            await proc.wait()
        except OSError:
            pass
        stdout_bytes, stderr_bytes = b"", b""

    # A child killed by its own enforced limits (CPU budget via SIGXCPU, or
    # SIGKILL e.g. from an OOM) is reported as a timeout-style resource kill.
    import signal as _signal

    if not timed_out and proc.returncode is not None and proc.returncode < 0:
        if -proc.returncode in (_signal.SIGXCPU, _signal.SIGKILL):
            timed_out = True
            stderr_bytes = f"Execution terminated by resource limits (signal {-proc.returncode}).\n".encode()

    stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
    stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

    if timed_out:
        stderr = f"Execution timed out after {limits.timeout_s}s.\n" + stderr

    max_out = limits.max_output_bytes
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


# ---------------------------------------------------------------------------
# LocalPythonRunner
# ---------------------------------------------------------------------------


@dataclass
class LocalPythonRunner:
    """Execute code in a restricted Python subprocess on the host machine.

    On POSIX the child receives ``RLIMIT_AS`` (address space), ``RLIMIT_CPU``,
    ``RLIMIT_NPROC`` (0 — no forking), ``RLIMIT_FSIZE`` (1 MiB) and
    ``RLIMIT_CORE`` (0) via ``preexec_fn`` before the interpreter starts, and
    runs in its own session (``setsid``) so it cannot touch the parent's
    terminal. On Windows only timeouts and env scrubbing apply (documented
    limitation).
    """

    limits: Limits = field(default_factory=Limits)
    python_exe: str = field(default_factory=lambda: sys.executable)

    def __post_init__(self) -> None:
        if not os.path.isfile(self.python_exe):
            raise FileNotFoundError(f"python_exe not found: {self.python_exe}")

    async def run(self, code: str, stdin: str = "") -> RunResult:
        fd, script_path = tempfile.mkstemp(suffix=".py", prefix="apex_sandbox_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(code)
            cmd = [
                self.python_exe,
                "-I",  # isolated mode: no user site, no PYTHON* env tricks
                "-S",  # no site.py
                "-B",  # no .pyc writes
                script_path,
            ]
            return await _run_argv(
                cmd,
                stdin,
                self.limits,
                new_session=_IS_POSIX,
                pre_exec=_child_setup(self.limits),
            )
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass


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
        fd, script_path = tempfile.mkstemp(suffix=".py", prefix="apex_docker_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(code)
            return await _run_argv(self._build_cmd(script_path), stdin, self.limits)
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

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
            "--security-opt=no-new-privileges",
        ]
        if limits.cpu_s:
            # Docker CPU quota: period=100000, quota = cpu_s * 100000
            quota_ns = int(limits.cpu_s * 1_000_000)
            args.extend(["--cpu-period=100000", f"--cpu-quota={quota_ns}"])
        args.extend(
            [
                "--cap-drop=ALL",
                f"--volume={os.path.realpath(script_path)}:/sandbox/apex_run.py:ro",
                self.image,
                "python",
                "-I",
                "-S",
                "-B",
                "/sandbox/apex_run.py",
            ]
        )
        return args
