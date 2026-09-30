# APEX v0.5 — Memory Science Spec

**Status:** draft for review · **Branch target:** `rework/engine-hardening` → PR to `master`
**Predecessor:** v0.4.0 (multi-domain + intent layer, 405 tests, 12/12 eval spec)

This spec is written the way this repo works: every line is a claim the code
must **prove** by running the real application. Nothing here is aspirational
prose — each criterion gets an adversarial acceptance check in
`apex/tests/eval_spec.py`, the same way S1–S12 work today.

---

## 0. TL;DR — what "top spec" means for v0.5

APEX currently has a strong *teaching* loop (prereq gates, BKT mastery,
intent steering, sandbox grading) but a weak *memory* loop:

| Component | v0.4 today | Problem | v0.5 target |
|---|---|---|---|
| Review scheduling | Per-node SM-2-ish `interval = 2^(m·5)` **derived from mastery, not from recall events**; dashboard `_schedule_items()` is fully synthetic | Mastery ≠ memory. A high-BKT node reviewed once never gets scheduled longer; a low-BKT node with proven stable memory is never released | **FSRS-5 DSR memory model** per node: Difficulty, Stability, Retrievability computed from *graded recall events* |
| Mastery | BKT update on attempt score | Fine, keep | Keep BKT as the **gate**; FSRS as the **scheduler** |
| Exercise selection | Weakest-first, intent-primary | No diversity pressure; knowledge-web browsing doesn't teach | Add **retrievability-below-target** as primary scheduler key + **interleaving** window |
| Due-review queue | `apex practice` and `/api/schedule` disagree | Two sources of truth | Single memory module; both surfaces read the same queue |
| Engagement | None | No retention loop between sessions | Streak-free **daily goal + retention-aware streak** (evidence-based, non-punitive) |
| Progress API | attempts + mastery only | Dashboard shows a number, not a trajectory | `/api/forecast` projects recall probability per node for N days |

The organizing claim of v0.5:

> **Mastery says what you can do. Memory says when you must practise it again.**
> v0.5 separates these two signals and wires them into one scheduler.

---

## 1. Evidence base (why these choices)

With citations, because a spec that asserts without citing is marketing.

### 1.1 Retrieval practice is the intervention APEX already makes

- Practice testing: weighted mean effect size **g ≈ 0.49** across 5
  meta-analyses, 744 studies, 902 effects (Visible Learning MetaX synthesis of
  Adesope et al. 2017 and successors).
- The benefit **grows with delay** — the testing effect is largest when the
  final test is more than a day after practice (Adesope et al. 2017;
  Rowland 2014). This is precisely APEX's position: it is a *longitudinal*
  system, so it should lean on retrieval, not re-exposure.

### 1.2 Spacing: the gap-to-retention rule

- Cepeda et al. 2006 (meta-analysis of 254 studies): optimal inter-study
  gap is **10–20% of the retention horizon**. APEX should schedule to a
  *requested retention* (default 0.9), not a fixed multiplier ladder.

### 1.3 FSRS-5 as the replacement for SM-2

- FSRS (open-spaced-repetition) is the current state of the art for
  open scheduler implementations; the project benchmark shows it beating
  SM-2 and neural baselines on real review logs (expertium.github.io
  benchmark; Ye 2023–2026 iterations FSRS-4.5 → FSRS-5 → FSRS-6).
- FSRS-5 uses **19 parameters** over the DSR (Difficulty, Stability,
  Retrievability) memory state:
  - Forgetting curve: `R(t,S) = (1 + FACTOR·t/S)^DECAY`, with
    `DECAY = −0.5`, `FACTOR = 19/81`, so `R(S,S) = 0.9`.
  - Next interval solving `R(t,S) = requested_retention`:
    `I(r,S) = S/FACTOR · (r^(1/DECAY) − 1)`.
  - Post-lapse stability: `S'_f = w11 · D^(−w12) · ((S+1)^w13 − 1) · e^(w14·(1−R))`
  - Recall stability (FSRS-4.5/5 core): `S'_r = S·(e^w8·(11−D)·S^(−w9)·(e^(w10·(1−R))−1)·G_w + 1)`
    where `G_w = w15` for hard, `w16` for easy.
  - Difficulty: `D0(G) = w4 − e^(w5·(G−1)) + 1`, updates with linear damping
    and mean reversion toward `D0(4)`; `D ∈ [1,10]`.
