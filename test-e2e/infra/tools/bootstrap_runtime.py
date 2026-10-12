"""Standard-library-only bootstrap for a fresh developer or Ubuntu machine."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

from suite_runtime import BatchLock, logged


def bootstrap_commands(repo):
    return [
        (["uv", "sync", "--frozen", "--extra", "test", "--extra", "data-process"], repo / "backend"),
        (["uv", "pip", "install", "--python", "{runtime_python}", "--editable", str(repo / "sdk")], repo),
        (["npm", "ci"], repo / "frontend"),
        (["npm", "ci"], repo / "test-e2e/infra/automation/d1/frontend"),
        (["node", "ensure-product-react.mjs"], repo / "test-e2e/infra/automation/d1/frontend"),
        (["npm", "ci"], repo / "test-e2e/infra/automation/d4"),
        (["node", str(repo / "test-e2e/infra/automation/d4/node_modules/playwright/cli.js"), "install", "chromium"], repo),
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-home", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[3]
    home = args.test_home.resolve()
    if home.is_relative_to(repo) or repo.is_relative_to(home):
        parser.error("Test home must be outside, and must not contain, the checkout")
    runtime_python = home / "runtime/test-venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    commands = [(list(map(lambda value: str(runtime_python) if value == "{runtime_python}" else value, command)), cwd)
                for command, cwd in bootstrap_commands(repo)]
    if not args.execute:
        print(json.dumps([{"argv": command, "cwd": str(cwd)} for command, cwd in commands], indent=2))
        return 0
    missing = [name for name in ("uv", "npm", "node") if not shutil.which(name)]
    if missing:
        parser.error("Install these tools first: " + ", ".join(missing))
    env = dict(os.environ, UV_PROJECT_ENVIRONMENT=str(home / "runtime/test-venv"),
               PLAYWRIGHT_BROWSERS_PATH=str(home / "runtime/playwright-browsers"), NEXENT_REPO=str(repo))
    try:
        with BatchLock(home / "state/daily.lock"):
            for index, (command, cwd) in enumerate(commands):
                command[0] = shutil.which(command[0]) or command[0]
                if logged(command, cwd, env, home / "runtime/bootstrap-logs" / f"{index}.log", 3600):
                    print("Bootstrap failed; inspect runtime/bootstrap-logs", file=sys.stderr)
                    return 2
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    print("Locks installed in runtime/test-venv. Run doctor; SDK-only extras and Linux browser system libraries must also be checked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
