"""Learner state tracking for the APEX adaptive engine.

Records mastery scores, attempt history, confidence levels, and
evidence of learning so the engine can personalise progression.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LearnerState(BaseModel):
    """Mutable snapshot of everything the engine knows about a learner.

    Attributes:
        mastery_scores: Mapping from topic name to a mastery score in
            the range 0-100 (inclusive).
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
    """

    mastery_scores: dict[str, int] = Field(default_factory=dict)
    attempt_history: list[dict[str, Any]] = Field(default_factory=list)
    confidence_levels: dict[str, float] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    current_topic: str = ""
    errors: list[str] = Field(default_factory=list)
    attempts: int = 0
    confidence: float = 0.5
    pace: str = "normal"
    preferred_teacher: str | None = None

    model_config = ConfigDict(validate_assignment=True)

    def record_attempt(self, topic: str, result: bool) -> None:
        """Log a single attempt and update derived state.

        Args:
            topic: The topic that was attempted.
            result: True when the learner answered correctly, False
                otherwise.
        """
        now = datetime.now(UTC).isoformat()
        self.attempt_history.append({"topic": topic, "result": result, "timestamp": now})

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
        """Return the current mastery score for *topic*.

        Returns 0 when the learner has never attempted the topic.

        Args:
            topic: Topic name to look up.

        Returns:
            Mastery score in the range 0-100.
        """
        return self.mastery_scores.get(topic, 0)

    def next_topic(self) -> str | None:
        """Suggest the next topic to work on.

        Picks the topic with the lowest mastery score.  When multiple
        topics share the same minimum score the first one (in insertion
        order) is returned.  Returns ``None`` when no topics have been
        recorded yet.

        Returns:
            Topic name or ``None``.
        """
        if not self.mastery_scores:
            return None
        return min(self.mastery_scores, key=lambda k: self.mastery_scores[k])