- Default w (FSRS-5): `[0.40255, 1.18385, 3.173, 15.69105, 7.1949, 0.5345, 1.4604, 0.0046, 1.54575, 0.1192, 1.01925, 1.9395, 0.11, 0.29605, 2.2698, 0.2315, 2.9898, 0.51655, 0.6621]`
  (APEX will vendor these constants and cite; optimisation of w from local
  logs is out of scope for v0.5.)
- Why not HLR (Duolingo, Settles & Meeder 2016)? HLR needs a trained
  regressor over lexeme-tag features and a proper training loop; APEX is a
  dependency-light local app. FSRS-5's fixed parameters give ~all the win
  with zero ML infra. Revisit HLR-style item features in v0.6+.

### 1.4 Interleaving — and its honest caveat

- Brunmair & Richter 2019 (59 studies): interleaved practice beats blocked,
  **g ≈ 0.42 overall**, but the effect is **moderator-dependent**: strongest
  for mathematics category-learning (g ≈ 0.34 here; up to ~0.83 in some
  nested designs) and weak/negative for expository texts and foreign-language
  vocabulary*.
- **Design consequence:** interleaving in APEX must be a *mixin*, not a rule.
  Within a domain that has confusable siblings (math operations, verb
  tenses), interleave; for isolated recall chains, keep blocks.

### 1.5 Feedback and motivation

- Feedback works, but **immediate vs delayed** matters less than assumed
  (meta-analytic d ≈ 0.09 difference; van der Kleij et al. 2015). APEX grades
  immediately — fine — but should prefer **retrieval-then-feedback** (learner
  commits an answer first, always true in APEX) and avoid showing answers
  before an attempt.
- Gamification meta-analysis (Sailer & Homner 2020, 39 studies): significant
  **cognitive g ≈ 0.49, motivational g ≈ 0.36** effects, with stronger effects
  in short interventions; badges alone ≈ null. Design consequence: minimal,
  competence-framed engagement layer (goal + honest streak), no point soup.

### 1.6 Learning Engineering data points we adopt

- **Desirable difficulty** (Bjork): at ~90% requested retention, ~10–15% of
  reviews *should* fail. A dashboard that never shows failures is scheduling
  too easy. Success metric: realized recall rate per week ∈ [0.80, 0.92].
- **Knowledge tracing** (BKT, Corbett & Anderson 1995) stays as the mastery
  gate — it is conceptually clean and already tested in this repo.
- **Duolingo-style forward forecasting** is the user-facing payoff of FSRS:
  show *predicted recall* per skill for the next 14 days, not just a due
  date — a forecast the model can actually be held to.

---

## 2. v0.5 Architecture

```
apex/
├── engine/
│   ├── memory.py          # NEW: FSRS-5 DSR core, pure functions
│   └── assessment.py      # SM-2 kept for compatibility, marked legacy
├── store.py               # +memory_states table (per node: D, S, last_review, history)
├── session.py             # submit() feeds memory.update(); next_exercise() merges due queue
├── cli/commands.py        # apex review (due queue CLI), apex forecast
└── dashboard/server.py    # /api/forecast; /api/schedule rewritten on memory module
```

### 2.1 `apex/engine/memory.py` — the FSRS-5 core (pure, testable)

```python
@dataclass(frozen=True)
class MemoryState:
    difficulty: float      # D ∈ [1, 10]
    stability: float       # S in days, ≥ 0.1
    last_review: datetime
    review_count: int
    lapse_count: int

def retrievability(state: MemoryState, now: datetime) -> float:
    """R(t,S) = (1 + FACTOR·t/S)^DECAY, DECAY=-0.5, FACTOR=19/81."""

def next_interval(state: MemoryState, request_retention: float = 0.9) -> int:
    """I(r,S) = S/FACTOR·(r^(1/DECAY)-1), days, ceil, min 1."""

def update(state: MemoryState | None, score: float, *, difficulty_hint: float,
           now: datetime) -> MemoryState:
    """Grade G∈{1..4} derived from exercise score & difficulty_hint.

    score≥0.95 → G=4, ≥0.80 → 3, ≥0.50 → 2, else 1 (lapse).
    difficulty_hint = exercise difficulty (1-5) mapped to D-range 1-10.
    """

def due(state: MemoryState, request_retention: float = 0.9) -> bool:
    """A node is due when R < request_retention (or never reviewed)."""
```

Design rules:
- **Pure functions, no I/O** — mirrors `apex/core/bkt.py` style; the session
  composes them.
- Score→grade mapping keeps *code* exercises honest: a hard exercise passed
  cleanly raises stability more than an easy one (via `difficulty_hint`
  damping the `S'_r` update), which is exactly FSRS's `(11−D)` term.

