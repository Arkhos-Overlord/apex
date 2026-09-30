/* APEX dashboard — three.js r186 knowledge web + practice workspace.
 *
 * The knowledge web is the centrepiece: a 3D force-directed layout of the
 * real graph from /api/graph (which mirrors apex.session.graph_payload()),
 * rendered with three.js and OrbitControls. Nodes are coloured by state
 * (mastered / unlocked / locked / concept), sized by mastery, and clickable
 * via raycasting. The force simulation runs in plain JS and feeds positions
 * to three.js each frame.
 */

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const STATE = {
    learner: null,
    graph: null,
    stats: null,
    currentExercise: null,
    hintsShown: 0,
    // three.js handles
    renderer: null,
    scene: null,
    camera: null,
    controls: null,
    nodeMeshes: [],
    edgeLines: [],
    simNodes: [],
    simLinks: [],
    labelSprites: [],
    picked: null,
    raf: null,
    charts: {},
};

const COLORS = {
    mastered: 0x34d399,
    unlocked: 0x818cf8,
    locked: 0x3d4459,
    concept: 0xf59e0b,
    edge: 0x4c5a7a,
};

const RELATION_STYLE = {
    prereq: { label: "must learn first", color: "#818cf8", dashed: false },
    related: { label: "related", color: "#6b7280", dashed: true },
    "contrasts-with": { label: "easy to confuse", color: "#f87171", dashed: true },
    "part-of": { label: "part of", color: "#4a5063", dashed: false },
    "applies-to": { label: "applies to", color: "#3d4252", dashed: true },
};

/* ── utilities ─────────────────────────────────────────── */

async function api(path, options) {
    const res = await fetch(path, options);
    if (!res.ok) {
        let detail = res.status;
        try { detail = (await res.json()).detail || detail; } catch { /* keep status */ }
        throw new Error(`${path} → ${detail}`);
    }
    return res.json();
}

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

/* ── tabs ──────────────────────────────────────────────── */

const TITLES = {
    web: "Knowledge Web",
    dashboard: "Dashboard",
    courses: "Courses",
    practice: "Practice",
    mastery: "Mastery",
    spaced: "Reviews",
};

document.querySelectorAll(".sidebar nav a").forEach((a) => {
    a.addEventListener("click", () => {
        document.querySelectorAll(".sidebar nav a").forEach((x) => x.classList.remove("active"));
        a.classList.add("active");
        const tab = a.dataset.tab;
        document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
        document.getElementById("panel-" + tab).classList.add("active");
        document.getElementById("page-title").textContent = TITLES[tab] || tab;
        loadTab(tab);
    });
});

function loadTab(tab) {
    try {
        if (tab === "web") renderWeb();
        if (tab === "dashboard") renderDashboard();
        if (tab === "courses") renderCourses();
        if (tab === "practice") renderPractice();
        if (tab === "mastery") renderMastery();
        if (tab === "spaced") renderSchedule();
    } catch (e) {
        console.error("loadTab failed:", e);
    }
}

/* ── top bar stats ─────────────────────────────────────── */

async function refreshStats() {
    const data = await api("/api/stats");
    STATE.stats = data.stats;
    document.getElementById("stat-mastered").textContent =
        `${data.stats.mastered}/${data.stats.concepts}`;
    document.getElementById("stat-frontier").textContent = data.stats.frontier_size;
    document.getElementById("stat-accuracy").textContent =
        Math.round((data.stats.accuracy || 0) * 100) + "%";
    document.getElementById("learner-pill").textContent = data.stats.learner;
    return data.stats;
}

/* ════════════════════════════════════════════════════════ */
/* 3D knowledge web (three.js r186)                         */
/* ════════════════════════════════════════════════════════ */

async function renderWeb() {
    if (STATE.renderer) return; // already running
    const canvas = document.getElementById("web-canvas");
    if (!canvas) return;

    let payload;
    try {
        payload = await api("/api/graph");
    } catch (e) {
        showWebError(String(e.message || e));
        return;
    }
    STATE.graph = payload;
    initThree(canvas);
    buildGraphScene(payload);
    animateWeb();
    // Exposed for apex/tests/check_ui.py to assert on the live scene.
    window.__apexWeb = {
        nodeCount: STATE.simNodes.length,
        edgeCount: STATE.simLinks.length,
        threeRevision: THREE.REVISION,
    };
}

