from pathlib import Path


def test_conversation_message_action_columns_exist_in_all_schema_paths() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (
        root
        / "deploy/sql/migrations/v2.4.0_0722_add_conversation_message_metadata.sql"
    ).read_text(encoding="utf-8")
    fresh_init = (root / "deploy/sql/init.sql").read_text(encoding="utf-8")

    for sql in (migration, fresh_init):
        assert "message_type" in sql
        assert "message_metadata" in sql
        assert "nl2agent_action" in sql


def test_conversation_message_action_migration_is_idempotent() -> None:
    migration = Path(
        "deploy/sql/migrations/v2.4.0_0722_add_conversation_message_metadata.sql"
    ).read_text(encoding="utf-8")

    assert migration.count("ADD COLUMN IF NOT EXISTS") == 2