### 2.2 Store: `memory_states` table

```sql
CREATE TABLE IF NOT EXISTS memory_states (
  learner TEXT NOT NULL,
  node_id TEXT NOT NULL,
  difficulty REAL NOT NULL DEFAULT 5.0,
  stability REAL NOT NULL DEFAULT 0.5,
  last_review TEXT NOT NULL,
  review_count INTEGER NOT NULL DEFAULT 0,
  lapse_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (learner, node_id)
);
```

Plus `Store.memory_state(learner, node_id)` and
`Store.set_memory_state(...)`. Node-level (not per-exercise) because the
graph is the unit of steering.

### 2.3 Session integration

- `LearningSession.submit()` — after the BKT update, calls
  `memory.update(...)` for each skill in `exercise.skills` and persists.
- `next_exercise()` priority becomes:
  1. archived drop (unchanged)
   exercises of skills where `memory.due(node)` (R < 0.9), weakest-first
  3. new-skill queue (never-seen, prereq-unlocked), weakest-first
  4. interleaving window: ≥ 3 consecutive same-skill picks → force a
     different skill from the same domain's confusable set
- The **BKT mastery gate is unchanged** — FSRS never fabricates mastery.

### 2.4 Intent × memory (the two loops shake hands)

- `wantToLearn`/`learning` intent keeps its primary-sort role (v0.4).
- A `learned` claim on a node with `R < 0.7` shows an honest badge in the UI:
  "claimed — memory decayed, schedule a review" — never a lie, never a
  silent demotion.

### 2.5 API surface (v0.5)

| Endpoint | Change |
|---|---|
| `GET /api/forecast?days=14` | **New.** Per node: `[{node_id, name, r: [floats], due_date}]` |
| `GET /api/schedule` | Rewritten: real FSRS due dates, intervals, R now |
| `GET /api/graph` | nodes gain `stability`, `retrievability` (numeric, optional) |
| `POST /api/practice/submit` | response gains `memory_after: {stability, difficulty, interval}` |

⚠ FastAPI response-model footgun: every new field must be declared on the
Pydantic response model (GraphNode/GraphNode additions), per the v0.4 fix
for `kind/language/options/intent`.

### 2.6 CLI

```
apex review              # due-only practice session (R<0.9 nodes first)
apex forecast [days]     # table: node, R now, next interval, due date
apex learn board         # board gains per-node R and due badge
```

---

## 3. Eval-spec criteria (S13–S20, adversarial, run the real app)

The file `apex/tests/eval_spec.py` gains eight criteria. Each is a claim
the running system must prove; failure = spec regression.

| # | Criterion (written before implementation) | Pass condition |
|---|---|---|
| S13 | **FSRS core is correct at boundaries** | `retrievability(S,S)=0.9`; `next_interval(r=0.9, S) == S` (±1 day); R decreases monotonically with t; interval grows with S |
| S14 | **Lapses drop stability, successes raise it** | simulate 12-node log: after lapse S'f < S; after 3 clean passes S'' > S; difficulty drifts toward exercise's true difficulty |
| S15 | **Due queue beats weakest-first when both apply** | seed node A (high BKT, R=0.55, overdue) and B (low BKT, R=0.95); `next_exercise` returns A's exercise, *not* the weakest node's |
| S16 | **BKT gate is never bypassed by memory** | node with S=100d, R=0.99 but BKT mastery 0.30 stays `locked` for gate purposes; memory alone cannot mark mastery |
| S17 | **Forecast endpoint is honest** | `GET /api/forecast` for a node reviewed today with S=10d: R(7d) > R(10d) > R(14d); all values ∈ (0,1); due_date = day R crosses 0.9 |
| S18 | **Schedule surfaces agree** | `/api/schedule` and `apex review --dry-run` return the same due set for the same learner state |
| S19 | **Interleaving is a mixin, not a rule** | domain with 3 confusable siblings: ≥3 consecutive same-skill picks trigger a different-sibling pick; isolated domain: no forced switch |
| S20 | **Engagement data is honest** | streak counts a day with ≥1 graded attempt; a missed day breaks it; no fake "streak freeze" fabrications; `GET /api/engagement` returns {current, longest, today_done} |

### S13–S20 wiring into the existing harness

- Reuse `Ctx.cli()` for S15/S18/S20 CLI checks (`apex review --dry-run`,
  `apex forecast`).
- Reuse the FastAPI TestClient / DashboardHandler pattern from
  `apex/tests/test_intent.py` for S17/S18/S20 HTTP surfaces.
