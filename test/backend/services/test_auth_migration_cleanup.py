# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Source cleanup follows an explicit committed worker result."""

import json

import pytest

from test.backend.services.migration_shell_fixture import run_migration


def source_removals(result):
    return [command for command in result.commands if command[0] == "docker" and command[1] in {"stop", "rm"}
            and not command[-1].startswith("account-migration-")]


@pytest.mark.parametrize("apply", [False, True])
def test_cleanup_only_after_successful_apply(tmp_path, apply):
    result = run_migration(tmp_path, ["--apply"] if apply else [])
    assert result.code == 0, result.stderr
    calls = source_removals(result)
    assert bool(calls) is apply
    if apply:
        assert [c[-1] for c in calls if c[1] == "rm"] == ["supabase-kong-mini", "supabase-auth-mini", "supabase-db-mini"]
        started = next(i for i,c in enumerate(result.commands) if c[1:3] == ["start", "-a"])
        assert all(result.commands.index(c) > started for c in calls)
        assert not any("-v" in c or "volume" in c for c in calls)


@pytest.mark.parametrize("values", [{"FAKE_WORKER_STATUS": "1"}, {"FAKE_EXIT_CODE": "1"},
    {"FAKE_RESULT": '{"committed":false}'}, {"FAKE_RESULT": '{"skipped":true}'}])
def test_failed_or_uncommitted_worker_preserves_source(tmp_path, values):
    result = run_migration(tmp_path, ["--apply"], values)
    assert not source_removals(result)
    assert result.code == (0 if "skipped" in values.get("FAKE_RESULT", "") else 1)
    assert any(c[1:3] == ["rm", "-f"] and c[-1].startswith("account-migration-") for c in result.commands)


def test_remote_source_does_not_remove_local_containers(tmp_path):
    result = run_migration(tmp_path, ["--apply"], {"SUPABASE_POSTGRES_HOST": "original.example"})
    assert result.code == 0, result.stderr
    assert not source_removals(result)


def test_cleanup_error_reports_committed_data_without_driver_values(tmp_path):
    result = run_migration(tmp_path, ["--apply"], {"FAKE_CLEANUP_STATUS": "1"})
    assert result.code == 0
    assert "cleanup incomplete" in result.stderr
    assert "private-source" not in result.stderr and "private-target" not in result.stderr
