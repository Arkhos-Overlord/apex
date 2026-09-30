"""A dependency-free dashboard that serves the learner's knowledge web.

apex had a ``dashboard`` command that opened a browser pointed at
localhost:8080 -- a port nothing was listening on.  This module makes that
port real: a stdlib HTTP server that serves the live graph as JSON and a
single self-contained page that draws it.

No JavaScript build step and no npm, deliberately.  The page pulls
Cytoscape from a CDN and everything else is inline, so the UI can never
drift out of sync with the Python that feeds it, and the whole thing runs
on a machine with nothing installed but apex's own dependencies.

If the CDN is unreachable the page still renders the data as a readable
table rather than showing an empty canvas, because a learner who cannot
see their progress is worse off than one reading a plain list.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from apex.session import LearningSession

DEFAULT_PORT = 8080


class DashboardHandler(BaseHTTPRequestHandler):
    """Serves the page, the graph JSON, and the content health report."""

    #: Injected by :func:`build_server`.
    session: LearningSession

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Silence the default stderr access log.

        The dashboard is a local, read-only view of one learner's data;
        logging every asset request to stderr makes the terminal
        unusable during a practice session.
        """

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/":
            self._send_html(render_page(self.session.learner))
        elif path == "/api/graph":
            self._send_json(self.session.graph_payload())
        elif path == "/api/stats":
            self._send_json(self.session.stats())
        elif path == "/api/health":
            self._send_json(self.session.library.health())
        elif path == "/api/proposals":
            self._send_json([p.__dict__ for p in self.session.proposals()])
        else:
            self._send_json({"error": "not found", "path": path}, status=404)

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
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def serve_in_background(
    session: LearningSession, port: int = DEFAULT_PORT
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Start the server on a daemon thread and return both.

    The thread is a daemon so a forgotten dashboard cannot keep the
    process alive.

    Raises:
        OSError: If the port cannot be bound.
    """
    server = build_server(session, port)
    thread = threading.Thread(target=server.serve_forever, name="apex-dashboard", daemon=True)
    thread.start()
    return server, thread


def render_page(learner: str) -> str:
    """The dashboard page.

    Kept as a template with ``__LEARNER__`` substituted rather than an
    f-string, because the body is full of CSS and JavaScript braces.
    """
    return _PAGE.replace("__LEARNER__", learner)


_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Apex &mdash; knowledge web</title>
<script src="https://cdn.jsdelivr.net/npm/cytoscape@3.30.2/dist/cytoscape.min.js"></script>
<style>
  :root {
    --bg: #0f1117; --panel: #171a23; --line: #262a36;
    --ink: #e6e8ee; --muted: #8b93a7; --accent: #4c8dff;
    --mastered: #35c98a; --unlocked: #4c8dff; --locked: #4a5063; --concept: #f0a93b;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    /* Flex column so the graph pane can take the leftover height instead of
       the page scrolling. Without the explicit body height, main collapses
       and Cytoscape renders into 0x0 canvases. */
    display: flex; flex-direction: column;
  }
  header {
    flex: 0 0 auto;
    padding: 18px 24px; border-bottom: 1px solid var(--line);
    display: flex; align-items: baseline; gap: 18px; flex-wrap: wrap;
  }
  h1 { font-size: 18px; margin: 0; letter-spacing: .2px; }
  h1 .dim { color: var(--muted); font-weight: 400; }
  #stats { color: var(--muted); font-size: 13px; display: flex; gap: 16px; flex-wrap: wrap; }
  #stats b { color: var(--ink); font-weight: 600; }
  main {
    flex: 1 1 auto;
    /* min-height:0 is required: a flex/grid child defaults to min-content,
       so the pane refuses to shrink and the canvas gets no height. */
    min-height: 0;
    display: grid; grid-template-columns: minmax(0, 1fr) 340px;
  }
  #cy { width: 100%; height: 100%; min-height: 0; background: var(--bg); }
  aside {
    border-left: 1px solid var(--line); background: var(--panel);
    padding: 20px; overflow-y: auto; min-height: 0;
  }
  aside h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .8px;
             color: var(--muted); margin: 0 0 10px; }
  #detail .title { font-size: 17px; font-weight: 600; margin-bottom: 4px; }
  #detail .kind { font-size: 12px; color: var(--muted); margin-bottom: 12px; }
  #detail p { color: #c3c9d6; font-size: 14px; }
  .bar { height: 6px; background: var(--line); border-radius: 3px; overflow: hidden;
         margin: 6px 0 14px; }
  .bar > i { display: block; height: 100%; background: var(--accent); }
  .rel { margin-top: 8px; }
  .rel .k { color: var(--muted); font-size: 12px; text-transform: uppercase;
            letter-spacing: .5px; }
  .rel .v { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
  .chip { background: var(--line); border-radius: 999px; padding: 2px 9px;
          font-size: 12px; cursor: pointer; }
  .chip:hover { background: var(--accent); color: #fff; }
  .legend { margin-top: 22px; font-size: 12px; color: var(--muted); }
  .legend div { display: flex; align-items: center; gap: 8px; margin: 5px 0; }
  .dot { width: 9px; height: 9px; border-radius: 50%; }
  #fallback { display: none; padding: 24px; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--line); }
  th { color: var(--muted); font-weight: 500; }
  .hint { color: var(--muted); font-size: 13px; font-style: italic; }
</style>
</head>
<body>
<header>
  <h1>Apex <span class="dim">&mdash; knowledge web</span></h1>
  <div id="stats">loading&hellip;</div>
</header>
<main>
  <div id="cy"></div>
  <aside>
    <div id="detail">
      <h2>Select a concept</h2>
      <p class="hint">Click any node to see what it depends on, what it
      relates to, and what learners confuse it with.</p>
    </div>
    <div class="legend">
      <h2>Nodes</h2>
      <div><span class="dot" style="background:var(--mastered)"></span> mastered</div>
      <div><span class="dot" style="background:var(--unlocked)"></span> unlocked now</div>
      <div><span class="dot" style="background:var(--locked)"></span> still locked</div>
      <div><span class="dot" style="background:var(--concept)"></span> knowledge, no test yet</div>
      <h2 style="margin-top:16px">Edges</h2>
      <div><span style="color:var(--accent)">&#9472;&#9472;</span> prerequisite (blocks)</div>
      <div><span style="color:#6b7280">- - -</span> related</div>
      <div><span style="color:#ef6f6f">&#183;&#183;&#183;</span> easy to confuse</div>
      <div><span style="color:#4a5063">&#9475;</span> part of / applies to</div>
    </div>
  </aside>
</main>
<div id="fallback">
  <h2>Your knowledge web</h2>
  <p class="hint" id="fallback-note">The graph library could not be loaded,
  so here is the same data as a list.</p>
  <table id="ftable"></table>
</div>
<script>
const LEARNER = "__LEARNER__";
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// Rendering style is kept separate from the human-readable description:
// Cytoscape wants flat "line-color"/"line-width" keys, and a `label` key
// here would silently put text on every edge.
const EDGE_STYLE = {
  "prereq":          { style: { "line-color": "#4c8dff", "line-width": 2.4,
                               "line-style": "solid" },
                       label: "must learn first" },
  "related":         { style: { "line-color": "#6b7280", "line-width": 1.2,
                               "line-style": "dashed" },
                       label: "related" },
  "contrasts-with":  { style: { "line-color": "#ef6f6f", "line-width": 1.8,
                               "line-style": "dotted" },
                       label: "easy to confuse" },
  "part-of":         { style: { "line-color": "#4a5063", "line-width": 1.0,
                               "line-style": "solid" },
                       label: "part of" },
  "applies-to":      { style: { "line-color": "#3d4252", "line-width": 1.0,
                               "line-style": "dashed" },
                       label: "applies to" },
};
const DEFAULT_EDGE = EDGE_STYLE.related;

function nodeColor(n) {
  if (n.mastered) return getComputedStyle(document.documentElement)
    .getPropertyValue("--mastered").trim();
  if (!n.has_exercises) return getComputedStyle(document.documentElement)
    .getPropertyValue("--concept").trim();
  if (n.unlocked) return getComputedStyle(document.documentElement)
    .getPropertyValue("--unlocked").trim();
  return getComputedStyle(document.documentElement).getPropertyValue("--locked").trim();
}

function renderStats(s) {
  $("#stats").innerHTML = [
    "learner <b>" + esc(s.learner) + "</b>",
    "attempts <b>" + s.attempts + "</b>",
    "accuracy <b>" + Math.round(s.accuracy * 100) + "%</b>",
    "mastered <b>" + s.mastered + "/" + s.concepts + "</b>",
    "graph <b>" + s.graph_concepts + "</b> nodes / <b>" + s.graph_edges + "</b> edges",
    "unlocked now <b>" + s.frontier_size + "</b>",
  ].join("");
}

function renderDetail(d, cy) {
  // Derive the relations from the element rather than from a precomputed
  // index. An earlier version pre-passed this onto node data and called a
  // method that does not exist, which threw and silently swapped the whole
  // graph for the fallback table.
  const rel = {};
  d.connectedEdges().forEach((e) => {
    const other = e.source().id() === d.id() ? e.target().id() : e.source().id();
    (rel[e.data("relation")] = rel[e.data("relation")] || []).push(other);
  });
  // Relations are commonly declared from both ends ("loops relates to
  // recursion" and the reverse), so a naive walk lists every neighbour
  // twice. De-duplicate and sort so the panel is stable between clicks.
  Object.keys(rel).forEach((k) => {
    rel[k] = Array.from(new Set(rel[k])).sort();
  });
  let html = '<div class="title">' + esc(d.data("name")) + "</div>";
  html += '<div class="kind">' + esc(d.data("id")) + " &middot; " + esc(d.data("kind")) + "</div>";
  html += "<p>" + esc(d.data("summary") || "No summary yet.") + "</p>";
  const pct = Math.round((d.data("mastery") || 0) * 100);
  html += '<div class="k" style="font-size:12px;color:var(--muted)">MASTERY</div>';
  html += '<div class="bar"><i style="width:' + pct + '%"></i></div>';
  Object.keys(EDGE_STYLE).forEach((k) => {
    if (!rel[k] || !rel[k].length) return;
    const def = EDGE_STYLE[k];
    html += '<div class="rel"><div class="k">' + esc(def.label) + "</div><div class='v'>";
    rel[k].forEach((other) => {
      html += '<span class="chip" data-goto="' + esc(other) + '">' + esc(other) + "</span>";
    });
    html += "</div></div>";
  });
  const d2 = $("#detail");
  d2.innerHTML = html;
  d2.querySelectorAll("[data-goto]").forEach((el) => {
    el.onclick = () => {
      const t = cy.getElementById(el.dataset.goto);
      if (t.length) { cy.animate({ center: { eles: t }, zoom: 1.4 }, { duration: 350 });
                      renderDetail(t[0], cy); }
    };
  });
}

function drawGraph(data) {
  if (typeof cytoscape !== "function") {
    renderFallback(data, "cytoscape unavailable");
    return null;
  }
  const els = [];
  data.nodes.forEach((n) => {
    els.push({ data: { ...n, label: n.name },
      style: { "background-color": nodeColor(n),
               "border-width": n.has_exercises ? 2 : 5,
               "border-color": n.has_exercises ? "#0f1117" : nodeColor(n),
               "width": 10 + (n.mastery || 0) * 22,
               "height": 10 + (n.mastery || 0) * 22 } });
  });
  data.edges.forEach((e) => {
    const def = EDGE_STYLE[e.relation] || DEFAULT_EDGE;
    els.push({ data: { ...e, rels: [[e.relation, e.target]] }, style: def.style });
  });

  const cy = cytoscape({
    container: $("#cy"), elements: els, style: CYTOSCAPE_STYLESHEET,
    layout: { name: "cose", animate: false, padding: 40, nodeRepulsion: 9000,
              idealEdgeLength: 110, edgeElasticity: 90 },
  });

  cy.on("tap", "node", (evt) => renderDetail(evt.target, cy));
  cy.on("tap", (evt) => {
    if (evt.target === cy) {
      $("#detail").innerHTML = '<h2>Select a concept</h2><p class="hint">' +
        "Click any node to see what it depends on, what it relates to, " +
        "and what learners confuse it with.</p>";
    }
  });
  // Cytoscape measures its container once, at init. The pane is
  // fluid, so tell it when the geometry changes or the canvas stays
  // stretched after a resize.
  window.addEventListener("resize", () => cy.resize());
  // Exposed so the UI check can assert on the live instance.
  window.cy = cy;
  return cy;
}

function renderFallback(data, reason) {
  $("#cy").style.display = "none";
  $("#fallback").style.display = "block";
  let h = "<thead><tr><th>Concept</th><th>Kind</th><th>Mastery</th><th>State</th></tr></thead><tbody>";
  (data.nodes || []).forEach((n) => {
    const state = n.mastered ? "mastered" : n.unlocked ? "unlocked" : "locked";
    h += "<tr><td>" + esc(n.name) + "<br><span style='color:var(--muted)'>" +
         esc(n.id) + "</span></td><td>" + esc(n.kind) + "</td><td>" +
         Math.round(n.mastery * 100) + "%</td><td>" + state + "</td></tr>";
  });
  $("#ftable").innerHTML = h + "</tbody>";
  // Say why. The previous version fell back silently, which turned a
  // thrown exception into what looked like an empty page.
  const note = $("#fallback-note");
  if (note) {
    note.textContent = reason
      ? "The graph library could not be loaded (" + reason + "), so here is the same data as a list."
      : "The graph library could not be loaded, so here is the same data as a list.";
  }
}

// Cytoscape's own stylesheet handles everything that is not per-node data,
// which keeps the console free of "style bypass" warnings.
const CYTOSCAPE_STYLESHEET = [
  { selector: "node",
    style: { "cursor": "pointer", label: "data:name", color: "#c3c9d6",
             "font-size": 9, "text-valign": "bottom", "text-margin-y": 4 } },
  { selector: "node:selected", style: { "border-color": "#fff", "border-width": 3 } },
  { selector: "edge",
    style: { "curve-style": "bezier", "target-arrow-shape": "triangle",
             "target-arrow-color": "#4a5063", opacity: 0.75 } },
];

fetch("/api/graph").then((r) => r.json()).then((data) => {
  renderStats(data.stats);
  return drawGraph(data);
}).catch((err) => {
  console.error("apex dashboard failed to draw the graph:", err);
  renderFallback({ nodes: [] }, String((err && err.message) || err));
});
</script>
</body>
</html>
"""
