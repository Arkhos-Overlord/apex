"""APEX Assessment & Spaced Repetition Engine.

SM-2 variant spaced repetition, auto-generated quizzes, and mastery scoring
with confidence intervals.

All data is kept in-memory (no storage layer); integrations that need
persistence should wrap these classes or subclass them.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Data types (lightweight dicts; typed for mypy)
# ---------------------------------------------------------------------------

LearnerState = dict[str, Any]
""" Learner state bag.  Keys are topic ids; values are metadata dicts.

Reserved inner keys: ``scores`` (list[float]) for overriding scorer data. """

Card = dict[str, Any]
""" Spaced-repetition card state.

Keys: ``material``, ``easiness_factor`` (float), ``interval`` (int days),
``repetitions`` (int), ``next_date`` (datetime), ``last_review`` (datetime). """

QuizQuestion = dict[str, Any]
""" A single quiz question.

Keys: ``question`` (str), ``options`` (list[str] | None), ``answer`` (str),
``difficulty`` (str), ``topic`` (str). """


# ===================================================================
# SpacedRepetition  (SM-2 variant)
# ===================================================================


class SpacedRepetition:
    """Manage spaced-repetition scheduling using an SM-2-inspired algorithm.

    Each unique *material* string maps to one card that tracks the
    easiness factor, interval, repetition count, and next review date.
    All state lives in a private dict — no persistence layer is included.
    """

    def __init__(self) -> None:
        self._cards: dict[str, Card] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def schedule_review(
        self,
        material: str,
        quality: int,
        *,
        now: datetime | None = None,
    ) -> Card:
        """Record a review for *material* with rating *quality* (0–5).

        Creates a new card on first encounter; updates an existing card
        otherwise, applying the SM-2 interpolation rules.

        Parameters
        ----------
        material:
            Identifying string for the learning item (e.g. ``"lesson:42"``).
        quality:
            Subjective recall quality 0–5.  0 = complete blackout,
            5 = perfect response.  Values outside [0, 5] are silently
            clamped.
        now:
            Override the "current time" — useful for deterministic tests.

        Returns
        -------
        Card
            The updated (or newly created) card.
        """
        reference = now if now is not None else datetime.now(UTC)
        card = dict(self._cards.get(material, self._new_card(material, reference)))
        self._advance(card, quality, reference)
        self._cards[material] = card
        return card

    def next_review_date(self, material: str, now: datetime | None = None) -> datetime:
        """Return the date the *material* is next due for review.

        Parameters
        ----------
        material:
            Material id that has already been scheduled.
        now:
            Override for the reference timestamp (unused; kept for
            API symmetry with other methods).

        Returns
        -------
        datetime
            The card's ``next_date``.

        Raises
        ------
        KeyError
            If *material* has not yet been scheduled.
        """
        try:
            return self._cards[material]["next_date"]
        except KeyError:
            raise KeyError(f"No card for material {material!r}") from None

    def get_due_reviews(
        self,
        learner_state: LearnerState,
        *,
        now: datetime | None = None,
    ) -> list[str]:
        """Return materials whose ``next_date`` is on or before *now*.

        Parameters
        ----------
        learner_state:
            May carry per-topic metadata; currently unused by this
            implementation but reserved for future filtering.
        now:
            Reference timestamp.  Defaults to ``datetime.now(timezone.utc)``.

        Returns
        -------
        list[str]
            Sorted list of due material ids.
        """
        reference = now if now is not None else datetime.now(UTC)
        due: list[str] = [
            material for material, card in self._cards.items() if card["next_date"] <= reference
        ]
        return sorted(due)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _new_card(material: str, now: datetime) -> Card:
        return {
            "material": material,
            "easiness_factor": 2.5,
            "interval": 0,
            "repetitions": 0,
            "next_date": now,
            "last_review": now,
        }

    @staticmethod
    def _advance(card: Card, quality: int, now: datetime) -> None:
        """Apply the SM-2 update rules to *card* in-place."""
        q = max(0, min(5, int(quality)))
        card["last_review"] = now

        if q < 3:
            card["repetitions"] = 0
            card["interval"] = 1
        else:
            card["repetitions"] += 1
            if card["repetitions"] == 1:
                card["interval"] = 1
            elif card["repetitions"] == 2:
                card["interval"] = 6
            else:
                new_interval = round(card["interval"] * card["easiness_factor"])
                card["interval"] = max(1, new_interval)

        # SM-2 easiness-factor update.
        ef = card["easiness_factor"]
        delta = 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)
        card["easiness_factor"] = max(1.3, ef + delta)

        # Schedule next review.
        card["next_date"] = now + timedelta(days=card["interval"])


# ===================================================================
# QuizGenerator
# ===================================================================


class QuizGenerator:
    """Generate lightweight quizzes from lesson content text.

    Uses sentence splitting, keyword blanking, and distractor sampling
    rather than an LLM call — quality varies and generated items should
    be reviewed before being presented to learners.
    """

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_mcq(
        self,
        content: str,
        count: int = 5,
    ) -> list[QuizQuestion]:
        """Generate multiple-choice questions from *content*.

        Creates up to *count* questions by blanking out a keyword in each
        sentence and offering the real word alongside distractors drawn
        from the rest of the text.

        Parameters
        ----------
        content:
            Lesson text to source questions from.
        count:
            Maximum number of questions to return.

        Returns
        -------
        list[QuizQuestion]
            Each item has keys ``question``, ``options``, ``answer``,
            ``difficulty``, ``topic``.
        """
        sentences = _split_sentences(content)
        self._rng.shuffle(sentences)
        questions: list[QuizQuestion] = []
        for sentence in sentences:
            if len(questions) >= count:
                break
            q = self._try_mcq(sentence, content)
            if q is not None:
                questions.append(q)
        return questions

    def generate_fill_blank(
        self,
        content: str,
        count: int = 3,
    ) -> list[QuizQuestion]:
        """Generate fill-in-the-blank questions from *content*.

        Parameters
        ----------
        content:
            Lesson text.
        count:
            Maximum number of questions to return.

        Returns
        -------
        list[QuizQuestion]
            Each item has ``options: None``, ``answer``, ``difficulty``,
            ``topic``, and a ``question`` containing ``______``.
        """
        sentences = _split_sentences(content)
        self._rng.shuffle(sentences)
        questions: list[QuizQuestion] = []
        for sentence in sentences:
            if len(questions) >= count:
                break
            q = self._try_fill_blank(sentence)
            if q is not None:
                questions.append(q)
        return questions

    def generate_coding_challenge(self, content: str) -> QuizQuestion:
        """Produce a single coding challenge prompt based on *content*.

        Returns
        -------
        QuizQuestion
            A dict with ``options: None``, ``answer: ""``, and metadata.
        """
        topic = _extract_topic(content) or "general"
        return {
            "question": (
                "Write a function that demonstrates your understanding of "
                f"{topic}. Include at least two test cases and handle "
                "edge cases appropriately."
            ),
            "options": None,
            "answer": "",
            "difficulty": "medium",
            "topic": topic,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _try_mcq(self, sentence: str, full_text: str) -> QuizQuestion | None:
        keyword = _pick_keyword(sentence.split(), self._rng)
        if not keyword or len(keyword) < 3:
            return None
        distractors = _pick_distractors(keyword, full_text, 3, self._rng)
        options = [keyword] + distractors
        self._rng.shuffle(options)
        blanked = sentence.replace(keyword, "______", 1)
        return {
            "question": f"Fill in the blank:\n{blanked}",
            "options": options,
            "answer": keyword,
            "difficulty": "easy",
            "topic": _extract_topic(full_text) or "general",
        }

    def _try_fill_blank(self, sentence: str) -> QuizQuestion | None:
        keyword = _pick_keyword(sentence.split(), self._rng)
        if not keyword or len(keyword) < 3:
            return None
        blanked = sentence.replace(keyword, "______", 1)
        return {
            "question": f"Complete the sentence:\n{blanked}",
            "options": None,
            "answer": keyword,
            "difficulty": "medium",
            "topic": _extract_topic(sentence) or "general",
        }


# ===================================================================
# MasteryScorer
# ===================================================================


class MasteryScorer:
    """Compute mastery scores (0–100) with simple confidence intervals.

    Tracks per-topic metrics: exposure count, assisted successes,
    independent successes, delayed-recall events, and a rolling score
    history used for confidence estimation.
    """

    def __init__(self) -> None:
        self._topics: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def calculate_score(
        self,
        attempts: int,
        accuracy: float,
        time_spent: float,
    ) -> float:
        """Convert raw performance metrics to a 0–100 mastery score.

        Parameters
        ----------
        attempts:
            Number of attempts the learner made.
        accuracy:
            Fraction correct, in [0, 1].
        time_spent:
            Seconds spent on the task (excess time is lightly penalised).

        Returns
        -------
        float
            Score in [0, 100].
        """
        if attempts <= 0 or not (0.0 <= accuracy <= 1.0):
            return 0.0
        base = accuracy * 100.0
        # Diminishing-returns bonus for persistence.
        effort = min(1.0, 1.0 + 0.1 * math.log2(max(1, attempts)))
        # Time penalty: 30-point cap, linear above 300 s.
        penalty = min(30.0, (time_spent / 300.0) * 30.0)
        return round(max(0.0, min(100.0, base * effort - penalty)), 2)

    def update_mastery(
        self,
        topic: str,
        score: float,
    ) -> dict[str, Any]:
        """Update tracked metrics for *topic* with a new *score*.

        Parameters
        ----------
        topic:
            Topic identifier.
        score:
            Score in [0, 100].

        Returns
        -------
        dict[str, Any]
            A copy of the updated topic snapshot.
        """
        if topic not in self._topics:
            self._topics[topic] = _empty_topic()
        t = self._topics[topic]
        t["exposure_count"] += 1
        t["scores"].append(score)
        if score >= 80:
            t["independent_success"] += 1
        elif score >= 50:
            t["assisted_success"] += 1
        return dict(t)

    def record_recall(
        self,
        topic: str,
        successful: bool,
    ) -> dict[str, Any]:
        """Record a delayed-recall event for *topic*.

        Parameters
        ----------
        topic:
            Topic identifier.
        successful:
            Whether the learner recalled correctly.

        Returns
        -------
        dict[str, Any]
            Updated topic snapshot.
        """
        if topic not in self._topics:
            self._topics[topic] = _empty_topic()
        t = self._topics[topic]
        if successful:
            t["delayed_recall"] += 1
        return dict(t)

    def get_confidence(
        self,
        learner_state: LearnerState,
        topic: str,
    ) -> dict[str, float]:
        """Return a confidence interval for the learner's mastery of *topic*.

        Uses a Hoeffding-style half-width of ``50 / sqrt(n)`` capped at 50.
        Learner-state overrides (via the ``scores`` key) take precedence over
        internally tracked data.

        Parameters
        ----------
        learner_state:
            May contain ``{topic: {scores: [...]}}`` overrides.
        topic:
            Topic identifier.

        Returns
        -------
        dict[str, float]
            Keys: ``score``, ``lower``, ``upper``, ``half_width``.
        """
        explicit = learner_state.get(topic)
        if isinstance(explicit, dict) and "scores" in explicit:
            scores = list(explicit["scores"])
        else:
            meta = self._topics.get(topic)
            scores = list(meta["scores"]) if meta else []

        if not scores:
            return {"score": 0.0, "lower": 0.0, "upper": 0.0, "half_width": 50.0}

        mean = sum(scores) / len(scores)
        n = len(scores)
        half_width = min(50.0, 50.0 / math.sqrt(max(1, n)))
        return {
            "score": round(mean, 2),
            "lower": round(max(0.0, mean - half_width), 2),
            "upper": round(min(100.0, mean + half_width), 2),
            "half_width": round(half_width, 2),
        }


# ===================================================================
# Module-level convenience wrappers
# ===================================================================


def schedule_review(material: str, quality: int) -> Card:
    """Single-use wrapper around ``SpacedRepetition.schedule_review``."""
    engine = SpacedRepetition()
    return engine.schedule_review(material, quality)


def next_review_date(material: str) -> datetime:
    """Single-use wrapper; primes the card with a mid rating if absent."""
    engine = SpacedRepetition()
    if material not in engine._cards:
        engine.schedule_review(material, 3)
    return engine.next_review_date(material)


def get_due_reviews(learner_state: LearnerState) -> list[str]:
    """Single-use wrapper around ``SpacedRepetition.get_due_reviews``."""
    engine = SpacedRepetition()
    return engine.get_due_reviews(learner_state)


# ===================================================================
# Private helpers
# ===================================================================

STOP_WORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "need",
        "dare",
        "ought",
        "used",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "under",
        "again",
        "further",
        "then",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "both",
        "each",
        "every",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "and",
        "but",
        "or",
        "because",
        "until",
        "while",
        "if",
        "this",
        "that",
        "these",
        "those",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
        "his",
        "its",
        "our",
        "their",
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "about",
        "up",
        "out",
        "off",
        "over",
    }
)


def _split_sentences(text: str) -> list[str]:
    """Split *text* into sentence-ish chunks (period/newline separated)."""
    parts: list[str] = []
    for raw in text.replace("\n", ".").split("."):
        s = raw.strip()
        if len(s) > 20:
            parts.append(s)
    return parts


def _pick_keyword(words: list[str], rng: random.Random) -> str | None:
    """Pick a blankable keyword from *words*, preferring longer non-stop words."""
    clean: list[str] = []
    for w in words:
        stripped = w.strip(".,!?;:\"'()[]{}").lower()
        if len(stripped) >= 4 and stripped not in STOP_WORDS:
            clean.append(stripped)
    if not clean:
        return None
    best = max(clean, key=lambda w: (len(w), hash(w) % 10000 / 10000.0))
    return best


def _pick_distractors(
    answer: str,
    full_text: str,
    n: int,
    rng: random.Random,
) -> list[str]:
    """Pick up to *n* distractors from *full_text* that differ from *answer*."""
    candidates: list[str] = []
    for sentence in _split_sentences(full_text):
        for w in sentence.split():
            stripped = w.strip(".,!?;:\"'()[]{}").lower()
            if len(stripped) >= 4 and stripped != answer and stripped not in candidates:
                candidates.append(stripped)
        if len(candidates) >= n:
            break
    rng.shuffle(candidates)
    return candidates[:n]


def _extract_topic(text: str) -> str | None:
    """Crude topic slug: first two meaningful words of the first sentence."""
    for sentence in _split_sentences(text):
        words = sentence.split()
        if len(words) >= 2:
            slug = "_".join(w.strip(".,!?;:\"'()[]{}").lower() for w in words[:2])
            if slug:
                return slug
    return None


def _empty_topic() -> dict[str, Any]:
    return {
        "exposure_count": 0,
        "assisted_success": 0,
        "independent_success": 0,
        "delayed_recall": 0,
        "scores": [],
    }
