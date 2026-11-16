# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise actual fresh processes and temporary leases; never deploy or send messages."""
from contextlib import nullcontext
import importlib.util
import json
import os
from pathlib import Path
import py_compile
import signal
import subprocess
import sys
from unittest.mock import patch

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import daily_process as processes
import daily_recovery as recovery
from suite_runtime import BatchLock, deployment_lock, save


def script(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), TOOLS.parent / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launcher, worker = script("daily-launch"), script("daily-worker")


def test_recovery_write_does_not_import_deployment_executor(tmp_path):
    import builtins
    original_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert name != "deployment_exceptions", "Recovery must not preload the executor before Git sync"
        return original_import(name, *args, **kwargs)

    target = tmp_path / "private/config"
    with patch("builtins.__import__", side_effect=guarded):
        recovery.protected_write(target, b"preserved local data")
    assert target.read_bytes() == b"preserved local data"


@pytest.mark.parametrize("reverse_handles", [False, True])
def test_real_child_loads_new_code_and_holds_both_locks(tmp_path, reverse_handles):
    repo, home = tmp_path / "repo", tmp_path / "home"
    (repo / ".git").mkdir(parents=True)
    root = repo / "test-e2e/infra/scripts"
    root.mkdir(parents=True)
    module = root / "versioned_executor.py"
    module.write_text("def execute_campaign(*, on_batch_created=None): return 'old-version'\n")
    spec = importlib.util.spec_from_file_location("cached_old_executor", module)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    py_compile.compile(str(module), doraise=True)
    previous_time = module.stat().st_mtime
    module.write_text("def execute_campaign(*, on_batch_created=None): return 'new-version'\n")
    os.utime(module, (previous_time, previous_time))
    child = root / "daily-worker.py"
    child.write_text(f'''import json,sys
from pathlib import Path
sys.path.insert(0, {str(TOOLS)!r})
from daily_process import inherited_locks
from suite_runtime import BatchLock, deployment_lock, deployment_lock_owned
import versioned_executor
repo,home=Path({str(repo)!r}),Path({str(home)!r})
with inherited_locks(repo,home):
 assert deployment_lock_owned(repo)
 with deployment_lock(repo):
  assert deployment_lock_owned(repo)
 for p in (home/'state/daily.lock',repo/'.git/nexent-e2e-deployment.lock'):
  try:
   with BatchLock(p): raise AssertionError('Execution lost mutual exclusion')
  except RuntimeError: pass
 (home/'child-result.json').write_text(json.dumps({{'version':versioned_executor.execute_campaign(on_batch_created=None),'pid':__import__('os').getpid()}}))
''')
    with BatchLock(home / "state/daily.lock") as daily, deployment_lock(repo) as checkout:
        locks = [checkout, daily] if reverse_handles else [daily, checkout]
        assert processes.run_worker(repo, home, home / "unused-launch", "head", False, locks) == (1 if reverse_handles else 0)
        for path in (daily.path, checkout.path):
            with pytest.raises(RuntimeError, match="another daily run"):
                with BatchLock(path):
                    pass
    if reverse_handles:
        assert not (home / "child-result.json").exists()
    else:
        result = json.loads((home / "child-result.json").read_text())
        assert result["version"] == "new-version" and result["pid"] != os.getpid()
    assert old.execute_campaign() == "old-version"
    for path in (daily.path, checkout.path):
        with BatchLock(path):
            pass


@pytest.mark.parametrize("lease", [None, "broken", "[]", '{"parent":0,"handles":[],"kind":"posix"}'])
def test_missing_or_forged_lease_is_rejected(tmp_path, monkeypatch, lease):
    if lease is None:
        monkeypatch.delenv(processes.LEASE_ENV, raising=False)
    else:
        monkeypatch.setenv(processes.LEASE_ENV, lease)
    with pytest.raises(RuntimeError, match="inherited supervisor locks"):
        with processes.inherited_locks(tmp_path / "repo", tmp_path / "home"):
            pytest.fail("Missing locks must never permit execution")


