"""SAI-D3-001: actual CoreAgent/Gateway integration in both sandbox scopes."""

import os
from pathlib import Path

import pytest
from shared.config import repo_root, test_root
from shared.sai_docker import execute_probe, verification_image


@pytest.mark.case_id("SAI-D3-001")
@pytest.mark.stage("D3")
@pytest.mark.parametrize("scope", ["session", "system"])
def test_SAI_D3_001_real_kernel_isolation(scope):
    repo = repo_root()
    evidence = Path(os.environ.get("RESULT_DIR") or test_root() / "results/SAI-D3-001") / scope
    with verification_image(repo) as image:
        result = execute_probe(repo, image, evidence, scope, batches=1)
    assert result["successful_invocations"] == 2
    assert result["unhealthy"] == result["replacements"] == result["leftovers"] == 0
    assert result["source_fingerprints"]
    assert result["failed_invocations"] == 1 and result["recovered_after_failure"]
    pair = result["batches"][0]
    assert len(set(pair["kernels"])) == 2 and pair["peak_active_executions"] == 2
    windows = pair["execution_windows"]
    assert [entry["marker"] for entry in windows] == ["LEFT", "RIGHT"]
    assert max(entry["start"] for entry in windows) < min(entry["end"] for entry in windows)
