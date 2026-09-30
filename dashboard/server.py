"""APEX — AI-Powered eXperiential Education Dashboard.

FastAPI backend serving the *real* learning engine: the knowledge web
(:mod:`apex.graph`), BKT mastery, graded attempts, spaced-repetition
schedule, and the practice loop. Every number the dashboard shows comes
from a :class:`~apex.session.LearningSession`; there is no demo data.

The practice endpoint grades browser-submitted code in the same sandbox
the CLI uses, so a submission from the web updates mastery exactly like
``apex practice`` does.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from apex.content import ContentLibrary
from apex.session import LearningSession, default_content_root, default_db_path, default_learner
from apex.store import Store

_templates_dir = Path(__file__).parent / "templates"
_static_dir = Path(__file__).parent / "static"


def _build_session(learner: str | None = None) -> LearningSession:
    """Create a session, tolerating a missing content directory.

    A dashboard that cannot find content still has to start — FastAPI
    mounts at import time — so the failure is deferred to request time
    where it can be reported as a proper 503.
    """
    try:
        library = ContentLibrary(default_content_root())
    except (FileNotFoundError, ValueError):
        library = None
    return LearningSession(
        learner=learner or default_learner(),
        library=library,
        store=Store(default_db_path()),
    )


_session = _build_session()

app = FastAPI(
    title="APEX Dashboard API",
    description="AI-Powered eXperiential Education — live knowledge web and practice API",
    version="0.4.0",
)

app.mount("/static", StaticFiles(directory=_static_dir), name="static")


# ---------------------------------------------------------------------------
# Rendering (Jinja is only used to inject the learner id; the page itself is
# a static shell so the frontend can never drift from the Python data model)
# ---------------------------------------------------------------------------

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    _jinja: Environment | None = Environment(
        loader=FileSystemLoader(str(_templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
except ImportError:  # pragma: no cover - jinja is a dashboard extra
    _jinja = None


def _render(name: str, **context: Any) -> str:
    if _jinja is None:
        raise RuntimeError("jinja2 is required to serve dashboard pages")
    return _jinja.get_template(name).render(**context)


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class GraphNode(BaseModel):
    id: str
    name: str
    kind: str
    summary: str = ""
    mastery: float = 0.0
    mastered: bool = False
    unlocked: bool = False
    has_exercises: bool = False
    # Declared intent (wantToLearn/learning/learned) or None; the 3D web
    # colours intent nodes cyan even before their mastery moves.
    intent: str | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: str
    confirmed: bool | None = None


class GraphPayload(BaseModel):
    learner: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    stats: dict[str, Any]


class StatsResponse(BaseModel):
    stats: dict[str, Any]


class ProposalItem(BaseModel):
    concept_id: str
    name: str
    summary: str
    kind: str
    reason: str
    has_exercises: bool
    neighbours: list[str] = []


class ProposalList(BaseModel):
    proposals: list[ProposalItem]


class CourseProgressItem(BaseModel):
    id: str
    title: str
    description: str
    skills: list[str]
    solved: int
    total: int
    mastery: float
    complete: bool
    level: str


class CourseListResponse(BaseModel):
    courses: list[CourseProgressItem]


class ExercisePublic(BaseModel):
    id: str
    title: str
    kind: str = "code"
    language: str = "python"
    skills: list[str]
    difficulty: int
    prompt: str
    starter: str
    options: list[str] = []
    hints: list[str]
    tests: list[dict[str, Any]]


class NextExerciseResponse(BaseModel):
    exercise: ExercisePublic | None = None


class SubmissionResult(BaseModel):
    exercise_id: str
    passed: bool
    passed_count: int
    total: int
    score: float
    details: list[dict[str, Any]]
    duration_s: float
    newly_mastered: list[str]
    mastery_after: dict[str, float]


class AttemptItem(BaseModel):
    exercise: str
    passed: bool
    score: float
    duration: int
    ts: str


class AttemptsResponse(BaseModel):
    attempts: list[AttemptItem]


class ReviewItem(BaseModel):
    skill: str
    due_date: str
    interval_days: int
    ease_factor: float


class ScheduleResponse(BaseModel):
    learner_id: str
    items: list[ReviewItem]


class HealthResponse(BaseModel):
    health: dict[str, Any]


class IntentItem(BaseModel):
    id: str
    name: str
    kind: str
    mastery: float
    earned: bool
    has_exercises: bool


class IntentBoardResponse(BaseModel):
    wantToLearn: list[IntentItem]
    learning: list[IntentItem]
    learned: list[IntentItem]


class IntentRequest(BaseModel):
    concept_id: str
    state: str


class IntentResponse(BaseModel):
    concept: str
    state: str
    mastery: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session_or_503() -> LearningSession | JSONResponse:
    if _session.library is None:
        return JSONResponse(
            status_code=503,
            content={"detail": "content library not found; set APEX_CONTENT_DIR"},
        )
    return _session


def _library_or_503() -> ContentLibrary | JSONResponse:
    if _session.library is None:
        return JSONResponse(
            status_code=503,
            content={"detail": "content library not found; set APEX_CONTENT_DIR"},
        )
    return _session.library


def _due_reviews(learner: str, limit: int = 12) -> list[ReviewItem]:
    """Deterministic SM-2-style review schedule over mastered skills.

    Intervals grow with mastery (the better you know something, the longer
    the gap), and the anchor date is stable per skill, so the schedule does
    not reshuffle between refreshes.
    """
    library = _session.library
    mastery = _session.mastery()
    items: list[ReviewItem] = []
    today = date.today()
    for skill in sorted(library.skills):
        m = mastery.get(skill)
        if m is None or m < 0.5:
            continue
        interval = max(1, min(60, int(2 ** (m * 5))))
        anchor_days = int.from_bytes(skill.encode()[:2], "big") % 7
        due = today + timedelta(days=anchor_days - (today.toordinal() % interval or 0))
        items.append(
            ReviewItem(
                skill=skill,
                due_date=due.isoformat(),
                interval_days=interval,
                ease_factor=round(1.3 + m * 1.2, 2),
            )
        )
    items.sort(key=lambda r: r.due_date)
    return items[:limit]


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "service": "apex", "version": "0.3.0"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return HTMLResponse(_render("index.html", learner=_session.learner))


# ---------------------------------------------------------------------------
# Knowledge web API
# ---------------------------------------------------------------------------


@app.get("/api/graph", response_model=GraphPayload)
async def knowledge_graph() -> GraphPayload | JSONResponse:
    """The whole knowledge web, annotated with the learner's mastery."""
    session = _session_or_503()
    if isinstance(session, JSONResponse):
        return session
    return GraphPayload(**session.graph_payload())


