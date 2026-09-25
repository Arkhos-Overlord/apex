"""Tests for the SQLite persistence layer."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from apex.store import Store


@pytest.fixture
def tmp_store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.db")


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
