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
    the content.  After each performance sample the learner's rating is
    updated with the classic Elo rule, and the gap between the two ratings
    becomes the suggested difficulty for the next exercise.

    The content rating does *not* track the learner's rating one-for-one.
    Doing that is the obvious implementation and it is a no-op: if both
    sides move by the same delta the gap is invariant, so
    :meth:`suggest_difficulty` and :attr:`zpd_topics` would return the
    same answer no matter how the learner performed.  The content rating
    therefore moves by a damped fraction of the learner's delta -- a
    smoothed difficulty estimate that still drifts toward what the learner
    has demonstrated, but slowly enough for the gap to mean something.

    Attributes:
        k_factor: Maximum change in the learner's rating per observation.
        difficulty_damping: Fraction of the learner's delta applied to the
            content rating, in (0, 1].  Smaller means the difficulty
            estimate is stickier and the gap is more responsive.
        learner_ratings: Mapping from topic name to the learner's
            current Elo rating for that topic.
        topic_ratings: Mapping from topic name to the content's Elo
            rating for that topic (proxy for difficulty).
        default_rating: Starting rating assigned to brand-new topics.
    """

    k_factor: float = Field(default=32.0, ge=1.0, le=100.0)
    difficulty_damping: float = Field(default=0.25, gt=0.0, le=1.0)
    learner_ratings: dict[str, float] = Field(default_factory=dict)
    topic_ratings: dict[str, float] = Field(default_factory=dict)
    default_rating: float = Field(default=1200.0, ge=0.0)

    def suggest_difficulty(self, learner_state: LearnerState, topic: str) -> int:
        """Recommend a difficulty level (1-10) for the next exercise.

        The recommendation tracks the rating *gap* between the learner and
        the content for *topic*.  A learner rated well above the content
        has found it easy and should be pushed toward harder material, so
        a large positive gap raises the suggestion; a learner rated below
        the content is struggling and the suggestion falls toward 1.

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

    def _seed_learner_rating(self, learner_state: LearnerState, topic: str) -> float:
        """Return the learner's starting rating for *topic*.

        Seeds from the learner's recorded 0-100 mastery for the topic when
        there is one, mapped onto the Elo scale, so a returning learner's
        first observation is judged against what they already know rather
        than against a flat 1200.  Falls back to :attr:`default_rating`
        when the topic is unseen.
        """
        mastery = learner_state.mastery_scores.get(topic)
        if mastery is None:
            return self.default_rating
        # 0-100 mastery -> 800-1600 Elo, i.e. ±400 either side of default.
        return self.default_rating + (mastery - 50.0) * 8.0

    def update_model(self, learner_state: LearnerState, topic: str, performance: float) -> None:
        """Update Elo ratings after a performance observation.

        Performance is expected as a float in the range [0.0, 1.0] where
        1.0 means perfect and 0.0 means completely incorrect.

        Args:
            learner_state: Current learner state, used to seed the
                learner's rating the first time a topic is seen.
            topic: Topic that was attempted.
            performance: Observed performance in [0.0, 1.0].

        Raises:
            ValueError: If *performance* is outside [0.0, 1.0].
        """
        if not (0.0 <= performance <= 1.0):
            raise ValueError("performance must be between 0.0 and 1.0")

        learner_rating = self.learner_ratings.get(
            topic, self._seed_learner_rating(learner_state, topic)
        )
        topic_rating = self.topic_ratings.get(topic, self.default_rating)

        expected = 1.0 / (1.0 + 10.0 ** ((topic_rating - learner_rating) / 400.0))
        delta = self.k_factor * (performance - expected)

        self.learner_ratings[topic] = learner_rating + delta
        # Damped, not equal: the gap has to be able to move.
        self.topic_ratings[topic] = topic_rating + delta * self.difficulty_damping

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