function showWebError(message) {
    const wrap = document.getElementById("web-canvas-wrap");
    if (!wrap) return;
    let box = document.getElementById("web-error");
    if (!box) {
        box = el("div");
        box.id = "web-error";
        box.style.cssText =
            "position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:13px;padding:30px;text-align:center;";
        wrap.appendChild(box);
    }
    box.textContent = `Knowledge web unavailable: ${message}`;
}

function initThree(canvas) {
    const wrap = canvas.parentElement;

    STATE.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    STATE.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    STATE.scene = new THREE.Scene();
    STATE.scene.fog = new THREE.FogExp2(0x0b0e16, 0.028);

    STATE.camera = new THREE.PerspectiveCamera(55, 1, 0.1, 2000);
    STATE.camera.position.set(0, 40, 220);

    STATE.controls = new OrbitControls(STATE.camera, canvas);
    STATE.controls.enableDamping = true;
    STATE.controls.dampingFactor = 0.08;
    STATE.controls.rotateSpeed = 0.6;

    STATE.resizeObserver = new ResizeObserver(() => {
        const w = wrap.clientWidth, h = wrap.clientHeight;
        if (!w || !h) return;
        STATE.camera.aspect = w / h;
        STATE.camera.updateProjectionMatrix();
        STATE.renderer.setSize(w, h);
    });
    STATE.resizeObserver.observe(wrap);
    const w = wrap.clientWidth, h = wrap.clientHeight;
    STATE.renderer.setSize(w, h);
    STATE.camera.aspect = w / h;
    STATE.camera.updateProjectionMatrix();

    STATE.raycaster = new THREE.Raycaster();
    STATE.pointer = new THREE.Vector2();
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("click", onCanvasClick);
}

/* Force simulation in plain JS; three.js just renders positions. */
function buildGraphScene(payload) {
    STATE.simNodes = payload.nodes.map((n, i) => ({
        id: n.id,
        data: n,
        x: Math.cos(i / payload.nodes.length * Math.PI * 2) * 90 + (Math.random() - 0.5) * 20,
        y: (Math.random() - 0.5) * 40,
        z: Math.sin(i / payload.nodes.length * Math.PI * 2) * 90 + (Math.random() - 0.5) * 20,
        vx: 0, vy: 0, vz: 0,
    }));
    STATE.byId = new Map(STATE.simNodes.map((n) => [n.id, n]));
    STATE.simLinks = payload.edges
        .filter((e) => STATE.byId.has(e.source) && STATE.byId.has(e.target))
        .map((e) => ({ e, s: STATE.byId.get(e.source), t: STATE.byId.get(e.target) }));

    // Nodes: emissive spheres; label sprites on top.
    const nodeGroup = new THREE.Group();
    for (const node of STATE.simNodes) {
        const r = 2.2 + (node.data.mastery || 0) * 4.5;
        const color = nodeColor(node.data);
        const geo = new THREE.SphereGeometry(r, 24, 24);
        const mat = new THREE.MeshStandardMaterial({
            color, emissive: color, emissiveIntensity: node.data.mastered ? 0.65 : 0.28,
            roughness: 0.4, metalness: 0.1,
        });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.userData.node = node;
        nodeGroup.add(mesh);
        STATE.nodeMeshes.push(mesh);

        const sprite = makeLabel(node.data.name, color);
        sprite.userData.node = node;
        nodeGroup.add(sprite);
        STATE.labelSprites.push(sprite); // sprites are rendered but never raycast
    }
    STATE.scene.add(nodeGroup);
    STATE.nodeGroup = nodeGroup;

    // Lights
    STATE.scene.add(new THREE.AmbientLight(0xffffff, 0.5));
    const key = new THREE.PointLight(0xffffff, 900, 0, 2);
    key.position.set(120, 160, 120);
    STATE.scene.add(key);
    const rim = new THREE.PointLight(0x818cf8, 500, 0, 2);
    rim.position.set(-140, -60, -120);
    STATE.scene.add(rim);

    // Edges: one LineSegments for all links, rebuilt as positions settle.
    const edgeGeo = new THREE.BufferGeometry();
    const positions = new Float32Array(STATE.simLinks.length * 6);
    edgeGeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    const edgeMat = new THREE.LineBasicMaterial({ color: COLORS.edge, transparent: true, opacity: 0.4 });
    STATE.edgeLines = new THREE.LineSegments(edgeGeo, edgeMat);
    STATE.scene.add(STATE.edgeLines);
}

