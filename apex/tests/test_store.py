"""Tests for the SQLite persistence layer."""

from __future__ import annotations

import json
import pickle
import sqlite3
from pathlib import Path

import pytest

from apex.store import PRECISION, Store, StoreError


@pytest.fixture
def tmp_store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.db")


# ── mastery serialisation ───────────────────────────────────────────────


def test_mastery_is_stored_as_readable_json(tmp_store: Store) -> None:
    """The payload must be inspectable text, not an opaque pickle."""
    tmp_store.set_mastery("alice", {"io": 0.5, "arithmetic": 0.8})
    conn = sqlite3.connect(tmp_store._db_path)
    raw = conn.execute("SELECT p FROM mastery WHERE learner = 'alice'").fetchone()[0]
    conn.close()
    assert isinstance(raw, str)
    assert json.loads(raw) == {"arithmetic": 0.8, "io": 0.5}


def test_mastery_values_are_rounded_to_precision(tmp_store: Store) -> None:
    tmp_store.set_mastery("alice", {"io": 1 / 3})
    assert tmp_store.get_mastery("alice")["io"] == pytest.approx(1 / 3, abs=10**-PRECISION)


def test_legacy_pickled_mastery_still_loads(tmp_store: Store) -> None:
    """Databases written before the JSON switch must remain readable."""
    legacy = pickle.dumps([("io", 0.25), ("loops", 0.75)])
    conn = sqlite3.connect(tmp_store._db_path)
    conn.execute("INSERT OR REPLACE INTO mastery (learner, p) VALUES (?, ?)", ("old", legacy))
    conn.commit()
    conn.close()

    assert tmp_store.get_mastery("old") == {"io": 0.25, "loops": 0.75}


def test_corrupt_mastery_raises_store_error(tmp_store: Store) -> None:
    """A garbage payload raises StoreError, not an unrelated decode error."""
    conn = sqlite3.connect(tmp_store._db_path)
    conn.execute("INSERT OR REPLACE INTO mastery (learner, p) VALUES (?, ?)", ("bad", "{not json"))
    conn.commit()
    conn.close()

    with pytest.raises(StoreError):
        tmp_store.get_mastery("bad")


def test_non_object_mastery_raises_store_error(tmp_store: Store) -> None:
    """Valid JSON of the wrong shape is rejected rather than coerced."""
    conn = sqlite3.connect(tmp_store._db_path)
    conn.execute("INSERT OR REPLACE INTO mastery (learner, p) VALUES (?, ?)", ("bad", "[1, 2]"))
    conn.commit()
    conn.close()

    with pytest.raises(StoreError):
        tmp_store.get_mastery("bad")


def test_empty_mastery_round_trips(tmp_store: Store) -> None:
    tmp_store.set_mastery("alice", {})
    assert tmp_store.get_mastery("alice") == {}


# ── schema and CRUD ─────────────────────────────────────────────────────


def test_store_creates_tables(tmp_store: Store) -> None:
    """Store initializes the database schema."""
    assert tmp_store._db_path.exists()
    conn = sqlite3.connect(tmp_store._db_path)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn.close()
    table_names = {r[0] for r in rows}
    assert "mastery" in table_names
    assert "attempts" in table_names


def test_set_and_get_mastery(tmp_store: Store) -> None:
    """Store persists and retrieves mastery scores."""
    tmp_store.set_mastery("alice", {"io": 0.5, "arithmetic": 0.8})
    mastery = tmp_store.get_mastery("alice")
    assert mastery["io"] == pytest.approx(0.5)
    assert mastery["arithmetic"] == pytest.approx(0.8)


def test_get_mastery_unknown_learner(tmp_store: Store) -> None:
    """Unknown learner returns empty dict."""
    mastery = tmp_store.get_mastery("nobody")
    assert mastery == {}


def test_add_and_list_attempts(tmp_store: Store) -> None:
    """Store records and retrieves attempts."""
    tmp_store.add_attempt("alice", "py-hello", True, 1.0, 500)
    tmp_store.add_attempt("alice", "py-sum-two", False, 0.5, 200)
    attempts = tmp_store.attempts("alice")
    assert len(attempts) == 2
    assert attempts[0]["exercise"] == "py-hello"
    assert attempts[0]["passed"] == 1
    assert attempts[1]["passed"] == 0


def test_solved_exercises(tmp_store: Store) -> None:
    """Store returns only passed exercises."""
    tmp_store.add_attempt("alice", "py-hello", True, 1.0, 500)
    tmp_store.add_attempt("alice", "py-sum-two", False, 0.5, 200)
    solved = tmp_store.solved("alice")
    assert any(d.get("exercise") == "py-hello" for d in solved)
    assert not any(d.get("exercise") == "py-sum-two" for d in solved)


def test_learners_list(tmp_store: Store) -> None:
    """Store returns all learners."""
    tmp_store.add_attempt("alice", "py-hello", True, 1.0, 500)
    tmp_store.add_attempt("bob", "py-sum-two", False, 0.5, 200)
    learners = tmp_store.learners()
    assert "alice" in learners
    assert "bob" in learners


def test_set_mastery_overwrites(tmp_store: Store) -> None:
    """Setting mastery for the same skill overwrites."""
    tmp_store.set_mastery("alice", {"io": 0.5})
    tmp_store.set_mastery("alice", {"io": 0.9})
    mastery = tmp_store.get_mastery("alice")
    assert mastery["io"] == pytest.approx(0.9)


def test_concurrent_access(tmp_store: Store) -> None:
    """Multiple learners don't interfere."""
    tmp_store.set_mastery("alice", {"io": 0.5})
    tmp_store.set_mastery("bob", {"arithmetic": 0.7})
    assert tmp_store.get_mastery("alice")["io"] == pytest.approx(0.5)
    assert tmp_store.get_mastery("bob")["arithmetic"] == pytest.approx(0.7)
