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
    assert fake_session.params == {
        "instance_id": "scheduler-a",
        "batch_size": 2,
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
