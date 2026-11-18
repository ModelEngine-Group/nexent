# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Docker source discovery and one-shot worker boundaries."""

import pytest

from test.backend.services.migration_shell_fixture import run_migration


@pytest.mark.parametrize("running", ["true", "false"])
def test_existing_source_only_starts_when_stopped(tmp_path, running):
    result = run_migration(tmp_path, values={"FAKE_RUNNING": running})
    assert result.code == 0, result.stderr
    starts = [c for c in result.commands if c[1:] == ["start", "supabase-db-mini"]]
    assert bool(starts) is (running == "false")
    create = next(c for c in result.commands if c[1] == "create")
    assert "--entrypoint" in create and "python" in create and "--container" in create
    assert "private-source" not in str(result.commands) and "private-target" not in str(result.commands)


def test_selected_original_source_is_used(tmp_path):
    result = run_migration(tmp_path, ["--source-container", "supabase-original-db"],
        {"FAKE_NAMES": "supabase-original-db\nsupabase-other-db"})
    assert result.code == 0, result.stderr
    assert any(c[1:] == ["inspect", "supabase-original-db"] for c in result.commands)


@pytest.mark.parametrize("names,data", [("", False), ("supabase-one-db\nsupabase-two-db", True)])
def test_missing_or_ambiguous_source_never_creates_empty_database(tmp_path, names, data):
    result = run_migration(tmp_path, values={"FAKE_NAMES": names}, data=data)
    assert result.code != 0
    assert not any(c[1] in {"create", "compose"} for c in result.commands)


def test_no_start_option_preserves_stopped_container(tmp_path):
    result = run_migration(tmp_path, ["--no-start-source"], {"FAKE_RUNNING": "false"})
    assert result.code != 0
    assert not any(c[1] == "start" for c in result.commands)


def test_explicit_remote_source_never_starts_a_source_container(tmp_path):
    result = run_migration(tmp_path, values={"SUPABASE_POSTGRES_HOST": "original.example"})
    assert result.code == 0, result.stderr
    assert not any(c[1] == "ps" or c[1:] == ["start", "supabase-db-mini"] for c in result.commands)


@pytest.mark.parametrize("timeout", ["0", "301", "bad"])
def test_readiness_timeout_is_bounded_before_platform_access(tmp_path, timeout):
    result = run_migration(tmp_path, ["--wait-timeout", timeout])
    assert result.code != 0
    assert result.commands == []
