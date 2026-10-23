"""SAI-D5-001: forty overlapping invocations against the current SDK image."""

import os
from pathlib import Path

import pytest
from shared.config import repo_root, test_root
from shared.sai_docker import execute_probe, verification_image


@pytest.mark.case_id("SAI-D5-001")
@pytest.mark.stage("D5")
def test_SAI_D5_001_repeated_parallel_calls():
    repo = repo_root()
    evidence = Path(os.environ.get("RESULT_DIR") or test_root() / "results/SAI-D5-001")
    profiles = []
    with verification_image(repo) as image:
        for scope in ("session", "system"):
            profiles.append(execute_probe(repo, image, evidence / scope, scope, batches=10))
    assert sum(profile["successful_invocations"] for profile in profiles) == 40
    kernels = []
    for profile in profiles:
        assert profile["unhealthy"] == profile["replacements"] == profile["leftovers"] == 0
        assert len(profile["batches"]) == 10
        assert profile["failed_invocations"] == 1 and profile["recovered_after_failure"]
        for pair in profile["batches"]:
            kernels.extend(pair["kernels"])
            assert pair["peak_active_executions"] == 2
            windows = pair["execution_windows"]
            assert [entry["marker"] for entry in windows] == ["LEFT", "RIGHT"]
            assert max(entry["start"] for entry in windows) < min(entry["end"] for entry in windows)
    assert len(kernels) == len(set(kernels)) == 40