function makeLabel(text, color) {
    const canvas2d = document.createElement("canvas");
    const ctx = canvas2d.getContext("2d");
    const fontSize = 34;
    ctx.font = `600 ${fontSize}px Inter, sans-serif`;
    const w = Math.ceil(ctx.measureText(text).width) + 16;
    canvas2d.width = w;
    canvas2d.height = fontSize + 14;
    const c2 = canvas2d.getContext("2d");
    c2.font = `600 ${fontSize}px Inter, sans-serif`;
    c2.fillStyle = "#" + color.toString(16).padStart(6, "0");
    c2.shadowColor = "rgba(0,0,0,0.9)";
    c2.shadowBlur = 6;
    c2.fillText(text, 8, fontSize + 2);

    const tex = new THREE.CanvasTexture(canvas2d);
    tex.colorSpace = THREE.SRGBColorSpace;
    const spriteMat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false });
    const sprite = new THREE.Sprite(spriteMat);
    sprite.scale.set(w / 6, canvas2d.height / 6, 1);
    return sprite;
}

function nodeColor(n) {
    if (n.mastered) return COLORS.mastered;
    if (!n.has_exercises) return COLORS.concept;
    if (n.unlocked) return COLORS.unlocked;
    return COLORS.locked;
}

/* d3-style velocity Verlet integration, tuned for graph layout. */
function tickSimulation() {
    const nodes = STATE.simNodes;
    const links = STATE.simLinks;
    if (!nodes.length) return;

    const repulsion = 2600, springLength = 60, springK = 0.05, damping = 0.86, dt = 0.5;

    for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i];
        for (let j = i + 1; j < nodes.length; j++) {
            const b = nodes[j];
            let dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
            let d2 = dx * dx + dy * dy + dz * dz;
            if (d2 < 1) d2 = 1;
            const f = repulsion / d2;
            const d = Math.sqrt(d2);
            dx /= d; dy /= d; dz /= d;
            a.vx -= dx * f; a.vy -= dy * f; a.vz -= dz * f;
            b.vx += dx * f; b.vy += dy * f; b.vz += dz * f;
        }
    }
    for (const link of links) {
        let dx = link.t.x - link.s.x, dy = link.t.y - link.s.y, dz = link.t.z - link.s.z;
        const d = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
        const f = springK * (d - springLength);
        dx /= d; dy /= d; dz /= d;
        link.s.vx += dx * f; link.s.vy += dy * f; link.s.vz += dz * f;
        link.t.vx -= dx * f; link.t.vy -= dy * f; link.t.vz -= dz * f;
    }
    // Gentle pull to origin so the web stays centred.
    for (const n of nodes) {
        n.vx -= n.x * 0.0015; n.vy -= n.y * 0.0015; n.vz -= n.z * 0.0015;
    }
    for (const n of nodes) {
        n.vx *= damping; n.vy *= damping; n.vz *= damping;
        n.x += n.vx * dt; n.y += n.vy * dt; n.z += n.vz * dt;
    }
}

function syncScene() {
    const pos = STATE.edgeLines.geometry.attributes.position;
    let i = 0;
    for (const link of STATE.simLinks) {
        pos.array[i++] = link.s.x; pos.array[i++] = link.s.y; pos.array[i++] = link.s.z;
        pos.array[i++] = link.t.x; pos.array[i++] = link.t.y; pos.array[i++] = link.t.z;
    }
    pos.needsUpdate = true;

    for (const mesh of STATE.nodeGroup.children) {
        const n = mesh.userData.node;
        mesh.position.set(n.x, n.y, n.z);
    }
}

function animateWeb() {
    const loop = () => {
        STATE.raf = requestAnimationFrame(loop);
        tickSimulation();
        syncScene();
        STATE.controls.update();
        STATE.renderer.render(STATE.scene, STATE.camera);
    };
    loop();
}

