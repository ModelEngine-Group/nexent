from pathlib import Path


MIGRATION = Path(
    "deploy/sql/migrations/v2.5.0_merged_migrations.sql"
)


def test_conversation_knowledge_scope_migration_is_repeatable():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "SET search_path TO nexent, public" in sql
    assert "ADD COLUMN IF NOT EXISTS knowledge_scope JSONB" in sql
    assert "COMMENT ON COLUMN nexent.conversation_record_t.knowledge_scope" in sql


def test_init_sql_is_not_used_for_conversation_knowledge_scope():
    init_sql = Path("deploy/sql/init.sql").read_text(encoding="utf-8")

    assert "knowledge_scope" not in init_sql
