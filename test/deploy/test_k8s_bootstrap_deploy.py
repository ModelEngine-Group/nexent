# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Deployment command ordering with controlled cluster and Helm boundaries."""

import pytest
from test_k8s_helm import _deploy_command, _run
from test_k8s_helm import isolated_k8s_project as _isolated_project

isolated_k8s_project = _isolated_project


@pytest.mark.parametrize("failure", ["", "scale", "bootstrap"])
def test_existing_release_stops_writers_and_activates_only_after_bootstrap(isolated_k8s_project, failure):
    project, env, mock_log = isolated_k8s_project
    env.update({"MOCK_APP_EXISTS": "true", "MOCK_INFRA_EXISTS": "true"})
    if failure:
        env[f"MOCK_FAIL_{failure.upper()}"] = "true"
    result = _run(_deploy_command(project, scope="nexent"), check=False, env=env)
    assert result.returncode == (1 if failure else 0), result.stdout + result.stderr
    commands = mock_log.read_text(encoding="utf-8").splitlines()
    scales = [i for i, line in enumerate(commands) if line.startswith("kubectl scale ")]
    upgrades = [i for i, line in enumerate(commands) if line.startswith("helm upgrade --install nexent ")]
    assert scales
    assert all("--replicas=0" in commands[i] for i in scales)
    assert not any("helm upgrade --install nexent-infrastructure " in line for line in commands)
    if failure == "scale":
        assert not upgrades
        assert not any("nexent-bootstrap-start" in line for line in commands)
        return
    assert len(scales) == 6
    assert max(scales) < upgrades[0]
    assert "global.businessPaused=true" in commands[upgrades[0]]
    if failure == "bootstrap":
        assert len(upgrades) == 1
        assert any(line.startswith("kubectl delete job nexent-system-bootstrap-test ") for line in commands)
        assert not any("nexent-bootstrap-start" in line for line in commands)
        return
    assert len(upgrades) == 2
    start = next(i for i, line in enumerate(commands) if "nexent-bootstrap-start" in line)
    assert upgrades[0] < start < upgrades[1]
    assert "global.businessPaused=false" in commands[upgrades[1]]
    assert {commands[i].split()[2] for i in scales} == {
        f"deployment/nexent-{name}" for name in ("config", "runtime", "mcp", "northbound", "web", "data-process")
    }
