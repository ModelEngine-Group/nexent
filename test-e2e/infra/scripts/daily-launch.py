# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Synchronize a clean checkout and execute repository-owned Daily under one lock."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import uuid

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from suite_runtime import BatchLock, deployment_lock, now, save
from daily_git import run_git
from daily_recovery import prepare_daily_retry
from daily_process import notify_terminal, run_worker


def git(repo, *args, log_dir=None):
    return run_git(repo, args, log_dir=log_dir)


def sync_checkout(repo, branch, *, log_dir=None):
    """Never stash, reset, switch a dirty checkout, or merge divergent history."""
    def checked(*args):
        return git(repo, *args, log_dir=log_dir) if log_dir is not None else git(repo, *args)

    if checked("status", "--porcelain", "--untracked-files=normal"):
        raise RuntimeError("Daily requires a clean checkout before synchronization")
    if checked("branch", "--show-current") != branch:
        raise RuntimeError("Checkout branch differs from requested branch; switch it explicitly first")
    checked("check-ref-format", "--branch", branch)
    checked("fetch", "origin", f"refs/heads/{branch}")
    target = checked("rev-parse", "FETCH_HEAD")
    checked("merge", "--ff-only", target)
    if checked("rev-parse", "HEAD") != target:
        raise RuntimeError("Local commits differ from remote branch; refusing Daily")
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-home", type=Path, required=True)
    parser.add_argument("--branch", required=True,
                        help="Explicit remote branch, validated and fast-forwarded under the Daily lock")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--publish-latest", action="store_true",
                        help="Publish complete Daily logs to test-home/runs-ubuntu; default disabled")
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[3]
    home = args.test_home.resolve()
    if home.is_relative_to(repo) or repo.is_relative_to(home):
        parser.error("Test home must be outside the checkout")
    if not args.execute:
        print(json.dumps({"branch": args.branch, "execute": False, "publish_latest": args.publish_latest,
                          "steps": ["lock", "fast-forward", "derived-view-validation", "static-assets",
                                    "doctor", "build", "deploy", "D1-D5", "D6"]}))
        return 0
    runtime = home / "runtime/test-venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if os.path.normcase(os.path.abspath(sys.executable)) != os.path.normcase(os.path.abspath(runtime)):
        parser.error("Invoke the launcher with the dedicated test-home Python")
    directory = home / "runs/daily-launch" / (now().replace(":", "") + "-" + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True)
    state = {"branch": args.branch, "started_at": now(), "status": "PREPARING"}
    save(directory / "status.json", state)
    old_handler = signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))

    try:
        with BatchLock(home / "state/daily.lock") as daily_lock:
            try:
                with deployment_lock(repo) as checkout_lock, prepare_daily_retry(repo, home, directory):
                    state["head"] = sync_checkout(repo, args.branch, log_dir=directory / "git")
                    save(directory / "status.json", state)
                    code = run_worker(repo, home, directory, state["head"], args.publish_latest,
                                      [daily_lock, checkout_lock])
                    result = json.loads((directory / "status.json").read_text(encoding="utf-8"))
                    state.update(result, worker_exit_code=code)
                    if (state.get("status") not in {"PASSED", "FAILED", "INCOMPLETE", "INTERRUPTED"}
                            or (code == 0 and state.get("status") != "PASSED")
                            or (code != 0 and state.get("status") == "PASSED")):
                        state.update(status="INCOMPLETE",
                                     error=f"Execution process exited with code {code} without a matching terminal receipt")
                        return 2
                    return code if code >= 0 else 2
            except (Exception, KeyboardInterrupt) as exc:
                state.update(status="INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "INCOMPLETE",
                             error="Interrupted" if isinstance(exc, KeyboardInterrupt) else
                             str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)
                if isinstance(exc, RuntimeError) and str(exc) == "another daily run is active":
                    raise
                return 2
    except (Exception, KeyboardInterrupt) as exc:
        state.update(status="INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "INCOMPLETE",
                     error="Interrupted" if isinstance(exc, KeyboardInterrupt) else
                     str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)
        print(state["error"], file=sys.stderr)
        return 3 if isinstance(exc, RuntimeError) else 2
    finally:
        signal.signal(signal.SIGTERM, old_handler)
        # Preserve any batch link already written by an interrupted executor.
        try:
            persisted = json.loads((directory / "status.json").read_text(encoding="utf-8"))
            if persisted.get("batch"):
                state["batch"] = persisted["batch"]
        except (OSError, ValueError, AttributeError):
            pass
        state["finished_at"] = now()
        save(directory / "status.json", state)
        print(f"Daily launch: {directory}; status={state['status']}")
        notify_terminal(repo, home, directory)


if __name__ == "__main__":
    raise SystemExit(main())
