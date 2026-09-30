"""SQLite persistence layer for APEX mastery and attempt data.

Provides a ``Store`` class that persists learner mastery scores and
attempt records to a SQLite database.  The store is designed to be
used standalone or injected into :class:`~apex.core.learner.LearnerState`
via the ``persistence`` parameter.
"""

from __future__ import annotations

import json
import pickle
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

PRECISION = 6

#: Every value the ``learning_states.state`` column accepts.
LEARNING_STATES = ("wantToLearn", "learning", "learned", "archived")
_LEARNING_STATES = frozenset(LEARNING_STATES)
"""Decimal places preserved for mastery probabilities."""


def _encode_mastery(mastery: dict[str, float]) -> str:
    """Serialise a mastery mapping to a JSON string.

    JSON rather than pickle because this is a data file, not an object
    graph: a learner should be able to open their database in a text
    editor, and a future change to the mastery representation should not
    make every existing database unreadable.  Pickle also executes
    arbitrary code on load, which is a poor default for a file that could
    arrive from a backup or a shared machine.
    """
    return json.dumps({k: round(float(v), PRECISION) for k, v in mastery.items()}, sort_keys=True)


def _decode_mastery(raw: Any) -> dict[str, float]:
    """Deserialise a stored mastery payload back into a dict.

    Accepts the JSON written by :func:`_encode_mastery` and, for databases
    created before that change, the pickled list-of-pairs that
    ``set_mastery`` used to write.

    Args:
        raw: The value read from the ``mastery.p`` column, or ``None``.

    Returns:
        Mapping of skill name to a mastery probability in [0, 1].

    Raises:
        StoreError: If the payload is neither readable JSON nor a legacy
            pickle, rather than letting a decode error escape as an
            unrelated exception type.
    """
    if raw is None:
        return {}

    if isinstance(raw, memoryview):
        raw = raw.tobytes()

    if isinstance(raw, bytes):
        # Legacy pickle payload -- only reached for databases written
        # before the switch to JSON.
        try:
            pairs = pickle.loads(raw)
        except Exception as exc:
            raise StoreError(f"mastery payload is not readable: {exc!r}") from exc
        return {str(k): float(v) for k, v in pairs}

    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise StoreError(f"mastery payload is not valid JSON: {exc!r}") from exc

    if not isinstance(data, dict):
        raise StoreError(f"mastery payload must be a JSON object, got {type(data).__name__}")
    return {str(k): float(v) for k, v in data.items()}


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
        """Create the mastery and attempts tables if they do not exist.

        Also creates the parent directory.  The default database lives at
        ``~/.apex/apex.db``, and a first run has no ``~/.apex`` -- SQLite
        does not create intermediate directories, so without this the very
        first command a new user runs fails with "unable to open database
        file".
        """
        if self._readonly:
            raise StoreError("Cannot initialise schema in read-only mode")
        self._ensure_parent()
        with self._session() as conn:
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
                CREATE TABLE IF NOT EXISTS edges (
                    learner   TEXT NOT NULL,
                    source    TEXT NOT NULL,
                    target    TEXT NOT NULL,
                    relation  TEXT NOT NULL,
                    accepted  INTEGER NOT NULL,
                    ts        TEXT NOT NULL,
                    PRIMARY KEY (learner, source, target, relation)
                );
                CREATE TABLE IF NOT EXISTS learning_states (
                    learner   TEXT NOT NULL,
                    concept   TEXT NOT NULL,
                    state     TEXT NOT NULL CHECK (state IN
                              ('wantToLearn', 'learning', 'learned', 'archived')),
                    ts        TEXT NOT NULL,
                    PRIMARY KEY (learner, concept)
                );
                """
            )

    # ── connection helper ───────────────────────────────────────────────

    def _ensure_parent(self) -> None:
        """Create the directory holding the database, if it is missing."""
        parent = Path(self._db_path).expanduser().parent
        if str(parent) and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        """Return a new connection to the database.

        Read-only connections use the ``file:...&mode=ro`` URI scheme
        supported by the SQLite OS layer.

        The caller owns the returned connection and must close it; use
        :meth:`_session` rather than calling this directly.
        """
        if self._readonly:
            uri = f"file:{self._db_path}?mode=ro"
            return sqlite3.connect(uri, uri=True)
        return sqlite3.connect(self._db_path)

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection, committing writes and always closing it.

        ``with sqlite3.connect(...) as conn`` is a common mistake here: it
        is a *transaction* context manager, so it commits or rolls back but
        never closes. Every read and write then leaks a file handle until
        the garbage collector gets round to it -- which on Windows shows up
        as the database file being locked against deletion or rewrite for
        the rest of the process's life.
        """
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ── mastery ─────────────────────────────────────────────────────────

    def get_mastery(self, learner: str) -> dict[str, float]:
        """Return the mastery dict for *learner*.

        Returns an empty dict when *learner* has no recorded mastery.

        Args:
            learner: Unique learner identifier.

        Returns:
            Mapping from skill name to a mastery probability in [0, 1].
        """
        with self._session() as conn:
            row = conn.execute("SELECT p FROM mastery WHERE learner = ?", (learner,)).fetchone()
        return _decode_mastery(row[0] if row else None)

    def set_mastery(self, learner: str, mastery_dict: dict[str, float]) -> None:
        """Persist *mastery_dict* for *learner*, replacing any existing row.

        Args:
            learner: Unique learner identifier.
            mastery_dict: Mapping from skill name to a mastery probability
                in [0, 1].

        Raises:
            StoreError: When the store is opened in read-only mode or the
                database write fails.
        """
        if self._readonly:
            raise StoreError("Cannot write in read-only mode")
        payload = _encode_mastery(mastery_dict)
        with self._session() as conn:
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
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        with self._session() as conn:
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
        with self._session() as conn:
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
        with self._session() as conn:
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
        with self._session() as conn:
            mastery_rows = conn.execute("SELECT learner FROM mastery").fetchall()
            attempt_rows = conn.execute("SELECT DISTINCT learner FROM attempts").fetchall()
        combined = {r[0] for r in mastery_rows} | {r[0] for r in attempt_rows}
        return sorted(combined)

    # ── learner-confirmed edges ────────────────────────────────────────

    def set_edge_verdict(
        self,
        learner: str,
        source: str,
        target: str,
        relation: str,
        accepted: bool,
    ) -> None:
        """Record whether a learner agreed that a relation holds.

        The verdict is the only ground truth about prerequisite order --
        no knowledge graph can infer it, because 'you must learn loops
        before recursion' is a claim about teaching, not about the world.
        Storing the accept *and* the reject case matters: a rejected
        prerequisite is evidence the learner does not need it, which is
        used to stop proposing it again.

        Raises:
            StoreError: When the store is opened in read-only mode.
        """
        if self._readonly:
            raise StoreError("Cannot write in read-only mode")
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        with self._session() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO edges
                    (learner, source, target, relation, accepted, ts)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (learner, source, target, relation, int(accepted), ts),
            )

    def edge_verdicts(self, learner: str) -> dict[tuple[str, str, str], bool]:
        """Every verdict this learner has given, keyed by the edge triple."""
        with self._session() as conn:
            rows = conn.execute(
                "SELECT source, target, relation, accepted FROM edges WHERE learner = ?",
                (learner,),
            ).fetchall()
        return {(r[0], r[1], r[2]): bool(r[3]) for r in rows}

    def rejected_relations(self, learner: str) -> set[tuple[str, str, str]]:
        """Edges the learner explicitly refused."""
        return {k for k, v in self.edge_verdicts(learner).items() if not v}

    # ── learning intent ─────────────────────────────────────────────────

    def set_learning_state(self, learner: str, concept: str, state: str) -> None:
        """Record that *learner* wants to learn / is learning / has learned *concept*.

        ``archived`` is the explicit opt-out: it suppresses the topic from
        proposals and selection without pretending the learner never said
        anything.

        Raises:
            StoreError: In read-only mode or on an invalid state value.
        """
        if state not in _LEARNING_STATES:
            raise StoreError(f"invalid learning state '{state}'")
        if self._readonly:
            raise StoreError("Cannot write in read-only mode")
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        with self._session() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO learning_states (learner, concept, state, ts)
                VALUES (?, ?, ?, ?)
                """,
                (learner, concept, state, ts),
            )

    def learning_states(self, learner: str) -> dict[str, str]:
        """The learner's declared intents, keyed by concept id.

        ``archived`` rows are excluded — they are a negative signal, not a
        bucket the learner browses.
        """
        with self._session() as conn:
            rows = conn.execute(
                "SELECT concept, state FROM learning_states WHERE learner = ?",
                (learner,),
            ).fetchall()
        return {r[0]: r[1] for r in rows if r[1] != "archived"}

    def archived_concepts(self, learner: str) -> set[str]:
        """Concepts the learner has explicitly parked."""
        with self._session() as conn:
            rows = conn.execute(
                "SELECT concept FROM learning_states WHERE learner = ? AND state = 'archived'",
                (learner,),
            ).fetchall()
        return {r[0] for r in rows}

    # ── utility ─────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close any lingering connections (no-op for the context-manager
        based implementation but provided for interface completeness)."""
