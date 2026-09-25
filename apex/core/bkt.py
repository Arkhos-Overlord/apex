"""Bayesian Knowledge Tracing (BKT) for the APEX adaptive engine.

BKT models each skill as a hidden binary variable (known / unknown) and
updates the probability that the learner has mastered the skill after
every observed attempt, using Bayes' rule.

The four classic BKT parameters are:

* ``p_init`` – probability the skill is known before any observation.
* ``p_learn`` – probability the skill transitions from unknown → known
  on a single opportunity (learning rate).
* ``p_guess`` – probability of a correct response when the skill is
  *unknown* (guessing).
* ``p_slip`` – probability of an incorrect response when the skill is
  *known* (slipping).

References:
    Corbett, A. T., & Anderson, J. R. (1994). Knowledge tracing:
    Modeling the acquisition of procedural knowledge. User Modeling
    and User-Adapted Interaction, 4(4), 253–278.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Constants ────────────────────────────────────────────────────────────

MASTERED: float = 0.95
"""Mastery probability threshold above which a skill is considered mastered."""

# ── Parameter container ──────────────────────────────────────────────────


@dataclass(frozen=True)
class BKTParams:
    """Immutable container for the four Bayesian Knowledge Tracing parameters.

    Attributes:
        p_init: Prior probability the skill is known (0–1).
        p_learn: Per-attempt learning probability (0–1).
        p_guess: Guess probability when skill is unknown (0–1).
        p_slip: Slip probability when skill is known (0–1).
    """

    p_init: float = 0.25
    p_learn: float = 0.15
    p_guess: float = 0.20
    p_slip: float = 0.10

    def __post_init__(self) -> None:
        for name, val in (
            ("p_init", self.p_init),
            ("p_learn", self.p_learn),
            ("p_guess", self.p_guess),
            ("p_slip", self.p_slip),
        ):
            if not 0.0 <= val <= 1.0:
                raise ValueError(f"{name} must be in [0, 1], got {val}")


# ── Core BKT computations ────────────────────────────────────────────────


def predict_correct(p_known: float, params: BKTParams) -> float:
    """Probability the learner answers correctly given current knowledge.

    When the skill is known the learner slips with probability
    ``p_slip``, so the correct probability is ``1 - p_slip``.
    When the skill is unknown the learner guesses with probability
    ``p_guess``.

    Args:
        p_known: Current posterior probability the skill is known.
        params: BKT parameters.

    Returns:
        Probability of a correct response in [0, 1].
    """
    return p_known * (1.0 - params.p_slip) + (1.0 - p_known) * params.p_guess


def update(p_known: float, correct: bool, params: BKTParams) -> float:
    """Apply one observation and return the new posterior ``p_known``.

    Uses the standard BKT Bayesian update:

    * If the answer was **correct**, the posterior is driven upward
      because a correct answer is more likely when the skill is known.
    * If the answer was **incorrect**, the posterior is driven downward.

    Args:
        p_known: Prior probability the skill is known.
        correct: ``True`` when the learner answered correctly.
        params: BKT parameters.

    Returns:
        Updated posterior probability in [0, 1].
    """
    p_c = predict_correct(p_known, params)

    if p_c <= 0.0 or p_c >= 1.0:
        # Edge case: observation gives no information.
        return p_known

    if correct:
        # P(known | correct) ∝ P(correct | known) · P(known)
        likelihood_known = 1.0 - params.p_slip
        posterior = (likelihood_known * p_known) / p_c
    else:
        # P(known | incorrect) ∝ P(incorrect | known) · P(known)
        likelihood_known = params.p_slip
        posterior = (likelihood_known * p_known) / (1.0 - p_c)

    # Apply the learning transition: even unknown skills can become known.
    # After the observation, an unknown skill has probability p_learn of
    # transitioning to known.
    p_unknown = 1.0 - posterior
    posterior = posterior + p_unknown * params.p_learn

    return max(0.0, min(1.0, posterior))


# ── Exercise model ────────────────────────────────────────────────────────


class ExerciseDef:
    """A single exercise tied to one or more skill identifiers.

    Attributes:
        id: Unique identifier for the exercise.
        skills: Set of skill names this exercise assesses.
        content: Human-readable description or prompt.
    """

    def __init__(
        self,
        id: str,
        skills: set[str],
        content: str = "",
    ) -> None:
        self.id = id
        self.skills = frozenset(skills)
        self.content = content

    def __repr__(self) -> str:
        return f"Exercise(id={self.id!r}, skills={set(self.skills)!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ExerciseDef):
            return NotImplemented
        return self.id == other.id and self.skills == other.skills

    def __hash__(self) -> int:
        return hash((self.id, tuple(sorted(self.skills))))


# ── High-level helpers ────────────────────────────────────────────────────


_DEFAULT_PARAMS: BKTParams = BKTParams()
DEFAULT = _DEFAULT_PARAMS


def apply_attempt(
    mastery: dict[str, float],
    exercise_skills: set[str],
    score: float,
    params: BKTParams = _DEFAULT_PARAMS,
) -> dict[str, float]:
    """Update mastery probabilities after an exercise attempt.

    For each skill in ``exercise_skills``, the function treats the
    ``score`` (in [0, 1]) as a soft observation and applies the BKT
    update.  A score ≥ 0.5 is treated as a correct observation;
    otherwise incorrect.

    Args:
        mastery: Current mastery probabilities keyed by skill name.
        exercise_skills: Skills assessed by the exercise that was
            attempted.
        score: Observed performance in [0, 1].
        params: BKT parameters (defaults to ``BKTParams()``).

    Returns:
        A **new** dict with updated mastery probabilities.
    """
    if not 0.0 <= score <= 1.0:
        raise ValueError("score must be in [0, 1]")

    correct = score >= 0.5
    result: dict[str, float] = {}

    for skill, p_k in mastery.items():
        if skill in exercise_skills:
            p_k = update(p_k, correct, params)
        result[skill] = p_k

    # Seed any exercise skills not yet in mastery with p_init.
    for skill in exercise_skills:
        if skill not in result:
            result[skill] = params.p_init

    return result


def select_next(
    mastery: dict[str, float],
    solved: set[str],
    exercises: list[ExerciseDef],
    prm: BKTParams = _DEFAULT_PARAMS,
) -> ExerciseDef | None:
    """Choose the next exercise using a BKT-informed policy.

    The policy selects the exercise whose **minimum** skill mastery is
    the lowest among exercises that have not yet been solved and that
    contain at least one unmastered skill (below ``MASTERED``).

    When every exercise has been solved or every skill is mastered the
    function returns ``None``.

    Args:
        mastery: Current mastery probabilities keyed by skill name.
        solved: Set of exercise IDs that have already been solved.
        exercises: Candidate exercises to choose from.

    Returns:
        The selected ``Exercise`` or ``None`` when no suitable
        exercise exists.
    """
    best: ExerciseDef | None = None
    best_score: float = 2.0  # anything above 1.0

    for ex in exercises:
        if ex.id in solved:
            continue

        # Compute the minimum mastery across the exercise's skills.
        min_mastery = 1.0
        has_unmastered = False
        for skill in ex.skills:
            p = mastery.get(skill, prm.p_init)  # unseen → assume mastered
            if p < MASTERED:
                has_unmastered = True
            min_mastery = min(min_mastery, p)

        if not has_unmastered:
            continue

        if min_mastery < best_score:
            best_score = min_mastery
            best = ex

    return best
