from pathlib import Path

from database.db_models import AgentShare, AgentShareSession, ConversationRecord


AGENT_SHARE_MIGRATION = Path(
    "deploy/sql/migrations/v2.5.4_agent_share.sql"
)


def test_agent_share_models_preserve_required_identity_boundaries():
    assert AgentShare.__tablename__ == "agent_share_t"
    assert AgentShareSession.__tablename__ == "agent_share_session_t"

    share_columns = AgentShare.__table__.c
    assert {"tenant_id", "agent_id", "owner_user_id", "public_share_id"} <= set(
        share_columns.keys()
    )
    assert "expire_time" not in share_columns

    session_columns = AgentShareSession.__table__.c
    assert {"agent_share_id", "visitor_user_id", "conversation_id", "agent_version_no"} <= set(
        session_columns.keys()
    )
    assert "visitor_subject_hash" not in session_columns

    index_names = {index.name for index in AgentShareSession.__table__.indexes}
    assert "uq_agent_share_session_visitor" in index_names


def test_share_sessions_are_hidden_from_regular_conversation_history():
    assert "is_agent_share" in ConversationRecord.__table__.columns


def test_agent_share_migration_is_repeatable_and_uses_no_expiry():
    sql = AGENT_SHARE_MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS nexent.agent_share_t" in sql
    assert "CREATE TABLE IF NOT EXISTS nexent.agent_share_session_t" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_share_active" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_share_session_visitor" in sql
    assert "visitor_user_id" in sql
    assert "expire_time" not in sql
    assert "is_agent_share" in sql


def test_init_sql_does_not_backfill_agent_share_schema():
    init_sql = Path("deploy/sql/init.sql").read_text(encoding="utf-8")

    assert "agent_share_t" not in init_sql
    assert "agent_share_session_t" not in init_sql
