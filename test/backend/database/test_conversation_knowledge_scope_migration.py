from pathlib import Path


MERGED_MIGRATION = Path("deploy/sql/migrations/v2.5.0_merged_migrations.sql")
KNOWLEDGE_SCOPE_SOURCE_MARKER = (
    "-- Source migration: v2.5.0_0806_add_conversation_knowledge_scope.sql"
)


def _read_conversation_knowledge_scope_migration() -> str:
    merged = MERGED_MIGRATION.read_text(encoding="utf-8")
    assert KNOWLEDGE_SCOPE_SOURCE_MARKER in merged
    knowledge_scope_and_later = merged.split(KNOWLEDGE_SCOPE_SOURCE_MARKER, maxsplit=1)[1]
    next_source_marker = "\n-- Source migration:"
    assert next_source_marker in knowledge_scope_and_later
    return knowledge_scope_and_later.split(next_source_marker, maxsplit=1)[0]


def test_conversation_knowledge_scope_migration_is_repeatable():
    sql = _read_conversation_knowledge_scope_migration()

    assert "SET search_path TO nexent, public" in sql
    assert "ADD COLUMN IF NOT EXISTS knowledge_scope JSONB" in sql
    assert "COMMENT ON COLUMN nexent.conversation_record_t.knowledge_scope" in sql


def test_init_sql_is_not_used_for_conversation_knowledge_scope():
    init_sql = Path("deploy/sql/init.sql").read_text(encoding="utf-8")

    assert "knowledge_scope" not in init_sql