@app.get("/api/stats", response_model=StatsResponse)
async def stats() -> StatsResponse | JSONResponse:
    session = _session_or_503()
    if isinstance(session, JSONResponse):
        return session
    return StatsResponse(stats=session.stats())


@app.get("/api/proposals", response_model=ProposalList)
async def proposals() -> ProposalList | JSONResponse:
    """What to learn next, with the reason each suggestion was made."""
    session = _session_or_503()
    if isinstance(session, JSONResponse):
        return session
    return ProposalList(proposals=[ProposalItem(**asdict(p)) for p in session.proposals()])


@app.get("/api/intents", response_model=IntentBoardResponse)
async def intent_board() -> IntentBoardResponse | JSONResponse:
    """The learner's declared intents: wantToLearn / learning / learned."""
    session = _session_or_503()
    if isinstance(session, JSONResponse):
        return session
    board = session.intent_board()
    return IntentBoardResponse(**board)


@app.post("/api/intents", response_model=IntentResponse)
def declare_intent(body: IntentRequest) -> IntentResponse | JSONResponse:
    """Declare intent on a concept (wantToLearn / learning / learned / archived)."""
    session = _session_or_503()
    if isinstance(session, JSONResponse):
        return session
    try:
        result = session.set_learning_state(body.concept_id, body.state)
    except KeyError:
        return JSONResponse(status_code=404, content={"detail": f"unknown concept '{body.concept_id}'"})
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return IntentResponse(**result)


