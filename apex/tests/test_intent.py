"""The learner-intent layer: wantToLearn / learning / learned / archived.

Declaring intent is real engine signal, not a sticky note: it seeds the
BKT prior, reorders exercise selection, hides archived material, and is
auto-promoted when graded evidence crosses the mastery threshold.
"""

from __future__ import annotations

import pytest

from apex.core.bkt import DEFAULT, MASTERED
from apex.session import INTENT_PRIORS, LearningSession
from apex.store import LEARNING_STATES, Store, StoreError

# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def lib():
    from pathlib import Path

    from apex.content import ContentLibrary

    return ContentLibrary(Path(__file__).resolve().parents[2] / "content")


@pytest.fixture
def session(lib, tmp_path) -> LearningSession:
    return LearningSession("intent-tester", library=lib, store=Store(tmp_path / "intent.db"))


def _exercise_for(session: LearningSession, skill: str):
    return session.library.exercises_for_skill(skill)[0]


# ── store layer ──────────────────────────────────────────────────────────


class TestStoreLearningStates:
    def test_roundtrip(self, tmp_path) -> None:
        store = Store(tmp_path / "s.db")
        store.set_learning_state("alice", "loops", "learning")
        assert store.learning_states("alice") == {"loops": "learning"}

    def test_replace(self, tmp_path) -> None:
        store = Store(tmp_path / "s.db")
        store.set_learning_state("alice", "loops", "wantToLearn")
        store.set_learning_state("alice", "loops", "learning")
        assert store.learning_states("alice") == {"loops": "learning"}

    def test_per_learner_isolation(self, tmp_path) -> None:
        store = Store(tmp_path / "s.db")
        store.set_learning_state("alice", "loops", "learning")
        assert store.learning_states("bob") == {}

    def test_invalid_state_raises(self, tmp_path) -> None:
        store = Store(tmp_path / "s.db")
        with pytest.raises(StoreError):
            store.set_learning_state("alice", "loops", "kind-of")

    def test_archive_is_hidden_from_states(self, tmp_path) -> None:
        store = Store(tmp_path / "s.db")
        store.set_learning_state("alice", "loops", "archived")
        assert store.learning_states("alice") == {}
        assert store.archived_concepts("alice") == {"loops"}

    def test_states_constant(self) -> None:
        assert set(LEARNING_STATES) == {"wantToLearn", "learning", "learned", "archived"}


# ── session semantics ────────────────────────────────────────────────────


class TestDeclareIntent:
    def test_unknown_concept_raises(self, session: LearningSession) -> None:
        with pytest.raises(KeyError):
            session.set_learning_state("not-a-node", "learning")

    def test_invalid_state_raises(self, session: LearningSession) -> None:
        with pytest.raises(ValueError):
            session.set_learning_state("io", "sort-of")

    def test_learning_seeds_prior_above_default(self, session: LearningSession) -> None:
        result = session.set_learning_state("spanish-greetings", "learning")
        assert result["mastery"] == pytest.approx(INTENT_PRIORS["learning"])
        assert result["mastery"] > DEFAULT.p_init

    def test_seed_does_not_lower_existing_mastery(self, session: LearningSession) -> None:
        # Prove mastery first, then declare: the seed must never pull the
        # posterior back down.
        ex = _exercise_for(session, "spanish-greetings")
        session.submit(ex.answer, ex)
        proven = session.mastery()["spanish-greetings"]
        assert proven > DEFAULT.p_init
        session.set_learning_state("spanish-greetings", "wantToLearn")
        assert session.mastery()["spanish-greetings"] == pytest.approx(proven)

    def test_intent_radiates_to_neighbours(self, session: LearningSession) -> None:
        before = session.mastery()
        session.set_learning_state("order-of-operations", "learning")
        after = session.mastery()
        assert after["order-of-operations"] > before["order-of-operations"]
        neighbours = set(session.library.graph.neighbourhoods("order-of-operations", 1))
        fresh = [n for n in neighbours if before.get(n, DEFAULT.p_init) <= DEFAULT.p_init]
        assert fresh, "expected at least one untouched neighbour"
        for n in fresh:
            assert after[n] > before.get(n, DEFAULT.p_init)

    def test_learned_claim_does_not_fake_mastery(self, session: LearningSession) -> None:
        result = session.set_learning_state("io", "learned")
        # A claim may nudge nothing at all — crucially it must never cross
        # the mastery threshold on its own.
        assert result["mastery"] < MASTERED
        assert "io" not in session.mastered_ids()


class TestSelection:
    def test_learning_intent_jumps_the_queue(self, session: LearningSession) -> None:
        session.set_learning_state("order-of-operations", "learning")
        chosen = session.next_exercise()
        assert chosen is not None
        assert "order-of-operations" in chosen.skills

    def test_archive_hides_exercises(self, session: LearningSession) -> None:
        for skill in ("spanish-greetings", "spanish-numbers", "spanish-verbs", "spanish-family"):
            session.set_learning_state(skill, "archived")
        for _ in range(10):
            chosen = session.next_exercise()
            assert chosen is not None
            assert not ({"spanish-greetings", "spanish-numbers", "spanish-verbs", "spanish-family"} & set(chosen.skills))


