"""Ad-hoc check: every exercise's reference solution must pass its own tests.

Run from the repo root:  python apex/tests/verify_content.py
Not part of the pytest suite -- this is the authoring tool that catches a
wrong `expected` block before it becomes a learner-facing failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apex.content import ContentLibrary
from apex.engine.code_exec import grade_code

ROOT = Path(__file__).resolve().parents[2] / "content"

lib = ContentLibrary(ROOT)
print(f"loaded {lib.skill_count} skills, {lib.course_count} courses, {lib.exercise_count} exercises\n")

failures = 0
for ex in lib.exercises.values():
    if not ex.solution.strip():
        print(f"SKIP {ex.id}: no solution")
        failures += 1
        continue
    grade = grade_code(ex.solution, ex.grader_cases())
    status = "ok  " if grade["score"] == 1.0 else "FAIL"
    if grade["score"] != 1.0:
        failures += 1
    print(f"{status} {ex.id:<20} {grade['passed']}/{grade['total']}")
    for detail in grade["details"]:
        if not detail["passed"]:
            print(f"       case {detail['description']}")
            print(f"         input    {detail['input']!r}")
            print(f"         expected {detail['expected']!r}")
            print(f"         got      {detail['got']!r}")

print()
if failures:
    print(f"{failures} exercise(s) failed")
    raise SystemExit(1)
print("all exercises verified")