function stopWeb() {
    if (STATE.raf) cancelAnimationFrame(STATE.raf);
    STATE.raf = null;
}

/* Picking */
function onPointerMove(event) {
    const rect = event.target.getBoundingClientRect();
    STATE.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    STATE.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
}

function onCanvasClick(event) {
    STATE.raycaster.setFromCamera(STATE.pointer, STATE.camera);
    const meshes = STATE.nodeMeshes.filter((m) => m.isMesh);
    const hits = STATE.raycaster.intersectObjects(meshes, false);
    if (hits.length) {
        const node = hits[0].object.userData.node;
        showNodeDetail(node.data);
        highlightNode(node);
    }
}

function highlightNode(node) {
    for (const mesh of STATE.nodeMeshes) {
        if (!mesh.isMesh) continue;
        const mat = mesh.material;
        if (mesh.userData.node === node) {
            mat.emissiveIntensity = 1.1;
            mesh.scale.setScalar(1.25);
        } else {
            mat.emissiveIntensity = mesh.userData.node.data.mastered ? 0.65 : 0.28;
            mesh.scale.setScalar(1);
        }
    }
}

/* Detail panel */
function showNodeDetail(n) {
    const panel = document.getElementById("web-detail");
    if (!panel) return;
    panel.textContent = "";

    const stateClass = n.mastered ? "state-mastered" : n.unlocked ? "state-unlocked" : n.has_exercises ? "state-locked" : "state-concept";
    const stateText = n.mastered ? "mastered" : n.unlocked ? "unlocked now" : n.has_exercises ? "still locked" : "knowledge node";

    const badge = el("span", `state-badge ${stateClass}`, stateText);
    panel.appendChild(badge);
    panel.appendChild(el("h3", null, n.name));
    panel.appendChild(el("div", "kind", `${n.id} · ${n.kind}`));
    panel.appendChild(el("p", "summary", n.summary || "No summary yet."));

    const pct = Math.round((n.mastery || 0) * 100);
    const mLabel = el("div", "rel-label", `mastery — ${pct}%`);
    const bar = el("div", "mastery-bar");
    const fill = el("i");
    fill.style.width = pct + "%";
    bar.appendChild(fill);
    panel.append(mLabel, bar);

    // Group neighbours by relation, using the real edge list.
    const rels = {};
    for (const e of STATE.graph.edges) {
        let other = null;
        if (e.source === n.id) other = e.target;
        else if (e.target === n.id) other = e.source;
        else continue;
        (rels[e.relation] = rels[e.relation] || []).push(other);
    }
    for (const [rel, targets] of Object.entries(rels)) {
        const style = RELATION_STYLE[rel] || { label: rel, color: "#6b7280" };
        const group = el("div", "rel-group");
        group.appendChild(el("div", "rel-label", `${style.label} (${targets.length})`));
        const row = el("div", "chip-row");
        const unique = [...new Set(targets)].sort();
        for (const t of unique) {
            const chip = el("span", "chip", t);
            chip.onclick = () => {
                const sim = STATE.byId.get(t);
                if (sim) { showNodeDetail(sim.data); highlightNode(sim); }
            };
            row.appendChild(chip);
        }
        group.appendChild(row);
        panel.appendChild(group);
    }
}

/* ════════════════════════════════════════════════════════ */
/* Dashboard panel                                          */
/* ════════════════════════════════════════════════════════ */

async function renderDashboard() {
    const [stats, graph, attempts, proposals] = await Promise.all([
        STATE.stats ? Promise.resolve(STATE.stats) : refreshStats(),
        STATE.graph || api("/api/graph"),
        api("/api/attempts"),
        api("/api/proposals"),
    ]);
    STATE.graph = graph;

    document.getElementById("stat-attempts").textContent = stats.attempts;
    document.getElementById("stat-passed").textContent = stats.passed;
    document.getElementById("stat-concepts").textContent = stats.concepts;
    document.getElementById("stat-graph-edges").textContent = stats.graph_edges;

    renderRelationsChart(stats.relations || {});
    renderAttemptsChart(attempts.attempts || []);
    renderProposals(proposals.proposals || []);
}

