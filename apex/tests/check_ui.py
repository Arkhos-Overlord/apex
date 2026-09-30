"""Render the dashboard in a real browser and confirm it draws the web.

Run:  python apex/tests/check_ui.py [--headed]

Complements eval_spec.py's S8, which proves the server returns the right
JSON. This proves the page actually turns that JSON into a rendered 3D
graph, that three.js loaded, and that no JavaScript errors occurred --
none of which a status code or a payload assertion can tell you.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from apex.cli.dashboard import serve_in_background  # noqa: E402
from apex.session import LearningSession  # noqa: E402
from apex.store import Store  # noqa: E402

PORT = 8123


def build_learner(tmp: Path) -> LearningSession:
    """A learner with a little history, so the colours are varied."""
    session = LearningSession("ui-check", store=Store(str(tmp / "ui.db")))
    for _ in range(6):
        exercise = session.next_exercise()
        if exercise is None:
            break
        session.submit(exercise.solution, exercise)
    return session


def main() -> int:
    # The Windows console codepage cannot encode whatever a third-party
    # bundle put in a console error, and this script reports on exactly
    # that. Force UTF-8 so the report always prints.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    args = parser.parse_args()

    import tempfile

    from playwright.sync_api import sync_playwright

    tmp = Path(tempfile.mkdtemp(prefix="apex-ui-"))
    session = build_learner(tmp)
    server, _thread = serve_in_background(session, port=PORT)

    url = f"http://127.0.0.1:{PORT}/"
    problems: list[str] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not args.headed)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors: list[str] = []
            page.on("console", lambda m: errors.append(f"{m.type}: {m.text}")
                    if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

            page.goto(url, wait_until="networkidle", timeout=30_000)
            # three.js renders into a WebGL canvas; wait for the module to
            # publish its scene summary before asserting on it.
            page.wait_for_selector("#web-canvas", timeout=15_000)
            page.wait_for_function(
                "() => window.__apexWeb && window.__apexWeb.nodeCount > 0",
                timeout=20_000,
            )
            time.sleep(1.5)  # let the force simulation spread the web

            rendered = page.evaluate(
                """() => {
                    const canvas = document.querySelector('#web-canvas');
                    const web = window.__apexWeb || {};
                    return {
                        threeRevision: web.threeRevision || '',
                        hasSize: !!(canvas && canvas.width > 0 && canvas.height > 0),
                        stats: document.querySelector('#stat-mastered')?.innerText || '',
                        nodeCount: web.nodeCount || 0,
                        edgeCount: web.edgeCount || 0,
                    };
                }"""
            )

            # Click a node and confirm the detail panel populates.
            detail_before = page.evaluate("() => document.querySelector('#web-detail').innerText")
            if rendered["nodeCount"] > 0:
                page.evaluate(
                    "() => { const canvas = document.getElementById('web-canvas');"
                    "canvas.dispatchEvent(new MouseEvent('click', {clientX: canvas.getBoundingClientRect().width/2, clientY: canvas.getBoundingClientRect().height/2})); }"
                )
                time.sleep(0.8)
            detail_after = page.evaluate("() => document.querySelector('#web-detail').innerText")

            shot = tmp / "dashboard.png"
            page.screenshot(path=str(shot), full_page=False)
            browser.close()

        print(json.dumps({**rendered, "detail_before": detail_before[:80],
                          "detail_after": detail_after[:160], "screenshot": str(shot)},
                         indent=2))

        if not rendered["threeRevision"]:
            problems.append("three.js did not load (no revision published)")
        if not rendered["hasSize"]:
            problems.append("the canvas has zero size")
        if rendered["nodeCount"] < 15:
            problems.append(f"only {rendered['nodeCount']} nodes in the layout")
        if rendered["edgeCount"] < 50:
            problems.append(f"only {rendered['edgeCount']} edges in the layout")
        if not rendered["stats"].strip():
            problems.append("the stats bar is empty")
        if detail_after == detail_before:
            problems.append("clicking a node did not populate the detail panel")
        if errors:
            problems.append(f"console errors: {errors[:3]}")
    except Exception as exc:
        problems.append(f"{type(exc).__name__}: {exc}")
    finally:
        server.shutdown()
        server.server_close()

    if problems:
        print("\nUI CHECK FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("\nUI CHECK PASSED: the 3D knowledge web renders and is interactive.")
    print(f"screenshot: {shot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
