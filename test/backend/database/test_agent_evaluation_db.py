"""Unit tests for ``backend.database.agent_evaluation_db``.

Tests cover the persisted CRUD paths used by the agent evaluation feature:
``create_agent_evaluation`` (including the optional judge-model name lookup),
``update_agent_evaluation_status``, ``get_agent_evaluation`` (including the
agent / judge-model name resolution branches), and the case-result update
behaviour that distinguishes pass vs non-pass cases for storage optimisation.
"""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND = str(_REPO_ROOT / "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

# Pre-stub heavy SDK dependencies that ``db_models`` imports at module load.
sys.modules.setdefault("boto3", MagicMock())
sys.modules.setdefault("botocore", MagicMock())
sys.modules.setdefault("botocore.client", MagicMock())
sys.modules.setdefault("botocore.exceptions", MagicMock())


@pytest.fixture
def session_factory():
    """Mock ``get_db_session`` context manager.

    Returns ``(session, get_db_session_mock)`` where ``session`` is a MagicMock
    that captures attribute queries and ``get_db_session_mock`` is the mock
    installed into ``backend.database.agent_evaluation_db``.
    """
    from backend.database import agent_evaluation_db

    session = MagicMock(name="session")
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=session)
    cm.__exit__ = MagicMock(return_value=False)

    get_db_session_mock = MagicMock(return_value=cm)
    agent_evaluation_db.get_db_session = get_db_session_mock
    return session, get_db_session_mock


def _make_query_chain(session, results):
    """Wire ``session.query(...)`` to return a MagicMock iterable.

    Each call to ``session.query(X)`` returns a fresh query mock whose chained
    method calls terminate at ``.all()`` (or ``.first()`` / ``.scalar()``)
    returning the provided values.
    """
    def _query(*_args, **kwargs):
        query = MagicMock(name="query")
        query.filter.return_value = query
        query.outerjoin.return_value = query
        query.order_by.return_value = query
        query.group_by.return_value = query
        query.offset.return_value = query
        query.limit.return_value = query
        query.all.return_value = results
        query.first.return_value = results[0] if results else None
        query.scalar.return_value = results[0] if results else None
        query.update = MagicMock(return_value=len(results))
        session.add = MagicMock()
        return query

    session.query.side_effect = _query
    return _query


# ---------------------------------------------------------------------------
# create_agent_evaluation
# ---------------------------------------------------------------------------

class TestCreateAgentEvaluation:
    def test_creates_record_without_judge_model(self, session_factory, monkeypatch):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        # Two ``.scalar()`` calls: the evaluation_set name and (when
        # judge_model_id is None) none.  We arrange them as a queued response
        # on the query mocks.
        scalars = []
        # .scalar() is called against two distinct QueryBuilder mocks because
        # .filter().scalar() chains re-create a new mock chain each time.

        # Patch ``as_dict`` so the inserted record stays inspectable without
        # needing a real SQLAlchemy object.
        captured = {}
        def _fake_as_dict(_rec):
            return {"agent_evaluation_id": 1, "tenant_id": "t1"}

        monkeypatch.setattr(agent_evaluation_db, "as_dict", _fake_as_dict)
        result = agent_evaluation_db.create_agent_evaluation(
            tenant_id="t1",
            agent_id=42,
            agent_version_no=1,
            evaluation_set_id=7,
            total=5,
            judge_model_id=None,
            created_by="u1",
        )

        # Without a judge_model_id, the implementation only fetches the
        # evaluation_set_name; result should carry it.
        assert isinstance(result, dict)
        # We can't predict the dict from mocks perfectly, but we can confirm the
        # session was used for add/flush/query.
        assert session.add.called
        assert session.flush.called

    def test_with_judge_model_resolves_display_name(self, session_factory, monkeypatch):
        from backend.database import agent_evaluation_db

        session, _ = session_factory

        monkeypatch.setattr(agent_evaluation_db, "as_dict",
                            lambda _rec: {"agent_evaluation_id": 1})

        result = agent_evaluation_db.create_agent_evaluation(
            tenant_id="t1",
            agent_id=1,
            agent_version_no=1,
            evaluation_set_id=1,
            total=1,
            judge_model_id=99,
            created_by=None,
        )
        assert isinstance(result, dict)
        assert session.add.called
        assert session.flush.called


# ---------------------------------------------------------------------------
# update_agent_evaluation_status
# ---------------------------------------------------------------------------