function renderRelationsChart(relations) {
    const ctx = document.getElementById("relations-chart");
    destroyChart("relations");
    const labels = Object.keys(relations);
    const values = Object.values(relations);
    STATE.charts.relations = new Chart(ctx, {
        type: "doughnut",
        data: {
            labels,
            datasets: [{
                data: values.length ? values : [1],
                backgroundColor: ["#818cf8", "#6b7280", "#f87171", "#4a5063", "#34d399"],
                borderColor: "#151a28",
                borderWidth: 2,
            }],
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { position: "right", labels: { color: "#a7b0c5", boxWidth: 12 } } },
        },
    });
}

function renderAttemptsChart(attempts) {
    const ctx = document.getElementById("attempts-chart");
    destroyChart("attempts");
    const recent = attempts.slice(-12);
    STATE.charts.attempts = new Chart(ctx, {
        type: "bar",
        data: {
            labels: recent.map((_, i) => `#${i + 1}`),
            datasets: [{
                label: "Score %",
                data: recent.map((a) => Math.round(a.score)),
                backgroundColor: recent.map((a) => (a.passed ? "rgba(52,211,153,0.7)" : "rgba(248,113,113,0.6)")),
                borderRadius: 4,
            }],
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { beginAtZero: true, max: 100, grid: { color: "rgba(35,42,61,0.6)" }, ticks: { color: "#6b7590" } },
                x: { grid: { display: false }, ticks: { color: "#6b7590" } },
            },
        },
    });
}

function renderProposals(proposals) {
    const container = document.getElementById("proposals-list");
    container.textContent = "";
    if (!proposals.length) {
        container.appendChild(el("p", "hint", "Nothing proposed — the frontier is empty."));
        return;
    }
    for (const p of proposals.slice(0, 6)) {
        const row = el("div", "proposal-item");
        const kind = el("span", "proposal-kind", p.kind);
        const text = el("div");
        text.appendChild(el("div", "proposal-name", p.name));
        text.appendChild(el("div", "proposal-reason", p.reason));
        row.append(kind, text);
        container.appendChild(row);
    }
}

function destroyChart(key) {
    if (STATE.charts[key]) { STATE.charts[key].destroy(); delete STATE.charts[key]; }
}

/* ════════════════════════════════════════════════════════ */
/* Courses panel                                            */
/* ════════════════════════════════════════════════════════ */

async function renderCourses() {
    const data = await api("/api/courses");
    const container = document.getElementById("courses-list");
    container.textContent = "";
    for (const c of data.courses || []) {
        const card = el("div", "course-item");
        card.appendChild(el("h4", null, c.title));
        card.appendChild(el("p", "meta", `${c.description || ""} · ${c.skills.length} skills`));
        const bar = el("div", "progress-bar");
        const fill = el("div", "progress-fill");
        fill.style.width = c.total ? Math.round((c.solved / c.total) * 100) + "%" : "0%";
        bar.appendChild(fill);
        const stats = el("div", "course-stats");
        stats.appendChild(el("span", null, `${c.solved}/${c.total} exercises`));
        stats.appendChild(el("span", null, c.level));
        card.append(bar, stats);
        container.appendChild(card);
    }
}

/* ════════════════════════════════════════════════════════ */
/* Practice workspace                                       */
/* ════════════════════════════════════════════════════════ */

async function renderPractice() {
    if (STATE.currentExercise) return; // keep current work when switching tabs
    await loadNextExercise();
}

async function loadNextExercise() {
    const status = document.getElementById("practice-status");
    status.textContent = "Fetching next exercise…";
    status.className = "";
    try {
        const data = await api("/api/practice/next");
        STATE.currentExercise = data.exercise;
        STATE.hintsShown = 0;
        document.getElementById("grade-results").textContent = "";
        renderExercise();
        status.textContent = "";
    } catch (e) {
        status.textContent = `Could not load an exercise: ${e.message}`;
        status.className = "err";
    }
}