@pytest.mark.parametrize("outcome", ["missing", "crash", "launch-error", "interrupt", "success"])
def test_supervisor_accounts_for_worker_exit_and_always_calls_notifier(tmp_path, monkeypatch, outcome):
    home = tmp_path / "home"
    runtime = home / "runtime/test-venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    monkeypatch.setattr(launcher.sys, "executable", str(runtime))
    monkeypatch.setattr(launcher, "deployment_lock", lambda *_: nullcontext())
    monkeypatch.setattr(launcher, "prepare_daily_retry", lambda *_: nullcontext())
    monkeypatch.setattr(launcher, "sync_checkout", lambda *a, **k: "head")

    def execute(repo, home, directory, *args):
        if outcome == "launch-error":
            raise OSError("offline subprocess launch failure")
        if outcome == "interrupt":
            raise KeyboardInterrupt()
        if outcome == "success":
            state = json.loads((directory / "status.json").read_text())
            save(directory / "status.json", {**state, "status": "PASSED"})
        return -9 if outcome == "crash" else 0

    monkeypatch.setattr(launcher, "run_worker", execute)
    with patch.object(launcher, "notify_terminal") as notify:
        code = launcher.main(["--test-home", str(home), "--branch", "develop", "--execute"])
    notify.assert_called_once()
    directory = next((home / "runs/daily-launch").iterdir())
    state = json.loads((directory / "status.json").read_text())
    assert code == (0 if outcome == "success" else 2)
    assert state["status"] == ("PASSED" if outcome == "success" else "INTERRUPTED" if outcome == "interrupt" else "INCOMPLETE")
    if outcome in {"crash", "missing"}:
        assert "without a matching terminal receipt" in state["error"]


def test_worker_rejects_revision_change_before_any_execution(tmp_path):
    with patch.object(worker.subprocess, "check_output", side_effect=["develop", "other-head"]):
        with pytest.raises(RuntimeError, match="revision changed"):
            worker.checked_revision(tmp_path, "develop", "expected-head")


@pytest.fixture
def abandoned_process(tmp_path):
    import deployment_exceptions as modes
    repo, home = tmp_path / "repo", tmp_path / "home"
    (repo / ".git").mkdir(parents=True)
    env = repo / "deploy/env/.env"
    env.parent.mkdir(parents=True)
    env.write_bytes(b"ENABLE_AIDP_KNOWLEDGE=false\nDATABASE=preserved\n")
    save(home / "runs/repository-daily/old/status.json", {"status": "INCOMPLETE"})
    (home / "config").mkdir()
    (home / "config/environment.yaml").write_text("features: {aidp_knowledge: false}\n")
    settings = {"hooks": {"deploy": [["offline-deploy"]], "preflight": [["offline-check"]]}}
    switch = modes.ModeSwitch(repo, home, home / "runs/repository-daily/old", settings, {}, None)
    switch.snapshot()
    marker = home / modes.MARKER
    value = json.loads(marker.read_text())
    value.pop("owner_pid")
    save(marker, value)
    return repo, home, marker, switch


@pytest.mark.parametrize("failure", ["checksum", "config", "receipt", "before-image", "missing-marker"])
def test_child_revalidates_prepared_recovery_without_replacing_original_backup(abandoned_process, failure):
    import deployment_exceptions as modes
    repo, home, marker, switch = abandoned_process
    original = marker.read_bytes()
    launch = home / "runs/daily-launch/upgrade"
    with deployment_lock(repo), recovery.prepare_daily_retry(repo, home, launch) as prepared:
        baseline = (switch.backup / "0").read_bytes()
        with recovery.prepare_daily_retry(repo, home, launch, prepared=True) as resumed:
            assert resumed.marker_bytes == original
            modes.assert_recovered(home, allow_retry=True)
        if failure == "checksum":
            (prepared.archive / "pending.json").write_text("changed")
        elif failure == "before-image":
            (prepared.archive / "0").write_text("corrupted before-image")
        elif failure == "missing-marker":
            marker.unlink()
        elif failure == "config":
            env = repo / "deploy/env/.env"
            env.write_bytes(env.read_bytes().replace(b"KNOWLEDGE=false", b"KNOWLEDGE=true"))
        else:
            save(launch / "recovery.json", {"status": "RECOVERED"})
        with pytest.raises(RuntimeError):
            with recovery.prepare_daily_retry(repo, home, launch, prepared=True):
                pytest.fail("Changed recovery evidence cannot be adopted")
    if failure != "missing-marker":
        assert marker.read_bytes() == original
    assert (switch.backup / "0").read_bytes() == baseline


