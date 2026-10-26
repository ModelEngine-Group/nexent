# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Offline regressions for the October Daily environment and fixture failures."""
import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parents[2]
sys.path.insert(0, str(TOOLS))
from bootstrap_runtime import bootstrap_commands
from node_preflight import node_toolchain_problems


def test_bootstrap_generates_only_a_missing_machine_local_product_lock(tmp_path):
    frontend = tmp_path / 'frontend'
    commands = bootstrap_commands(tmp_path)
    product_npm = [argv for argv, cwd in commands if cwd == frontend and argv[0] == 'npm']
    assert product_npm == [
        ['npm', 'install', '--package-lock-only', '--ignore-scripts', '--legacy-peer-deps'],
        ['npm', 'ci', '--legacy-peer-deps'],
    ]
    assert not frontend.exists(), 'Planning must not install or create files'
    assert '--legacy-peer-deps' in (REPO / 'deploy/images/dockerfiles/web/Dockerfile').read_text(encoding='utf-8')
    assert '\npackage-lock.json\n' in (REPO / 'frontend/.gitignore').read_text(encoding='utf-8')


def test_bootstrap_keeps_existing_product_lock_and_test_package_policies(tmp_path):
    frontend = tmp_path / 'frontend'
    frontend.mkdir()
    lock = frontend / 'package-lock.json'
    # Even an outdated local lock must reach npm ci, not an automatic version refresh.
    original = b'{"lockfileVersion":3,"packages":{}}\n'
    lock.write_bytes(original)
    commands = bootstrap_commands(tmp_path)
    assert [argv for argv, cwd in commands if cwd == frontend and argv[0] == 'npm'] == [
        ['npm', 'ci', '--legacy-peer-deps']]
    assert lock.read_bytes() == original
    assert not (frontend / '.npmrc').exists()
    for relative in ['test-e2e/infra/automation/d1/frontend', 'test-e2e/infra/automation/d4']:
        assert [argv for argv, cwd in commands if cwd == tmp_path / relative and argv[0] == 'npm'] == [['npm', 'ci']]


def test_bootstrap_installs_both_independently_locked_browser_toolchains():
    commands = bootstrap_commands(REPO)
    browsers = [argv for argv, _ in commands if argv[-2:] == ["install", "chromium"]]
    assert len(browsers) == 2
    assert any(str(REPO / "frontend/node_modules/playwright/cli.js") in argv for argv in browsers)
    assert any(str(REPO / "test-e2e/infra/automation/d4/node_modules/playwright/cli.js") in argv for argv in browsers)


def test_doctor_probes_selected_closures_without_installing(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("node_preflight.shutil.which", lambda _: "node")
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("node_preflight.subprocess.run", run)
    assert node_toolchain_problems(REPO, tmp_path, {"vitest", "playwright", "custom"}) == []
    assert len(calls) == 3
    assert all("install" not in argv for argv, _ in calls)
    assert all(kwargs["env"]["PLAYWRIGHT_BROWSERS_PATH"] == str(tmp_path / "runtime/playwright-browsers")
               for _, kwargs in calls)
    assert "jsdom" in calls[0][0][2]
    assert [Path(argv[-2]).parent for argv, _ in calls[1:]] == [REPO / "frontend", REPO / "test-e2e/infra/automation/d4"]
    assert [argv[-1] for argv, _ in calls[1:]] == ["", "chromium"]
    assert 'channel: "chromium"' in (REPO / 'test-e2e/infra/automation/d4/playwright.config.ts').read_text(encoding='utf-8')


@pytest.mark.parametrize("failure", ["resolution", "timeout", "permission"])
def test_doctor_rejects_broken_or_inaccessible_closure(monkeypatch, tmp_path, failure):
    monkeypatch.setattr("node_preflight.shutil.which", lambda _: "node")
    def run(argv, **kwargs):
        if failure == "timeout": raise subprocess.TimeoutExpired(argv, 30)
        if failure == "permission": raise PermissionError("fixture")
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr("node_preflight.subprocess.run", run)
    assert len(node_toolchain_problems(REPO, tmp_path, {"vitest"})) == 1
    assert node_toolchain_problems(REPO, tmp_path, set()) == []


@pytest.mark.parametrize("case_id", ["AGENT-PROMPT-D5-001", "EVAL-LEGACY-D5-001", "USER-MODEL-READ-D5-001"])
def test_isolated_database_waits_for_final_tcp_server_and_cleans_up(monkeypatch, case_id):
    spec = importlib.util.spec_from_file_location("repair_" + case_id.replace("-", "_"),
        REPO / "test-e2e/cases" / case_id / "test_migration.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    attempts = []
    monkeypatch.setattr(module.shutil, "which", lambda _: "docker")
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    def run(argv, **kwargs):
        calls.append(argv)
        if "pg_isready" in argv:
            # Unix readiness would incorrectly pass during initialization.
            assert argv[argv.index("-h") + 1] == "127.0.0.1"
            attempts.append(1)
            return SimpleNamespace(returncode=1 if len(attempts) == 1 else 0)
        if "psql" in argv:
            assert len(attempts) == 2
            assert argv[argv.index("-h") + 1] == "127.0.0.1"
        return SimpleNamespace(returncode=0, stdout="" if kwargs.get("text") else b"")
    monkeypatch.setattr(module.subprocess, "run", run)
    fixture = module.postgres.__wrapped__()
    next(fixture)("SELECT 1")
    fixture.close()
    assert calls[-1][:3] == ["docker", "rm", "--force"]


def test_prompt_bundle_contains_all_sections_without_unrelated_schema_migrations():
    path = REPO / "test-e2e/cases/AGENT-PROMPT-D5-001/test_migration.py"
    spec = importlib.util.spec_from_file_location("prompt_sections", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "ALTER TABLE nexent.ag_tenant_agent_t" in module.MIGRATION
    assert "unify_marketplace_prompt" in module.MARKETPLACE_MIGRATION
    assert "RENAME COLUMN duty_prompt TO prompt" in module.RENAME_MIGRATION