function renderExercise() {
    const ex = STATE.currentExercise;
    const header = document.getElementById("exercise-header");
    const prompt = document.getElementById("exercise-prompt");
    const starter = document.getElementById("exercise-starter");
    const editor = document.getElementById("code-editor");
    const hints = document.getElementById("exercise-hints");
    header.textContent = "";
    hints.textContent = "";
    if (!ex) {
        header.appendChild(el("div", "ex-title", "Nothing left to practise 🎉"));
        prompt.textContent = "Every exercise available to you has been mastered. Check back when new content lands.";
        starter.textContent = "";
        editor.value = "";
        return;
    }
    header.appendChild(el("div", "ex-title", ex.title));
    header.appendChild(
        el("div", "ex-meta", `${ex.id} · ${kindLabel(ex)} · difficulty ${ex.difficulty}/5 · skills: ${ex.skills.join(", ")}`)
    );
    prompt.textContent = ex.prompt;

    // Answer surface depends on the kind: code gets an editor, mcq gets
    // option buttons, recall/numeric get a one-line input.
    if (ex.kind === "code") {
        starter.textContent = ex.starter || "(no starter code)";
        editor.value = ex.starter || "";
        editor.style.display = "";
        renderStaticAnswer(null);
    } else {
        starter.textContent = "";
        editor.value = "";
        editor.style.display = "none";
        renderStaticAnswer(ex);
    }
    renderHintButton();
}

function kindLabel(ex) {
    if (ex.kind === "code") return `code · ${ex.language || "python"}`;
    if (ex.kind === "mcq") return "multiple choice";
    if (ex.kind === "recall") return "short answer";
    return "numeric";
}

/* Static-answer surface: options for mcq, an input otherwise. The chosen
 * value lands in STATE.answer, which submitSolution sends as `source`. */
function renderStaticAnswer(ex) {
    STATE.answer = "";
    let holder = document.getElementById("static-answer");
    if (!holder) {
        holder = el("div");
        holder.id = "static-answer";
        document.getElementById("code-editor").before(holder);
    }
    holder.textContent = "";
    if (!ex) return;

    if (ex.kind === "mcq") {
        (ex.options || []).forEach((opt, i) => {
            const btn = el("button", "btn btn-secondary option-btn", `${i + 1}. ${opt}`);
            btn.style.cssText = "display:block;width:100%;text-align:left;margin-bottom:8px;";
            btn.onclick = () => {
                STATE.answer = opt;
                holder.querySelectorAll(".option-btn").forEach((b) => (b.style.borderColor = ""));
                btn.style.borderColor = "var(--accent)";
            };
            holder.appendChild(btn);
        });
    } else {
        const input = el("input");
        input.type = "text";
        input.id = "static-answer-input";
        input.placeholder = ex.kind === "numeric" ? "Enter a number" : "Type your answer";
        input.style.cssText = "width:100%;background:#0d1120;border:1px solid var(--border-bright);border-radius:8px;color:var(--text-primary);font-size:14px;padding:10px 14px;outline:none;margin-bottom:4px;";
        input.oninput = () => { STATE.answer = input.value; };
        input.onkeydown = (e) => { if (e.key === "Enter") submitSolution(); };
        holder.appendChild(input);
        input.focus();
    }
}

function renderHintButton() {
    const ex = STATE.currentExercise;
    const hints = document.getElementById("exercise-hints");
    hints.textContent = "";
    if (!ex || !ex.hints || !ex.hints.length) return;
    for (let i = 0; i <= Math.min(STATE.hintsShown, ex.hints.length - 1); i++) {
        hints.appendChild(el("div", "hint-item", ex.hints[i]));
    }
    if (STATE.hintsShown < ex.hints.length - 1) {
        const btn = el("button", "btn btn-secondary", "Show another hint");
        btn.onclick = () => { STATE.hintsShown += 1; renderHintButton(); };
        hints.appendChild(btn);
    }
}

document.getElementById("btn-submit")?.addEventListener("click", submitSolution);
document.getElementById("btn-skip")?.addEventListener("click", () => {
    STATE.currentExercise = null;
    loadNextExercise();
});

