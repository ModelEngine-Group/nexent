from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "deploy/sql/migrations/v2.6.0_0903_model_feature_capabilities.sql"
OVERRIDE_MIGRATION = ROOT / "deploy/sql/migrations/v2.6.0_0904_model_feature_capability_override.sql"


def test_feature_capability_migration_is_nullable_idempotent_and_secret_free():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "add column if not exists feature_capability_metadata jsonb default null" in sql
    assert "update nexent.model_record_t" not in sql
    assert "api_key" not in sql
    assert "begin;" in sql
    assert "commit;" in sql


def test_p8_015_feature_capability_override_migration_is_nullable_and_idempotent():
    sql = OVERRIDE_MIGRATION.read_text(encoding="utf-8").lower()
    assert "add column if not exists feature_capability_override jsonb default null" in sql
    assert "update nexent.model_record_t" not in sql
    assert "api_key" not in sql
    assert "begin;" in sql
    assert "commit;" in sql
