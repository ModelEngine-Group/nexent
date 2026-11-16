# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Execute only synchronized code, under inherited and verified supervisor locks."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import traceback

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from daily_process import inherited_locks
from daily_recovery import prepare_daily_retry
from suite_notify import notification_environment, notification_text, notify_launch, snapshot
from suite_runtime import logged, now, save


def checked_revision(repo, branch, head):
    """Do not fetch, switch branches, or trust a stale supervisor's source snapshot."""
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()
    if git("branch", "--show-current") != branch or git("rev-parse", "HEAD") != head:
        raise RuntimeError("Synchronized revision changed before Daily execution")
    if git("status", "--porcelain", "--untracked-files=normal"):
        raise RuntimeError("Daily execution requires a clean synchronized checkout")


def execute_locked(repo, home, directory, head, publish_latest=False):
    state = snapshot(directory / "status.json")
    state["worker_pid"] = os.getpid()
    old_handlers = {}
    for sig in (signal.SIGTERM, *([signal.SIGBREAK] if os.name == "nt" else [])):
        old_handlers[sig] = signal.signal(sig, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))

    def record_batch(batch):
        state["batch"] = str(batch)
        save(directory / "status.json", state)

    try:
        if state.get("head") != head or state.get("status") != "PREPARING":
            raise RuntimeError("Daily execution does not match the synchronized launch receipt")
        checked_revision(repo, state["branch"], head)
        state["worker_head"] = head
        save(directory / "status.json", state)
        with prepare_daily_retry(repo, home, directory, prepared=True):
            command = [sys.executable, str(repo / "test-e2e/infra/tools/validate_test_assets.py"),
                       "--phase", "implementation", "--daily-report", str(directory / "asset-validation.json")]
            if logged(command, repo, os.environ.copy(), directory / "validate.log", 180):
                raise RuntimeError("Formal asset validation failed; inspect local launcher log")
            checked_revision(repo, state["branch"], head)
            import static_assets
            import suite
            static_assets.apply(home, repo / "test-e2e/infra/assets")
            records = suite.selection(repo, argparse.Namespace(case=None, stage=None, feature=None, change=None), daily=True)
            problems = suite.doctor(repo, home, records, common_only=True)
            if problems:
                save(directory / "doctor.json", {"ready": False, "problems": problems})
                raise RuntimeError("Runtime preflight failed; inspect local doctor.json")
            settings = suite.config(repo, home)
            state["status"] = "EXECUTING"
            save(directory / "status.json", state)
            code = suite.execute(repo, home, records, settings, daily=True, publish_latest=publish_latest,
                                 on_batch_created=record_batch)
            state["status"] = "PASSED" if code == 0 else "FAILED"
            return code
    except (Exception, KeyboardInterrupt) as exc:
        env = notification_environment(home)
        reason = "Interrupted" if isinstance(exc, KeyboardInterrupt) else f"{type(exc).__name__}: {exc}"
        state.update(status="INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "INCOMPLETE",
                     error=notification_text(reason, env))
        trace = directory / "worker-error.log"
        trace.write_text(notification_text(traceback.format_exc(), env), encoding="utf-8")
        return 2
    finally:
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        state["finished_at"] = now()
        save(directory / "status.json", state)


def execute(repo, home, directory, head, publish_latest=False):
    with inherited_locks(repo, home):
        return execute_locked(repo, home, directory, head, publish_latest)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-home", type=Path, required=True)
    parser.add_argument("--launch", type=Path, required=True)
    parser.add_argument("--head")
    parser.add_argument("--publish-latest", action="store_true")
    parser.add_argument("--notify-only", action="store_true")
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[3]
    home, directory = args.test_home.resolve(), args.launch.resolve()
    if home.is_relative_to(repo) or repo.is_relative_to(home) or directory.parent != home / "runs/daily-launch":
        parser.error("Daily execution paths must belong to an external test-home launch")
    runtime = home / "runtime/test-venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if os.path.normcase(os.path.abspath(sys.executable)) != os.path.normcase(os.path.abspath(runtime)):
        parser.error("Invoke the worker with the dedicated test-home Python")
    if args.notify_only:
        notify_launch(directory, home)
        return 0
    if not args.head:
        parser.error("Daily execution needs a synchronized commit")
    try:
        return execute(repo, home, directory, args.head, args.publish_latest)
    finally:
        notify_launch(directory, home)


if __name__ == "__main__":
    raise SystemExit(main())
