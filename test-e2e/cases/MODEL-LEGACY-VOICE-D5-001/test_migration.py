# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Verify that the PostgreSQL upgrade retires only built-in voice placeholders."""

import json
from pathlib import Path

import pytest
from shared.factories.scratch_database import create_scratch, drop_scratch, scratch_name
from shared.postgres import postgres_sql

pytestmark = [pytest.mark.case_id("MODEL-LEGACY-VOICE-D5-001"), pytest.mark.stage("D5")]


@pytest.fixture
def database():
    name = scratch_name()
    create_scratch(name)
    try:
        postgres_sql(
            """
            CREATE SCHEMA nexent;
            CREATE TABLE nexent.model_record_t (
                model_id integer PRIMARY KEY, tenant_id text, model_type text,
                model_name text, display_name text, model_factory text, model_repo text,
                base_url text, api_key text, model_appid text, access_token text, ssl_verify boolean DEFAULT true,
                max_tokens integer DEFAULT 0, used_token integer DEFAULT 0,
                connect_status text DEFAULT 'unavailable', created_by text, create_time timestamptz,
                delete_flag char(1) NOT NULL DEFAULT 'N', updated_by text, update_time timestamptz
            );
            CREATE TABLE nexent.user_tenant_t (user_id text, tenant_id text, create_time timestamptz);
            CREATE TABLE nexent.tenant_config_t (
                tenant_config_id integer PRIMARY KEY, tenant_id text, config_key text, config_value text,
                delete_flag char(1) NOT NULL DEFAULT 'N', updated_by text, update_time timestamptz
            );
            INSERT INTO nexent.model_record_t
                (model_id, tenant_id, model_type, model_name, display_name, model_factory,
                 base_url, model_appid, delete_flag)
            VALUES
                (1, 'a', 'stt', 'volcano_stt', 'volcano_stt', 'OpenAI-API-Compatible', '', '', 'N'),
                (2, 'a', 'stt', 'volcano_stt', 'volcano_stt', 'OpenAI-API-Compatible', NULL, NULL, 'N'),
                (3, 'a', 'tts', 'volcano_tts', 'volcano_tts', 'OpenAI-API-Compatible', '', '', 'N'),
                (4, 'b', 'tts', 'volcano_tts', 'volcano_tts', 'OpenAI-API-Compatible', '', '', 'Y'),
                (5, 'b', 'stt', 'volcano_stt', 'volcano_stt', 'OpenAI-API-Compatible', '', '', 'N'),
                (6, 'b', 'stt', 'volcano_stt', 'volcano_stt', 'OpenAI-API-Compatible', '', 'fixture-app', 'N'),
                (7, 'a', 'tts', 'volcano_tts', 'volcano_tts', 'volcengine', 'wss://fixture.invalid', '', 'N'),
                (8, 'a', 'llm', 'volcano_tts', 'volcano_tts', 'OpenAI-API-Compatible', '', '', 'N');
            INSERT INTO nexent.model_record_t
                (model_id, tenant_id, model_type, model_name, display_name, model_factory,
                 ssl_verify, created_by, updated_by, create_time)
            VALUES
                (9, 'c', 'stt', 'volcano_stt', 'volcano_stt', 'OpenAI-API-Compatible', false,
                    'creator', 'creator', '2026-06-01 12:00:00+00'),
                (10, 'd', 'tts', 'volcano_tts', 'volcano_tts', 'OpenAI-API-Compatible', true,
                    'manual-admin', 'manual-admin', '2026-06-01 12:00:00+00'),
                (11, 'd', 'stt', 'volcano_stt', 'volcano_stt', 'OpenAI-API-Compatible', true,
                    'manual-admin', 'manual-admin', '2026-06-01 12:00:01+00'),
                (12, 'e', 'stt', 'volcano_stt', 'volcano_stt', 'OpenAI-API-Compatible', true,
                    'unpaired-admin', 'unpaired-admin', '2026-06-01 12:00:00+00'),
                (13, 'f', 'tts', 'volcano_tts', 'volcano_tts', 'OpenAI-API-Compatible', true,
                    'seed-admin', 'seed-admin', '2026-06-01 12:00:00+00'),
                (14, 'f', 'stt', 'volcano_stt', 'volcano_stt', 'OpenAI-API-Compatible', true,
                    'seed-admin', 'seed-admin', '2026-06-01 12:00:01+00');
            INSERT INTO nexent.user_tenant_t VALUES
                ('manual-admin', 'd', '2026-06-01 10:00:00+00'),
                ('unpaired-admin', 'e', '2026-06-01 11:59:59+00'),
                ('seed-admin', 'f', '2026-06-01 11:59:59+00');
            INSERT INTO nexent.tenant_config_t (tenant_config_id, tenant_id, config_key, config_value)
            VALUES
                (1, 'a', 'STT_ID', ' 001 '),
                (2, 'a', 'TTS_ID', '3'),
                (3, 'a', 'STT_MODEL_FACTORY', 'volcengine'),
                (4, 'a', 'STT_MODEL_APPID', 'separately-configured-app'),
                (5, 'a', 'STT_ACCESS_TOKEN', 'fixture-access-token'),
                (6, 'b', 'TTS_ID', '4'),
                (7, 'b', 'STT_ID', '5'),
                (8, 'b', 'STT_ID', '6'),
                (9, 'b', 'STT_MODEL_APPID', 'fixture-app'),
                (10, 'b', 'TTS_ID', '3'),
                (11, 'a', 'LLM_ID', '3'),
                (12, 'a', 'TTS_ID', '1'),
                (13, 'a', 'TTS_ID', '7'),
                (14, 'b', 'TTS_ID', 'bad-id'),
                (15, 'f', 'TTS_ID', '13'),
                (16, 'f', 'STT_ID', '14'),
                (17, 'c', 'STT_ID', '9'),
                (18, 'd', 'TTS_ID', '10'),
                (19, 'e', 'STT_ID', '12');
            """,
            database=name,
        )
        yield name
    finally:
        drop_scratch(name)


