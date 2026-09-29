# Apex

An adaptive learning engine. It tracks what you know, decides what to teach
you next, grades what you write, and draws the result as a knowledge web
that grows as you go.

```bash
apex doctor              # is the content library sound?
apex courses             # what is there, and how far through are you?
apex practice            # attempt an exercise, graded against every test
apex progress            # mastery across the whole web
apex graph               # the web as a table, and where it grows next
apex dashboard           # the web, drawn
```

## The idea

Most learning software models a course as an ordered list. Apex models it as
a **graph**. Every concept is a node, and the ties between concepts are
typed:

| Relation | Meaning | Blocks progress? |
|---|---|---|
| `prereq` | you cannot read B before A | yes |
| `related` | adjacent material; neither needs the other | no |
| `contrasts-with` | commonly confused; the edge is the warning | no |
| `part-of` | containment, e.g. sorting is part-of algorithms | no |
| `applies-to` | a context the concept gets used in | no |

Only `prereq` gates what you may attempt. The rest exist so that "what else
should I look at" has an answer that is not a linear list.

The practical difference: a ladder of 10 skills and a web of 23 concepts with
121 typed edges are different products, and only one of them keeps offering
you something after you finish the syllabus.

## Never ending, without inventing anything

There is no fixed endpoint. Two mechanisms keep the web growing, and
neither one requires a model to guess:

**Knowledge nodes.** The library declares more concepts than it has
exercises for. A concept with no exercises is reading material, not a gate.
The moment someone writes its first exercise it is promoted to a gate and
everything downstream of it unlocks. That promotion *is* the growth
mechanism.

**Learner-confirmed edges.** No knowledge graph can infer that you must
learn loops before recursion — `subclass of` does not imply that. It is a
judgement about teaching. So apex asks instead of assuming:

```python
session.confirm_edge("arithmetic", "io", "prereq", accepted=False)
```

A refusal is stored and the edge stops being proposed. That makes the
learner's own corrections part of the graph rather than noise in it.

## How mastery works

Mastery is a probability per concept, in `[0, 1]`, updated by **Bayesian
Knowledge Tracing** (Corbett & Anderson, 1994). Four parameters:

- `p_init` — the prior that a skill is known
- `p_learn` — the chance of learning it on one opportunity
- `p_guess` — the chance of a correct answer when *not* known
- `p_slip` — the chance of a wrong answer when *known*

Two properties make this better than a running score:

- A correct answer is weak evidence, because a learner can guess.
- An incorrect answer is strong evidence, because a learner who knows the
  material does not usually get it wrong by accident.

Difficulty is kept separately by an Elo-style model that compares the
learner's rating against the content's. The two ratings move by *different*
amounts — moving them together would leave the gap invariant and make the
recommendation blind to how you did, which is a bug this codebase shipped
and then fixed.

The one rule that keeps the graph from deadlocking: **you only need to pass
what has tests.** Gating on a concept with no exercises would lock its
entire subtree away forever, since mastery only ever accrues to skills.

## Grading

Submissions run in a sandboxed subprocess with a wall-clock timeout, a
scrubbed environment, and output truncation. Grading compares stdout
against every test case, hidden ones included — you are not told which cases
exist, but passing requires getting all of them right.

`apex practice --solution` submits the reference implementation, which is how
you check the grader itself still works.

## The dashboard

`apex dashboard` starts a local server and draws the web with Cytoscape.
Node colour is your state: mastered, unlocked, still locked, or knowledge
with no test yet. Edge style is the relation. Click a node to see what it
depends on, what it relates to, and what learners confuse it with.

No build step and no npm. The page pulls Cytoscape from a CDN, so the UI
cannot drift out of sync with the Python feeding it, and it falls back to a
readable table when the CDN is unreachable rather than showing an empty
canvas.

## Running your code

The default `LocalPythonRunner` applies `RLIMIT_AS`, `RLIMIT_CPU`,
`RLIMIT_NPROC` and `RLIMIT_FSIZE` on POSIX, and scrubs the environment
everywhere. On Windows resource limits are unavailable, so only the timeout
and env scrubbing apply — a real limitation, documented rather than hidden.

`DockerRunner` is the stronger path: network none, read-only rootfs, all
capabilities dropped, PID and memory caps, and the script bind-mounted
read-only so the learner's code cannot rewrite itself.

## Layout

