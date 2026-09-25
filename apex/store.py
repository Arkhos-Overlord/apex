"""SQLite persistence layer for APEX mastery and attempt data.

Provides a ``Store`` class that persists learner mastery scores and
attempt records to a SQLite database.  The store is designed to be
used standalone or injected into :class:`~apex.core.learner.LearnerState`
via the ``persistence`` parameter.
"""

from __future__ import annotations

import sqlite3
from typing import Any

PECISION = 6  # decimal places preserved for mastery scores


def _adapt_dict(value: dict[str, float]) -> list[tuple[str, float]]:
    """Adapt a mastery dict for storage as a BLOB via sqlite3."""
    return [(k, round(v, PECISION)) for k, v in value.items()]


def _convert_dict(blob: bytes | None) -> dict[str, float]:
    """Convert a stored BLOB back into a mastery dict."""
    if blob is None:
        return {}
    pairs: list[tuple[str, float]] = __import__("pickle").loads(blob)
    return {k: float(v) for k, v in pairs}


class StoreError(Exception):
    """Raised when a persistence operation fails."""


class Store:
    """SQLite-backed persistence for APEX mastery and attempt data.

    Parameters:
        db_path: Path to the SQLite database file.  Defaults to
            ``apex.db`` in the current working directory.
        readonly: When ``True`` the connection is opened in read-only
            mode and write operations raise :exc:`StoreError`.

    Example::

        store = Store("learner_data.db")
        store.set_mastery("alice", {"python": 85.0, "sql": 60.0})
        mastery = store.get_mastery("alice")
        # {'python': 85.0, 'sql': 60.0}

        store.add_attempt("alice", "exercise_1", True, 95.0, 12000)
        for attempt in store.attempts("alice"):
            print(attempt)
    """

    def __init__(self, db_path: str = "apex.db", readonly: bool = False) -> None:
        self._db_path = db_path
        self._readonly = readonly
        if not readonly:
            self._init_schema()

    # ── schema ──────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        """Create the mastery and attempts tables if they do not exist."""
        if self._readonly:
            raise StoreError("Cannot initialise schema in read-only mode")
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS mastery (
                    learner   TEXT PRIMARY KEY,
                    p         BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    learner   TEXT    NOT NULL,
                    exercise  TEXT    NOT NULL,
                    passed    INTEGER NOT NULL,
                    score     REAL    NOT NULL,
                    duration  INTEGER NOT NULL,
                    ts        TEXT    NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_attempts_learner
                    ON attempts(learner);
                """
            )

    # ── connection helper ───────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        """Return a new connection to the database.

        Read-only connections use the ``file:...&mode=ro`` URI scheme
        supported by the SQLite OS layer.
        """
        if self._readonly:
            uri = f"file:{self._db_path}?mode=ro"
            return sqlite3.connect(uri, uri=True)
        return sqlite3.connect(self._db_path)

    # ── mastery ─────────────────────────────────────────────────────────

    def get_mastery(self, learner: str) -> dict[str, float]:
        """Return the mastery dict for *learner*.

        Returns an empty dict when *learner* has no recorded mastery.

        Args:
            learner: Unique learner identifier.

        Returns:
            Mapping from skill name to mastery score (0-100).
        """
        with self._connect() as conn:
            row = conn.execute("SELECT p FROM mastery WHERE learner = ?", (learner,)).fetchone()
        return _convert_dict(row[0] if row else None)

    def set_mastery(self, learner: str, mastery_dict: dict[str, float]) -> None:
        """Persist *mastery_dict* for *learner*, replacing any existing row.

        Args:
            learner: Unique learner identifier.
            mastery_dict: Mapping from skill name to mastery score (0-100).

        Raises:
            StoreError: When the store is opened in read-only mode or the
                database write fails.
        """
        if self._readonly:
            raise StoreError("Cannot write in read-only mode")
        payload = __import__("pickle").dumps(_adapt_dict(mastery_dict))
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO mastery (learner, p) VALUES (?, ?)",
                (learner, payload),
            )

    # ── attempts ────────────────────────────────────────────────────────

    def add_attempt(
        self,
        learner: str,
        exercise: str,
        passed: bool,
        score: float,
        duration_ms: int,
    ) -> int:
        """Record a single attempt and return its row id.

        Args:
            learner: Unique learner identifier.
            exercise: Identifier of the exercise attempted.
            passed: ``True`` when the learner passed the exercise.
            score: Fractional score in the range 0.0-100.0.
            duration_ms: Time taken in milliseconds.

        Returns:
            The auto-generated row id of the inserted attempt.

        Raises:
            StoreError: When the store is opened in read-only mode or the
                database write fails.
        """
        if self._readonly:
            raise StoreError("Cannot write in read-only mode")
        import time

        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO attempts (learner, exercise, passed, score, duration, ts)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (learner, exercise, int(passed), score, duration_ms, ts),
            )
            rid = cur.lastrowid
            assert rid is not None
            return rid

    def attempts(self, learner: str) -> list[dict[str, Any]]:
        """Return all attempts for *learner* in chronological order.

        Args:
            learner: Unique learner identifier.

        Returns:
            List of dicts with keys ``id``, ``learner``, ``exercise``,
            ``passed``, ``score``, ``duration``, ``ts``.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, learner, exercise, passed, score, duration, ts
                FROM attempts
                WHERE learner = ?
                ORDER BY ts ASC
                """,
                (learner,),
            ).fetchall()
        return [
            {
                "id": r[0],
                "learner": r[1],
                "exercise": r[2],
                "passed": bool(r[3]),
                "score": r[4],
                "duration": r[5],
                "ts": r[6],
            }
            for r in rows
        ]

    def solved(self, learner: str) -> list[dict[str, Any]]:
        """Return attempts where the learner passed, newest first.

        Args:
            learner: Unique learner identifier.

        Returns:
            List of passed attempt dicts ordered by ``ts`` descending.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, learner, exercise, passed, score, duration, ts
                FROM attempts
                WHERE learner = ? AND passed = 1
                ORDER BY ts DESC
                """,
                (learner,),
            ).fetchall()
        return [
            {
                "id": r[0],
                "learner": r[1],
                "exercise": r[2],
                "passed": bool(r[3]),
                "score": r[4],
                "duration": r[5],
                "ts": r[6],
            }
            for r in rows
        ]

    def learners(self) -> list[str]:
        """Return every learner id that has at least one record.

        Returns:
            Sorted list of unique learner identifiers present in the
            ``mastery`` and ``attempts`` tables.
        """
        with self._connect() as conn:
            mastery_rows = conn.execute("SELECT learner FROM mastery").fetchall()
            attempt_rows = conn.execute("SELECT DISTINCT learner FROM attempts").fetchall()
        combined = {r[0] for r in mastery_rows} | {r[0] for r in attempt_rows}
        return sorted(combined)

    # ── utility ─────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close any lingering connections (no-op for the context-manager
        based implementation but provided for interface completeness)."""