async function submitSolution() {
    const ex = STATE.currentExercise;
    if (!ex) return;
    let source;
    if (ex.kind === "code") {
        source = document.getElementById("code-editor").value;
        if (!source.trim()) {
            setStatus("Write some code first.", "err");
            return;
        }
    } else {
        source = (STATE.answer || "").trim();
        if (!source) {
            setStatus("Choose or type an answer first.", "err");
            return;
        }
    }
    const btn = document.getElementById("btn-submit");
    btn.disabled = true;
    setStatus("Grading in the sandbox…", "");
    try {
        const params = new URLSearchParams({ exercise_id: ex.id });
        const result = await api(`/api/practice/submit?${params}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ source }),
        });
        showGrade(result);
        STATE.currentExercise = null; // fetch a fresh one next time
        await refreshStats();
    } catch (e) {
        setStatus(`Grading failed: ${e.message}`, "err");
    } finally {
        btn.disabled = false;
    }
}

function setStatus(text, cls) {
    const status = document.getElementById("practice-status");
    status.textContent = text;
    status.className = cls || "";
}

function showGrade(result) {
    const box = document.getElementById("grade-results");
    box.textContent = "";
    const summary = el(
        "div",
        "grade-summary " + (result.passed ? "pass" : "fail"),
        result.passed
            ? `✓ Passed all ${result.total} tests (score ${Math.round(result.score * 100)}%)`
            : `✗ ${result.passed_count}/${result.total} tests passing`
    );
    box.appendChild(summary);
    for (const d of result.details) {
        const row = el("div", "grade-case " + (d.passed ? "pass" : "fail"));
        row.appendChild(el("span", "case-desc", d.description));
        row.appendChild(el("span", "case-outcome", d.passed ? "✓" : `got ${JSON.stringify(d.got)}`));
        box.appendChild(row);
    }
    if (result.newly_mastered && result.newly_mastered.length) {
        box.appendChild(
            el("div", "mastery-delta", `🎉 Newly mastered: ${result.newly_mastered.join(", ")}`)
        );
    } else if (!result.passed) {
        box.appendChild(el("div", "mastery-delta", "Mastery updated — keep at it."));
    }
    if (result.passed) {
        const next = el("button", "btn btn-primary", "Next exercise →");
        next.onclick = () => { STATE.currentExercise = null; loadNextExercise(); };
        box.appendChild(next);
    }
}

/* ════════════════════════════════════════════════════════ */
/* Mastery + reviews                                        */
/* ════════════════════════════════════════════════════════ */

async function renderMastery() {
    const [graph] = await Promise.all([STATE.graph || api("/api/graph")]);
    STATE.graph = graph;
    const skills = graph.nodes.filter((n) => n.has_exercises || n.mastered);
    const container = document.getElementById("mastery-bars");
    container.textContent = "";
    const palette = ["#818cf8", "#a855f7", "#34d399", "#38bdf8", "#f59e0b", "#f87171", "#22d3ee"];
    skills.sort((a, b) => b.mastery - a.mastery);
    skills.forEach((n, i) => {
        const row = el("div", "mastery-item");
        row.appendChild(el("span", "mastery-label", n.name));
        const bar = el("div", "mastery-bar");
        const fill = el("div", "mastery-fill");
        fill.style.width = Math.round(n.mastery * 100) + "%";
        fill.style.background = palette[i % palette.length];
        bar.appendChild(fill);
        row.appendChild(bar);
        row.appendChild(el("span", "mastery-value", Math.round(n.mastery * 100) + "%"));
        container.appendChild(row);
    });
}

async function renderSchedule() {
    const data = await api("/api/schedule");
    const container = document.getElementById("schedule-list");
    container.textContent = "";
    if (!(data.items || []).length) {
        container.appendChild(el("p", "hint", "Nothing due — master a skill to start the review cycle."));
        return;
    }
    for (const item of data.items) {
        const row = el("div", "schedule-item");
        row.appendChild(el("span", "topic-name", item.skill));
        row.appendChild(el("span", "interval", item.interval_days + "d"));
        row.appendChild(el("span", "due-date", "due " + item.due_date));
        container.appendChild(row);
    }
}

/* ── boot ──────────────────────────────────────────────── */

(async function boot() {
    window.__apexBooted = true; // lets index.html's CDN-failure guard stand down
    try {
        await refreshStats();
    } catch (e) {
        console.error("stats failed:", e);
    }
    renderWeb();
    loadTab("web");
})();
