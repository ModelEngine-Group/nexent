# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Send the finalized report itself; only unusable reports need an exception payload."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import suite_notify
import suite_runtime
import suite_terminal
import suite
from suite_runtime import finalize, render_report, save

ENV = {"LARK_CLI": "offline-cli", "FEISHU_REPORT_CHAT_ID": "offline-chat", "TEST_API_KEY": "fixture-private-key"}


def terminal(directory):
    save(directory / "status.json", {"status": "INCOMPLETE", "error": "fixture-private-key", "local_restored_and_verified": False})
    rows = [{"case_id": "CASE-A", "stage": "D1", "result": "FAIL", "reason": "Bearer fixture-bearer-value"}]
    return rows, finalize(directory, rows, rows, "fixture-private-key")


def test_report_is_redacted_when_generated_and_sent_without_rewriting(tmp_path):
    rows, summary = terminal(tmp_path)
    render_report(tmp_path, rows, rows, summary, environment=ENV)
    report = tmp_path / "report.md"
    before, stamp = report.read_bytes(), report.stat().st_mtime_ns
    assert b"fixture-private-key" not in before and b"fixture-bearer-value" not in before
    assert "批次终态：INCOMPLETE" in before.decode() and "环境恢复状态：" in before.decode()
    with patch.object(suite_notify, "logged", return_value=0) as send:
        assert suite_notify.send_report(tmp_path, ENV) == "SENT"
    assert send.call_args.args[0][-1] == "./report.md"
    assert not (tmp_path / "notification-report.md").exists()
    assert report.read_bytes() == before and report.stat().st_mtime_ns == stamp
    assert "fixture-private-key" in (tmp_path / "summary.json").read_text()
    assert "fixture-bearer-value" in (tmp_path / "checkpoints/results.jsonl").read_text()


@pytest.mark.parametrize("content", [None, b"", b"\xff\xfe"])
def test_only_missing_empty_or_unreadable_report_uses_exception_payload(tmp_path, content):
    _, summary = terminal(tmp_path)
    report = tmp_path / "report.md"
    report.unlink()
    if content is not None:
        report.write_bytes(content)
    with patch.object(suite_notify, "logged", return_value=0) as send:
        assert suite_notify.send_report(tmp_path, ENV) == "SENT"
    assert send.call_args.args[0][-1] == "./notification-report.md"
    text = (tmp_path / "notification-report.md").read_text(encoding="utf-8")
    assert "详细报告未生成" in text and "INCOMPLETE" in text and "环境恢复状态：" in text
    assert "fixture-private-key" not in text
    assert (report.read_bytes() if report.exists() else None) == content


def test_legacy_report_is_updated_in_place_with_one_current_terminal_section(tmp_path):
    rows, summary = terminal(tmp_path)
    summary.update(status="PASSED", error=None, execution_complete=True)
    render_report(tmp_path, rows, rows, summary)
    summary.update(status="INCOMPLETE", error="fixture-private-key", execution_complete=False)
    save(tmp_path / "summary.json", summary)
    with patch.object(suite_notify, "logged", return_value=0) as send:
        assert suite_notify.send_report(tmp_path, ENV) == "SENT"
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert text.count("## 终态与环境恢复") == 1
    assert "批次终态：INCOMPLETE" in text and "批次终态：PASSED" not in text
    assert "fixture-private-key" not in text
    assert "## Case results" in text
    assert "| Result | Count |" in text and "Status: INCOMPLETE" in text
    assert send.call_args.args[0][-1] == "./report.md"
    assert not (tmp_path / "notification-report.md").exists()


def test_failed_atomic_render_keeps_the_previous_complete_report(tmp_path):
    rows, summary = terminal(tmp_path)
    before = (tmp_path / "report.md").read_bytes()
    with patch.object(suite_terminal.os, "replace", side_effect=OSError("fixture disk failure")), pytest.raises(OSError):
        render_report(tmp_path, rows, rows, summary, environment=ENV)
    assert (tmp_path / "report.md").read_bytes() == before
    assert not list(tmp_path.glob(".report-*.tmp"))


def test_execution_passes_machine_secrets_to_report_generation(tmp_path):
    record = {"case_id": "CASE-A", "stage": "D1", "status": "active", "execution": {"test": True}}

    def run(command, cwd, env, log, timeout):
        if "--case" in command:
            directory = Path(command[command.index("--batch-dir") + 1])
            save(directory / "cases/CASE-A/receipt.json", {
                "case_id": "CASE-A", "stage": "D1", "result": "FAIL", "reason": "fixture-private-key"})
        return 0

    with patch.object(suite, "machine_environment", return_value={**os.environ, **ENV}), \
            patch.object(suite, "fingerprint", return_value={"head": "fixture"}), \
            patch.object(suite, "static_requirements", return_value=set()), \
            patch.object(suite, "static_inventory", return_value=[]), \
            patch.object(suite, "logged", side_effect=run):
        assert suite.execute(tmp_path, tmp_path, [record], {"hooks": {}, "case_timeout_seconds": 20}) == 1
    directory = next((tmp_path / "runs/repository-daily").iterdir())
    assert "fixture-private-key" not in (directory / "report.md").read_text(encoding="utf-8")
    assert "fixture-private-key" in (directory / "cases/CASE-A/receipt.json").read_text(encoding="utf-8")


def test_unwritable_legacy_report_does_not_send_unsanitized_original(tmp_path):
    terminal(tmp_path)
    original = (tmp_path / "report.md").read_bytes()
    real_write = suite_notify.write_report

    def write(path, text):
        if path.name == "report.md":
            raise PermissionError("fixture report write failure")
        return real_write(path, text)

    with patch.object(suite_notify, "write_report", side_effect=write), \
            patch.object(suite_notify, "logged", return_value=0) as send:
        assert suite_notify.send_report(tmp_path, ENV) == "SENT"
    assert send.call_args.args[0][-1] == "./notification-report.md"
    assert (tmp_path / "report.md").read_bytes() == original
    assert "fixture-private-key" not in (tmp_path / "notification-report.md").read_text(encoding="utf-8")
