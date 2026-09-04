from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "deploy/sql/migrations/v2.6.0_0903_model_feature_capabilities.sql"


def test_feature_capability_migration_is_nullable_idempotent_and_secret_free():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "add column if not exists feature_capability_metadata jsonb default null" in sql
    assert "update nexent.model_record_t" not in sql
    assert "api_key" not in sql
    assert "begin;" in sql
    assert "commit;" in sql
