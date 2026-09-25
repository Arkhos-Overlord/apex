"""Learner state tracking for the APEX adaptive engine.

Records mastery scores, attempt history, confidence levels, and
evidence of learning so the engine can personalise progression.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from apex.store import Store, StoreError

from .bkt import MASTERED, BKTParams
from .bkt import apply_attempt as bkt_apply_attempt

# ── Mode flag ──────────────────────────────────────────────────────────────

BKT_MODE: bool = False
"""Global switch.  When ``True`` the learner uses BKT probabilities
instead of integer mastery scores.

Set this to ``True`` before creating ``LearnerState`` instances to
enable BKT tracking.
"""


class LearnerState(BaseModel):
    """Mutable snapshot of everything the engine knows about a learner.

    Attributes:
        mastery_scores: Mapping from topic name to a mastery score in
            the range 0-100 (inclusive).  Used in Elo mode.
        mastery_probabilities: Mapping from skill name to a mastery
            probability in [0, 1].  Used in BKT mode.
        attempt_history: Chronological log of every attempt the learner
            has made. Each entry is a plain dict with at least the keys
            ``topic``, ``result``, and ``timestamp``.
        confidence_levels: Mapping from topic name to a confidence
            score between 0.0 (no confidence) and 1.0 (maximum
            confidence).
        evidence: Observable pieces of evidence that the learner has
            encountered a topic. Each entry carries a ``type`` key whose
            value is one of ``"exposure"``, ``"assisted"``, or
            ``"independent"``.
        bkt_params: BKT parameters used when ``BKT_MODE`` is active.
    """

    mastery_scores: dict[str, int] = Field(default_factory=dict)
    mastery_probabilities: dict[str, float] = Field(default_factory=dict)
    attempt_history: list[dict[str, Any]] = Field(default_factory=list)
    confidence_levels: dict[str, float] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    current_topic: str = ""
    errors: list[str] = Field(default_factory=list)
    attempts: int = 0
    confidence: float = 0.5
    pace: str = "normal"
    preferred_teacher: str | None = None
    bkt_params: BKTParams = Field(default_factory=BKTParams)
    persistence: Store | None = Field(default=None, exclude=True)

    model_config = ConfigDict(validate_assignment=True, arbitrary_types_allowed=True)

    def record_attempt(self, topic: str, result: bool) -> None:
        """Log a single attempt and update derived state.

        In BKT mode the update is applied to ``mastery_probabilities``
        via Bayesian Knowledge Tracing.  In Elo mode the integer
        ``mastery_scores`` are adjusted with the legacy +10 / -5 rule.

        Args:
            topic: The topic that was attempted.
            result: True when the learner answered correctly, False
                otherwise.
        """
        now = datetime.now(UTC).isoformat()
        self.attempt_history.append({"topic": topic, "result": result, "timestamp": now})

        if BKT_MODE:
            current = self.mastery_probabilities.get(topic, self.bkt_params.p_init)
            updated = bkt_apply_attempt(
                {topic: current},
                {topic},
                1.0 if result else 0.0,
                self.bkt_params,
            )
            self.mastery_probabilities[topic] = updated[topic]
        else:
            current = self.mastery_scores.get(topic, 0)
            current = min(100, current + 10) if result else max(0, current - 5)
            self.mastery_scores[topic] = current

        conf = self.confidence_levels.get(topic, 0.5)
        conf = min(1.0, conf + 0.05) if result else max(0.0, conf - 0.1)
        self.confidence_levels[topic] = conf

        self.evidence.append(
            {
                "type": "independent",
                "topic": topic,
                "timestamp": now,
            }
        )

    def get_mastery(self, topic: str) -> int:
        """Return the current mastery score for *topic* (Elo mode).

        Returns 0 when the learner has never attempted the topic.

        Args:
            topic: Topic name to look up.

        Returns:
            Mastery score in the range 0-100.
        """
        return self.mastery_scores.get(topic, 0)

    def get_mastery_probability(self, topic: str) -> float:
        """Return the current mastery probability for *topic* (BKT mode).

        Returns ``MASTERED`` (0.95) when the learner has never attempted
        the topic, signalling that the skill is assumed mastered for the
        purpose of exercise selection.

        Args:
            topic: Skill name to look up.

        Returns:
            Mastery probability in [0, 1].
        """
        return self.mastery_probabilities.get(topic, MASTERED)

    def is_mastered(self, topic: str) -> bool:
        """Return ``True`` when the topic is considered mastered.

        In BKT mode the threshold is ``MASTERED`` (0.95).
        In Elo mode a score of 100 is required.

        Args:
            topic: Topic / skill name.

        Returns:
            Whether the topic is mastered.
        """
        if BKT_MODE:
            return self.get_mastery_probability(topic) >= MASTERED
        return self.get_mastery(topic) >= 100

    def next_topic(self) -> str | None:
        """Suggest the next topic to work on.

        In Elo mode picks the topic with the lowest mastery score.
        In BKT mode picks the topic with the lowest mastery probability.

        Returns ``None`` when no topics have been recorded yet.

        Returns:
            Topic name or ``None``.
        """
        if BKT_MODE:
            if not self.mastery_probabilities:
                return None
            return min(self.mastery_probabilities, key=lambda k: self.mastery_probabilities[k])
        if not self.mastery_scores:
            return None
        return min(self.mastery_scores, key=lambda k: self.mastery_scores[k])

    # ── persistence ──────────────────────────────────────────────────────

    def save(self, learner: str) -> None:
        """Persist the current mastery scores to the attached store.

        Args:
            learner: Unique learner identifier passed to the store.

        Raises:
            StoreError: When ``persistence`` is ``None`` or the store
                write fails.
        """
        if self.persistence is None:
            raise StoreError("No persistence store attached")
        self.persistence.set_mastery(learner, {k: float(v) for k, v in self.mastery_scores.items()})

    def load(self, learner: str) -> None:
        """Replace in-memory mastery scores with those from the store.

        Also appends the reloaded topics to ``attempt_history`` as
        synthetic ``"exposure"`` evidence so downstream consumers see
        the full picture.

        Args:
            learner: Unique learner identifier to look up in the store.
        """
        if self.persistence is None:
            raise StoreError("No persistence store attached")
        stored = self.persistence.get_mastery(learner)
        now = datetime.now(UTC).isoformat()
        for topic, score in stored.items():
            self.mastery_scores[topic] = round(score)
            self.confidence_levels.setdefault(topic, 0.5)
            self.evidence.append({"type": "exposure", "topic": topic, "timestamp": now})
