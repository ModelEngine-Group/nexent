from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "deploy/sql/migrations/v2.6.0_0903_context_usage_observability.sql"


def test_usage_observability_migration_is_nullable_idempotent_and_content_free():
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "add column if not exists context_budget_evidence jsonb default null" in sql
    assert "update nexent.model_monitoring_record_t" not in sql
    for content_field in ("api_key", "prompt", "messages", "tool_arguments", "endpoint"):
        assert content_field not in sql
    assert "begin;" in sql
    assert "commit;" in sql
