# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Real Jiuwen resources through canonical model transport."""
import asyncio
import json
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/'sdk'), str(ROOT/'backend'), str(ROOT/'test-e2e/infra/automation')]
from jiuwen_resource_runtime import resource_provider, run_resources
from jiuwen_bridge_runtime import stop_infrastructure
pytestmark = [pytest.mark.case_id("JIUWEN-RESOURCES-D5-001"), pytest.mark.stage("D5")]

@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    stop_infrastructure()

@pytest.mark.parametrize("protocol", ["native", "text"])
@pytest.mark.parametrize("scenario", ["timeout", "cancel"])
def test_resource_blocked_mcp_cleanup(monkeypatch, tmp_path, protocol, scenario):
    with resource_provider(tmp_path) as url:
        info, state, output, calls, effects, elapsed = asyncio.run(run_resources(monkeypatch, tmp_path, url, protocol, scenario))
    assert info.attempt_outcome == ("stopped" if scenario == "cancel" else "failed"), output[-1:]
    assert state["mcp_calls"] == 1 and state["model_calls"] == 1
    assert calls == [] and effects == ""
    assert elapsed < 10
    # A fresh owner and provider must still complete after cancellation/timeout.
    with resource_provider(tmp_path) as url:
        restored, _, _, _, effects, _ = asyncio.run(run_resources(monkeypatch, tmp_path, url, protocol))
    assert restored.attempt_outcome == "completed" and effects == "x"
