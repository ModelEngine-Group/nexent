"""Synchronize a clean checkout and execute repository-owned Daily under one lock."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from suite_runtime import BatchLock, logged, now, save


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True,
                                   encoding="utf-8", stderr=subprocess.PIPE, timeout=120).strip()


def sync_checkout(repo, branch):
    """Never stash, reset, switch a dirty checkout, or merge divergent history."""
    if git(repo, "status", "--porcelain", "--untracked-files=normal"):
        raise RuntimeError("Daily requires a clean checkout before synchronization")
    if git(repo, "branch", "--show-current") != branch:
        raise RuntimeError("Checkout branch differs from requested branch; switch it explicitly first")
    git(repo, "check-ref-format", "--branch", branch)
    git(repo, "fetch", "origin", f"refs/heads/{branch}")
    target = git(repo, "rev-parse", "FETCH_HEAD")
    git(repo, "merge", "--ff-only", target)
    if git(repo, "rev-parse", "HEAD") != target:
        raise RuntimeError("Local commits differ from remote branch; refusing Daily")
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-home", type=Path, required=True)
    parser.add_argument("--branch", required=True, choices=("djb/test-baseline", "develop"))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[3]
    home = args.test_home.resolve()
    if home.is_relative_to(repo) or repo.is_relative_to(home):
        parser.error("Test home must be outside the checkout")
    if not args.execute:
        print(json.dumps({"branch": args.branch, "execute": False,
                          "steps": ["lock", "fast-forward", "derived-view-validation", "static-assets",
                                    "doctor", "build", "deploy", "D1-D5", "D6"]}))
        return 0
    runtime = home / "runtime/test-venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if os.path.normcase(os.path.abspath(sys.executable)) != os.path.normcase(os.path.abspath(runtime)):
        parser.error("Invoke the launcher with the dedicated test-home Python")
    directory = home / "runs/daily-launch" / (now().replace(":", "") + "-" + uuid.uuid4().hex[:8])
    try:
        with BatchLock(home / "state/daily.lock"):
            directory.mkdir(parents=True)
            state = {"branch": args.branch, "started_at": now(), "status": "PREPARING"}
            save(directory / "status.json", state)
            try:
                if (home / "state/deployment-guard/pending.json").exists():
                    raise RuntimeError("Pending deployment recovery must be resolved before synchronization")
                state["head"] = sync_checkout(repo, args.branch)
                env = os.environ.copy()
                # Derived output must never silently change tracked Feature navigation.
                command = [str(runtime), str(repo / "test-e2e/infra/tools/validate_test_assets.py"),
                           "--phase", "implementation", "--generate"]
                if logged(command, repo, env, directory / "validate.log", 180):
                    raise RuntimeError("Formal asset validation failed; inspect local launcher log")
                if git(repo, "status", "--porcelain", "--untracked-files=normal"):
                    raise RuntimeError("Derived generation changed tracked assets; repair them on the product branch")
                # Import only after checkout synchronization; use this exact revision's code.
                import static_assets
                import suite
                static_assets.apply(home, repo / "test-e2e/infra/assets")
                records = suite.selection(repo, argparse.Namespace(case=None, stage=None, feature=None, change=None))
                problems = suite.doctor(repo, home, records)
                if problems:
                    save(directory / "doctor.json", {"ready": False, "problems": problems})
                    raise RuntimeError("Runtime preflight failed; inspect local doctor.json")
                settings = suite.config(repo, home)
                state["status"] = "EXECUTING"
                save(directory / "status.json", state)
                # execute() does not acquire another lock; all normal entrypoints use the same lock.
                code = suite.execute(repo, home, records, settings, daily=True)
                state["status"] = "PASSED" if code == 0 else "FAILED"
                return code
            except (Exception, KeyboardInterrupt) as exc:
                state.update(status="INCOMPLETE", error=str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)
                return 2
            finally:
                state["finished_at"] = now()
                save(directory / "status.json", state)
                print(f"Daily launch: {directory}; status={state['status']}")
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