- S13/S14 are pure-math tests (`test_memory.py`) + eval spec mirrors them
  against the real module (not mocks).

---

## 4. Content work (must ship with the engine)

Engine changes without content are invisible to users. v0.5 ships:

1. **Confusable sets** for interleaving (S19): declare in skills YAML:
   ```yaml
   confusable-with: [multiplication, subtraction]   # sibling skill ids
   ```
2. **Review-density pass**: every skill needs ≥2 exercises tagged with
   `kind: recall|numeric` (fast static reviews; code reviews stay for
   deep practice). Target: +20 review exercises across math/spanish.
3. **Prompt hygiene for recall reviews**: every recall exercise must have
   `explanation` (shown post-attempt) — retrieval + feedback, not just
   right/wrong.

## 5. Dashboard work

- **Forecast ribbon** on the web tab: 14-day sparkline of portfolio recall
  (Σ R per day) rendered with Chart.js; node-level R in the detail panel.
- **Due-first practice tab**: "Reviews due today: N" badge; starting
  practice drains due items before new material.
- **Honest streak widget** (S20) in the sidebar: current / longest / today.
- Web tab detail panel gains a **memory row**: "stability ~12d · recall 78%
  today · due in 3d" — plain language, no jargon.

## 6. Non-goals for v0.5 (explicit)

- Parameter optimization from local logs (FSRS optimizer port) → v0.6+
- Per-exercise memory granularity (node-level is the right unit for steering)
- Neural schedulers (DASH/HLR training loops) — dependency-light constraint
- Multi-learner server features; APEX stays single-learner-local
- Mobile app, notifications/reminders (needs a push story, not this spec)

## 7. Migration & compat

- `memory_states` table is additive; SM-2 `SpacedRepetition` class stays
  (legacy, tested) but session no longer calls it. The eval spec S-gates
  that referenced the old synthetic schedule are rewritten to S17/S18.
- No content-format breaking change; `confusable-with` and `explanation`
  are additive YAML keys.
- Version bump: `0.4.0 → 0.5.0` (pyproject, `apex/__init__.py`,
  `dashboard/server.py` FastAPI version).

## 8. Test plan summary

- `apex/tests/test_memory.py` — new: ~40 tests (boundary math, lapse/raise
  invariants, grade mapping, store round-trip, session integration).
- `apex/tests/eval_spec.py` — S13–S20 appended, SPEC list updated; target
  **20/20 criteria**.
- Full suite target: **445+ passed** (405 + ~40 new), CI unchanged
  (pytest 3.11/3.12, node for JS grading, eval-spec gate).

## 9. Effort & sequencing (one developer-weeks shape)

| Step | Scope | Depends on |
|---|---|---|
| 1 | `memory.py` + `test_memory.py` (S13/S14) | — |
| 2 | `store.py` memory_states + round-trip tests | 1 |
| 3 | session.submit integration + next_exercise due-first (S15/S16) | 2 |
| 4 | `/api/schedule` rewrite + `/api/forecast` + CLI (S17/S18) | 3 |
| 5 | Interleaving mixin + confusable content (S19) | 3 |
| 6 | Engagement + dashboard widgets (S20) | 4 |
| 7 | Eval spec 20/20 green, README badge + docs | 1–6 |

## References

1. Adesope, Trevisan & Sundararajan (2017). *Rethinking the Use of Tests:
   A Meta-Analysis of Practice Testing.* Review of Educational Research.
2. Rowland (2014). *The effect of testing versus restudy on retention.*
   Psychological Bulletin.
3. Cepeda, Pashler, Vul, Wixted & Rohrer (2006). *Distributed practice in
   verbal recall tasks.* Psychological Bulletin, 132(3).
4. Brunmair & Richter (2019). *Similarity matters: A meta-analysis of
   interleaved learning and its moderators.* Psychological Bulletin.
5. Settles & Meeder (2016). *A Trainable Spaced Repetition Model for
   Language Learning (HLR).* ACL 2016.
6. Ye (2023–2026). *FSRS algorithm versions 4.5/5/6.*
   open-spaced-repetition/awesome-fsrs wiki, "The Algorithm".
7. Sailer & Homner (2020). *The Gamification of Learning: a Meta-analysis.*
   Educational Psychology Review.
8. van der Kleij et al. (2015). *Feedback in computer-based learning
   environments: a systematic review.* Computers in Human Behavior.
9. Corbett & Anderson (1995). *Knowledge tracing.* UMUAI.
10. Visible Learning MetaX (2024). *Practice testing* synthesis,
    visiblelearningmetax.com.
