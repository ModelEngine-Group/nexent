from contextlib import contextmanager
from pathlib import Path

from database import agent_automation_db
from database.db_models import AgentAutomationTask


class _FakeRow:
    def __init__(self, payload):
        self._mapping = payload


class _FakeResult:
    def fetchall(self):
        return [_FakeRow({"task_id": 1, "lock_owner": "scheduler-a"})]


class _FakeSession:
    def __init__(self):
        self.statement = None
        self.params = None

    def execute(self, statement, params=None):
        self.statement = str(statement)
        self.params = params
        return _FakeResult()


class _FakeScalarRows:
    def scalars(self):
        return self

    def all(self):
        return []


class _RecordingResult:
    def __init__(self, payload=None, rows=None, rowcount=1):
        self.payload = payload
        self.rows = rows if rows is not None else []
        self.rowcount = rowcount

    def scalar_one(self):
        return self.payload

    def scalar_one_or_none(self):
        return self.payload

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def fetchall(self):
        return self.rows


class _RecordingSession:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((statement, params))
        return self.result


def _install_recording_session(monkeypatch, result):
    session = _RecordingSession(result)

    @contextmanager
    def fake_get_db_session():
        yield session

    monkeypatch.setattr(agent_automation_db, "get_db_session", fake_get_db_session)
    monkeypatch.setattr(agent_automation_db, "as_dict", lambda value: value)
    return session


def test_list_tasks_filters_by_owner_status_and_literal_title_search(monkeypatch):
    class ListSession(_FakeSession):
        def execute(self, statement, params=None):
            self.statement = statement
            self.params = params
            return _FakeScalarRows()

    fake_session = ListSession()

    @contextmanager
    def fake_get_db_session():
        yield fake_session

    monkeypatch.setattr(agent_automation_db, "get_db_session", fake_get_db_session)

    tasks = agent_automation_db.list_tasks(
        "tenant-1",
        "user-1",
        status="ACTIVE",
        search="  100%_天气  ",
    )

    compiled = fake_session.statement.compile()
    statement = str(fake_session.statement)
    assert tasks == []
    assert "tenant_id" in statement
    assert "user_id" in statement
    assert "status" in statement
    assert "lower" in statement
    assert "LIKE" in statement
    assert "ESCAPE" in statement
    assert r"%100\%\_天气%" in compiled.params.values()


def test_claim_due_tasks_uses_db_lease_and_skip_locked(monkeypatch):
    fake_session = _FakeSession()

    @contextmanager
    def fake_get_db_session():
        yield fake_session

    monkeypatch.setattr(agent_automation_db, "get_db_session", fake_get_db_session)

    claimed = agent_automation_db.claim_due_tasks(
        instance_id="scheduler-a",
        batch_size=2,
        lease_seconds=120,
    )

    assert claimed == [{"task_id": 1, "lock_owner": "scheduler-a"}]
    assert "FOR UPDATE SKIP LOCKED" in fake_session.statement
    assert "lock_until = now() + (:lease_seconds * interval '1 second')" in fake_session.statement
    assert "AUTOMATION_LEASE_EXPIRED" in fake_session.statement
    assert "run.status IN ('QUEUED', 'RUNNING')" in fake_session.statement
    assert fake_session.params == {
        "instance_id": "scheduler-a",
        "batch_size": 2,
        "lease_seconds": 120,
    }


def test_get_active_run_task_ids_filters_owner_and_active_statuses(monkeypatch):
    class ScalarRows:
        def scalars(self):
            return self

        def all(self):
            return [1, 3]

    class ActiveRunSession(_FakeSession):
        def execute(self, statement, params=None):
            self.statement = statement
            return ScalarRows()

    fake_session = ActiveRunSession()

    @contextmanager
    def fake_get_db_session():
        yield fake_session

    monkeypatch.setattr(agent_automation_db, "get_db_session", fake_get_db_session)

    task_ids = agent_automation_db.get_active_run_task_ids([1, 2, 3], "tenant", "user")
    statement = str(fake_session.statement)

    assert task_ids == {1, 3}
    assert "tenant_id" in statement
    assert "user_id" in statement
    assert "status" in statement
    assert "delete_flag" in statement


def test_renew_rejects_expired_or_reassigned_lease(monkeypatch):
    class ScalarResult:
        def scalar_one_or_none(self):
            return 1

    class ScalarSession(_FakeSession):
        def execute(self, statement, params=None):
            self.statement = str(statement)
            self.params = params
            return ScalarResult()

    fake_session = ScalarSession()

    @contextmanager
    def fake_get_db_session():
        yield fake_session

    monkeypatch.setattr(agent_automation_db, "get_db_session", fake_get_db_session)

    assert agent_automation_db.renew_task_lock(1, "scheduler-a", 120) is True
    assert "lock_owner = :lock_owner" in fake_session.statement
    assert "lock_until > now()" in fake_session.statement
    assert fake_session.params == {
        "task_id": 1,
        "lock_owner": "scheduler-a",
        "lease_seconds": 120,
    }


def test_conversation_unique_active_index_exists_in_orm_and_sql():
    index_names = {index.name for index in AgentAutomationTask.__table__.indexes}
    assert "uq_agent_automation_conversation_active" in index_names

    unique_index = next(
        index for index in AgentAutomationTask.__table__.indexes
        if index.name == "uq_agent_automation_conversation_active"
    )
    assert unique_index.unique is True
    assert "status <> 'DELETED'" in str(unique_index.dialect_options["postgresql"]["where"])

    init_sql = Path("deploy/sql/init.sql").read_text()
    migration_sql = Path("deploy/sql/migrations/v2.3.0_0713_add_agent_automation.sql").read_text()
    for sql in (init_sql, migration_sql):
        assert "CREATE TABLE IF NOT EXISTS nexent.agent_automation_task_t" in sql
        assert "CREATE TABLE IF NOT EXISTS nexent.agent_automation_run_t" in sql
        assert "CREATE TABLE IF NOT EXISTS nexent.agent_automation_proposal_t" in sql
        assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_automation_conversation_active" in sql
        assert "WHERE delete_flag = 'N' AND status <> 'DELETED'" in sql