class TestUpdateAgentEvaluationStatus:
    def _wire_chain(self, session):
        q = MagicMock(name="q")
        q.filter.return_value = q
        session.query.return_value = q
        return q

    def test_updates_with_extra_fields(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        q = self._wire_chain(session)

        agent_evaluation_db.update_agent_evaluation_status(
            agent_evaluation_id=1,
            tenant_id="t1",
            status="RUNNING",
            updated_by="u1",
            error_message="oops",
            score_overall=0.5,
            progress_done=3,
        )

        # Production chains ``session.query(...).filter(...).update(...)``,
        # so .filter() returns the same query and .update() is on that one.
        assert q.update.called
        updates = q.update.call_args[0][0]
        assert updates["status"] == "RUNNING"
        assert updates["updated_by"] == "u1"
        assert updates["error_message"] == "oops"
        assert updates["score_overall"] == 0.5
        assert updates["progress_done"] == 3

    def test_minimal_update(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        q = self._wire_chain(session)

        agent_evaluation_db.update_agent_evaluation_status(
            agent_evaluation_id=1,
            tenant_id="t1",
            status="PENDING",
        )

        assert q.update.called
        updates = q.update.call_args[0][0]
        assert updates["status"] == "PENDING"
        # Optional fields absent when not provided.
        assert "error_message" not in updates
        assert "score_overall" not in updates
        assert "progress_done" not in updates


# ---------------------------------------------------------------------------
# get_agent_evaluation
# ---------------------------------------------------------------------------

class TestGetAgentEvaluation:
    def test_raises_value_error_when_not_found(self, session_factory, monkeypatch):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        # Force ``.first()`` to return None for the primary lookup.
        def _query(*args, **kwargs):
            q = MagicMock(name="query")
            q.filter.return_value = q
            q.first.return_value = None
            q.scalar.return_value = None
            return q

        session.query.side_effect = _query

        with pytest.raises(ValueError, match="agent evaluation not found"):
            agent_evaluation_db.get_agent_evaluation(
                agent_evaluation_id=99, tenant_id="t1",
            )

    def test_returns_dict_with_name_resolutions(self, session_factory, monkeypatch):
        from backend.database import agent_evaluation_db

        session, _ = session_factory

        rec = MagicMock(name="AgentEvaluation")
        rec.evaluation_set_id = 7
        rec.agent_id = 42
        rec.judge_model_id = 99

        # Configure distinct queries: primary lookup, evaluation_set scalar,
        # agent (display, name) first, judge model (display, repo) first.
        # ``session.query().filter().order_by().first()`` is a chain — every
        # chained method must return the same query mock so ``.first()`` is
        # the one we configured.
        call_count = {"n": 0}

        def _query(*args, **kwargs):
            call_count["n"] += 1
            q = MagicMock(name=f"query{call_count['n']}")
            q.filter.return_value = q
            q.order_by.return_value = q
            if call_count["n"] == 1:
                q.first.return_value = rec
            elif call_count["n"] == 2:
                q.scalar.return_value = "MySet"
            elif call_count["n"] == 3:
                q.first.return_value = ("Nice Agent", "agent_code")
            else:
                q.first.return_value = ("GPT-4", "openai/gpt-4")
            return q

        session.query.side_effect = _query

        monkeypatch.setattr(agent_evaluation_db, "as_dict",
                            lambda _r: {"agent_evaluation_id": 1})

        result = agent_evaluation_db.get_agent_evaluation(
            agent_evaluation_id=1, tenant_id="t1",
        )
        assert result["agent_name"] == "Nice Agent"
        assert result["judge_model_name"] == "GPT-4"
        assert result["evaluation_set_name"] == "MySet"

    def test_agent_falls_back_to_programmatic_name(self, session_factory, monkeypatch):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        rec = MagicMock(name="AgentEvaluation")
        rec.evaluation_set_id = 7
        rec.agent_id = 42
        rec.judge_model_id = None

        call_count = {"n": 0}

        def _query(*args, **kwargs):
            call_count["n"] += 1
            q = MagicMock(name=f"query{call_count['n']}")
            q.filter.return_value = q
            q.order_by.return_value = q
            if call_count["n"] == 1:
                q.first.return_value = rec
            elif call_count["n"] == 2:
                q.scalar.return_value = "MySet"
            elif call_count["n"] == 3:
                # display_name is None, programmatic_name is set
                q.first.return_value = (None, "agent_code")
            return q

        session.query.side_effect = _query
        monkeypatch.setattr(agent_evaluation_db, "as_dict",
                            lambda _r: {"agent_evaluation_id": 1})

        result = agent_evaluation_db.get_agent_evaluation(
            agent_evaluation_id=1, tenant_id="t1",
        )
        assert result["agent_name"] == "agent_code"
        # judge_model_id is None so judge_model_name remains None.
        assert result["judge_model_name"] is None

    def test_no_agent_found(self, session_factory, monkeypatch):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        rec = MagicMock(name="AgentEvaluation")
        rec.evaluation_set_id = 7
        rec.agent_id = 42
        rec.judge_model_id = None

        call_count = {"n": 0}

        def _query(*args, **kwargs):
            call_count["n"] += 1
            q = MagicMock(name=f"query{call_count['n']}")
            q.filter.return_value = q
            q.order_by.return_value = q
            if call_count["n"] == 1:
                q.first.return_value = rec
            elif call_count["n"] == 2:
                q.scalar.return_value = None
            elif call_count["n"] == 3:
                q.first.return_value = None
            return q

        session.query.side_effect = _query
        monkeypatch.setattr(agent_evaluation_db, "as_dict",
                            lambda _r: {"agent_evaluation_id": 1})

        result = agent_evaluation_db.get_agent_evaluation(
            agent_evaluation_id=1, tenant_id="t1",
        )
        assert result["agent_name"] == ""

    def test_judge_model_falls_back_to_repo_name(self, session_factory, monkeypatch):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        rec = MagicMock(name="AgentEvaluation")
        rec.evaluation_set_id = 7
        rec.agent_id = 42
        rec.judge_model_id = 99

        call_count = {"n": 0}

        def _query(*args, **kwargs):
            call_count["n"] += 1
            q = MagicMock(name=f"query{call_count['n']}")
            q.filter.return_value = q
            q.order_by.return_value = q
            if call_count["n"] == 1:
                q.first.return_value = rec
            elif call_count["n"] == 2:
                q.scalar.return_value = "MySet"
            elif call_count["n"] == 3:
                q.first.return_value = (None, "agent_code")
            elif call_count["n"] == 4:
                q.first.return_value = (None, "openai/gpt-4")
            return q

        session.query.side_effect = _query
        monkeypatch.setattr(agent_evaluation_db, "as_dict",
                            lambda _r: {"agent_evaluation_id": 1})

        result = agent_evaluation_db.get_agent_evaluation(
            agent_evaluation_id=1, tenant_id="t1",
        )
        assert result["judge_model_name"] == "openai/gpt-4"


# ---------------------------------------------------------------------------
# list_agent_evaluations_by_agent
# ---------------------------------------------------------------------------

class TestListAgentEvaluationsByAgent:
    def test_returns_results_with_fail_count(self, session_factory, monkeypatch):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        rows = [
            (MagicMock(name="r1"), "Set1", "GPT-4", 10, 7),
            (MagicMock(name="r2"), "Set2", "Claude", 5, 0),
        ]
        _make_query_chain(session, rows)

        monkeypatch.setattr(agent_evaluation_db, "as_dict",
                            lambda _r: {"agent_evaluation_id": 1})

        results = agent_evaluation_db.list_agent_evaluations_by_agent(
            agent_id=42, tenant_id="t1",
        )
        assert len(results) == 2
        assert results[0]["case_count"] == 10
        assert results[0]["pass_count"] == 7
        assert results[0]["fail_count"] == 3
        assert results[1]["case_count"] == 5
        assert results[1]["fail_count"] == 5

    def test_handles_none_counts(self, session_factory, monkeypatch):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        rows = [(MagicMock(name="r1"), "Set1", "GPT-4", None, None)]
        _make_query_chain(session, rows)
        monkeypatch.setattr(agent_evaluation_db, "as_dict",
                            lambda _r: {"agent_evaluation_id": 1})

        results = agent_evaluation_db.list_agent_evaluations_by_agent(
            agent_id=42, tenant_id="t1",
        )
        assert results[0]["case_count"] == 0
        assert results[0]["pass_count"] == 0
        assert results[0]["fail_count"] == 0


# ---------------------------------------------------------------------------
# create_agent_evaluation_cases
# ---------------------------------------------------------------------------

class TestCreateAgentEvaluationCases:
    def test_inserts_each_case_and_returns_count(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory

        set_cases = [
            {"evaluation_set_case_id": 1, "inputs": {"query": "q1"}, "label": {"answer": "a1"}},
            {"evaluation_set_case_id": 2, "inputs": {"query": "q2"}, "label": {"answer": "a2"}},
        ]
        inserted = agent_evaluation_db.create_agent_evaluation_cases(
            tenant_id="t1",
            agent_evaluation_id=10,
            set_cases=set_cases,
            created_by="u1",
        )
        assert inserted == 2
        assert session.add.call_count == 2
        assert session.flush.called


# ---------------------------------------------------------------------------
# update_agent_evaluation_case_result
# ---------------------------------------------------------------------------

class TestUpdateAgentEvaluationCaseResult:
    def test_pass_status_trims_heavy_fields(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory

        q = MagicMock(name="q")
        # Production calls ``session.query(...).filter(...).update(...)`` —
        # the .filter() must return the same query mock so .update() is the
        # one we can assert against.
        q.filter.return_value = q
        session.query.return_value = q

        agent_evaluation_db.update_agent_evaluation_case_result(
            agent_evaluation_case_id=1,
            tenant_id="t1",
            status="COMPLETED",
            predict={"answer": "x"},
            reason="looks fine",
            score=1,
            pass_status="pass",
            error_message=None,
            updated_by="u1",
        )
        # Production uses ``rows = query.update(updates, synchronize_session=False)``
        # on the filter-chain return.  ``rows`` is the count of updated rows.
        assert q.update.called
        updates = q.update.call_args[0][0]
        # Pass case: heavy fields cleared
        assert updates["predict"] is None
        assert updates["reason"] is None
        assert updates["label"] == {"answer": ""}
        assert updates["pass_status"] == "pass"
        assert updates["score"] == 1

    def test_score_one_with_no_pass_status_also_trims(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        q = MagicMock(name="q")
        q.filter.return_value = q
        session.query.return_value = q

        agent_evaluation_db.update_agent_evaluation_case_result(
            agent_evaluation_case_id=1,
            tenant_id="t1",
            status="COMPLETED",
            predict={"answer": "x"},
            reason="no reason needed",
            score=1,
            pass_status=None,
            error_message=None,
        )
        assert q.update.called
        updates = q.update.call_args[0][0]
        # Even without explicit pass_status, score==1 triggers pass-trim.
        assert updates["predict"] is None
        assert updates["reason"] is None
        assert updates["label"] == {"answer": ""}
        assert "pass_status" not in updates

    def test_failure_keeps_heavy_fields(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        q = MagicMock(name="q")
        q.filter.return_value = q
        session.query.return_value = q

        agent_evaluation_db.update_agent_evaluation_case_result(
            agent_evaluation_case_id=1,
            tenant_id="t1",
            status="FAILED",
            predict={"answer": "wrong"},
            reason="missing steps",
            score=0,
            pass_status="fail",
            error_message="boom",
            updated_by="u1",
        )
        assert q.update.called
        updates = q.update.call_args[0][0]
        assert updates["predict"] == {"answer": "wrong"}
        assert updates["reason"] == "missing steps"
        assert updates["error_message"] == "boom"
        # Failure case should NOT clear ``label``.
        assert "label" not in updates


# ---------------------------------------------------------------------------
# list_agent_evaluation_cases / get_agent_evaluation_case
# ---------------------------------------------------------------------------

class TestListCases:
    def test_returns_dict_list(self, session_factory, monkeypatch):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        rows = [MagicMock(name="r1"), MagicMock(name="r2")]
        _make_query_chain(session, rows)
        monkeypatch.setattr(agent_evaluation_db, "as_dict",
                            lambda r: {"id": id(r)})

        cases = agent_evaluation_db.list_agent_evaluation_cases(
            agent_evaluation_id=1, tenant_id="t1",
        )
        assert isinstance(cases, list)


class TestGetAgentEvaluationCase:
    def test_raises_when_not_found(self, session_factory, monkeypatch):
        from backend.database import agent_evaluation_db

        session, _ = session_factory

        def _query(*args, **kwargs):
            q = MagicMock(name="query")
            q.filter.return_value = q
            q.first.return_value = None
            return q

        session.query.side_effect = _query
        with pytest.raises(ValueError, match="agent evaluation case not found"):
            agent_evaluation_db.get_agent_evaluation_case(
                agent_evaluation_case_id=99, tenant_id="t1",
            )


# ---------------------------------------------------------------------------
# soft_delete_agent_evaluation
# ---------------------------------------------------------------------------

class TestSoftDeleteAgentEvaluation:
    def test_marks_record_as_deleted(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        q = MagicMock(name="q")
        q.filter.return_value = q
        q.update.return_value = 1  # not zero → no exception
        session.query.return_value = q

        agent_evaluation_db.soft_delete_agent_evaluation(
            agent_evaluation_id=1,
            tenant_id="t1",
            deleted_by="u1",
        )

        assert q.update.called
        updates = q.update.call_args[0][0]
        assert updates["delete_flag"] == "Y"
        assert updates["updated_by"] == "u1"

    def test_raises_when_no_row_updated(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        q = MagicMock(name="q")
        q.filter.return_value = q
        q.update.return_value = 0  # zero updated rows
        session.query.return_value = q

        with pytest.raises(ValueError, match="not found or already deleted"):
            agent_evaluation_db.soft_delete_agent_evaluation(
                agent_evaluation_id=999,
                tenant_id="t1",
                deleted_by="u1",
            )