def snapshot(database, table, key):
    rows = postgres_sql(
        f"SELECT row_to_json(record) FROM nexent.{table} AS record ORDER BY {key};",
        database=database,
    )
    return {row[key]: row for row in map(json.loads, rows.splitlines())}


def assert_only_retired(before, after, retired):
    assert before.keys() == after.keys()
    for key, row in before.items():
        if key in retired:
            update_time = after[key]["update_time"]
            assert update_time
            assert after[key] == {**row, "delete_flag": "Y", "updated_by": "system", "update_time": update_time}
        else:
            assert after[key] == row


def test_upgrade_retires_only_legacy_voice_settings_and_is_idempotent(database):
    migrations = Path(__file__).resolve().parents[3] / "deploy/sql/migrations"
    migration, = migrations.glob("*_retire_legacy_volcano_voice_models.sql")
    sql = migration.read_text(encoding="utf-8")
    before_models = snapshot(database, "model_record_t", "model_id")
    before_configs = snapshot(database, "tenant_config_t", "tenant_config_id")

    counts = postgres_sql(sql, database=database).strip().split("\t")
    after_models = snapshot(database, "model_record_t", "model_id")
    after_configs = snapshot(database, "tenant_config_t", "tenant_config_id")
    assert_only_retired(before_models, after_models, {1, 2, 3, 5, 13, 14})
    assert_only_retired(before_configs, after_configs, {1, 2, 6, 7, 15, 16})
    assert counts == ["6", "6"]

    assert postgres_sql(sql, database=database).strip().split("\t") == ["0", "0"]
    assert snapshot(database, "model_record_t", "model_id") == after_models
    assert snapshot(database, "tenant_config_t", "tenant_config_id") == after_configs
