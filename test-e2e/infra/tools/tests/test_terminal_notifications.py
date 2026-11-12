# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Offline terminal-report regression tests; sending, deployment and Git are substituted."""
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import signal
import sys
from unittest.mock import patch

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import deployment_exceptions as modes
import suite
import suite_notify
from suite_runtime import finalize, save

fixture_spec = importlib.util.spec_from_file_location("offline_campaign_fixture", TOOLS / "tests/test_deployment_exceptions.py")
campaign_module = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(campaign_module)
campaign_fixture = campaign_module.campaign_fixture

spec = importlib.util.spec_from_file_location("terminal_daily_launcher", TOOLS.parent / "scripts/daily-launch.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
worker_spec = importlib.util.spec_from_file_location("terminal_daily_worker", TOOLS.parent / "scripts/daily-worker.py")
worker = importlib.util.module_from_spec(worker_spec)
worker_spec.loader.exec_module(worker)
ENV = {"LARK_CLI": "offline-cli", "FEISHU_REPORT_CHAT_ID": "offline-chat"}


def receipt(directory, status, *, complete=False, error=None):
    save(directory / "summary.json", {"status": status, "execution_complete": complete,
         "d6_complete": True, "planned": 2, "recorded": 2,
         "counts": {"PASS": 1, "NOT_EXECUTED": 1} if not complete else {"PASS": 2},
         "error": error, "finished_at": "2026-11-10T03:25:00+00:00"})
    save(directory / "status.json", {"status": status, "finished_at": "2026-11-10T03:25:00+00:00",
         "error": error, "local_restored_and_verified": False})
    (directory / "report.md").write_text("# Original report\n", encoding="utf-8")


@pytest.mark.parametrize("status", ["PASSED", "FAILED", "INCOMPLETE", "INTERRUPTED", "CANCELLED"])
def test_every_terminal_state_sends_and_preserves_results(tmp_path, status):
    receipt(tmp_path, status, complete=status in {"PASSED", "FAILED"}, error="Interrupted" if status == "INTERRUPTED" else None)
    original = (tmp_path / "summary.json").read_bytes()
    with patch.object(suite_notify, "logged", return_value=0) as send:
        assert suite_notify.send_report(tmp_path, ENV) == "SENT"
        assert suite_notify.send_report(tmp_path, ENV) == "SENT"
    send.assert_called_once()
    text = (tmp_path / "notification-report.md").read_text(encoding="utf-8")
    assert f"批次终态：{status}" in text
    assert "环境恢复状态：" in text
    assert "Original report" in text
    if status == "INTERRUPTED":
        assert "Interrupted" in text and "NOT_EXECUTED=1" in text
    assert (tmp_path / "summary.json").read_bytes() == original
    assert send.call_args.args[0][-1] == "./notification-report.md"


@pytest.mark.parametrize("verified", [False, True])
def test_restored_configuration_is_not_mistaken_for_verified_recovery(tmp_path, verified):
    receipt(tmp_path, "INCOMPLETE", error="Incomplete or unsafe deployment group: restore-local")
    save(tmp_path / "restoration.json", {"status": "RESTORED"})
    state = json.loads((tmp_path / "status.json").read_text())
    state["local_restored_and_verified"] = verified
    save(tmp_path / "status.json", state)
    with patch.object(suite_notify, "logged", return_value=0):
        assert suite_notify.send_report(tmp_path, ENV) == "SENT"
    text = (tmp_path / "notification-report.md").read_text(encoding="utf-8")
    assert "restore-local" in text
    assert ("恢复用例验证通过" in text) is verified
    assert ("恢复用例未通过或尚未完成" in text) is (not verified)


def test_missing_report_still_sends_saved_terminal_reason(tmp_path):
    receipt(tmp_path, "INCOMPLETE", error="Deployment preflight failed")
    (tmp_path / "report.md").unlink()
    with patch.object(suite_notify, "logged", return_value=0) as send:
        assert suite_notify.send_report(tmp_path, ENV) == "SENT"
    send.assert_called_once()
    text = (tmp_path / "notification-report.md").read_text(encoding="utf-8")
    assert "详细报告未生成" in text and "Deployment preflight failed" in text
    assert "未记录恢复验证证据" in text


def test_prepared_launch_reports_pending_redeployment_instead_of_recovered_environment(tmp_path):
    receipt(tmp_path, "INCOMPLETE", error="worker could not start")
    save(tmp_path / "recovery.json", {"status": "PREPARED_FOR_REDEPLOY"})
    with patch.object(suite_notify, "logged", return_value=0):
        assert suite_notify.send_report(tmp_path, ENV) == "SENT"
    text = (tmp_path / "notification-report.md").read_text(encoding="utf-8")
    assert "待重新部署及恢复验证" in text and "前批恢复标记仍待处理" in text


@pytest.mark.parametrize("delivery", [124, RuntimeError("offline transport failure")])
def test_uncertain_or_failed_delivery_is_never_blindly_repeated(tmp_path, delivery):
    receipt(tmp_path, "INCOMPLETE", error="Interrupted")
    with patch.object(suite_notify, "logged", side_effect=delivery if isinstance(delivery, Exception) else None,
                      return_value=delivery) as send:
        assert suite_notify.send_report(tmp_path, ENV) == "UNKNOWN"
        assert suite_notify.send_report(tmp_path, ENV) == "UNKNOWN"
    send.assert_called_once()


@pytest.mark.parametrize("marker", ["SENDING", "UNKNOWN", "SENT", "corrupt"])
def test_existing_delivery_receipt_prevents_duplicate_send(tmp_path, marker):
    receipt(tmp_path, "INCOMPLETE")
    if marker == "corrupt":
        (tmp_path / "notification.json").write_text("broken", encoding="utf-8")
    else:
        save(tmp_path / "notification.json", {"status": marker})
    with patch.object(suite_notify, "logged") as send:
        assert suite_notify.send_report(tmp_path, ENV) == ("UNKNOWN" if marker == "corrupt" else marker)
    send.assert_not_called()


@pytest.mark.parametrize("status", ["RUNNING", "PREPARING", None])
def test_active_or_unknown_run_never_sends_terminal_report(tmp_path, status):
    save(tmp_path / "status.json", {"status": status})
    with patch.object(suite_notify, "logged") as send:
        assert suite_notify.send_report(tmp_path, ENV) == "NOT_TERMINAL"
    send.assert_not_called()


def test_notification_redacts_known_secret_without_rewriting_local_evidence(tmp_path):
    receipt(tmp_path, "INCOMPLETE", error="Service failed with fake-secret-value")
    with patch.object(suite_notify, "logged", return_value=0):
        assert suite_notify.send_report(tmp_path, {**ENV, "TEST_API_KEY": "fake-secret-value"}) == "SENT"
    assert "fake-secret-value" not in (tmp_path / "notification-report.md").read_text(encoding="utf-8")
    assert "fake-secret-value" in (tmp_path / "summary.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("failure", [None, "build", "interrupt", "recovery-probe", "restore-local", "publish"])
def test_campaign_notifies_for_failure_and_recovery_interruptions(tmp_path, failure):
    repo, home, env_path, original, records, settings = campaign_fixture(tmp_path)
    settings["hooks"]["build"] = [["offline-build"]]
    env = {**ENV, "NEXENT_CONFIG_URL": "http://localhost:5010", "NEXENT_TEST_ASSETS_CONTAINER_HOST": "host"}
    created = []
    prior_report = home / "runs-ubuntu/latest-report.md"
    prior_report.parent.mkdir(parents=True)
    prior_report.write_text("previous complete batch", encoding="utf-8")

    def hook(name, settings, repo, home, directory, env):
        if failure == "build" and name == "build":
            raise RuntimeError("offline build failed")
        if failure == "restore-local" and directory.name == "restore-local" and name == "deploy":
            raise RuntimeError("offline Local restoration failed")

    def execute(repo, home, selected, settings, *, directory, on_result=None):
        assert settings["notify"] is False
        if failure == "interrupt" and directory.name == "modelengine":
            raise KeyboardInterrupt()
        directory.mkdir(parents=True)
        rows = [{"case_id": r["case_id"], "stage": r["stage"], "result":
                 "TIMEOUT" if failure == "recovery-probe" and directory.name == "restore-local" else "PASS"}
                for r in selected]
        for row in rows:
            if on_result:
                on_result(dict(row))
        finalize(directory, selected, rows)
        return 0

    with patch.object(modes, "fingerprint", return_value={"head": "a" * 40}), \
            patch.object(modes.ModeSwitch, "verify"), \
            patch.object(modes.subprocess, "check_output", return_value=""), \
            patch("static_assets.inventory", return_value=[]), \
            patch("report_ownership.enrich", side_effect=lambda repo, rows, head: (rows, [])), \
            patch("suite_publish.publish_latest", side_effect=OSError("offline publication failure")) as publish, \
            patch.object(suite_notify, "logged", return_value=0) as send:
        code = modes.execute_campaign(repo, home, records[:2], settings, daily=True,
                                      publish_latest=failure in {"publish", "recovery-probe", "restore-local"},
                                      execute_one=execute, all_records=records, hook=hook,
                                      machine_env=lambda *_: env, on_batch_created=created.append)
    assert len(created) == 1
    directory = created[0]
    send.assert_called_once()
    assert json.loads((directory / "notification.json").read_text())["status"] == "SENT"
    summary = json.loads((directory / "summary.json").read_text())
    assert code == (0 if failure in {None, "publish"} else 1)
    assert summary["execution_complete"] is (failure in {None, "publish"})
    text = (directory / "notification-report.md").read_text(encoding="utf-8")
    if failure in {"recovery-probe", "restore-local"}:
        publish.assert_not_called()
        assert prior_report.read_text(encoding="utf-8") == "previous complete batch"
        assert "环境可用性未验证" in text or "不能认为环境已恢复可用" in text
    if failure == "recovery-probe":
        assert summary["counts"] == {"PASS": 2}  # The separate recovery probe is not a third business case.
        assert "restore-local" in text
    assert env_path.read_bytes() == original
    assert text.count("## 终态与环境恢复") == 1


@pytest.mark.parametrize("failure", ["build", "interrupt", "environment"])
def test_regular_daily_notifies_after_aborted_execution(tmp_path, failure):
    record = {"case_id": "OFFLINE-001", "stage": "D1", "status": "blocked", "execution": None,
              "git_last_modifier": {"status": "UNKNOWN"}, "responsibility": {"status": "UNASSIGNED"}}
    settings = {"hooks": {name: [["offline-command"]] for name in ("build", "deploy", "preflight")}, "notify": True}
    created = []

    def hook(name, *args):
        if name == "build":
            if failure == "interrupt":
                raise KeyboardInterrupt()
            raise RuntimeError("offline build failed")

    with patch.object(suite, "machine_environment", side_effect=ValueError("missing config") if failure == "environment" else None,
                      return_value=ENV), \
            patch.object(suite_notify, "notification_environment", return_value=ENV), \
            patch.object(suite, "fingerprint", return_value={"head": "a" * 40}), \
            patch.object(suite, "enrich_ownership", return_value=([record], [])), \
            patch.object(suite, "static_inventory", return_value=[]), \
            patch.object(suite.subprocess, "check_output", return_value=""), \
            patch.object(suite, "execute_hooks", side_effect=hook), \
            patch.object(suite_notify, "logged", return_value=0) as send, \
            patch("suite_publish.publish_latest") as publish:
        code = suite._execute(tmp_path, tmp_path, [record], settings, daily=True, publish_latest=True,
                              validation_report={"ready": True, "status": "VALID", "issues": [], "blocked_cases": []},
                              on_batch_created=created.append)
    assert code == 1
    send.assert_called_once()
    publish.assert_not_called()
    assert json.loads((created[0] / "summary.json").read_text())["counts"] == {"NOT_EXECUTED": 1}


@pytest.mark.parametrize("failure", ["sync", "signal"])
def test_launcher_reports_preflight_failures_without_product_configuration(tmp_path, monkeypatch, failure):
    save(tmp_path / "status.json", {})
    (tmp_path / "config").mkdir()
    (tmp_path / "config/pipeline.yaml").write_text("notify: true\n", encoding="utf-8")
    (tmp_path / "config/daily.env").write_text("LARK_CLI=offline-cli\nFEISHU_REPORT_CHAT_ID=offline-chat\n", encoding="utf-8")
    runtime = tmp_path / "runtime/test-venv" / ("Scripts/python.exe" if launcher.os.name == "nt" else "bin/python")
    monkeypatch.setattr(launcher.sys, "executable", str(runtime))
    monkeypatch.setattr(launcher, "deployment_lock", lambda *_: nullcontext())
    monkeypatch.setattr(launcher, "prepare_daily_retry", lambda *_: nullcontext())
    monkeypatch.setattr(launcher, "notify_terminal", lambda repo, home, directory: suite_notify.notify_launch(directory, home))

    def sync(*args, **kwargs):
        if failure == "signal":
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        raise RuntimeError("Daily requires a clean checkout before synchronization")

    monkeypatch.setattr(launcher, "sync_checkout", sync)
    old_handler = signal.getsignal(signal.SIGTERM)
    with patch.object(suite_notify, "logged", return_value=0) as send:
        assert launcher.main(["--test-home", str(tmp_path), "--branch", "develop", "--execute"]) == 2
    send.assert_called_once()
    directory = next((tmp_path / "runs/daily-launch").iterdir())
    state = json.loads((directory / "status.json").read_text())
    assert state["status"] == ("INTERRUPTED" if failure == "signal" else "INCOMPLETE")
    text = (directory / "notification-report.md").read_text(encoding="utf-8")
    assert "未建立执行批次或未记录" in text and "详细报告未生成" in text
    assert state["error"] in text
    assert signal.getsignal(signal.SIGTERM) == old_handler


def test_launch_and_execution_share_one_delivery_receipt(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/pipeline.yaml").write_text("notify: true\n", encoding="utf-8")
    batch = tmp_path / "runs/repository-daily/current"
    receipt(batch, "INCOMPLETE", error="restore-local failed")
    launch = tmp_path / "runs/daily-launch/current"
    save(launch / "status.json", {"status": "FAILED", "batch": str(batch)})
    save(tmp_path / "reports/repository-latest.json", {"batch": "unrelated old report"})
    with patch.object(suite_notify, "notification_environment", return_value=ENV), \
            patch.object(suite_notify, "logged", return_value=0) as send:
        assert suite_notify.send_report(batch, ENV) == "SENT"
        assert suite_notify.notify_launch(launch, tmp_path) == "SENT"
    send.assert_called_once()
    assert not (launch / "notification.json").exists()


def test_disabled_notifications_remain_disabled(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/pipeline.yaml").write_text("notify: false\n", encoding="utf-8")
    receipt(tmp_path / "launch", "INCOMPLETE")
    with patch.object(suite_notify, "logged") as send:
        assert suite_notify.notify_launch(tmp_path / "launch", tmp_path) == "DISABLED"
    send.assert_not_called()


@pytest.mark.parametrize("failure", ["validation", "doctor", "success", "case-failure", "render"])
def test_launcher_uses_explicit_batch_link_or_reports_preparation_failure(tmp_path, monkeypatch, failure):
    import static_assets
    (tmp_path / "config").mkdir()
    (tmp_path / "config/pipeline.yaml").write_text("notify: true\n", encoding="utf-8")
    runtime = tmp_path / "runtime/test-venv" / ("Scripts/python.exe" if launcher.os.name == "nt" else "bin/python")
    monkeypatch.setattr(launcher.sys, "executable", str(runtime))
    monkeypatch.setattr(launcher, "deployment_lock", lambda *_: nullcontext())
    monkeypatch.setattr(launcher, "prepare_daily_retry", lambda *_: nullcontext())
    monkeypatch.setattr(launcher, "notify_terminal", lambda repo, home, directory: suite_notify.notify_launch(directory, home))
    monkeypatch.setattr(launcher, "sync_checkout", lambda *a, **k: "fixed-revision")
    monkeypatch.setattr(launcher, "git", lambda *a, **k: "")
    monkeypatch.setattr(worker, "logged", lambda *a, **k: 1 if failure == "validation" else 0)
    monkeypatch.setattr(worker, "checked_revision", lambda *a: None)
    monkeypatch.setattr(worker, "inherited_locks", lambda *a: nullcontext())
    monkeypatch.setattr(worker, "prepare_daily_retry", lambda *a, **k: nullcontext())
    monkeypatch.setattr(launcher, "run_worker", lambda repo, home, directory, head, publish, locks:
                        worker.execute(repo, home, directory, head, publish))
    monkeypatch.setattr(static_assets, "apply", lambda *a, **k: None)
    monkeypatch.setattr(suite, "selection", lambda *a, **k: [])
    monkeypatch.setattr(suite, "doctor", lambda *a, **k: ["offline missing browser"] if failure == "doctor" else [])
    monkeypatch.setattr(suite, "config", lambda *a: {"notify": True})
    monkeypatch.setattr(suite_notify, "notification_environment", lambda *_: ENV)
    batch = tmp_path / "runs/repository-daily/current"

    def execute(repo, home, records, settings, *, on_batch_created, **kwargs):
        receipt(batch, "PASSED" if failure == "success" else "INCOMPLETE" if failure == "render" else "FAILED",
                complete=failure != "render", error="report renderer failed" if failure == "render" else None)
        on_batch_created(batch)
        if failure == "render":
            (batch / "report.md").unlink()
            raise OSError("offline rendering failure")
        suite_notify.send_report(batch, ENV)
        return 0 if failure == "success" else 1

    monkeypatch.setattr(suite, "execute", execute)
    with patch.object(suite_notify, "logged", return_value=0) as send:
        code = launcher.main(["--test-home", str(tmp_path), "--branch", "develop", "--execute"])
    send.assert_called_once()
    launch = next((tmp_path / "runs/daily-launch").iterdir())
    assert code == (0 if failure == "success" else 1 if failure == "case-failure" else 2)
    if failure in {"validation", "doctor"}:
        assert (launch / "notification.json").exists()
        assert not batch.exists()
    else:
        assert json.loads((launch / "status.json").read_text())["batch"] == str(batch)
        assert not (launch / "notification.json").exists()
        assert (batch / "notification.json").exists()
    if failure == "render":
        assert "report renderer failed" in (batch / "notification-report.md").read_text(encoding="utf-8")


def test_delivery_receipt_write_failure_remains_uncertain_without_resending(tmp_path):
    receipt(tmp_path, "INCOMPLETE", error="Interrupted")
    real_save = suite_notify.save

    def write(path, value):
        if path.name == "notification.json" and value.get("status") == "SENT":
            raise OSError("offline receipt failure")
        return real_save(path, value)

    with patch.object(suite_notify, "save", side_effect=write), \
            patch.object(suite_notify, "logged", return_value=0) as send:
        assert suite_notify.send_report(tmp_path, ENV) == "UNKNOWN"
        assert suite_notify.send_report(tmp_path, ENV) == "SENDING"
    send.assert_called_once()


@pytest.mark.parametrize("pipeline", [None, "notify: [broken", "- invalid mapping"])
def test_invalid_or_missing_pipeline_does_not_hide_configured_failure_alert(tmp_path, pipeline):
    if pipeline is not None:
        (tmp_path / "config").mkdir()
        (tmp_path / "config/pipeline.yaml").write_text(pipeline, encoding="utf-8")
    directory = tmp_path / "launch"
    save(directory / "status.json", {"status": "INCOMPLETE", "error": "Invalid pipeline configuration"})
    with patch.object(suite_notify, "notification_environment", return_value=ENV), \
            patch.object(suite_notify, "logged", return_value=0) as send:
        assert suite_notify.notify_launch(directory, tmp_path) == "SENT"
    send.assert_called_once()


def test_fresh_notifier_works_with_runtime_module_cached_before_checkout_sync(tmp_path, monkeypatch):
    import suite_runtime
    receipt(tmp_path, "INCOMPLETE", error="Interrupted")
    monkeypatch.delattr(suite_runtime, "terminal_context")
    fresh_spec = importlib.util.spec_from_file_location("post_sync_notifier", TOOLS / "suite_notify.py")
    fresh = importlib.util.module_from_spec(fresh_spec)
    fresh_spec.loader.exec_module(fresh)
    with patch.object(fresh, "logged", return_value=0) as send:
        assert fresh.send_report(tmp_path, ENV) == "SENT"
    send.assert_called_once()
