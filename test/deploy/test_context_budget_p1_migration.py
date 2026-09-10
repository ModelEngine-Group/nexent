from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "deploy/sql/migrations/v2.6.0_0903_model_capacity_governance.sql"


def test_capacity_governance_migration_is_nullable_idempotent_and_secret_free():
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    for column in (
        "canonical_model_id",
        "capacity_field_metadata",
        "model_identity_metadata",
        "tokenizer_match_metadata",
        "token_count_probe_metadata",
    ):
        assert f"add column if not exists {column}" in sql
    assert "update nexent.model_record_t" not in sql
    assert "api_key" not in sql
    assert "begin;" in sql
    assert "commit;" in sql