class TestAutoPromotion:
    def test_proof_promotes_learning_to_learned(self, session: LearningSession) -> None:
        session.set_learning_state("spanish-greetings", "learning")
        ex = _exercise_for(session, "spanish-greetings")
        report = None
        for _ in range(15):
            report = session.submit(ex.answer, ex)
            if report.mastery_after["spanish-greetings"] >= MASTERED:
                break
        assert report is not None and report.mastery_after["spanish-greetings"] >= MASTERED
        assert "spanish-greetings" in report.promoted
        assert session.learning_states()["spanish-greetings"] == "learned"

    def test_no_intent_no_promotion(self, session: LearningSession) -> None:
        ex = _exercise_for(session, "spanish-greetings")
        report = None
        for _ in range(15):
            report = session.submit(ex.answer, ex)
            if report.mastery_after["spanish-greetings"] >= MASTERED:
                break
        assert report is not None
        assert report.promoted == []
        assert "spanish-greetings" not in session.learning_states()

    def test_board_reports_earned_flag(self, session: LearningSession) -> None:
        session.set_learning_state("spanish-greetings", "learning")
        ex = _exercise_for(session, "spanish-greetings")
        for _ in range(15):
            report = session.submit(ex.answer, ex)
            if report.mastery_after["spanish-greetings"] >= MASTERED:
                break
        learned = {i["id"]: i for i in session.intent_board()["learned"]}
        assert learned["spanish-greetings"]["earned"] is True

    def test_claimed_but_unproven_flag(self, session: LearningSession) -> None:
        session.set_learning_state("io", "learned")
        learned = {i["id"]: i for i in session.intent_board()["learned"]}
        assert learned["io"]["earned"] is False


# ── graph payload ────────────────────────────────────────────────────────


class TestGraphPayload:
    def test_intent_surfaces_on_nodes(self, session: LearningSession) -> None:
        session.set_learning_state("io", "learning")
        payload = session.graph_payload()
        node = next(n for n in payload["nodes"] if n["id"] == "io")
        assert node["intent"] == "learning"
        untouched = next(n for n in payload["nodes"] if n["id"] == "conditionals")
        assert untouched["intent"] is None


# ── dashboard APIs (both servers) ────────────────────────────────────────


class TestIntentAPIs:
    def test_fastapi_board_and_declare(self, tmp_path, monkeypatch) -> None:
        import importlib
        import os
        import sys

        sys.path.insert(0, ".")
        monkeypatch.setenv("APEX_DB", str(tmp_path / "api.db"))
        monkeypatch.setenv("APEX_DB_PATH", str(tmp_path / "api.db"))
        monkeypatch.setenv("APEX_CONTENT_DIR", str(__import__("pathlib").Path(__file__).resolve().parents[2] / "content"))
        import dashboard.server as srv

        importlib.reload(srv)
        from fastapi.testclient import TestClient

        client = TestClient(srv.app)

        declared = client.post(
            "/api/intents",
            json={"concept_id": "spanish-greetings", "state": "learning"},
        )
        assert declared.status_code == 200, declared.text
        assert declared.json()["state"] == "learning"

        board = client.get("/api/intents")
        assert board.status_code == 200
        ids = {i["id"] for i in board.json()["learning"]}
        assert "spanish-greetings" in ids

        bad = client.post("/api/intents", json={"concept_id": "nope", "state": "learning"})
        assert bad.status_code == 404
        invalid = client.post("/api/intents", json={"concept_id": "io", "state": "later"})
        assert invalid.status_code == 422

    def test_stdlib_server_board_and_declare(self, tmp_path) -> None:
        from pathlib import Path

        from apex.cli.dashboard import DashboardHandler as Handler
        from apex.session import LearningSession
        from apex.store import Store
        import io
        import json

        session = LearningSession(
            "stdlib-tester",
            library=__import__("apex.content", fromlist=["ContentLibrary"]).ContentLibrary(
                Path(__file__).resolve().parents[2] / "content"
            ),
            store=Store(tmp_path / "stdlib.db"),
        )

        class FakeWrite(io.BytesIO):
            def __init__(self) -> None:
                super().__init__()
                self.status = None
                self.headers = {}

        def run_request(method: str, path: str, body: bytes | None = None):
            out = FakeWrite()

            class Req(Handler):
                def __init__(self) -> None:  # noqa: D107 - test double
                    self.path = path
                    self.command = method
                    self.headers = {"Content-Length": str(len(body or b""))}
                    self.rfile = io.BytesIO(body or b"")
                    self.wfile = out
                    self.session = session

                def send_response(self, code: int) -> None:
                    out.status = code

                def send_header(self, name: str, value: str) -> None:
                    self.headers[name] = value

                def end_headers(self) -> None:
                    pass

                def log_message(self, *a: object) -> None:
                    pass

            Req().do_POST() if method == "POST" else Req().do_GET()
            payload = json.loads(out.getvalue().decode()) if out.getvalue() else None
            return out.status, payload

        code, payload = run_request("GET", "/api/intents")
        assert code == 200 and payload == {"wantToLearn": [], "learning": [], "learned": []}

        code, payload = run_request(
            "POST",
            "/api/intents",
            json.dumps({"concept_id": "io", "state": "learning"}).encode(),
        )
        assert code == 200 and payload["state"] == "learning"

        code, payload = run_request("GET", "/api/intents")
        assert [i["id"] for i in payload["learning"]] == ["io"]

        code, _ = run_request(
            "POST",
            "/api/intents",
            json.dumps({"concept_id": "ghost", "state": "learning"}).encode(),
        )
        assert code == 404
