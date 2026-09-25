"""APEX — AI-Powered eXperiential Education Dashboard.

FastAPI backend serving learner progress, heatmaps, knowledge graphs,
course navigation, and spaced-repetition schedules.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from statistics import mean

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Data store (in-memory, seeded with realistic demo data)
# ---------------------------------------------------------------------------

COURSES = {
    "intro-python": {
        "id": "intro-python",
        "title": "Introduction to Python",
        "description": "Variables, loops, functions, and data structures.",
        "duration_weeks": 6,
        "modules": [
            {"id": "m1", "title": "Variables & Types", "lessons": 4},
            {"id": "m2", "title": "Control Flow", "lessons": 5},
            {"id": "m3", "title": "Functions", "lessons": 6},
            {"id": "m4", "title": "Data Structures", "lessons": 5},
            {"id": "m5", "title": "File I/O", "lessons": 3},
            {"id": "m6", "title": "Final Project", "lessons": 2},
        ],
    },
    "data-science": {
        "id": "data-science",
        "title": "Data Science Fundamentals",
        "description": "Pandas, NumPy, visualization, and statistical thinking.",
        "duration_weeks": 8,
        "modules": [
            {"id": "m1", "title": "NumPy & Arrays", "lessons": 4},
            {"id": "m2", "title": "Pandas Basics", "lessons": 6},
            {"id": "m3", "title": "Data Visualization", "lessons": 5},
            {"id": "m4", "title": "Statistical Inference", "lessons": 7},
            {"id": "m5", "title": "Machine Learning Intro", "lessons": 8},
        ],
    },
    "web-dev": {
        "id": "web-dev",
        "title": "Modern Web Development",
        "description": "HTML, CSS, JavaScript, and backend fundamentals.",
        "duration_weeks": 10,
        "modules": [
            {"id": "m1", "title": "HTML & Semantics", "lessons": 4},
            {"id": "m2", "title": "CSS Layouts", "lessons": 6},
            {"id": "m3", "title": "JavaScript Basics", "lessons": 8},
            {"id": "m4", "title": "DOM & Events", "lessons": 5},
            {"id": "m5", "title": "APIs & Fetch", "lessons": 4},
            {"id": "m6", "title": "Backend Basics", "lessons": 7},
        ],
    },
    "machine-learning": {
        "id": "machine-learning",
        "title": "Machine Learning Deep Dive",
        "description": "Supervised, unsupervised, and deep learning.",
        "duration_weeks": 12,
        "modules": [
            {"id": "m1", "title": "Linear Models", "lessons": 6},
            {"id": "m2", "title": "Decision Trees & Ensembles", "lessons": 7},
            {"id": "m3", "title": "Neural Networks", "lessons": 10},
            {"id": "m4", "title": "Convolutional & RNNs", "lessons": 8},
            {"id": "m5", "title": "Transformers", "lessons": 6},
        ],
    },
}

LEARNERS = {
    "alice": {
        "id": "alice",
        "name": "Alice Chen",
        "avatar": "AC",
        "joined": "2025-09-01",
        "courses": ["intro-python", "data-science"],
    },
    "bob": {
        "id": "bob",
        "name": "Bob Martinez",
        "avatar": "BM",
        "joined": "2025-10-15",
        "courses": ["web-dev", "machine-learning"],
    },
}

import hashlib


def _seed(learner_id: str, course_id: str, topic: str) -> float:
    h = hashlib.md5(f"{learner_id}:{course_id}:{topic}".encode()).hexdigest()
    return round(int(h[:6], 16) / 0xFFFF * 0.9 + 0.1, 2)


TOPICS_BY_COURSE = {
    "intro-python": ["variables", "loops", "functions", "lists", "dicts", "file-io"],
    "data-science": ["numpy", "pandas", "matplotlib", "statistics", "regression"],
    "web-dev": ["html", "css", "javascript", "dom", "fetch", "backend"],
    "machine-learning": ["linear-models", "trees", "nn-basics", "cv", "transformers"],
}

MASTERY = {}
TIME_ON_TASK = {}
SCHEDULE = {}

for lid, ldata in LEARNERS.items():
    for cid in ldata["courses"]:
        topics = TOPICS_BY_COURSE.get(cid, [])
        MASTERY.setdefault(lid, {}).setdefault(cid, {})
        TIME_ON_TASK.setdefault(lid, {}).setdefault(cid, {})
        for t in topics:
            MASTERY[lid][cid][t] = _seed(lid, cid, t)
            TIME_ON_TASK[lid][cid][t] = round(_seed(lid, cid, t + "_time") * 120, 1)
        SCHEDULE.setdefault(lid, {}).setdefault(cid, [])
        from datetime import date, timedelta

        base = date.today()
        for i, t in enumerate(topics):
            SCHEDULE[lid][cid].append(
                {
                    "topic": t,
                    "next_review": (base + timedelta(days=2 + i * 3)).isoformat(),
                    "last_reviewed": (base - timedelta(days=1 + i * 2)).isoformat(),
                    "interval_days": 2 + i * 3,
                    "ease_factor": round(2.0 + i * 0.15, 2),
                }
            )

KNOWLEDGE_GRAPH = {
    "intro-python": [
        {"source": "variables", "target": "lists", "strength": 0.9},
        {"source": "variables", "target": "dicts", "strength": 0.8},
        {"source": "loops", "target": "lists", "strength": 0.95},
        {"source": "loops", "target": "functions", "strength": 0.7},
        {"source": "functions", "target": "file-io", "strength": 0.6},
        {"source": "dicts", "target": "file-io", "strength": 0.5},
        {"source": "lists", "target": "file-io", "strength": 0.7},
    ],
    "data-science": [
        {"source": "numpy", "target": "pandas", "strength": 0.9},
        {"source": "numpy", "target": "matplotlib", "strength": 0.85},
        {"source": "pandas", "target": "matplotlib", "strength": 0.8},
        {"source": "pandas", "target": "statistics", "strength": 0.75},
        {"source": "statistics", "target": "regression", "strength": 0.9},
        {"source": "matplotlib", "target": "regression", "strength": 0.6},
    ],
    "web-dev": [
        {"source": "html", "target": "css", "strength": 0.85},
        {"source": "css", "target": "javascript", "strength": 0.7},
        {"source": "javascript", "target": "dom", "strength": 0.95},
        {"source": "dom", "target": "fetch", "strength": 0.8},
        {"source": "fetch", "target": "backend", "strength": 0.75},
        {"source": "html", "target": "javascript", "strength": 0.5},
    ],
    "machine-learning": [
        {"source": "linear-models", "target": "trees", "strength": 0.6},
        {"source": "trees", "target": "nn-basics", "strength": 0.7},
        {"source": "nn-basics", "target": "cv", "strength": 0.85},
        {"source": "nn-basics", "target": "transformers", "strength": 0.75},
        {"source": "cv", "target": "transformers", "strength": 0.6},
        {"source": "linear-models", "target": "nn-basics", "strength": 0.5},
    ],
}

HEATMAP = {}
for lid, ldata in LEARNERS.items():
    HEATMAP[lid] = {}
    for cid in ldata["courses"]:
        rows = []
        from datetime import date, timedelta

        today = date.today()
        for i in range(60):
            d = (today - timedelta(days=59 - i)).isoformat()
            row = {"date": d, "topics": {}}
            for t in TOPICS_BY_COURSE.get(cid, []):
                row["topics"][t] = round(_seed(lid, cid, t + "_" + d[:8]) * 90, 1)
            rows.append(row)
        HEATMAP[lid][cid] = rows


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class HeatmapRow(BaseModel):
    date: str
    topics: dict[str, float]


class HeatmapResponse(BaseModel):
    learner_id: str
    course_id: str
    course_title: str
    data: list[HeatmapRow]


class KnowledgeGraphNode(BaseModel):
    id: str
    group: str


class KnowledgeGraphEdge(BaseModel):
    source: str
    target: str
    strength: float


class KnowledgeGraphResponse(BaseModel):
    learner_id: str
    course_id: str
    nodes: list[KnowledgeGraphNode]
    edges: list[KnowledgeGraphEdge]


class ScheduleItem(BaseModel):
    topic: str
    next_review: str
    last_reviewed: str
    interval_days: int
    ease_factor: float


class ScheduleResponse(BaseModel):
    learner_id: str
    course_id: str
    items: list[ScheduleItem]


class CourseProgressResponse(BaseModel):
    course_id: str
    course_title: str
    modules: list[dict]
    completion_pct: float = Field(ge=0, le=100)
    lessons_completed: int
    total_lessons: int


class CourseListResponse(BaseModel):
    courses: list[dict]


class LearnerProgressResponse(BaseModel):
    learner_id: str
    learner_name: str
    courses: list[dict] = []
    overall_mastery: float = 0.0
    total_time_on_task: float = 0.0
    topics_covered: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _learner_or_404(lid: str):
    if lid not in LEARNERS:
        return JSONResponse(status_code=404, content={"detail": f"Learner '{lid}' not found"})
    return LEARNERS[lid]


def _course_or_404(cid: str):
    if cid not in COURSES:
        return JSONResponse(status_code=404, content={"detail": f"Course '{cid}' not found"})
    return COURSES[cid]


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

from jinja2 import Environment, FileSystemLoader, select_autoescape

templates_dir = Path(__file__).parent / "templates"
static_dir = Path(__file__).parent / "static"

jinja_env = Environment(
    loader=FileSystemLoader(str(templates_dir)),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_template(name: str, context: dict):
    """Render a Jinja2 template to HTML string."""
    tmpl = jinja_env.get_template(name)
    return tmpl.render(**context)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="APEX Dashboard API",
    description="AI-Powered eXperiential Education — learner progress API",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------




@app.get('/health')
async def health_check():
    return {'status': 'healthy', 'service': 'apex', 'version': '0.1.0'}


@app.get("/")
async def index(request: Request):
    return HTMLResponse(content=render_template("index.html", {"request": request}))


@app.get("/course/{course_id}")
async def course_page(request: Request, course_id: str):
    course = _course_or_404(course_id)
    if isinstance(course, JSONResponse):
        return course
    return HTMLResponse(
        content=render_template("course.html", {"request": request, "course": course})
    )


@app.get("/lesson/{course_id}/{lesson_slug}")
async def lesson_page(request: Request, course_id: str, lesson_slug: str):
    course = _course_or_404(course_id)
    if isinstance(course, JSONResponse):
        return course
    return HTMLResponse(
        content=render_template(
            "lesson.html",
            {"request": request, "course": course, "lesson_slug": lesson_slug},
        )
    )


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@app.get("/api/learner/{learner_id}/progress", response_model=LearnerProgressResponse)
async def learner_progress(learner_id: str):
    learner = _learner_or_404(learner_id)
    if isinstance(learner, JSONResponse):
        return learner

    courses_summary = []
    all_masteries = []
    total_time = 0.0

    for cid in learner["courses"]:
        m = MASTERY.get(learner_id, {}).get(cid, {})
        t = TIME_ON_TASK.get(learner_id, {}).get(cid, {})
        avg_mastery = mean(m.values()) if m else 0.0
        course_time = sum(t.values()) if t else 0.0
        total_time += course_time
        all_masteries.extend(m.values())
        courses_summary.append(
            {
                "course_id": cid,
                "course_title": COURSES[cid]["title"],
                "average_mastery": round(avg_mastery, 3),
                "time_on_task_minutes": round(course_time, 1),
                "topics_covered": len(m),
            }
        )

    overall = mean(all_masteries) if all_masteries else 0.0
    total_topics = sum(len(MASTERY.get(learner_id, {}).get(cid, {})) for cid in learner["courses"])

    return LearnerProgressResponse(
        learner_id=learner_id,
        learner_name=learner["name"],
        courses=courses_summary,
        overall_mastery=round(overall, 3),
        total_time_on_task=round(total_time, 1),
        topics_covered=total_topics,
    )


@app.get("/api/learner/{learner_id}/heatmap", response_model=HeatmapResponse)
async def learner_heatmap(learner_id: str, course_id: str = None):
    learner = _learner_or_404(learner_id)
    if isinstance(learner, JSONResponse):
        return learner

    if course_id is None:
        course_id = learner["courses"][0] if learner["courses"] else None
    if course_id is None:
        return JSONResponse(status_code=400, content={"detail": "Learner has no courses"})

    if course_id not in COURSES:
        return JSONResponse(status_code=404, content={"detail": f"Course '{course_id}' not found"})

    data = HEATMAP.get(learner_id, {}).get(course_id, [])
    return HeatmapResponse(
        learner_id=learner_id,
        course_id=course_id,
        course_title=COURSES[course_id]["title"],
        data=[HeatmapRow(**row) for row in data],
    )


@app.get("/api/learner/{learner_id}/knowledge-graph", response_model=KnowledgeGraphResponse)
async def learner_knowledge_graph(learner_id: str, course_id: str):
    learner = _learner_or_404(learner_id)
    if isinstance(learner, JSONResponse):
        return learner
    if course_id not in COURSES:
        return JSONResponse(status_code=404, content={"detail": f"Course '{course_id}' not found"})

    edges = KNOWLEDGE_GRAPH.get(course_id, [])
    nodes = []
    node_ids = set()
    for e in edges:
        node_ids.add(e["source"])
        node_ids.add(e["target"])
    for nid in sorted(node_ids):
        nodes.append(KnowledgeGraphNode(id=nid, group=course_id))

    return KnowledgeGraphResponse(
        learner_id=learner_id,
        course_id=course_id,
        nodes=nodes,
        edges=[
            KnowledgeGraphEdge(source=e["source"], target=e["target"], strength=e["strength"])
            for e in edges
        ],
    )


@app.get("/api/learner/{learner_id}/schedule", response_model=ScheduleResponse)
async def learner_schedule(learner_id: str, course_id: str):
    learner = _learner_or_404(learner_id)
    if isinstance(learner, JSONResponse):
        return learner
    if course_id not in COURSES:
        return JSONResponse(status_code=404, content={"detail": f"Course '{course_id}' not found"})

    items = SCHEDULE.get(learner_id, {}).get(course_id, [])
    return ScheduleResponse(
        learner_id=learner_id,
        course_id=course_id,
        items=[ScheduleItem(**item) for item in items],
    )


@app.get("/api/courses", response_model=CourseListResponse)
async def list_courses():
    return CourseListResponse(
        courses=[
            {
                "id": cid,
                "title": c["title"],
                "description": c["description"],
                "duration_weeks": c["duration_weeks"],
                "module_count": len(c["modules"]),
            }
            for cid, c in COURSES.items()
        ]
    )


@app.get("/api/course/{course_id}/progress", response_model=CourseProgressResponse)
async def course_progress(course_id: str):
    course = _course_or_404(course_id)
    if isinstance(course, JSONResponse):
        return course

    modules = course["modules"]
    total_lessons = sum(m["lessons"] for m in modules)
    lessons_done = round(total_lessons * 0.6)
    completion = round(lessons_done / total_lessons * 100, 1)

    return CourseProgressResponse(
        course_id=course_id,
        course_title=course["title"],
        modules=[
            {
                "id": m["id"],
                "title": m["title"],
                "lessons": m["lessons"],
                "completed_lessons": round(m["lessons"] * 0.6),
            }
            for m in modules
        ],
        completion_pct=completion,
        lessons_completed=lessons_done,
        total_lessons=total_lessons,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080, reload=False)
