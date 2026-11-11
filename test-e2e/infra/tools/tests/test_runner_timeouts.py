# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bound local Case processes and never accept stale successful JUnit after timeout."""

import json
from pathlib import Path
import sys
import time


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import run_cases


def record(timeout=1):
    return {"case_id": "LOCAL-TIMEOUT", "stage": "D3", "execution": {
        "timeout_seconds": timeout, "implementations": [{"framework": "pytest"}],
    }}


def command(delay, exit_code=0):
    code = (
        "import os,time;from pathlib import Path;"
        "Path(os.environ['RESULT_DIR'],'junit.xml').write_text('<testsuite><testcase name=\"ok\"/></testsuite>');"
        f"time.sleep({delay});raise SystemExit({exit_code})"
    )
    return [sys.executable, "-c", code]


def test_case_deadline_kills_process_and_cannot_pass_stale_junit(monkeypatch, tmp_path):
    monkeypatch.setattr(run_cases, "command_for", lambda *args, **kwargs: ([command(2)], tmp_path))
    import suite_runtime
    processes = []
    original_popen = suite_runtime.subprocess.Popen
    def launch(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(suite_runtime.subprocess, "Popen", launch)
    started = time.monotonic()
    _, status, result = run_cases.run_one(record(), tmp_path, tmp_path / "home", {})
    saved = json.loads((result / "status.json").read_text())
    assert status == "AUTOMATION_ERROR"
    assert saved["timed_out"] is True and saved["exit_code"] == 124
    assert "deadline" in saved["reason"]
    assert saved["execution_status"] != "PASS"
    assert time.monotonic() - started < 4
    assert processes and all(process.poll() is not None for process in processes)


def test_case_deadline_is_shared_across_commands(monkeypatch, tmp_path):
    monkeypatch.setattr(run_cases, "command_for", lambda *args, **kwargs: ([command(0.7), command(0.7)], tmp_path))
    _, status, result = run_cases.run_one(record(), tmp_path, tmp_path / "home", {})
    saved = json.loads((result / "status.json").read_text())
    assert status == "AUTOMATION_ERROR" and saved["timed_out"] is True
    assert saved["command_results"] == [
        {"step": 1, "exit_code": 0, "log": "step-1.log"},
        {"step": 2, "exit_code": 124, "log": "step-2.log"},
    ]


def test_non_timeout_exit_124_is_not_mislabeled(monkeypatch, tmp_path):
    monkeypatch.setattr(run_cases, "command_for", lambda *args, **kwargs: ([command(0, 124)], tmp_path))
    _, status, result = run_cases.run_one(record(), tmp_path, tmp_path / "home", {})
    saved = json.loads((result / "status.json").read_text())
    assert status != "PASS" and saved["exit_code"] == 124
    assert saved["timed_out"] is False


def test_timeout_cleanup_failure_is_reported_and_never_passes(monkeypatch, tmp_path):
    from suite_runtime import CommandTimeoutCleanupError

    monkeypatch.setattr(run_cases, "command_for", lambda *args, **kwargs: ([command(0)], tmp_path))
    def fail_cleanup(*args, **kwargs):
        raise CommandTimeoutCleanupError("Timed-out command cleanup failed")
    monkeypatch.setattr(run_cases, "logged", fail_cleanup)
    _, status, result = run_cases.run_one(record(), tmp_path, tmp_path / "home", {})
    saved = json.loads((result / "status.json").read_text())
    assert status == "AUTOMATION_ERROR" and saved["cleanup_failed"] is True
    assert saved["timed_out"] is True and saved["exit_code"] == 2
    assert "cleanup failed" in saved["reason"]
