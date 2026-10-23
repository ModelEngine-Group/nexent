# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Removing Kubernetes D5 must not discard or bypass Docker backup checks."""

from pathlib import Path
import sys
from unittest.mock import AsyncMock

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "test-e2e/infra/automation"))

from d5.scenarios import scenario_reliability_deployment_special as special
from d5.scenarios import scenario_security_reliability_deployment as main


@pytest.mark.parametrize("case_id", ["K8S-ENV-D5-001", "DEP-AUTO-00C24E57476D8253"])
def test_removed_cases_have_no_definition_script_or_binding(case_id):
    directory = ROOT / "test-e2e/cases" / case_id
    assert not (directory / "case.yaml").exists()
    assert not (directory / "test.py").exists()
    assert not (directory / "execution.yaml").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_code", [0, 1])
async def test_backup_executes_only_docker_and_preserves_failure(monkeypatch, tmp_path, exit_code):
    contract = tmp_path / "deploy/tests/test_docker_backup.sh"
    contract.parent.mkdir(parents=True)
    contract.write_text("# fixture contract\n", encoding="utf-8")
    monkeypatch.setattr(special, "repo_root", lambda: tmp_path)
    run = AsyncMock(return_value=(exit_code, "fixture backup result"))
    monkeypatch.setattr(special, "run_posix_contract", run)
    if exit_code:
        with pytest.raises(AssertionError, match="backup contract failed"):
            await special._backup_upgrade_rollback_contracts()
    else:
        await special._backup_upgrade_rollback_contracts()
    run.assert_awaited_once_with(contract, timeout=1200)


@pytest.mark.asyncio
async def test_old_kubernetes_dispatch_routes_are_not_executable():
    assert not hasattr(main, "_kubernetes_deployment")
    assert "DEP-03" not in special.CASES
    with pytest.raises(AssertionError, match="unmapped D5"):
        await main.execute_d5_main({"id": "DEP-002"}, None, None, None)
    with pytest.raises(KeyError):
        await special.execute_d5_reliability_deployment_special({"id": "DEP-03"}, None, None)


@pytest.mark.parametrize("case_id", ["DEP-06", "DEP-AUTO-7177AC18CCE799DD"])
def test_mixed_cases_retain_bindings_and_explicit_acceptance(case_id):
    directory = ROOT / "test-e2e/cases" / case_id
    definition = yaml.safe_load((directory / "case.yaml").read_text(encoding="utf-8"))["case"]
    execution = yaml.safe_load((directory / "execution.yaml").read_text(encoding="utf-8"))
    assert definition["status"] == "active"
    assert (directory / execution["implementations"][0]["file"]).is_file()
    assert {item["id"] for item in definition["acceptance"]} == set(execution["acceptance_bindings"])
    assert execution["preparation"]["anchors"] is False
    assert "Helm" not in str(definition) and "Kubernetes" not in str(definition)