def test_active_scheduled_occurrence_has_unique_partial_index():
    index_names = {index.name for index in AgentAutomationTask.metadata.tables[
        "nexent.agent_automation_run_t"
    ].indexes}
    assert "uq_agent_automation_active_occurrence" in index_names

    init_sql = Path("deploy/sql/init.sql").read_text()
    migration_sql = Path("deploy/sql/migrations/v2.3.0_0713_add_agent_automation.sql").read_text()
    for sql in (init_sql, migration_sql):
        assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_automation_active_occurrence" in sql
        assert "status IN ('QUEUED', 'RUNNING')" in sql


def test_task_crud_helpers_cover_owner_scoped_success_paths(monkeypatch):
    payload = {"task_id": 1, "status": "ACTIVE"}
    result = _RecordingResult(payload=payload, rows=[payload])
    session = _install_recording_session(monkeypatch, result)

    assert agent_automation_db.create_task({"title": "task"}, "user") == payload
    assert agent_automation_db.get_task(1, "tenant", "user") == payload
    assert agent_automation_db.get_task_by_conversation(9, "user") == payload
    assert agent_automation_db.get_task_by_conversation(9, "user", include_deleted=True) == payload
    assert agent_automation_db.list_tasks("tenant", "user") == [payload]
    assert agent_automation_db.update_task(1, "tenant", "user", {"title": "updated"}) == payload
    assert (
        agent_automation_db.update_task_if_lock_owner(
            1,
            "tenant",
            "user",
            "scheduler-a",
            {"status": "COMPLETED"},
        )
        == payload
    )
    assert agent_automation_db.soft_delete_task(1, "tenant", "user") is True
    assert agent_automation_db.soft_delete_task_by_conversation(9, "user") == 1
    assert len(session.calls) == 9


def test_proposal_crud_helpers_cover_pending_and_accepted_updates(monkeypatch):
    payload = {"proposal_id": 2, "status": "PENDING"}
    result = _RecordingResult(payload=payload, rowcount=1)
    _install_recording_session(monkeypatch, result)

    assert agent_automation_db.create_proposal({"agent_id": 1}, "user") == payload
    assert agent_automation_db.get_proposal(2, "tenant", "user") == payload
    assert agent_automation_db.update_proposal_status(2, "tenant", "user", "ACCEPTED") is True
    assert agent_automation_db.update_proposal_task(2, "tenant", "user", {"title": "task"}) is True
    assert (
        agent_automation_db.update_proposal(
            2,
            "tenant",
            "user",
            {"title": "task"},
            {"executable": True},
        )
        is True
    )


def test_run_crud_helpers_cover_lifecycle_and_owner_filters(monkeypatch):
    payload = {"run_id": 3, "task_id": 1, "status": "RUNNING"}
    result = _RecordingResult(payload=payload, rows=[payload], rowcount=1)
    _install_recording_session(monkeypatch, result)

    assert agent_automation_db.create_run({"task_id": 1}, "user") == payload
    assert (
        agent_automation_db.update_run(
            3,
            {"status": "SUCCEEDED"},
            user_id="user",
            expected_statuses=["RUNNING"],
        )
        == payload
    )
    assert agent_automation_db.update_run(3, {"status": "FAILED"}) == payload
    assert agent_automation_db.get_run(3, "tenant", "user") == payload
    assert agent_automation_db.cancel_run(3, "tenant", "user", "cancel") == payload
    assert agent_automation_db.soft_delete_run(3, "tenant", "user", ["CANCELED"]) == payload
    assert agent_automation_db.cancel_runs_by_conversation(9, "user", "deleted") == 1
    assert agent_automation_db.list_runs(1, "tenant", "user", limit=1) == [payload]
    assert agent_automation_db.has_active_run_for_conversation(9) is True


def test_lease_recovery_helpers_cover_empty_and_success_paths(monkeypatch):
    assert agent_automation_db.get_active_run_task_ids([], "tenant", "user") == set()

    result = _RecordingResult(payload=1, rowcount=2)
    session = _install_recording_session(monkeypatch, result)

    assert agent_automation_db.release_task_lock(1) is True
    assert agent_automation_db.release_task_lock(1, "scheduler-a") is True
    assert agent_automation_db.recover_orphaned_runs() == 2
    assert agent_automation_db.release_expired_locks() == 2
    assert any("AUTOMATION_LEASE_EXPIRED" in str(statement) for statement, _ in session.calls)


def test_optional_database_rows_return_empty_values(monkeypatch):
    result = _RecordingResult(payload=None, rows=[], rowcount=0)
    _install_recording_session(monkeypatch, result)

    assert agent_automation_db.get_task(1, "tenant", "user") is None
    assert agent_automation_db.get_task_by_conversation(9, "user") is None
    assert agent_automation_db.update_task(1, "tenant", "user", {}) is None
    assert agent_automation_db.get_proposal(2, "tenant", "user") is None
    assert agent_automation_db.get_run(3, "tenant", "user") is None
    assert agent_automation_db.cancel_run(3, "tenant", "user", "cancel") is None
    assert agent_automation_db.soft_delete_run(3, "tenant", "user", ["FAILED"]) is None
    assert agent_automation_db.has_active_run_for_conversation(9) is False
    assert agent_automation_db.renew_task_lock(1, "scheduler-a", 30) is False
