"""Unit tests for ``backend.database.evaluation_set_db``."""

import sys
from pathlib import Path
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
                update_rows=1):
    """Build a chained query mock whose calls return self."""
    q = MagicMock(name="query")
    q.filter.return_value = q
    q.order_by.return_value = q
    q.offset.return_value = q
    q.limit.return_value = q
    q.outerjoin.return_value = q
    q.first.return_value = first
    q.scalar.return_value = scalar
    q.all.return_value = all_rows if all_rows is not None else []
    q.update.return_value = update_rows
    session.query.return_value = q
    return q


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
        from backend.database import evaluation_set_db

        session, _ = session_factory
        _wire_chain(session, first=None)

        with pytest.raises(ValueError, match="evaluation set not found"):
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
        from backend.database import evaluation_set_db

        session, _ = session_factory
        _wire_chain(session, update_rows=0)

        with pytest.raises(ValueError, match="not found or already deleted"):
            evaluation_set_db.soft_delete_evaluation_set(
                evaluation_set_id=999, tenant_id="t1", deleted_by="u1",
            )
