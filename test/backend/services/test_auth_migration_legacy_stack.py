# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Manual legacy recovery uses original data and exact source names."""

import pytest

from test.backend.services.migration_shell_fixture import run_migration


def test_missing_data_refuses_to_create_any_container(tmp_path):
    result = run_migration(tmp_path, ["up"], {"FAKE_NAMES": ""}, data=False)
    assert result.code != 0
    assert "PG_VERSION" in result.stderr
    assert not any(c[1] == "compose" for c in result.commands)


def test_missing_containers_restore_only_database_by_default(tmp_path):
    result = run_migration(tmp_path, ["up"], {"FAKE_NAMES": ""})
    assert result.code == 0, result.stderr
    call = next(c for c in result.commands if c[1] == "compose")
    assert call[-4:] == ["up", "-d", "--no-recreate", "db"]
    assert "legacy-auth" not in call


def test_full_stack_requires_original_auth_keys(tmp_path):
    result = run_migration(tmp_path, ["up", "--with-auth"], {"FAKE_NAMES": "", "JWT_SECRET": "", "SUPABASE_KEY": "", "SERVICE_ROLE_KEY": "", "DASHBOARD_PASSWORD": ""})
    assert result.code != 0
    assert "original signing keys" in result.stderr
    assert not any(c[1] == "compose" for c in result.commands)


def test_full_stack_and_production_overlay(tmp_path):
    result = run_migration(tmp_path, ["up", "--with-auth", "--production"], {"FAKE_NAMES": "",
        "JWT_SECRET": "fixture-signing", "SUPABASE_KEY": "fixture-anon", "SERVICE_ROLE_KEY": "fixture-service", "DASHBOARD_PASSWORD": "fixture-dashboard"})
    assert result.code == 0, result.stderr
    call = next(c for c in result.commands if c[1] == "compose")
    assert call[-3:] == ["db", "auth", "kong"]
    assert "legacy-auth" in call
    assert any(value.endswith("docker-compose-supabase.prod.yml") for value in call)


@pytest.mark.parametrize("running", ["true", "false"])
def test_existing_container_is_reused_without_recreation(tmp_path, running):
    result = run_migration(tmp_path, ["up"], {"FAKE_NAMES": "supabase-db-mini", "FAKE_RUNNING": running})
    assert result.code == 0, result.stderr
    assert not any(c[1] == "compose" for c in result.commands)
    assert any(c[1] == "start" for c in result.commands) is (running == "false")


def test_mixed_container_set_requires_explicit_teardown(tmp_path):
    result = run_migration(tmp_path, ["up", "--with-auth"], {"FAKE_NAMES": "supabase-db-mini",
        "JWT_SECRET": "fixture", "SUPABASE_KEY": "fixture", "SERVICE_ROLE_KEY": "fixture", "DASHBOARD_PASSWORD": "fixture"})
    assert result.code != 0
    assert "Partial legacy stack" in result.stderr


@pytest.mark.parametrize("network,owner,removed", [("nexent_supabase_migration", "nexent-supabase-migration", True),
    ("nexent_network", "nexent-supabase-migration", False), ("nexent_supabase_migration", "foreign-project", False)])
def test_down_removes_only_owned_legacy_network_and_preserves_volumes(tmp_path, network, owner, removed):
    result = run_migration(tmp_path, ["down"], {"SUPABASE_MIGRATION_NETWORK": network, "FAKE_PROJECT": owner})
    assert result.code == 0, result.stderr
    assert any(c[1:3] == ["network", "rm"] for c in result.commands) is removed
    assert not any("-v" in c or "volume" in c for c in result.commands)
    assert [c[-1] for c in result.commands if c[1] == "rm"] == ["supabase-db-mini", "supabase-auth-mini", "supabase-kong-mini"]


@pytest.mark.parametrize("name", ["database", "supabase;unsafe", "../supabase"])
def test_invalid_or_nonlegacy_names_rejected_before_docker(tmp_path, name):
    result = run_migration(tmp_path, ["up"], {"SUPABASE_MIGRATION_DB_CONTAINER": name})
    assert result.code != 0
    assert result.commands == []
