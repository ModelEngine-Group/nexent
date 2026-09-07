"""Tests for tenant-scoped Skill name uniqueness."""

from pathlib import Path

from backend.database.db_models import SkillInfo


MIGRATION_PATH = Path(
    "deploy/sql/migrations/"
    "v2.4_merged_migrations.sql"
)


def test_skill_name_is_not_globally_unique_in_orm():
    assert SkillInfo.__table__.c.skill_name.unique is not True


def test_skill_name_partial_unique_indexes_exist_in_orm():
    indexes = {index.name: index for index in SkillInfo.__table__.indexes}

    tenant_index = indexes["uq_skill_info_tenant_name_active"]
    assert tenant_index.unique is True
    assert [column.name for column in tenant_index.columns] == [
        "tenant_id",
        "skill_name",
    ]
    assert (
        str(tenant_index.dialect_options["postgresql"]["where"])
        == "tenant_id IS NOT NULL AND delete_flag = 'N'"
    )

    global_index = indexes["uq_skill_info_global_name_active"]
    assert global_index.unique is True
    assert [column.name for column in global_index.columns] == ["skill_name"]
    assert (
        str(global_index.dialect_options["postgresql"]["where"])
        == "tenant_id IS NULL AND delete_flag = 'N'"
    )


def test_skill_name_partial_unique_indexes_exist_in_v240_migration():
    migration_sql = MIGRATION_PATH.read_text(encoding="utf-8")

    assert (
        "DROP CONSTRAINT IF EXISTS ag_skill_info_t_skill_name_key"
        in migration_sql
    )
    assert (
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_skill_info_tenant_name_active"
        in migration_sql
    )
    assert (
        "WHERE tenant_id IS NOT NULL AND delete_flag = 'N'"
        in migration_sql
    )
    assert (
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_skill_info_global_name_active"
        in migration_sql
    )
    assert "WHERE tenant_id IS NULL AND delete_flag = 'N'" in migration_sql
    assert "GROUP BY tenant_id, skill_name" in migration_sql
    assert "GROUP BY skill_name" in migration_sql
