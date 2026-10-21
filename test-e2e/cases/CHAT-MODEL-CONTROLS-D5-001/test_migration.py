# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""SU-AC-03: actual PostgreSQL upgrade preserves settings and unrelated resources."""

import json
from pathlib import Path

import pytest
from shared.factories.scratch_database import create_scratch, drop_scratch, scratch_name
from shared.postgres import postgres_sql

pytestmark = [pytest.mark.case_id("CHAT-MODEL-CONTROLS-D5-001"), pytest.mark.stage("D5")]
MIGRATION = Path(__file__).resolve().parents[3] / "deploy/sql/migrations/v2.7.1_007_unify_conversation_model_parameters.sql"


@pytest.fixture
def database():
    name = scratch_name()
    create_scratch(name)
    try:
        postgres_sql("""CREATE SCHEMA nexent;
            CREATE TABLE nexent.conversation_record_t (
                conversation_id integer PRIMARY KEY, workbench_config jsonb,
                workbench_config_version integer NOT NULL DEFAULT 0,
                model_parameter_preferences jsonb NOT NULL DEFAULT '{}',
                model_parameter_preferences_version integer NOT NULL DEFAULT 0,
                updated_by text, update_time timestamptz,
                message_fixture jsonb NOT NULL DEFAULT '{"messages":["keep"]}');""", database=name)
        yield name
    finally:
        drop_scratch(name)


def insert(database, identifier, config, preferences=None):
    # Inputs are fixed fixture values; quote SQL string literals without interpolation of secrets.
    def literal(value):
        return "'" + json.dumps(value).replace("'", "''") + "'::jsonb"
    postgres_sql(f"INSERT INTO nexent.conversation_record_t(conversation_id, workbench_config, model_parameter_preferences) "
                 f"VALUES ({identifier}, {literal(config)}, {literal(preferences or {})});", database=database)


def rows(database):
    output = postgres_sql("SELECT row_to_json(t)::text FROM nexent.conversation_record_t t ORDER BY conversation_id;", database=database)
    values = [json.loads(line) for line in output.splitlines() if line.strip()]
    for row in values:
        row.setdefault("selected_model_id", None)
    return values


def config(**generation):
    return {"schema_version": 3, "mode": "single_agent_chat", "model_id": 42,
            "generation_config": generation, "agent_mounts": [{"agent_id": 7, "version_no": 2}],
            "skill_mounts": [{"skill_id": 9, "config_values": {"region": "test"}}],
            "knowledge_scope": {"local": {"knowledge_ids": [4]}}}


def test_su_ac_03_upgrade_is_exact_and_idempotent(database):
    insert(database, 1, config(deep_thinking=True, thinking_effort="auto", reasoning_budget_tokens=1024,
                              temperature=0, top_p=1, requested_output_tokens=2000), {"43": {"temperature": 0.9}})
    insert(database, 2, config(deep_thinking=False, thinking_effort="high", reasoning_budget_tokens=1024),
           {"42": {"enable_thinking": True, "reasoning_effort": "low"}})
    insert(database, 3, config(deep_thinking=True, reasoning_budget_tokens=1024), {"42": {"enable_thinking": False}})
    insert(database, 4, {**config(deep_thinking=False, thinking_effort="low"), "model_parameters_source": "outlet_preferences"},
           {"42": {"temperature": 0.3}})
    insert(database, 5, None, {"42": {"temperature": 0.5}})
    before = rows(database)
    postgres_sql(MIGRATION.read_text(), database=database)
    after = rows(database)
    assert after[0]["model_parameter_preferences"] == {
        "42": {"enable_thinking": True, "reasoning_budget_tokens": 1024, "temperature": 0, "top_p": 1},
        "43": {"temperature": 0.9}}
    assert after[1]["model_parameter_preferences"]["42"] == {"enable_thinking": True, "reasoning_effort": "low"}
    assert after[2]["model_parameter_preferences"]["42"] == {"enable_thinking": False}
    assert after[3]["model_parameter_preferences"] == {"42": {"temperature": 0.3}}
    assert after[4] == before[4]
    for old, new in zip(before[:4], after[:4]):
        expected = {key: value for key, value in old["workbench_config"].items()
                    if key not in {"generation_config", "model_parameters_source", "schema_version", "model_id"}}
        assert new["workbench_config"] == {**expected, "schema_version": 4,
            **({"requested_output_tokens": 2000} if old["conversation_id"] == 1 else {})}
        assert new["selected_model_id"] == 42
        assert new["message_fixture"] == old["message_fixture"]
        assert new["workbench_config_version"] == old["workbench_config_version"] + 1
    postgres_sql(MIGRATION.read_text(), database=database)
    assert rows(database) == after


def test_su_ac_03_missing_model_identity_fails_without_discarding_settings(database):
    legacy = config(temperature=0.2)
    legacy.pop("model_id")
    insert(database, 1, legacy)
    before = rows(database)
    with pytest.raises(Exception):
        postgres_sql(MIGRATION.read_text(), database=database)
    assert rows(database) == before