```
apex/
  graph.py            the knowledge web: typed relations, traversals
  content.py          YAML library, prerequisite gating, health checks
  session.py          the seam - library + store + BKT + grader
  store.py            SQLite persistence (JSON, not pickle)
  sandbox.py          LocalPythonRunner, DockerRunner
  core/
    bkt.py            Bayesian Knowledge Tracing
    adaptive.py       Elo-style difficulty and the ZPD
    learner.py        learner state
    course.py         lesson/chapter/course models
  engine/
    code_exec.py      sandboxed execution and grading
    assessment.py     SM-2 spaced repetition, quiz generation
    content_gen.py    SVG diagrams, code examples, PDF handouts
  teachers/           four teacher personas over topic concept packs
  cli/                the command layer
content/
  skills.yaml         the web: nodes and their typed relations
  courses.yaml        paths through the web
  exercises/          one graded exercise per file
```

Content lives at the repository root, outside the package, so the exercise
bank is reviewable as YAML. `session.default_content_root()` finds it by
walking up; `APEX_CONTENT_DIR` overrides.

## Authoring an exercise

One file per exercise in `content/exercises/`. Include a `solution` — it is
how the answer key gets verified.

```yaml
id: py-even-odd
title: Even or Odd
skills: [conditionals, arithmetic]     # every skill must exist in skills.yaml
difficulty: 2                          # 1-5
prompt: |
  Read one integer and report whether it is even or odd.
hints:
  - "The remainder operator is %."
starter: |
  n = int(input())
  print("odd")                          # runs, and is wrong
solution: |
  n = int(input())
  if n % 2 == 0:
      print("even")
  else:
      print("odd")
tests:
  - input: "4\n"
    expected: "even"
    hidden: false                       # shown to the learner
  - input: "7\n"
    expected: "odd"
    hidden: false
  - input: "0\n"
    expected: "even"
    hidden: true                        # graded, but not revealed
```

Then verify the answer key:

```bash
python apex/tests/verify_content.py
```

This runs every reference solution against its own tests. It matters: a
wrong `expected` block fails a correct learner, and that is not a bug the
learner can do anything about.

## Checking your work

```bash
python -m pytest apex/tests -q         # 341 unit tests
python apex/tests/eval_spec.py         # 11 spec criteria, evaluated end to end
python apex/tests/check_ui.py          # renders the dashboard in Chromium
```

`eval_spec.py` is deliberately adversarial. It submits wrong code and
requires it to fail, walks the graph checking that no exercise is offered
before its gates are met, and confirms the dashboard serves mastery values
that match the store — because those are the failures a happy-path test
cannot see.

`check_ui.py` exists because "the endpoint returns the right JSON" and
"the page draws a graph" are completely different claims. The first was
true while the second was completely broken: three JavaScript errors, all
swallowed by a bare `.catch`, left the viewer showing a fallback table
instead of the web. Only opening it in a browser found that.

## Configuration

`~/.apex/config.json`, editable with `apex config set <key> <value>`:

| Key | Meaning |
|---|---|
| `learner` | which profile the store is keyed by |
| `teacher` | default persona for `apex teach` |
| `db_path` | database location (default `~/.apex/apex.db`) |
| `content_dir` | content library location (default: auto-detected) |

Environment overrides, useful for scripting: `APEX_DB_PATH`,
`APEX_LEARNER`, `APEX_CONTENT_DIR`, `APEX_OUTPUT_DIR`.

## Status

Alpha. The engine, the content library, the grading and the dashboard are
real and tested. Known limitations:

- SM-2 spaced repetition is implemented but **not wired into the practice
  loop** — `engine/assessment.py` has no caller. `SpacedRepetition` is the
  natural scheduler for revisiting a skill once it is mastered, and is the
  clearest single gap between this and something that retains knowledge
  over months.
- Elo's rating gap responds to performance but its parameters are
  uncalibrated. `pykt` would give fitted values and a benchmark to check
  the BKT implementation against.
- Content is hand-authored. The graph is designed to be expanded by
  promoting a concept to a skill once its first exercise exists, but
  nothing automates discovering those concepts yet — ConceptNet or
  Wikidata would be the source, and any auto-generated `prereq` edge would
  need the learner's confirmation the API already supports.
- The dashboard pulls Cytoscape from a CDN. Fine locally, but an offline
  machine gets the fallback table rather than the graph.
- Only Python exercises. The grader supports JavaScript; the content does
  not use it yet.
- Windows runners get a timeout and a scrubbed environment but no
  `RLIMIT_*`; use `DockerRunner` for real isolation.
