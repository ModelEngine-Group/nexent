from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "deploy/sql/migrations/v2.5.4_0910_context_budget_v2.sql"


def test_context_budget_v2_migration_is_transactional_and_idempotent():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert sql.startswith("-- Context Budget V2 final-state migration.")
    assert "BEGIN;" in sql
    assert sql.rstrip().endswith("COMMIT;")
    assert "ADD COLUMN IF NOT EXISTS budget_schema_version" in sql
    assert "DROP COLUMN IF EXISTS budget_hard_input_budget_tokens" in sql
    assert "to_regclass('nexent.model_monitoring_record_t')" in sql


def test_context_budget_v2_migration_preserves_trigger_and_derives_target():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "RENAME COLUMN budget_soft_limit_ratio" in sql
    assert "TO budget_compaction_trigger_ratio" in sql
    assert "RENAME COLUMN budget_soft_input_budget_tokens" in sql
    assert "TO budget_compaction_trigger_threshold_tokens" in sql
    assert "FLOOR(budget_effective_input_limit_tokens * 0.6)::INTEGER" in sql
    assert "budget_compaction_target_ratio_source" in sql
    assert "'code_default'" in sql


def test_orm_uses_only_canonical_physical_columns():
    model_source = (ROOT / "backend/database/db_models.py").read_text(encoding="utf-8")
    model_contract = model_source.split("class ModelMonitoringRecord", 1)[1].split(
        "class ToolInfo", 1
    )[0]

    for canonical in (
        "effective_input_limit_tokens",
        "budget_effective_input_limit_tokens",
        "budget_compaction_trigger_threshold_tokens",
        "budget_compaction_target_tokens",
        "budget_schema_version",
    ):
        assert canonical in model_contract

    for legacy in (
        "budget_provider_input_limit_tokens",
        "budget_soft_limit_ratio",
        "budget_soft_input_budget_tokens",
        "budget_hard_input_budget_tokens",
    ):
        assert legacy not in model_contract
