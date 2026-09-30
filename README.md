# APEX — AI-Powered eXperiential Education

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-252%20passing-brightgreen)](#running-tests)

> A standalone teaching platform that turns any AI agent into a personalized instructor. Real sandboxed code execution, Bayesian knowledge tracing, SM-2 spaced repetition, and an interactive dashboard — no vendor lock-in.

## What APEX actually does

| Capability | Implementation |
|---|---|
| **Code execution** | Python (and JavaScript) run in isolated subprocesses: POSIX `RLIMIT_AS` / `RLIMIT_CPU` / `RLIMIT_NPROC` / `RLIMIT_FSIZE` / `RLIMIT_CORE` in the child, env scrubbing, `setsid` isolation, wall-clock kill. Optional `DockerRunner` adds a container with `--network=none --read-only --cap-drop=ALL`. |
| **Auto-grading** | Submissions run against YAML-defined test cases (public + hidden), scored 0–1. |
| **Adaptive selection** | Bayesian Knowledge Tracing (Corbett & Anderson 1994) tracks per-skill mastery; the weakest unmastered skill picks the next exercise. Prerequisite cycles are rejected at load time. |
| **Elo difficulty** | Per-topic learner/content ratings (K-factor 32) suggest difficulty 1–10 and expose a ZPD view. |
| **Spaced repetition** | SM-2 with 1.3 easiness floor, interval growth 1 → 6 → n·EF. |
| **Quiz generation** | Deterministic (seeded) MCQ / fill-in-the-blank / coding prompts from lesson text. |
| **Content generation** | SVG diagrams (flowchart / tree / mind map), curated code examples, TTS stub (Hermes when configured), markdown→PDF handouts, markdown→exercise parser. |
| **Teacher personas** | Mentor, Drill Sergeant, Guide, Storyteller — greeting/explanation/questions/corrections in each voice. |
| **Dashboard** | FastAPI + Chart.js dark SPA: stats, heatmap, per-topic mastery, knowledge graph, spaced-repetition schedule. |
| **Persistence** | SQLite (`apex.db`): mastery, attempts, submissions. JSON-serialized, no pickle. |

## Quick Start

```bash
git clone https://github.com/Arkhos-Overlord/apex.git
cd apex
pip install -e ".[dev]"
```

### Practice from the CLI

```bash
# Adaptive session: picks exercises via BKT, runs your code in the sandbox,
# grades against hidden tests, updates mastery in apex.db
apex practice --rounds 3

# See what skills/exercises are available
apex teach python

# Inspect a course's exercises
apex course py

# Review mastery
apex progress
```

Environment: `APEX_DB` (default `./apex.db`), `APEX_CONTENT_DIR` (default `./content`), `APEX_LEARNER` (default `default`), `APEX_OUTPUT_DIR` (generated artifacts).

### Web dashboard

```bash
apex dashboard            # serves http://localhost:8080 and opens a browser
# or directly:
uvicorn dashboard.server:app --host 0.0.0.0 --port 8080
```

## Architecture

```
apex/
├── core/
│   ├── course.py            # Course / Chapter / Lesson (Pydantic)
│   ├── learner.py           # LearnerState + mastery tracking
│   ├── adaptive.py          # Elo-style difficulty + ZPD
│   └── bkt.py               # Bayesian Knowledge Tracing
├── engine/
│   ├── code_exec.py         # run_code / grade_code / test-case generation
│   ├── assessment.py        # SM-2 spaced repetition, quiz gen, mastery scorer
│   └── content_gen.py       # SVG, code examples, TTS, PDF, md→exercise
├── teachers/                # 4 personas + personality-aware instruction
├── cli/                     # teach, course, practice, progress, dashboard, docker
├── content.py               # YAML exercise/skill library (cycle-checked)
├── sandbox.py               # LocalPythonRunner + DockerRunner (Runner protocol)
└── store.py                 # SQLite persistence (mastery, attempts, submissions)
dashboard/                   # FastAPI server + dark Chart.js SPA
content/                     # skills.yaml + exercises/*.yaml (add your own!)
```

### Adding content

Drop a YAML file into `content/exercises/`:

```yaml
id: py-lists-basics
title: List Basics
skills: [io]
difficulty: 1
prompt: |
  Read three numbers and print them sorted.
starter: |
  nums = []
  for _ in range(3):
      nums.append(int(input()))
tests:
  - input: "3 1 2\n"
    expected: "1 2 3\n"
    hidden: false
  - input: "-1 -5 0\n"
    expected: "-5 -1 0\n"
    hidden: true
```

Skills live in `content/skills.yaml` with optional prerequisites; cycles are rejected on load.

## Running Tests

```bash
python -m pytest apex/tests/ -q
```

**252 passed, 1 skipped** (the fork-bomb guard test is skipped when running as root, because the Linux kernel does not enforce `RLIMIT_NPROC` for uid 0 — the limit is still applied for non-root users).

## Docker

```bash
docker compose build
docker compose up -d
# Dashboard: http://localhost:8080
apex docker build | up | down | logs
```

| Variable | Default | Description |
|---|---|---|
| `APEX_DB` | `/data/apex.db` | SQLite database path (volume `apex-data`) |
| `APEX_CONTENT_DIR` | `/app/content` | Exercises/skills (hot-reloadable bind mount) |
| `APEX_OUTPUT_DIR` | `/output` | Generated SVG/PDF artifacts (volume) |
| `HERMES_TTS_AVAILABLE` | `0` | Enable Hermes TTS integration |

## Sandbox notes (honest limitations)

- The local runner is a hardening layer, not a security boundary against a determined attacker: for untrusted code, use `DockerRunner` (or add user namespaces/seccomp) and run as a non-root user.
- Windows does not enforce rlimits; timeouts and env scrubbing still apply.
- Generated quizzes are heuristic (keyword-based), not LLM-quality — wire your agent in via the persona/`instruct()` APIs to author real content.

## License

MIT — see [LICENSE](LICENSE).