@app.get("/api/health", response_model=HealthResponse)
async def content_health() -> HealthResponse | JSONResponse:
    library = _library_or_503()
    if isinstance(library, JSONResponse):
        return library
    return HealthResponse(health=library.health())


# ---------------------------------------------------------------------------
# Courses & practice API
# ---------------------------------------------------------------------------


@app.get("/api/courses", response_model=CourseListResponse)
async def list_courses() -> CourseListResponse | JSONResponse:
    session = _session_or_503()
    if isinstance(session, JSONResponse):
        return session
    out: list[CourseProgressItem] = []
    for progress in session.all_course_progress():
        out.append(
            CourseProgressItem(
                id=progress.course.id,
                title=progress.course.title,
                description=progress.course.description,
                skills=list(progress.course.skills),
                solved=progress.solved,
                total=progress.total,
                mastery=round(progress.mastery, 4),
                complete=progress.complete,
                level=progress.level,
            )
        )
    return CourseListResponse(courses=out)


@app.get("/api/practice/next", response_model=NextExerciseResponse)
async def next_exercise(course_id: str | None = None) -> NextExerciseResponse | JSONResponse:
    """The next exercise to attempt, chosen by weakest-skill-first."""
    session = _session_or_503()
    if isinstance(session, JSONResponse):
        return session
    exercise = session.next_exercise(course_id=course_id)
    if exercise is None:
        return NextExerciseResponse(exercise=None)
    return NextExerciseResponse(exercise=ExercisePublic(**exercise.public()))


class Submission(BaseModel):
    source: str = Field(min_length=1, max_length=20_000)


@app.post("/api/practice/submit", response_model=SubmissionResult)
def submit_solution(body: Submission, exercise_id: str) -> SubmissionResult | JSONResponse:
    # Deliberately a *sync* endpoint: grading shells out through asyncio.run
    # (the sandbox is async), which would raise inside a running event loop.
    # FastAPI runs sync handlers in a threadpool, so there is no loop here.
    """Grade browser-submitted code in the sandbox and update mastery.

    Same path as ``apex practice``: :meth:`LearningSession.submit` runs the
    hidden tests, applies the BKT update for every assessed skill, and
    records the attempt.
    """
    session = _session_or_503()
    if isinstance(session, JSONResponse):
        return session
    exercise = session.library.get_exercise(exercise_id)
    if exercise is None:
        return JSONResponse(status_code=404, content={"detail": f"unknown exercise '{exercise_id}'"})
    report = session.submit(body.source, exercise)
    return SubmissionResult(
        exercise_id=exercise.id,
        passed=report.passed,
        passed_count=report.passed_count,
        total=report.total,
        score=round(report.score, 4),
        details=report.details,
        duration_s=round(report.duration_s, 3),
        newly_mastered=report.newly_mastered,
        mastery_after={k: round(v, 4) for k, v in report.mastery_after.items()},
    )


@app.get("/api/attempts", response_model=AttemptsResponse)
async def attempts() -> AttemptsResponse | JSONResponse:
    session = _session_or_503()
    if isinstance(session, JSONResponse):
        return session
    rows = session.attempts()[-50:]
    return AttemptsResponse(
        attempts=[
            AttemptItem(
                exercise=r["exercise"],
                passed=bool(r["passed"]),
                score=float(r["score"]),
                duration=int(r["duration"]),
                ts=str(r["ts"]),
            )
            for r in rows
        ]
    )


@app.get("/api/schedule", response_model=ScheduleResponse)
async def schedule() -> ScheduleResponse:
    return ScheduleResponse(learner_id=_session.learner, items=_due_reviews(_session.learner))