def test_pending_recovery_and_cached_old_executor_survive_upgrade_in_fresh_child(abandoned_process):
    import types
    repo, home, marker, switch = abandoned_process
    root = repo / "test-e2e/infra/scripts"
    root.mkdir(parents=True)
    child = root / "daily-worker.py"
    child.write_text(f'''import inspect,sys
from pathlib import Path
sys.path.insert(0,{str(TOOLS)!r})
from daily_process import inherited_locks
from daily_recovery import prepare_daily_retry
repo,home,launch=Path({str(repo)!r}),Path({str(home)!r}),Path({str(home / 'runs/daily-launch/upgrade')!r})
with inherited_locks(repo,home),prepare_daily_retry(repo,home,launch,prepared=True):
 import deployment_exceptions
 inspect.signature(deployment_exceptions.execute_campaign).bind_partial(on_batch_created=None)
 deployment_exceptions.assert_recovered(home,allow_retry=True)
 (home/'upgraded').write_text('fresh executor with preserved recovery')
''')
    old = types.ModuleType("deployment_exceptions")
    old.execute_campaign = lambda: None
    before = marker.read_bytes()
    with patch.dict(sys.modules, {"deployment_exceptions": old}):
        with BatchLock(home / "state/daily.lock") as daily, deployment_lock(repo) as checkout:
            with recovery.prepare_daily_retry(repo, home, home / "runs/daily-launch/upgrade"):
                with pytest.raises(TypeError):
                    old.execute_campaign(on_batch_created=None)
                assert processes.run_worker(repo, home, home / "runs/daily-launch/upgrade", "head", False,
                                            [daily, checkout]) == 0
                assert sys.modules["deployment_exceptions"] is old
    assert (home / "upgraded").read_text() == "fresh executor with preserved recovery"
    assert marker.read_bytes() == before and (switch.backup / "0").is_file()


def test_worker_invalid_lease_cannot_rewrite_a_running_launch(tmp_path, monkeypatch):
    launch = tmp_path / "runs/daily-launch/current"
    save(launch / "status.json", {"status": "EXECUTING", "head": "head"})
    original = (launch / "status.json").read_bytes()
    monkeypatch.delenv(processes.LEASE_ENV, raising=False)
    with pytest.raises(RuntimeError, match="inherited supervisor locks"):
        worker.execute(tmp_path / "repo", tmp_path, launch, "head")
    assert (launch / "status.json").read_bytes() == original


def test_interrupt_forwards_to_worker_and_waits_for_recovery():
    from unittest.mock import Mock
    process = Mock()
    process.wait.side_effect = [KeyboardInterrupt(), KeyboardInterrupt(), None]
    process.poll.return_value = None
    locks = [Mock(), Mock()]
    with patch.object(processes, "worker_options", return_value=nullcontext(({}, {}))), \
            patch.object(processes.subprocess, "Popen", return_value=process), \
            pytest.raises(KeyboardInterrupt):
        processes.run_worker(Path("repo"), Path("home"), Path("launch"), "head", False, locks)
    process.send_signal.assert_called_once_with(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
    assert process.wait.call_count == 3


def test_notifier_uses_fresh_interpreter_and_failure_never_relabels_result(tmp_path):
    save(tmp_path / "status.json", {"status": "INCOMPLETE", "error": "worker exited"})
    original = (tmp_path / "status.json").read_bytes()
    with patch.object(processes.subprocess, "run", side_effect=subprocess.TimeoutExpired("offline-helper", 150)) as send:
        processes.notify_terminal(Path("repo"), Path("home"), tmp_path)
    argv = send.call_args.args[0]
    assert "-B" in argv and any(str(arg).startswith("pycache_prefix=") for arg in argv)
    assert "--notify-only" in argv
    assert (tmp_path / "status.json").read_bytes() == original
