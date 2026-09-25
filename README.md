# APEX — AI-Powered eXperiential Education

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://python.org)
[![Tests](https://img.shields.io/badge/Tests-208%2F208-brightgreen)](https://github.com/Arkhos-Overlord/apex/actions)
[![Lint](https://img.shields.io/badge/Lint-Clean-success)](https://github.com/Arkhos-Overlord/apex/actions)

> A standalone teaching platform that turns any AI agent into a personalized instructor. Build courses, execute code, track mastery, and learn with adaptive difficulty — all from the terminal or a browser.

## Why APEX?

APEX is **standalone**. It works with any AI agent, any model, any provider. Your courses, progress, and learner state are stored as local JSON files. No vendor lock-in.

| Feature | APEX | Traditional Tools |
|---|---|---|
| **Deployment** | Standalone CLI + web app | Plugin for specific agents only |
| **Code execution** | Real sandboxed Python/JS with auto-grading | Static simulations only |
| **Dashboard** | Interactive charts, knowledge graph, mastery tracking | Basic browser render |
| **Adaptive learning** | Elo-style difficulty algorithm | Simple evidence tracking |
| **Spaced repetition** | SM-2 algorithm | None |
| **Teacher personas** | 4 AI personas with voice | Static profiles |
| **Content formats** | SVG, code, TTS, PDF, markdown→exercise | Text, images, videos |
| **Assessment** | Auto-generated MCQ, fill-in-blank, coding challenges | None |

## Features

### 🎓 Core Engine
- **Course model** — structured curriculum with chapters, lessons, exercises
- **Learner tracking** — mastery scores (0-100), attempt history, confidence levels, evidence-based progress
- **Adaptive difficulty** — Elo-style rating adjusts problem difficulty based on performance in real-time

### ⚡ Code Execution Engine
- **Safe sandboxed execution** — Python and JavaScript run in isolated subprocesses with timeout and memory limits
- **Auto-grading** — compare code output against expected results with detailed feedback
- **Test case generation** — auto-generate test cases from lesson content

### 📊 Web Dashboard
- **Interactive charts** — mastery trends, weekly activity, completion radar
- **Knowledge graph** — force-directed visualization of concept relationships
- **Heatmap** — calendar-style view of learning activity
- **Spaced repetition schedule** — optimized review intervals
- **Dark theme** with smooth animations and responsive design

### 🧠 Assessment System
- **Spaced repetition** — SM-2 algorithm schedules reviews based on forgetting curve
- **Auto-quiz generation** — multiple choice, fill-in-blank, and coding challenges from lesson content
- **Mastery scoring** — 0-100 scale with confidence intervals, exposure tracking

### 🎨 Multi-Modal Content Generation
- **SVG diagrams** — auto-generate concept diagrams (flowcharts, hierarchies, mind maps)
- **Code examples** — generate working, commented code examples
- **TTS voice narration** — text-to-speech for lessons using Hermes infrastructure
- **PDF handouts** — generate styled PDF documents from markdown
- **Markdown-to-exercise parser** — convert lesson content into structured exercises

### 🗣️ Teacher Personas
- **The Mentor** — patient, Socratic, explains step-by-step
- **The Drill Sergeant** — direct, high-expectations, lots of practice
- **The Guide** — navigational, helps find resources, inquiry-based
- **The Storyteller** — narrative-driven, uses stories to teach concepts
- Each persona has voice configuration, teaching style, and Socratic questioning patterns

## Quick Start

### Install

```bash
git clone https://github.com/Arkhos-Overlord/apex.git
cd apex
pip install -e .
```

### Start the Web Dashboard

```bash
cd dashboard
python -m uvicorn server:app --host 0.0.0.0 --port 8080
```

Open [http://localhost:8080](http://localhost:8080) in your browser.

### Use the CLI

```bash
# Start learning a topic
apex teach python

# Show course details
apex course intro-python

# Adaptive practice session
apex practice

# Show learning progress
apex progress

# Open the web dashboard
apex dashboard
```

## Architecture

```
apex/
├── core/                    # Core engine
│   ├── course.py            # Course data model
│   ├── learner.py           # LearnerState + tracking
│   └── adaptive.py          # Adaptive difficulty algorithm
├── engine/                  # Execution engines
│   ├── code_exec.py         # Sandboxed code execution + auto-grading
│   ├── assessment.py        # Spaced repetition, quiz generator, mastery scorer
│   └── content_gen.py       # SVG, code, voice, PDF generation
├── teachers/                # AI teacher personas
│   ├── teacher_config.py    # 4 teacher profiles
│   └── teacher_engine.py    # Personality-aware instruction
├── cli/                     # Command-line interface
│   ├── main.py              # Entry point
│   ├── commands.py          # teach, course, practice, progress, dashboard
│   └── config.py            # Configuration management
├── dashboard/               # Web dashboard
│   ├── server.py            # FastAPI backend
│   ├── templates/           # HTML templates
│   └── static/              # CSS, JS (Chart.js visualizations)
├── tests/                   # 208 tests, all passing
└── pyproject.toml           # Package configuration
```

## Running Tests

```bash
# Run all tests
python -m pytest apex/tests/ -q

# Run with coverage
python -m pytest apex/tests/ --cov=apex

# Lint check
ruff check apex/
ruff format --check apex/
mypy apex/
```

**208 tests passing, 0 lint errors.**

## API Reference

### Core Engine

```python
from apex.core import Course, LearnerState, AdaptiveDifficulty

# Create a course
course = Course(id="python-101", title="Python 101", description="Learn Python", duration_weeks=6)

# Track learner progress
learner = LearnerState()
learner.record_attempt("variables", result="correct")
print(learner.get_mastery("variables"))  # 0-100

# Adaptive difficulty
ad = AdaptiveDifficulty()
difficulty = ad.suggest_difficulty(learner, "loops")
```

### Code Execution

```python
from apex.engine import run_code, grade_code

# Run code safely
result = run_code("print('Hello')", language="python")
# {success: True, output: 'Hello\n', error: '', exit_code: 0, execution_time: 0.01}

# Grade code against test cases
score = grade_code(
    source="def add(a, b): return a + b",
    test_cases=[{"input": "add(1,2)", "expected_output": "3", "description": "basic addition"}],
    language="python",
)
# {passed: 1, total: 1, score: 1.0, details: [...]}
```

### Assessment

```python
from apex.engine import SpacedRepetition, QuizGenerator, MasteryScorer

# Spaced repetition scheduling
sr = SpacedRepetition()
sr.schedule_review("python-looping", quality=3)  # 0-5 quality
next = sr.next_review_date("python-looping")

# Auto-quiz generation
qg = QuizGenerator()
mcqs = qg.generate_mcq("# Python Loops", count=5)
# [{question, options, answer, difficulty, topic}, ...]
```

## License

MIT — see [LICENSE](LICENSE).

## Contributing

Contributions welcome! The project is structured to be extensible:

1. Add new teacher personas in `apex/teachers/teacher_config.py`
2. Add new content formats in `apex/engine/content_gen.py`
3. Add new exercise types in `apex/engine/content_gen.py`
4. Add new dashboard visualizations in `dashboard/static/js/app.js`

## Acknowledgments

Built as a standalone teaching platform for AI agents. APEX removes the plugin dependency and adds real code execution, adaptive learning, and interactive dashboards.
