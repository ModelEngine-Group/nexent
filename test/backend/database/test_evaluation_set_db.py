"""Unit tests for ``backend.database.evaluation_set_db``."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND = str(_REPO_ROOT / "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

sys.modules.setdefault("boto3", MagicMock())
sys.modules.setdefault("botocore", MagicMock())
sys.modules.setdefault("botocore.client", MagicMock())
sys.modules.setdefault("botocore.exceptions", MagicMock())


@pytest.fixture
def session_factory():
    from backend.database import evaluation_set_db

    session = MagicMock(name="session")
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=session)
    cm.__exit__ = MagicMock(return_value=False)

    get_db_session_mock = MagicMock(return_value=cm)
    evaluation_set_db.get_db_session = get_db_session_mock
    return session, get_db_session_mock


def _wire_chain(session, *, first=None, scalar=None, all_rows=None,
                update_rows=1, count=None):
    """Build a chained query mock whose calls return self."""
    q = MagicMock(name="query")
    q.filter.return_value = q
    q.order_by.return_value = q
    q.offset.return_value = q
    q.limit.return_value = q
    q.outerjoin.return_value = q
    q.first.return_value = first
    q.scalar.return_value = scalar
    q.count.return_value = count
    q.all.return_value = all_rows if all_rows is not None else []
    q.update.return_value = update_rows
    session.query.return_value = q
    return q


def _has_delete_flag_n_filter(q):
    """True if the first ``q.filter()`` call pins ``delete_flag == "N"``.

    SQLAlchemy wraps the right-hand literal in a BindParameter, so unwrap
    ``.value`` before comparing.
    """
    for a in q.filter.call_args_list[0].args:
        right = getattr(a, "right", None)
        if getattr(right, "value", right) == "N" and "delete_flag" in str(
            getattr(a, "left", "")
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# create_evaluation_set
# ---------------------------------------------------------------------------

class TestCreateEvaluationSet:
    def test_adds_record_and_returns_dict(self, session_factory, monkeypatch):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        monkeypatch.setattr(evaluation_set_db, "as_dict",
                            lambda _r: {"evaluation_set_id": 1})

        result = evaluation_set_db.create_evaluation_set(
            tenant_id="t1",
            name="My set",
            description="desc",
            source_filename="src.xlsx",
            created_by="u1",
        )

        assert session.add.called
        assert session.flush.called
        assert result == {"evaluation_set_id": 1}


# ---------------------------------------------------------------------------
# update_evaluation_set_case_count
# ---------------------------------------------------------------------------

class TestUpdateCaseCount:
    def test_invokes_update(self, session_factory):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        q = _wire_chain(session)

        evaluation_set_db.update_evaluation_set_case_count(
            evaluation_set_id=1, case_count=10, updated_by="u1",
        )

        assert q.update.called
        updates = q.update.call_args[0][0]
        assert updates["case_count"] == 10
        assert updates["updated_by"] == "u1"


# ---------------------------------------------------------------------------
# list_evaluation_sets
# ---------------------------------------------------------------------------

class TestListEvaluationSets:
    def test_returns_dict_list(self, session_factory, monkeypatch):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        q = _wire_chain(session, all_rows=[MagicMock(name="r1"), MagicMock(name="r2")])
        monkeypatch.setattr(evaluation_set_db, "as_dict",
                            lambda r: {"id": id(r)})

        result = evaluation_set_db.list_evaluation_sets(
            tenant_id="t1", limit=10, offset=0,
        )

        assert isinstance(result, list)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# get_evaluation_set
# ---------------------------------------------------------------------------

class TestGetEvaluationSet:
    def test_raises_when_not_found(self, session_factory):
        from consts.exceptions import AppException
        from backend.database import evaluation_set_db

        session, _ = session_factory
        _wire_chain(session, first=None)

        with pytest.raises(AppException, match="Evaluation set not found"):
            evaluation_set_db.get_evaluation_set(
                evaluation_set_id=99, tenant_id="t1",
            )

    def test_returns_as_dict(self, session_factory, monkeypatch):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        _wire_chain(session, first=MagicMock(name="rec"))
        monkeypatch.setattr(evaluation_set_db, "as_dict",
                            lambda _r: {"evaluation_set_id": 1})

        result = evaluation_set_db.get_evaluation_set(
            evaluation_set_id=1, tenant_id="t1",
        )
        assert result == {"evaluation_set_id": 1}


# ---------------------------------------------------------------------------
# insert_evaluation_set_cases
# ---------------------------------------------------------------------------

class TestInsertCases:
    def test_inserts_each_case(self, session_factory):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        cases = [
            {"case_id": "c1", "inputs": {"query": "q"}, "label": {"answer": "a"}},
            {"case_id": "c2", "inputs": {"query": "q2"}, "label": {"answer": "a2"},
             "order_no": 99},
            {"case_id": None, "inputs": {"query": "q3"}, "label": {"answer": "a3"}},
        ]
        inserted = evaluation_set_db.insert_evaluation_set_cases(
            tenant_id="t1", evaluation_set_id=1, cases=cases, created_by="u1",
        )
        assert inserted == 3
        assert session.add.call_count == 3
        assert session.flush.called


# ---------------------------------------------------------------------------
# list_evaluation_set_cases / get_evaluation_set_cases_all
# ---------------------------------------------------------------------------

class TestListCases:
    def test_returns_list(self, session_factory, monkeypatch):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        _wire_chain(session, all_rows=[MagicMock(name="r1")])
        monkeypatch.setattr(evaluation_set_db, "as_dict",
                            lambda r: {"id": id(r)})

        cases = evaluation_set_db.list_evaluation_set_cases(
            evaluation_set_id=1, tenant_id="t1",
        )
        assert isinstance(cases, list)
        assert len(cases) == 1

    def test_filters_out_deleted_cases(self, session_factory):
        """Soft-deleted (delete_flag='Y') cases must not be listed."""
        from backend.database import evaluation_set_db

        session, _ = session_factory
        q = _wire_chain(session, all_rows=[])

        evaluation_set_db.list_evaluation_set_cases(
            evaluation_set_id=1, tenant_id="t1",
        )

        # The first filter() call carries the row-level predicates; one of
        # them must pin delete_flag == "N".
        assert _has_delete_flag_n_filter(q)


class TestCountEvaluationSetCases:
    def test_filters_out_deleted_cases(self, session_factory):
        """count must ignore soft-deleted (delete_flag='Y') cases."""
        from backend.database import evaluation_set_db

        session, _ = session_factory
        q = _wire_chain(session, count=5)

        n = evaluation_set_db.count_evaluation_set_cases(
            evaluation_set_id=1, tenant_id="t1",
        )
        assert n == 5

        assert _has_delete_flag_n_filter(q)


class TestGetEvaluationSetCasesAll:
    def test_returns_all_cases(self, session_factory, monkeypatch):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        _wire_chain(session, all_rows=[MagicMock(name="r1"), MagicMock(name="r2")])
        monkeypatch.setattr(evaluation_set_db, "as_dict",
                            lambda r: {"id": id(r)})

        cases = evaluation_set_db.get_evaluation_set_cases_all(
            evaluation_set_id=1, tenant_id="t1",
        )
        assert len(cases) == 2

    def test_filters_out_deleted_cases(self, session_factory, monkeypatch):
        """Soft-deleted (delete_flag='Y') cases must not be exported."""
        from backend.database import evaluation_set_db

        session, _ = session_factory
        q = _wire_chain(session, all_rows=[])
        monkeypatch.setattr(evaluation_set_db, "as_dict",
                            lambda r: {"id": id(r)})

        evaluation_set_db.get_evaluation_set_cases_all(
            evaluation_set_id=1, tenant_id="t1",
        )
        assert _has_delete_flag_n_filter(q)


# ---------------------------------------------------------------------------
# soft_delete_evaluation_set
# ---------------------------------------------------------------------------

class TestSoftDelete:
    def test_marks_deleted(self, session_factory):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        q = _wire_chain(session, update_rows=1)

        evaluation_set_db.soft_delete_evaluation_set(
            evaluation_set_id=1, tenant_id="t1", deleted_by="u1",
        )

        assert q.update.called
        updates = q.update.call_args[0][0]
        assert updates["delete_flag"] == "Y"
        assert updates["updated_by"] == "u1"

    def test_raises_when_not_found(self, session_factory):
        from consts.exceptions import AppException
        from backend.database import evaluation_set_db

        session, _ = session_factory
        _wire_chain(session, update_rows=0)

        with pytest.raises(AppException, match="Evaluation set not found or already deleted"):
            evaluation_set_db.soft_delete_evaluation_set(
                evaluation_set_id=999, tenant_id="t1", deleted_by="u1",
            )


# ---------------------------------------------------------------------------
# count_evaluation_sets
# ---------------------------------------------------------------------------

class TestCountEvaluationSets:
    def test_counts_rows(self, session_factory):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        _wire_chain(session, count=7)

        n = evaluation_set_db.count_evaluation_sets(tenant_id="t1")
        assert n == 7


# ---------------------------------------------------------------------------
# list / count cases with query filter
# ---------------------------------------------------------------------------

class TestListCasesWithQuery:
    def test_filters_by_query(self, session_factory, monkeypatch):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        q = _wire_chain(session, all_rows=[MagicMock(name="r1")])
        monkeypatch.setattr(evaluation_set_db, "as_dict",
                            lambda r: {"id": id(r)})

        cases = evaluation_set_db.list_evaluation_set_cases(
            evaluation_set_id=1, tenant_id="t1", query="foo",
        )
        assert len(cases) == 1
        assert q.filter.call_count == 2  # base filters + ilike query filter


class TestCountCasesWithQuery:
    def test_filters_by_query(self, session_factory):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        q = _wire_chain(session, count=3)

        n = evaluation_set_db.count_evaluation_set_cases(
            evaluation_set_id=1, tenant_id="t1", query="foo",
        )
        assert n == 3
        assert q.filter.call_count == 2


# ---------------------------------------------------------------------------
# batch_delete_evaluation_set_cases
# ---------------------------------------------------------------------------

class TestBatchDeleteCases:
    def test_empty_list_returns_zero(self, session_factory):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        assert evaluation_set_db.batch_delete_evaluation_set_cases(
            case_ids=[], tenant_id="t1", evaluation_set_id=1,
        ) == 0
        assert not session.query.called

    def test_deletes_rows(self, session_factory):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        q = _wire_chain(session)
        q.delete.return_value = 3

        rows = evaluation_set_db.batch_delete_evaluation_set_cases(
            case_ids=[1, 2, 3], tenant_id="t1", evaluation_set_id=1,
        )
        assert rows == 3
        assert q.delete.called
        session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# hard_delete_evaluation_set
# ---------------------------------------------------------------------------

class TestHardDeleteEvaluationSet:
    def test_deletes_cases_and_set(self, session_factory):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        q = _wire_chain(session)
        q.delete.side_effect = [10, 2]  # cases first, then the set itself

        deleted = evaluation_set_db.hard_delete_evaluation_set(
            evaluation_set_id=1, tenant_id="t1",
        )
        assert deleted == 2
        assert q.delete.call_count == 2
        session.commit.assert_called_once()


class TestStartupRecovery:
    def test_interrupted_generation_keeps_baseline_and_deletes_appended_cases(
        self, session_factory
    ):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        evaluation_set = SimpleNamespace(
            evaluation_set_id=7,
            tenant_id="tenant-1",
            case_count=2,
            generation_status="GENERATING",
            generation_progress=80,
        )
        set_query = MagicMock(name="set_query")
        set_query.filter.return_value = set_query
        set_query.with_for_update.return_value = set_query
        set_query.all.return_value = [evaluation_set]
        case_query = MagicMock(name="case_query")
        case_query.filter.return_value = case_query
        case_query.order_by.return_value = case_query
        case_query.all.return_value = [(10,), (11,), (12,), (13,)]
        delete_query = MagicMock(name="delete_query")
        delete_query.filter.return_value = delete_query
        delete_query.delete.return_value = 2
        session.query.side_effect = [set_query, case_query, delete_query]

        assert evaluation_set_db.recover_interrupted_generations() == 1
        assert evaluation_set.generation_status == "FAILED"
        assert evaluation_set.generation_progress == 0
        delete_query.delete.assert_called_once_with(synchronize_session=False)

    def test_interrupted_generation_without_appended_cases_skips_delete(
        self, session_factory
    ):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        evaluation_set = SimpleNamespace(
            evaluation_set_id=7,
            tenant_id="tenant-1",
            case_count=2,
            generation_status="GENERATING",
            generation_progress=20,
        )
        set_query = MagicMock(name="set_query")
        set_query.filter.return_value = set_query
        set_query.with_for_update.return_value = set_query
        set_query.all.return_value = [evaluation_set]
        case_query = MagicMock(name="case_query")
        case_query.filter.return_value = case_query
        case_query.order_by.return_value = case_query
        case_query.all.return_value = [(10,), (11,)]
        session.query.side_effect = [set_query, case_query]

        assert evaluation_set_db.recover_interrupted_generations() == 1
        assert evaluation_set.generation_status == "FAILED"
        assert evaluation_set.generation_progress == 0
        assert session.query.call_count == 2

    def test_cleans_virtual_sets_that_were_never_linked_to_a_run(
        self, session_factory
    ):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        referenced_query = MagicMock(name="referenced_query")
        referenced_query.filter.return_value = referenced_query
        orphan_query = MagicMock(name="orphan_query")
        orphan_query.filter.return_value = orphan_query
        orphan_query.all.return_value = [(30, "tenant-1"), (31, "tenant-2")]
        case_delete = MagicMock(name="case_delete")
        case_delete.filter.return_value = case_delete
        set_delete = MagicMock(name="set_delete")
        set_delete.filter.return_value = set_delete
        session.query.side_effect = [
            referenced_query,
            orphan_query,
            case_delete,
            set_delete,
        ]

        assert evaluation_set_db.cleanup_orphaned_virtual_evaluation_sets() == 2
        case_delete.delete.assert_called_once_with(synchronize_session=False)
        set_delete.delete.assert_called_once_with(synchronize_session=False)

    def test_cleanup_virtual_sets_skips_delete_when_none_are_orphaned(
        self, session_factory
    ):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        referenced_query = MagicMock(name="referenced_query")
        referenced_query.filter.return_value = referenced_query
        orphan_query = MagicMock(name="orphan_query")
        orphan_query.filter.return_value = orphan_query
        orphan_query.all.return_value = []
        session.query.side_effect = [referenced_query, orphan_query]

        assert evaluation_set_db.cleanup_orphaned_virtual_evaluation_sets() == 0
        assert session.query.call_count == 2

    def test_materializes_virtual_set_and_links_pending_run_in_one_session(
        self, session_factory
    ):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        run = SimpleNamespace(
            evaluation_set_id=0,
            progress_total=0,
            updated_by=None,
        )
        query = MagicMock(name="run_query")
        query.filter.return_value = query
        query.with_for_update.return_value = query
        query.first.return_value = run
        session.query.return_value = query

        def assign_primary_key():
            for invocation in session.add.call_args_list:
                record = invocation.args[0]
                if isinstance(record, evaluation_set_db.EvaluationSet):
                    record.evaluation_set_id = 99

        session.flush.side_effect = assign_primary_key

        set_id = evaluation_set_db.materialize_virtual_evaluation_set_for_run(
            tenant_id="tenant-1",
            name="[No-Set] recovery",
            cases=[
                {"inputs": {"query": "q1"}, "label": {"answer": ""}},
                {"inputs": {"query": "q2"}, "label": {"answer": ""}},
            ],
            created_by="user-1",
            agent_evaluation_id=5,
        )

        assert set_id == 99
        assert run.evaluation_set_id == 99
        assert run.progress_total == 2
        assert run.updated_by == "user-1"
        assert session.add.call_count == 3

    def test_materialize_virtual_set_rejects_missing_pending_run(
        self, session_factory
    ):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        query = MagicMock(name="run_query")
        query.filter.return_value = query
        query.with_for_update.return_value = query
        query.first.return_value = None
        session.query.return_value = query

        with pytest.raises(evaluation_set_db.AppException):
            evaluation_set_db.materialize_virtual_evaluation_set_for_run(
                tenant_id="tenant-1",
                name="[No-Set] recovery",
                cases=[],
                created_by="user-1",
                agent_evaluation_id=5,
            )

        session.add.assert_not_called()


# ---------------------------------------------------------------------------
# list_case_turn_orders_by_session / get_case_ids_by_session
# ---------------------------------------------------------------------------

class TestListCaseTurnOrders:
    def test_returns_turn_orders(self, session_factory):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        _wire_chain(session, all_rows=[(1,), (None,), (2,)])

        orders = evaluation_set_db.list_case_turn_orders_by_session(
            evaluation_set_id=1, session_id="s1",
        )
        assert orders == [1, 2]

    def test_excludes_case_ids(self, session_factory):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        q = _wire_chain(session, all_rows=[(1,)])

        evaluation_set_db.list_case_turn_orders_by_session(
            evaluation_set_id=1, session_id="s1", exclude_case_ids=[9],
        )
        assert q.filter.call_count == 2  # base filters + notin_ exclude


class TestGetCaseIdsBySession:
    def test_returns_case_ids(self, session_factory):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        _wire_chain(session, all_rows=[(1,), (2,)])

        ids = evaluation_set_db.get_case_ids_by_session(
            evaluation_set_id=1, session_id="s1",
        )
        assert ids == [1, 2]


# ---------------------------------------------------------------------------
# get_cases_by_ids
# ---------------------------------------------------------------------------

class TestGetCasesByIds:
    def test_empty_list_returns_empty(self, session_factory):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        assert evaluation_set_db.get_cases_by_ids([], tenant_id="t1") == []
        assert not session.query.called

    def test_fetches_by_ids(self, session_factory, monkeypatch):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        _wire_chain(session, all_rows=[MagicMock(name="r1")])
        monkeypatch.setattr(evaluation_set_db, "as_dict",
                            lambda r: {"id": id(r)})

        cases = evaluation_set_db.get_cases_by_ids([1], tenant_id="t1")
        assert len(cases) == 1

    def test_filters_by_evaluation_set(self, session_factory, monkeypatch):
        from backend.database import evaluation_set_db

        session, _ = session_factory
        q = _wire_chain(session, all_rows=[])
        monkeypatch.setattr(evaluation_set_db, "as_dict",
                            lambda r: {"id": id(r)})

        evaluation_set_db.get_cases_by_ids(
            [1], tenant_id="t1", evaluation_set_id=2,
        )
        assert q.filter.call_count == 2
