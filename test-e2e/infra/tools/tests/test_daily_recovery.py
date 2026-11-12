# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Daily may redeploy a newer revision without erasing unresolved recovery evidence."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess
from unittest.mock import patch

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import deployment_exceptions as modes
import daily_recovery as recovery
import suite
from suite_runtime import BatchLock, deployment_lock, deployment_lock_owned, finalize, save

spec = importlib.util.spec_from_file_location("recovery_daily_launcher", TOOLS.parent / "scripts/daily-launch.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@pytest.fixture
def abandoned(tmp_path):
    repo, home = tmp_path / "repo", tmp_path / "home"
    (repo / ".git").mkdir(parents=True)
    env = repo / "deploy/env/.env"
    env.parent.mkdir(parents=True)
    env.write_bytes(b"ENABLE_AIDP_KNOWLEDGE=false\nMODEL_ENGINE_ENABLED=false\nDATABASE=preserved\n")
    (home / "config").mkdir(parents=True)
    (home / "config/environment.yaml").write_text("features:\n  aidp_knowledge: false\n")
    batch = home / "runs/repository-daily/old-failed"
    save(batch / "status.json", {"status": "INCOMPLETE", "error": "service unavailable"})
    switch = modes.ModeSwitch(repo, home, batch, {"hooks": {"deploy": [["deploy"]], "preflight": [["wait"]]}}, {}, None)
    switch.snapshot()
    marker = home / modes.MARKER
    value = json.loads(marker.read_text())
    value.pop("owner_pid", None)  # Exercise the existing production journal format.
    save(marker, value)
    return repo, home, batch, marker, switch


def test_pending_failed_deployment_allows_launcher_sync_but_keeps_evidence(abandoned):
    repo, home, batch, marker, switch = abandoned
    before = marker.read_bytes()
    calls = []
    runtime = home / "runtime/test-venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def synchronize(*args, **kwargs):
        assert marker.read_bytes() == before
        calls.append("fetch-latest")
        return "new-revision-with-fix"

    def execute(repo, home, directory, *args):
        calls.append("redeploy")
        assert marker.exists()
        state = json.loads((directory / "status.json").read_text())
        save(directory / "status.json", {**state, "status": "PASSED"})
        return 0

    with patch.object(launcher, "__file__", str(repo / "test-e2e/infra/scripts/daily-launch.py")), \
            patch.object(launcher.sys, "executable", str(runtime)), \
            patch.object(launcher, "sync_checkout", side_effect=synchronize), \
            patch.object(launcher, "run_worker", side_effect=execute), patch.object(launcher, "notify_terminal"):
        assert launcher.main(["--test-home", str(home), "--branch", "develop", "--execute"]) == 0
    assert calls == ["fetch-latest", "redeploy"]
    assert marker.read_bytes() == before


def test_restores_only_owned_local_config_and_retains_private_before_images(abandoned):
    repo, home, batch, marker, switch = abandoned
    env, *_, environment = switch.paths
    original = env.read_bytes()
    env.write_bytes(original.replace(b"KNOWLEDGE=false", b"KNOWLEDGE=true"))
    environment.write_text("features:\n  aidp_knowledge: true\n")
    changed = env.read_bytes()
    marker_before = marker.read_bytes()
    launch = home / "runs/daily-launch/retry"
    with deployment_lock(repo), recovery.prepare_daily_retry(repo, home, launch) as retry:
        assert deployment_lock_owned(repo)
        assert env.read_bytes() == original
        assert "false" in environment.read_text()
        assert (retry.archive / "0").read_bytes() == changed
        assert (retry.archive / "pending.json").read_bytes() == marker_before
        modes.assert_recovered(home, allow_retry=True)
        with pytest.raises(RuntimeError, match="Pending"):
            modes.assert_recovered(home)  # Targeted runs never inherit a Daily bypass.
        with patch.object(suite, "_execute") as execute, pytest.raises(RuntimeError, match="Pending"):
            suite.execute(repo, home, [], {}, daily=False)
        execute.assert_not_called()
    assert marker.read_bytes() == marker_before
    assert (switch.backup / "0").read_bytes() == original
    assert recovery.current_retry(home) is None
    with pytest.raises(RuntimeError, match="Pending"):
        modes.assert_recovered(home, allow_retry=True)


@pytest.mark.parametrize("fault", ["checksum", "missing_file", "index", "outside_backup", "target", "duplicate_target",
                                  "missing_baseline", "not_local", "unknown_status", "invalid_json", "active_legacy",
                                  "unrelated_env", "unrelated_yaml", "symlink"])
def test_uncertain_recovery_never_writes_configuration_or_clears_marker(abandoned, fault):
    repo, home, batch, marker, switch = abandoned
    value = json.loads(marker.read_text())
    if fault == "checksum":
        (switch.backup / "0").write_bytes(b"corrupted")
    elif fault == "missing_file":
        (switch.backup / "0").unlink()
    elif fault == "index":
        save(switch.backup / "index.json", {"files": []})
    elif fault == "outside_backup":
        value["backup"] = str(home.parent / "outside")
    elif fault == "target":
        value["files"][0]["path"] = str(repo / "source.py")
    elif fault == "duplicate_target":
        value["files"][1] = value["files"][0]
    elif fault == "missing_baseline":
        value["files"][0].update(existed=False, sha256=None)
    elif fault == "not_local":
        import hashlib
        content = (switch.backup / "0").read_bytes().replace(b"KNOWLEDGE=false", b"KNOWLEDGE=true")
        (switch.backup / "0").write_bytes(content)
        value["files"][0]["sha256"] = hashlib.sha256(content).hexdigest()
    elif fault == "unknown_status":
        value["status"] = "UNKNOWN"
    elif fault == "active_legacy":
        save(batch / "status.json", {"status": "RUNNING"})
    elif fault == "unrelated_env":
        switch.paths[0].write_bytes(switch.paths[0].read_bytes().replace(b"DATABASE=preserved", b"DATABASE=operator-update"))
    elif fault == "unrelated_yaml":
        switch.paths[-1].write_text("base_url: http://operator-update\nfeatures:\n  aidp_knowledge: false\n")
    if fault in {"target", "duplicate_target", "missing_baseline", "not_local"}:
        save(switch.backup / "index.json", {"files": value["files"]})
    save(marker, value)
    if fault == "invalid_json":
        marker.write_text("{")
    before = {path: path.read_bytes() if path.exists() else None for path in switch.paths}
    marker_before = marker.read_bytes()
    real_symlink = Path.is_symlink
    with patch.object(Path, "is_symlink", lambda path: (path == switch.backup / "0" and fault == "symlink") or real_symlink(path)):
        with deployment_lock(repo), pytest.raises(RuntimeError):
            with recovery.prepare_daily_retry(repo, home, home / "runs/daily-launch/invalid"):
                pytest.fail("unsafe recovery reached synchronization")
    assert marker.read_bytes() == marker_before
    assert {path: path.read_bytes() if path.exists() else None for path in switch.paths} == before


def test_live_owner_and_d5_fault_journal_remain_hard_stops(abandoned):
    repo, home, batch, marker, switch = abandoned
    value = json.loads(marker.read_text())
    value["owner_pid"] = os.getpid()
    save(marker, value)
    assert recovery.owner_alive(os.getpid())
    with deployment_lock(repo), pytest.raises(RuntimeError, match="still active"):
        with recovery.prepare_daily_retry(repo, home, home / "runs/daily-launch/alive"):
            pass
    save(home / recovery.FAULT_MARKER, {"record": {"pending": ["nexent-postgresql"]}})
    with deployment_lock(repo), pytest.raises(RuntimeError, match="D5 fault"):
        with recovery.prepare_daily_retry(repo, home, home / "runs/daily-launch/fault"):
            pass
    assert marker.exists() and (home / recovery.FAULT_MARKER).exists()


@pytest.mark.parametrize("outcome", ["TIMEOUT", "CLEANUP_FAILED"])
def test_prior_unsafe_d5_results_block_even_without_a_fault_marker(abandoned, outcome):
    repo, home, batch, marker, switch = abandoned
    path = batch / "results.journal.jsonl"
    path.write_text(json.dumps({"stage": "D5", "result": outcome}) + "\n")
    with deployment_lock(repo), pytest.raises(RuntimeError, match="D5 timeout/cleanup"):
        with recovery.prepare_daily_retry(repo, home, home / "runs/daily-launch/unsafe-d5"):
            pass
    assert marker.exists()


def test_dead_parent_without_terminal_batch_receipt_does_not_prove_children_exited(abandoned):
    repo, home, batch, marker, switch = abandoned
    value = json.loads(marker.read_text())
    value["owner_pid"] = 99999999
    save(marker, value)
    save(batch / "status.json", {"status": "RUNNING"})
    with deployment_lock(repo), patch.object(recovery, "owner_alive", return_value=False), pytest.raises(RuntimeError, match="terminal owner"):
        with recovery.prepare_daily_retry(repo, home, home / "runs/daily-launch/interrupted-parent"):
            pass
    assert marker.exists()


def test_missing_lease_and_another_checkout_operation_prevent_retry(abandoned):
    repo, home, batch, marker, switch = abandoned
    with pytest.raises(RuntimeError, match="deployment lock"):
        with recovery.prepare_daily_retry(repo, home, home / "runs/daily-launch/unlocked"):
            pass
    with BatchLock(repo / ".git/nexent-e2e-deployment.lock"), pytest.raises(RuntimeError, match="another daily"):
        with deployment_lock(repo):
            pass
    with BatchLock(home / "state/deployment-guard/exclusive.lock"), deployment_lock(repo), pytest.raises(RuntimeError, match="another daily"):
        with recovery.prepare_daily_retry(repo, home, home / "runs/daily-launch/d5-alive"):
            pass


def test_nested_campaign_lease_keeps_other_processes_out(abandoned):
    repo, home, batch, marker, switch = abandoned
    command = "import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from suite_runtime import BatchLock;\nwith BatchLock(Path(sys.argv[2])): pass"
    with deployment_lock(repo):
        with deployment_lock(repo):
            result = subprocess.run([sys.executable, "-c", command, str(TOOLS), str(repo / ".git/nexent-e2e-deployment.lock")], capture_output=True, text=True, timeout=15)
            assert result.returncode != 0 and "another daily run is active" in result.stderr
    with BatchLock(repo / ".git/nexent-e2e-deployment.lock"):
        pass


def test_changed_marker_cannot_be_adopted_or_cleared(abandoned):
    repo, home, batch, marker, switch = abandoned
    with deployment_lock(repo), recovery.prepare_daily_retry(repo, home, home / "runs/daily-launch/retry"):
        value = json.loads(marker.read_text())
        value["status"] = "changed-by-another-operation"
        save(marker, value)
        with pytest.raises(RuntimeError, match="Pending"):
            modes.assert_recovered(home, allow_retry=True)
    marker.write_text('{"replacement": true}')
    with pytest.raises(RuntimeError, match="journal changed"):
        switch.complete()
    assert json.loads(marker.read_text()) == {"replacement": True}


def test_partial_configuration_restore_retains_all_before_images(abandoned):
    repo, home, batch, marker, switch = abandoned
    original = marker.read_bytes()
    write = recovery.protected_write

    def failing_write(path, content):
        if path == switch.paths[-1]:
            raise OSError("injected write failure")
        return write(path, content)

    launch = home / "runs/daily-launch/write-failure"
    with deployment_lock(repo), patch.object(recovery, "protected_write", side_effect=failing_write), pytest.raises(OSError):
        with recovery.prepare_daily_retry(repo, home, launch):
            pass
    archive = home / "runtime/daily-recovery/write-failure"
    assert (archive / "0").is_file() and (archive / "3").is_file()
    assert marker.read_bytes() == original


def test_real_local_git_fetch_installs_the_fix_while_old_marker_remains(abandoned, tmp_path):
    repo, home, batch, marker, switch = abandoned

    def git(path, *args):
        return subprocess.check_output(["git", "-C", str(path), *args], text=True, stderr=subprocess.STDOUT)

    git(repo, "init", "-b", "develop")
    (repo / ".gitignore").write_text("/deploy/\n")
    (repo / "repair.txt").write_text("broken image")
    git(repo, "add", ".gitignore", "repair.txt")
    git(repo, "-c", "user.name=Runner", "-c", "user.email=runner@example.invalid", "commit", "-m", "initial")
    origin = tmp_path / "new-origin"
    subprocess.run(["git", "clone", str(repo), str(origin)], check=True, capture_output=True)
    (origin / "repair.txt").write_text("SDK source copied before installation")
    git(origin, "add", "repair.txt")
    git(origin, "-c", "user.name=Runner", "-c", "user.email=runner@example.invalid", "commit", "-m", "fix")
    git(repo, "remote", "add", "origin", str(origin))
    expected = git(origin, "rev-parse", "HEAD").strip()
    old_marker = marker.read_bytes()
    with deployment_lock(repo), recovery.prepare_daily_retry(repo, home, home / "runs/daily-launch/real-fetch"):
        assert launcher.sync_checkout(repo, "develop", log_dir=home / "git-logs") == expected
        assert (repo / "repair.txt").read_text() == "SDK source copied before installation"
        assert marker.read_bytes() == old_marker


def run_campaign(abandoned, launch_name, failure=None, invalid_recovery=None):
    repo, home, batch, marker, switch = abandoned
    calls, probes = [], []
    records = [{"case_id": cid, "stage": "D3", "status": "active", "execution": {"implemented": True}}
               for cid in ("NORMAL", "EXCEPTION", "LOCAL-RECOVERY")]
    rules = {"profiles": {"modelengine": {"environment": {"MODEL_ENGINE_ENABLED": "true"}}},
             "cases": {"EXCEPTION": "modelengine"}, "recovery_cases": ["LOCAL-RECOVERY"]}
    if invalid_recovery == "empty":
        rules["recovery_cases"] = []
    elif invalid_recovery == "blocked":
        records[-1]["status"] = "blocked"
    elif invalid_recovery == "unimplemented":
        records[-1]["execution"] = None
    settings = {"hooks": {name: [[name]] for name in ("build", "deploy", "preflight")}, "notify": False}
    failure_started = False

    def hook(name, *args):
        nonlocal failure_started
        calls.append(name)
        if name == failure:
            failure_started = True
            raise RuntimeError("injected " + name)

    def verify(controller, updates, label):
        if failure_started or failure == "verify":
            raise RuntimeError("services still unavailable")

    def execute(repo, home, selected, settings, *, directory, on_result=None):
        probes.append(directory.name)
        assert marker.exists()  # Neither old recovery nor the active campaign disappears early.
        results = [{"case_id": r["case_id"], "stage": r["stage"], "result": "FAIL" if failure == "probe" else "PASS", "evidence": []} for r in selected]
        directory.mkdir(parents=True)
        for row in results:
            if on_result:
                on_result(dict(row))
        finalize(directory, selected, results)
        return 0

    with deployment_lock(repo), recovery.prepare_daily_retry(repo, home, home / ("runs/daily-launch/" + launch_name)), \
            patch.object(modes, "catalog", return_value=rules), patch.object(modes, "enabled", return_value=True), \
            patch.object(modes, "fingerprint", return_value={"head": "fixed-revision"}), \
            patch.object(modes.subprocess, "check_output", return_value=""), patch("static_assets.inventory", return_value=[]), \
            patch.object(modes.ModeSwitch, "verify", new=verify), \
            patch("report_ownership.enrich", side_effect=lambda repo, rows, head: (rows, [])), \
            patch("suite_notify.send_report") as notify:
        code = modes.execute_campaign(repo, home, records[:2], settings, daily=True, publish_latest=False,
                                      execute_one=execute, all_records=records, hook=hook,
                                      machine_env=lambda *_: {"NEXENT_TEST_ASSETS_CONTAINER_HOST": "127.0.0.1"})
        notify.assert_not_called()
    return code, calls, probes


@pytest.mark.parametrize("failure", [None, "build", "deploy", "preflight", "verify", "probe"])
def test_redeploy_and_local_probe_must_succeed_before_business_cases(abandoned, failure):
    repo, home, batch, marker, switch = abandoned
    old = marker.read_bytes()
    code, calls, probes = run_campaign(abandoned, "campaign", failure)
    assert code == (0 if failure is None else 1)
    assert (home / "runtime/daily-recovery/campaign/pending.json").read_bytes() == old
    assert marker.exists() is (failure is not None)
    if failure is None:
        assert calls[:3] == ["build", "deploy", "preflight"]
        assert probes == ["recover-previous-local", "local", "modelengine", "restore-local"]
        assert json.loads((home / "runs/daily-launch/campaign/recovery.json").read_text())["status"] == "RECOVERED"
    else:
        assert "local" not in probes and "modelengine" not in probes


def test_another_failed_redeploy_does_not_prevent_a_later_success(abandoned):
    repo, home, batch, marker, switch = abandoned
    assert run_campaign(abandoned, "first-retry", "build")[0] == 1
    failed_marker = marker.read_bytes()
    # The fixture runs both invocations in this pytest process; the previous real launcher has exited.
    with patch.object(recovery, "owner_alive", return_value=False):
        assert run_campaign(abandoned, "second-retry")[0] == 0
    assert not marker.exists()
    assert (home / "runtime/daily-recovery/second-retry/pending.json").read_bytes() == failed_marker
    assert (switch.backup / "0").is_file()


@pytest.mark.parametrize("invalid", ["empty", "blocked", "unimplemented"])
def test_empty_or_unexecutable_recovery_is_never_a_success(abandoned, invalid):
    repo, home, batch, marker, switch = abandoned
    code, calls, probes = run_campaign(abandoned, "no-recovery", invalid_recovery=invalid)
    assert code == 1 and not probes and marker.exists()
    receipt = json.loads((home / "runs/daily-launch/no-recovery/recovery.json").read_text())
    assert receipt["status"] == "ADOPTED_BY_REDEPLOY"


def test_exited_owner_is_detected_without_signalling_it():
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    assert process.wait(timeout=10) == 0
    assert recovery.owner_alive(process.pid) is False


@pytest.mark.parametrize("exception,expected", [(None, True), (ProcessLookupError, False), (PermissionError, True)])
def test_posix_owner_probe_fails_closed_on_permission_errors(exception, expected):
    def probe(pid, signal):
        assert pid == 123 and signal == 0
        if exception:
            raise exception()
    with patch.object(recovery.os, "name", "posix"), patch.object(recovery.os, "kill", side_effect=probe):
        assert recovery.owner_alive(123) is expected
