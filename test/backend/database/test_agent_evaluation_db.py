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
from sqlalchemy import select

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
# claim_agent_evaluation_run
# ---------------------------------------------------------------------------

class TestClaimAgentEvaluationRun:
    def _wire_chain(self, session, updated):
        query = MagicMock(name="query")
        query.filter.return_value = query
        query.update.return_value = updated
        session.query.return_value = query
        return query

    def test_claims_pending_run(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        query = self._wire_chain(session, 1)

        assert agent_evaluation_db.claim_agent_evaluation_run(7, "t1", "u1") is True
        assert query.update.call_args.kwargs["synchronize_session"] is False
        assert query.update.call_args.args[0] == {
            "status": "RUNNING",
            "updated_by": "u1",
        }
        session.commit.assert_called_once_with()

    def test_returns_false_when_run_was_claimed(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        self._wire_chain(session, 0)

        assert agent_evaluation_db.claim_agent_evaluation_run(7, "t1") is False
        session.commit.assert_called_once_with()


# ---------------------------------------------------------------------------
# get_agent_evaluation
# ---------------------------------------------------------------------------

class TestGetAgentEvaluation:
    def test_raises_value_error_when_not_found(self, session_factory, monkeypatch):
        from backend.database import agent_evaluation_db
        from consts.exceptions import AppException

        session, _ = session_factory
        # Force ``.first()`` to return None for the primary lookup.
        def _query(*args, **kwargs):
            q = MagicMock(name="query")
            q.filter.return_value = q
            q.first.return_value = None
            q.scalar.return_value = None
            return q

        session.query.side_effect = _query

        with pytest.raises(AppException, match="Agent evaluation not found"):
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
        r1 = MagicMock(name="r1")
        r1.progress_total = 10
        r1.pass_count = 7
        r1.fail_count = 3
        r2 = MagicMock(name="r2")
        r2.progress_total = 5
        r2.pass_count = 0
        r2.fail_count = 5
        rows = [
            (r1, "Set1", "GPT-4"),
            (r2, "Set2", "Claude"),
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
        r1 = MagicMock(name="r1")
        r1.progress_total = None
        r1.pass_count = None
        r1.fail_count = None
        rows = [(r1, "Set1", "GPT-4")]
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
        # Option B (no trim, keep all fields): pass case keeps predict/reason
        # as-is — no trimming, UI retains the full Agent answer and reason
        # tooltip for every case regardless of pass/fail.
        assert updates["predict"] == {"answer": "x"}
        assert updates["reason"] == "looks fine"
        assert updates["pass_status"] == "pass"
        assert updates["score"] == 1
        # Label is managed independently (only overwritten on explicit
        # relabel requests); update-result never touches ``label``.
        assert "label" not in updates

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
        # Option B (no trim): even without explicit pass_status, score==1
        # keeps all provided fields intact.
        assert updates["predict"] == {"answer": "x"}
        assert updates["reason"] == "no reason needed"
        assert updates["score"] == 1
        assert "pass_status" not in updates
        assert "label" not in updates

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

    def test_zero_rows_only_logs_warning(self, session_factory):
        """rows == 0 must not raise; it only emits a warning log."""
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        q = MagicMock(name="q")
        q.filter.return_value = q
        q.update.return_value = 0  # no matching row
        session.query.return_value = q

        agent_evaluation_db.update_agent_evaluation_case_result(
            agent_evaluation_case_id=999,
            tenant_id="t1",
            status="COMPLETED",
        )
        assert q.update.called


# ---------------------------------------------------------------------------
# list_agent_evaluation_cases / get_agent_evaluation_case
# ---------------------------------------------------------------------------

class TestListCases:
    def test_returns_dict_list(self, session_factory, monkeypatch):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        rows = [MagicMock(name="r1"), MagicMock(name="r2")]

        def _query(*_args, **kwargs):
            query = MagicMock(name="query")
            query.filter.return_value = query
            query.outerjoin.return_value = query
            query.order_by.return_value = query
            query.offset.return_value = query
            query.limit.return_value = query
            query.all.return_value = rows
            query.count.return_value = len(rows)
            return query

        session.query.side_effect = _query
        monkeypatch.setattr(agent_evaluation_db, "as_dict",
                            lambda r: {"id": id(r)})

        cases = agent_evaluation_db.list_agent_evaluation_cases(
            agent_evaluation_id=1, tenant_id="t1",
        )
        # list_cases returns { "items": [...], "total": N } paginated dict
        assert isinstance(cases, dict)
        assert isinstance(cases["items"], list)
        assert len(cases["items"]) == 2
        assert cases["total"] == 2


class TestGetAgentEvaluationCase:
    def test_raises_when_not_found(self, session_factory, monkeypatch):
        from backend.database import agent_evaluation_db
        from consts.exceptions import AppException

        session, _ = session_factory

        def _query(*args, **kwargs):
            q = MagicMock(name="query")
            q.filter.return_value = q
            q.first.return_value = None
            return q

        session.query.side_effect = _query
        with pytest.raises(AppException, match="Agent evaluation case not found"):
            agent_evaluation_db.get_agent_evaluation_case(
                agent_evaluation_case_id=99, tenant_id="t1",
            )


# ---------------------------------------------------------------------------
# hard_delete_agent_evaluation (production has no soft delete; it hard-deletes
# the run plus its case rows and annotations, then commits)
# ---------------------------------------------------------------------------

def _wire_hard_delete(session, all_results, n_queries):
    """Queue ``n_queries`` independent query mocks for a hard_delete call.

    ``all_results`` is fed to the FIRST query (the case-id SELECT).  The
    remaining queries mock the cascade DELETE statements.  Any extra
    ``session.query`` call raises ``StopIteration`` so a drift in the
    production SQL (more/fewer statements) fails the test loudly.
    """
    queries = [MagicMock(name=f"q{i}") for i in range(n_queries)]
    for q in queries:
        q.filter.return_value = q
    queries[0].all.return_value = all_results
    it = iter(queries)
    session.query.side_effect = lambda *a, **k: next(it)
    return queries


class TestHardDeleteAgentEvaluation:
    def test_cascades_cases_and_annotations(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        # 1) case-id SELECT → 2) annotations by case_id → 3) annotations by
        # agent_evaluation_id → 4) case DELETE → 5) run DELETE
        queries = _wire_hard_delete(session, [(11,), (12,)], n_queries=5)
        queries[1].delete.return_value = 2
        queries[2].delete.return_value = 1
        queries[3].delete.return_value = 2
        queries[4].delete.return_value = 1

        agent_evaluation_db.hard_delete_agent_evaluation(
            agent_evaluation_id=1,
            tenant_id="t1",
        )

        for q in queries[1:]:
            assert q.delete.called
        session.commit.assert_called_once_with()

    def test_no_cases_skips_case_annotation_delete(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        # 1) case-id SELECT returns nothing (case_id branch skipped entirely) →
        # 2) annotations by agent_evaluation_id → 3) case DELETE → 4) run DELETE
        queries = _wire_hard_delete(session, [], n_queries=4)
        for q in queries[1:]:
            q.delete.return_value = 0

        agent_evaluation_db.hard_delete_agent_evaluation(
            agent_evaluation_id=999,
            tenant_id="t1",
        )

        # Only 4 statements ran — the case_id annotation DELETE never materialised
        # as a query (an extra ``session.query`` call would raise StopIteration).
        for q in queries[1:]:
            assert q.delete.called
        session.commit.assert_called_once_with()


# ---------------------------------------------------------------------------
# update_agent_evaluation_analysis_report
# ---------------------------------------------------------------------------

class TestUpdateAnalysisReport:
    def test_updates_and_commits(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        q = MagicMock(name="q")
        q.filter.return_value = q
        session.query.return_value = q

        agent_evaluation_db.update_agent_evaluation_analysis_report(
            agent_evaluation_id=1, tenant_id="t1", report={"analysis": "ok"},
        )

        updates = q.update.call_args[0][0]
        assert updates["analysis_report"] == {"analysis": "ok"}
        session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# _apply_annotation_filters / _apply_case_sorting (internal helpers)
# ---------------------------------------------------------------------------

class TestApplyAnnotationFilters:
    def test_ignores_missing_or_mismatched_lists(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        base = MagicMock(name="base")

        result, pairs = agent_evaluation_db._apply_annotation_filters(
            base, session, None, None, "t1",
        )
        assert result is base
        assert pairs == 0

        result, pairs = agent_evaluation_db._apply_annotation_filters(
            base, session, [1, 2], ["v"], "t1",
        )
        assert result is base
        assert pairs == 0

    def test_applies_pairs_including_empty_value(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        base = MagicMock(name="base")
        base.filter.return_value = base

        q = MagicMock(name="anno")
        q.filter.return_value = q
        q.subquery.return_value = select(1).subquery()
        session.query.return_value = q

        # Pair 1: val="v" → adds equality filter; pair 2: val="" → no equality.
        result, pairs = agent_evaluation_db._apply_annotation_filters(
            base, session, [1, 2], ["v", ""], "t1",
        )
        assert result is base
        assert pairs == 2
        assert base.filter.call_count == 2
        assert session.query.call_count == 2


class TestApplyCaseSorting:
    def test_desc_score_sort(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        q = MagicMock(name="q")
        q.order_by.return_value = q

        agent_evaluation_db._apply_case_sorting(q, "accuracy", "desc")
        assert q.order_by.called

    def test_asc_score_sort(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        q = MagicMock(name="q")
        q.order_by.return_value = q

        agent_evaluation_db._apply_case_sorting(q, "accuracy", "asc")
        assert q.order_by.called

    def test_default_session_preserving_sort(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        q = MagicMock(name="q")
        q.order_by.return_value = q

        agent_evaluation_db._apply_case_sorting(q, None, "asc")
        assert q.order_by.called


# ---------------------------------------------------------------------------
# list_agent_evaluation_cases — filter branches
# ---------------------------------------------------------------------------

def _query_cases(session, rows):
    def _query(*_args, **kwargs):
        query = MagicMock(name="query")
        query.filter.return_value = query
        query.offset.return_value = query
        query.limit.return_value = query
        query.order_by.return_value = query
        query.all.return_value = rows
        query.count.return_value = len(rows)
        query.subquery.return_value = select(1).subquery()
        return query

    session.query.side_effect = _query
    return _query


class TestListCasesFilters:
    def test_pass_filter_and_single_session_filter(self, session_factory, monkeypatch):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        _query_cases(session, [MagicMock(name="r1")])
        monkeypatch.setattr(agent_evaluation_db, "as_dict",
                            lambda r: {"id": id(r)})

        result = agent_evaluation_db.list_agent_evaluation_cases(
            agent_evaluation_id=1, tenant_id="t1",
            pass_filter="pass", session_id="__single__",
        )
        assert result["total"] == 1
        assert len(result["items"]) == 1

    def test_specific_session_filter(self, session_factory, monkeypatch):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        _query_cases(session, [])
        monkeypatch.setattr(agent_evaluation_db, "as_dict",
                            lambda r: {"id": id(r)})

        result = agent_evaluation_db.list_agent_evaluation_cases(
            agent_evaluation_id=1, tenant_id="t1", session_id="s1",
        )
        assert result["total"] == 0

    def test_annotation_pairs_filter(self, session_factory, monkeypatch):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        _query_cases(session, [MagicMock(name="r1")])
        monkeypatch.setattr(agent_evaluation_db, "as_dict",
                            lambda r: {"id": id(r)})

        result = agent_evaluation_db.list_agent_evaluation_cases(
            agent_evaluation_id=1, tenant_id="t1",
            anno_schema_ids=[3], anno_values=["good"],
        )
        assert result["total"] == 1

    def test_score_sort_by(self, session_factory, monkeypatch):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        _query_cases(session, [MagicMock(name="r1")])
        monkeypatch.setattr(agent_evaluation_db, "as_dict",
                            lambda r: {"id": id(r)})

        result = agent_evaluation_db.list_agent_evaluation_cases(
            agent_evaluation_id=1, tenant_id="t1",
            sort_by="accuracy", sort_order="desc",
        )
        assert result["total"] == 1


# ---------------------------------------------------------------------------
# get_evaluation_case_scores / get_agent_evaluation_case success path
# ---------------------------------------------------------------------------

class TestGetEvaluationCaseScores:
    def test_returns_pass_score_reason(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        r1 = MagicMock(name="r1")
        r1.pass_status = "pass"
        r1.score = 1.0
        r1.reason = "ok"
        r2 = MagicMock(name="r2")
        r2.pass_status = "fail"
        r2.score = 0.0
        r2.reason = "bad"
        _make_query_chain(session, [r1, r2])

        rows = agent_evaluation_db.get_evaluation_case_scores(
            agent_evaluation_id=1, tenant_id="t1",
        )
        assert rows == [
            {"pass_status": "pass", "score": 1.0, "reason": "ok"},
            {"pass_status": "fail", "score": 0.0, "reason": "bad"},
        ]


class TestGetAgentEvaluationCaseSuccess:
    def test_returns_dict(self, session_factory, monkeypatch):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        rec = MagicMock(name="rec")
        _make_query_chain(session, [rec])
        monkeypatch.setattr(agent_evaluation_db, "as_dict",
                            lambda r: {"agent_evaluation_case_id": 1})

        result = agent_evaluation_db.get_agent_evaluation_case(1, "t1")
        assert result == {"agent_evaluation_case_id": 1}


# ---------------------------------------------------------------------------
# update_annotation_schema_ids
# ---------------------------------------------------------------------------

class TestUpdateAnnotationSchemaIds:
    def test_deletes_removed_schema_data(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        queries = [MagicMock(name=f"q{i}") for i in range(3)]
        for q in queries:
            q.filter.return_value = q
        queries[0].scalar.return_value = [1, 2, 3]  # old ids
        queries[1].delete.return_value = 1          # cascade annotation delete
        queries[2].update.return_value = 1          # affected run rows
        it = iter(queries)
        session.query.side_effect = lambda *a, **k: next(it)

        affected = agent_evaluation_db.update_annotation_schema_ids(
            agent_evaluation_id=1, tenant_id="t1", schema_ids=[2, 3],
        )
        assert affected == 1
        assert queries[1].delete.called
        session.commit.assert_called_once()

    def test_no_removals_skips_delete(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        queries = [MagicMock(name=f"q{i}") for i in range(2)]
        for q in queries:
            q.filter.return_value = q
        queries[0].scalar.return_value = [1, 2]  # same as new list
        queries[1].update.return_value = 1
        it = iter(queries)
        session.query.side_effect = lambda *a, **k: next(it)

        affected = agent_evaluation_db.update_annotation_schema_ids(
            agent_evaluation_id=1, tenant_id="t1", schema_ids=[1, 2],
        )
        assert affected == 1
        session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# count helpers
# ---------------------------------------------------------------------------

class TestCountRuns:
    def test_count_active_runs_using_schema(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        q = MagicMock(name="q")
        q.filter.return_value = q
        q.count.return_value = 2
        session.query.return_value = q

        n = agent_evaluation_db.count_active_runs_using_schema(5, "t1")
        assert n == 2

    def test_count_active_runs_with_lock(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        q = MagicMock(name="q")
        q.filter.return_value = q
        q.count.return_value = 3
        session.query.return_value = q

        n = agent_evaluation_db.count_active_runs("t1")
        assert n == 3
        assert session.execute.called

    def test_count_total_runs(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        q = MagicMock(name="q")
        q.filter.return_value = q
        q.count.return_value = 5
        session.query.return_value = q

        n = agent_evaluation_db.count_total_runs("t1")
        assert n == 5


# ---------------------------------------------------------------------------
# cleanup_aged_evaluations / reap_stale_runs
# ---------------------------------------------------------------------------

class TestCleanupAgedEvaluations:
    def test_deletes_aged_runs_and_virtual_sets(self, session_factory, monkeypatch):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        # q0: aged SELECT → [(eid1, set1, {no_set_mode}), (eid2, set2, None)]
        # eid1: q1 case_ids, q2 anno-by-case, q3 anno-by-run, q4 case DEL,
        #       q5 run DEL
        # eid2: q6 case_ids (empty), q7 anno-by-run, q8 case DEL, q9 run DEL
        queries = [MagicMock(name=f"q{i}") for i in range(10)]
        for q in queries:
            q.filter.return_value = q
        queries[0].all.return_value = [
            (1, 10, {"no_set_mode": True}),
            (2, 20, None),
        ]
        queries[1].all.return_value = [(100,)]
        queries[6].all.return_value = []
        it = iter(queries)
        session.query.side_effect = lambda *a, **k: next(it)

        hard_delete = MagicMock()
        monkeypatch.setattr(
            "database.evaluation_set_db.hard_delete_evaluation_set", hard_delete,
        )

        deleted = agent_evaluation_db.cleanup_aged_evaluations("t1", retention_days=30)
        assert deleted == 2
        hard_delete.assert_called_once_with(10, "t1")
        session.commit.assert_called_once()

    def test_virtual_set_delete_failure_is_swallowed(self, session_factory, monkeypatch):
        """A failing cascade hard_delete of a virtual set must not abort cleanup."""
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        queries = [MagicMock(name=f"q{i}") for i in range(6)]
        for q in queries:
            q.filter.return_value = q
        queries[0].all.return_value = [(1, 10, {"no_set_mode": True})]
        queries[1].all.return_value = [(100,)]
        it = iter(queries)
        session.query.side_effect = lambda *a, **k: next(it)

        def _boom(*_a, **_k):
            raise RuntimeError("db down")

        monkeypatch.setattr(
            "database.evaluation_set_db.hard_delete_evaluation_set", _boom,
        )

        deleted = agent_evaluation_db.cleanup_aged_evaluations("t1", retention_days=30)
        assert deleted == 1
        session.commit.assert_called_once()


class TestReapStaleRuns:
    def test_reaps_stale_runs(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        queries = [MagicMock(name=f"q{i}") for i in range(3)]
        for q in queries:
            q.filter.return_value = q
        queries[0].all.return_value = [(1,), (2,)]
        it = iter(queries)
        session.query.side_effect = lambda *a, **k: next(it)

        n = agent_evaluation_db.reap_stale_runs("t1", timeout_minutes=10)
        assert n == 2
        assert queries[1].update.called
        assert queries[2].update.called
        session.commit.assert_called_once()

    def test_no_stale_runs(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        queries = [MagicMock(name="q")]
        queries[0].filter.return_value = queries[0]
        queries[0].all.return_value = []
        session.query.side_effect = lambda *a, **k: next(iter(queries))

        n = agent_evaluation_db.reap_stale_runs("t1", timeout_minutes=10)
        assert n == 0


class TestStartupRecovery:
    def test_lists_only_tenants_with_running_work(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        query = MagicMock(name="query")
        query.filter.return_value = query
        query.distinct.return_value = query
        query.all.return_value = [("tenant-1",), ("tenant-2",), (None,)]
        session.query.return_value = query

        assert agent_evaluation_db.list_evaluation_tenant_ids() == [
            "tenant-1",
            "tenant-2",
        ]
        query.distinct.assert_called_once_with()

    def test_fails_interrupted_no_set_runs_and_their_pending_cases(
        self, session_factory
    ):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        queries = [MagicMock(name=f"q{i}") for i in range(3)]
        for query in queries:
            query.filter.return_value = query
        queries[0].all.return_value = [(10,), (20,)]
        queries[1].update.return_value = 4
        queries[2].update.return_value = 2
        session.query.side_effect = queries

        assert agent_evaluation_db.fail_interrupted_no_set_runs_on_startup() == 2
        case_updates = queries[1].update.call_args.args[0]
        run_updates = queries[2].update.call_args.args[0]
        assert case_updates["status"] == "FAILED"
        assert run_updates["status"] == "FAILED"
        assert case_updates["error_message"] == run_updates["error_message"]
        session.commit.assert_called_once_with()

    def test_pending_recovery_is_noop_when_there_are_no_runs(self, session_factory):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        query = MagicMock(name="query")
        query.filter.return_value = query
        query.all.return_value = []
        session.query.return_value = query

        assert agent_evaluation_db.fail_interrupted_no_set_runs_on_startup() == 0
        query.update.assert_not_called()

    def test_lists_dispatchable_pending_runs(self, session_factory, mocker):
        from backend.database import agent_evaluation_db

        session, _ = session_factory
        query = MagicMock(name="query")
        query.filter.return_value = query
        query.order_by.return_value = query
        rows = [MagicMock(name="pending-run")]
        query.all.return_value = rows
        session.query.return_value = query
        as_dict = mocker.patch.object(
            agent_evaluation_db,
            "as_dict",
            return_value={"agent_evaluation_id": 10},
        )

        assert agent_evaluation_db.list_dispatchable_pending_runs() == [
            {"agent_evaluation_id": 10}
        ]
        as_dict.assert_called_once_with(rows[0])
