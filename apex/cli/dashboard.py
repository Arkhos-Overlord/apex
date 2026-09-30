"""A dependency-free dashboard that serves the learner's knowledge web.

apex once had a ``dashboard`` command that opened a browser pointed at
localhost:8080 -- a port nothing was listening on.  This module makes that
port real.

It now serves the *shared* frontend (``dashboard/static`` +
``dashboard/templates``) -- the same three.js knowledge web the FastAPI
app serves -- so there is one dashboard implementation and it cannot
drift out of sync with the Python that feeds it.  The JSON API mirrors
:mod:`dashboard.server` route-for-route; only the HTTP layer differs
(stdlib here, FastAPI there).  If the content library cannot be found
the server still starts and reports the problem as JSON, because a
dashboard that silently failed to start was the bug this command used to
have.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from apex.session import LearningSession, default_content_root, default_db_path, default_learner

DEFAULT_PORT = 8080

_FRONTEND_ROOT = Path(__file__).resolve().parents[2] / "dashboard"
_STATIC_ROOT = _FRONTEND_ROOT / "static"
_TEMPLATE = _FRONTEND_ROOT / "templates" / "index.html"

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


class DashboardHandler(BaseHTTPRequestHandler):
    """Serves the shared page, static assets, and the graph JSON API."""

    #: Injected by :func:`build_server`.
    session: LearningSession

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Silence the default stderr access log.

        The dashboard is a local, read-only view of one learner's data;
        logging every asset request to stderr makes the terminal
        unusable during a practice session.
        """

    # ── routing ──────────────────────────────────────────────────────

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path, _, query = self.path.partition("?")
        path = path.rstrip("/") or "/"
        params: dict[str, list[str]] = {}
        for pair in query.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                params.setdefault(k, []).append(v)

        if path == "/":
            self._send_html(self._render_index())
        elif path.startswith("/static/"):
            self._send_static(path)
        elif path == "/api/graph":
            self._send_json(self.session.graph_payload())
        elif path == "/api/stats":
            self._send_json({"stats": self.session.stats()})
        elif path == "/api/health":
            library = self.session.library
            self._send_json(
                {"health": library.health()}
                if library is not None
                else {"detail": "content library not found; set APEX_CONTENT_DIR"},
                status=200 if library is not None else 503,
            )
        elif path == "/api/proposals":
            self._send_json({"proposals": [asdict(p) for p in self.session.proposals()]})
        elif path == "/api/courses":
            self._send_json({"courses": [self._course_dict(p) for p in self.session.all_course_progress()]})
        elif path == "/api/attempts":
            self._send_json({"attempts": self.session.attempts()[-50:]})
        elif path == "/api/schedule":
            self._send_json({"learner_id": self.session.learner, "items": self._schedule_items()})
        elif path == "/api/practice/next":
            ex = self.session.next_exercise()
            self._send_json({"exercise": ex.public() if ex else None})
        else:
            self._send_json({"error": "not found", "path": path}, status=404)

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path, _, query = self.path.partition("?")
        path = path.rstrip("/") or "/"
        if path != "/api/practice/submit":
            self._send_json({"error": "not found", "path": path}, status=404)
            return

        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send_json({"detail": "request body is not valid JSON"}, status=400)
            return
        source = (body.get("source") or "").strip()
        if not source:
            self._send_json({"detail": "source is required"}, status=400)
            return
        if len(source) > 20_000:
            self._send_json({"detail": "source too large (max 20000 chars)"}, status=413)
            return

        params = dict(pair.split("=", 1) for pair in query.split("&") if "=" in pair)
        exercise_id = params.get("exercise_id", "")
        exercise = self.session.library.get_exercise(exercise_id) if self.session.library else None
        if exercise is None:
            self._send_json({"detail": f"unknown exercise '{exercise_id}'"}, status=404)
            return

        report = self.session.submit(source, exercise)
        self._send_json(
            {
                "exercise_id": exercise.id,
                "passed": report.passed,
                "passed_count": report.passed_count,
                "total": report.total,
                "score": round(report.score, 4),
                "details": report.details,
                "duration_s": round(report.duration_s, 3),
                "newly_mastered": report.newly_mastered,
                "mastery_after": {k: round(v, 4) for k, v in report.mastery_after.items()},
            }
        )

    # ── payload helpers (kept in one place so the two servers agree) ──

    @staticmethod
    def _course_dict(p: Any) -> dict[str, Any]:
        return {
            "id": p.course.id,
            "title": p.course.title,
            "description": p.course.description,
            "skills": list(p.course.skills),
            "solved": p.solved,
            "total": p.total,
            "mastery": round(p.mastery, 4),
            "complete": p.complete,
            "level": p.level,
        }

    @staticmethod
    def _schedule_items(limit: int = 12) -> list[dict[str, Any]]:
        """Deterministic review schedule mirroring dashboard.server._due_reviews."""
        from datetime import date, timedelta

        session = DashboardHandler.session
        mastery = session.mastery()
        items: list[dict[str, Any]] = []
        today = date.today()
        for skill in sorted(session.library.skills):
            m = mastery.get(skill)
            if m is None or m < 0.5:
                continue
            interval = max(1, min(60, int(2 ** (m * 5))))
            anchor_days = int.from_bytes(skill.encode()[:2], "big") % 7
            due = today + timedelta(days=anchor_days - (today.toordinal() % interval or 0))
            items.append(
                {
                    "skill": skill,
                    "due_date": due.isoformat(),
                    "interval_days": interval,
                    "ease_factor": round(1.3 + m * 1.2, 2),
                }
            )
        items.sort(key=lambda r: r["due_date"])
        return items[:limit]

    # ── file serving ─────────────────────────────────────────────────

    def _render_index(self) -> str:
        html = _TEMPLATE.read_text(encoding="utf-8")
        return html.replace("__LEARNER__", self.session.learner)

    def _send_static(self, path: str) -> None:
        rel = path.removeprefix("/static/")
        target = (_STATIC_ROOT / rel).resolve()
        if not str(target).startswith(str(_STATIC_ROOT.resolve())) or not target.is_file():
            self._send_json({"error": "not found", "path": path}, status=404)
            return
        payload = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _MIME.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_html(self, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, data: Any, status: int = 200) -> None:
        payload = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)


def build_server(session: LearningSession, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """Create (but do not start) a dashboard server for *session*.

    Raises:
        OSError: If the port is already bound, which the caller should
            report rather than swallow -- a dashboard that silently failed
            to start is the bug this command used to have.
    """
    handler = type("BoundDashboardHandler", (DashboardHandler,), {"session": session})
    return ThreadingHTTPServer(("0.0.0.0", port), handler)


def serve_in_background(
    session: LearningSession, port: int = DEFAULT_PORT
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Start the server on a daemon thread and return both.

    The thread is a daemon so a forgotten dashboard cannot keep the
    process alive.
    """
    server = build_server(session, port)
    thread = threading.Thread(target=server.serve_forever, name="apex-dashboard", daemon=True)
    thread.start()
    return server, thread
