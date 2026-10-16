# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Regression tests for the worker prerequisite-failure wiring.

Pins the review finding that attach-stage dependency failures must keep
their typed receipt (BLOCKED / BLOCKED_BY_DEPENDENCY with the concrete
reason) instead of collapsing into a bare AUTOMATION_ERROR, and that the
worker process itself binds RESULT_DIR so a receipt written before any
preparation subprocess starts is not silently dropped.
"""
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import suite


@pytest.fixture()
def case_dir(tmp_path):
    (tmp_path / "runtime").mkdir()
    return tmp_path


def write_receipt(case_dir, result="BLOCKED_BY_DEPENDENCY",
                  reason="identity mismatch: instance owned by run-other"):
    (case_dir / "runtime/preparation-failure.json").write_text(
        json.dumps({"result": result, "error_type": "AssetDependencyError", "reason": reason}),
        encoding="utf-8",
    )


def test_dependency_receipt_maps_to_blocked_outcome(case_dir):
    write_receipt(case_dir)
    outcome, reason, details = suite.dependency_failure_outcome(
        case_dir, {}, outcome="AUTOMATION_ERROR", exc=RuntimeError("boom"))
    assert outcome == "BLOCKED_BY_DEPENDENCY"
    assert "identity mismatch" in reason
    assert details == {"evidence": ["runtime/preparation-failure.json"]}


def test_receipt_adopted_without_preparation_log(case_dir):
    """Attach failures raise before any preparation step: preparation_log is None."""
    write_receipt(case_dir, reason="profile selection config config/aidp-journey.yaml is missing")
    outcome, reason, details = suite.dependency_failure_outcome(
        case_dir, {}, outcome="AUTOMATION_ERROR", exc=RuntimeError("x"), preparation_log=None)
    assert outcome == "BLOCKED_BY_DEPENDENCY"
    assert "aidp-journey" in reason
    assert details == {"evidence": ["runtime/preparation-failure.json"]}


def test_missing_receipt_keeps_automation_error(case_dir):
    outcome, reason, details = suite.dependency_failure_outcome(
        case_dir, {}, outcome="AUTOMATION_ERROR", exc=RuntimeError("boom"))
    assert outcome == "AUTOMATION_ERROR"
    assert reason == "RuntimeError"
    assert details is None


def test_preparation_log_evidence_retained_without_receipt(case_dir):
    log = case_dir / "logs/prepare-anchors.log"
    log.parent.mkdir()
    log.write_text("failed\n", encoding="utf-8")
    outcome, reason, details = suite.dependency_failure_outcome(
        case_dir, {}, outcome="BLOCKED", exc=RuntimeError("prep failed"), preparation_log=log)
    assert outcome == "BLOCKED"
    assert "prep failed" in reason
    assert details == {"evidence": ["logs/prepare-anchors.log"]}


def test_timeout_outcome_is_not_downgraded(case_dir):
    write_receipt(case_dir, result="TIMEOUT", reason="timed out")
    outcome, _, _ = suite.dependency_failure_outcome(
        case_dir, {}, outcome="TIMEOUT", exc=RuntimeError("x"))
    assert outcome == "TIMEOUT"


def test_bind_result_directory_sets_process_and_env(monkeypatch, tmp_path):
    monkeypatch.delenv("RESULT_DIR", raising=False)
    env: dict = {}
    target = tmp_path / "cases/CASE-1"
    suite.bind_result_directory(env, target)
    assert env["RESULT_DIR"] == str(target)
    assert os.environ["RESULT_DIR"] == str(target)
