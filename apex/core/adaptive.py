"""Adaptive difficulty engine using an Elo-like rating system.

Tracks each topic's hidden rating and the learner's rating per topic
to keep exercises inside the zone of proximal development (ZPD).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .learner import LearnerState


class AdaptiveDifficulty(BaseModel):
    """Elo-inspired difficulty adjustment engine.

    The model maintains a per-topic Elo rating for both the learner and
    the content.  After each performance sample the ratings are updated
    with the classic Elo update rule and the suggested difficulty for
    the next exercise is derived from the difference between the two
    ratings.

    Attributes:
        k_factor: Maximum change in rating points per observation.
        learner_ratings: Mapping from topic name to the learner's
            current Elo rating for that topic.
        topic_ratings: Mapping from topic name to the content's Elo
            rating for that topic (proxy for difficulty).
        default_rating: Starting rating assigned to brand-new topics.
    """

    k_factor: float = Field(default=32.0, ge=1.0, le=100.0)
    learner_ratings: dict[str, float] = Field(default_factory=dict)
    topic_ratings: dict[str, float] = Field(default_factory=dict)
    default_rating: float = Field(default=1200.0, ge=0.0)

    def suggest_difficulty(self, learner_state: LearnerState, topic: str) -> int:
        """Recommend a difficulty level (1-10) for the next exercise.

        The recommendation is based on the rating gap between the learner
        and the content for *topic*.  A large positive gap (content
        harder than the learner) pushes the suggestion toward 1;
        a large negative gap pushes it toward 10.

        Args:
            learner_state: Current state of the learner.
            topic: Topic to generate a difficulty recommendation for.

        Returns:
            Integer between 1 and 10 inclusive.
        """
        learner_rating = self.learner_ratings.get(topic, self.default_rating)
        topic_rating = self.topic_ratings.get(topic, self.default_rating)
        gap = learner_rating - topic_rating
        # Map gap roughly from [-400, 400] to [1, 10]
        clamped = max(-400.0, min(400.0, gap))
        normalized = (clamped + 400.0) / 800.0  # 0.0 -> 1.0
        raw = 1.0 + normalized * 9.0  # 1.0 -> 10.0
        return max(1, min(10, int(raw)))

    def update_model(self, learner_state: LearnerState, topic: str, performance: float) -> None:
        """Update Elo ratings after a performance observation.

        Performance is expected as a float in the range [0.0, 1.0] where
        1.0 means perfect and 0.0 means completely incorrect.

        Args:
            learner_state: Current learner state (used to seed the
                learner rating if the topic is unseen).
            topic: Topic that was attempted.
            performance: Observed performance in [0.0, 1.0].
        """
        if not (0.0 <= performance <= 1.0):
            raise ValueError("performance must be between 0.0 and 1.0")

        learner_rating = self.learner_ratings.get(topic, self.default_rating)
        topic_rating = self.topic_ratings.get(topic, self.default_rating)

        expected = 1.0 / (1.0 + 10.0 ** ((topic_rating - learner_rating) / 400.0))
        delta = self.k_factor * (performance - expected)

        self.learner_ratings[topic] = learner_rating + delta
        self.topic_ratings[topic] = topic_rating - delta

    @property
    def zpd_topics(self) -> list[str]:
        """Return topics that sit inside the learner's zone of proximal
        development.

        A topic is considered inside the ZPD when the rating gap
        between content and learner is in the range (-100, 100),
        i.e. the content is neither trivially easy nor impossibly hard.

        Returns:
            List of topic names currently inside the ZPD.
        """
        result: list[str] = []
        for topic, tr in self.topic_ratings.items():
            lr = self.learner_ratings.get(topic, self.default_rating)
            gap = tr - lr
            if -100.0 < gap < 100.0:
                result.append(topic)
        return result
