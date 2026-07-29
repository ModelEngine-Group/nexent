from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "deploy/sql/migrations/v2.4.0_0727_add_generate_a2ui_tool.sql"
)


def test_a2ui_tool_migration_uses_canonical_tenants_and_is_idempotent():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "FROM nexent.user_tenant_t" in sql
    assert "existing.author = tenant_catalog.tenant_id" in sql
    assert "existing.name = 'generate_a2ui'" in sql
    assert "ROW_NUMBER() OVER" in sql
    assert "FROM nexent.ag_tool_instance_t instance" in sql
    assert "SET source = 'local'" in sql
    assert "usage = NULL" in sql
    assert "SET source = 'builtin'" not in sql


def test_a2ui_tool_migration_cleans_only_non_tenant_placeholder():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "author = 'tenant_id'" in sql
    assert "tenant.tenant_id = 'tenant_id'" in sql
    assert "SET delete_flag = 'Y'" in sql
    assert "AND source = 'builtin'" not in sql
