"""Run selected formal cases from the repository with machine-local assets.

This is a targeted developer runner, not the Ubuntu deployment/scheduling
controller. Results and logs stay under NEXENT_TEST_HOME.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from xml.etree import ElementTree

if __name__ == "__main__" and any(arg == "--test-home" or arg.startswith("--test-home=") for arg in sys.argv[1:]):
    from launch_runtime import selected_python

    try:
        runtime = selected_python(["run", *sys.argv[1:]], Path(sys.executable))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from None
    if runtime is not None:
        raise SystemExit(subprocess.call([str(runtime), str(Path(__file__).resolve()), *sys.argv[1:]],
                                         env=os.environ.copy()))

import yaml

from test_asset_lib import repository_root
from validate_execution import inspect


ENV_LINE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def machine_environment(home: Path, repo: Path) -> dict[str, str]:
    env = dict(os.environ)
    for filename in ("daily.env", "secrets.env"):
        path = home / "config" / filename
        if not path.is_file():
            raise ValueError(f"Required machine-local config is missing: {path}")
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            match = ENV_LINE.fullmatch(line)
            if not match:
                raise ValueError(f"{path}:{number}: expected NAME=value")
            key, value = match.groups()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            if value:
                env[key] = value
    environment_path = home / "config/environment.yaml"
    if not environment_path.is_file():
        raise ValueError(f"Required machine-local config is missing: {environment_path}")
    settings = yaml.safe_load(environment_path.read_text(encoding="utf-8")) or {}
    if not isinstance(settings, dict):
        raise ValueError(f"{environment_path}: expected a mapping")
    base_url = str(settings.get("base_url") or "").rstrip("/")
    if base_url:
        env["NEXENT_BASE_URL"] = base_url.removesuffix("/zh")
    services = settings.get("services") or {}
    for name, variable in {
        "config": "NEXENT_CONFIG_URL", "data_process": "NEXENT_DATA_PROCESS_URL",
        "northbound": "NEXENT_NORTHBOUND_URL", "runtime": "NEXENT_RUNTIME_URL",
    }.items():
        service = services.get(name, {}) if isinstance(services, dict) else {}
        if isinstance(service, dict) and service.get("url"):
            env[variable] = str(service["url"]).rstrip("/")
    env.update(NEXENT_REPO=str(repo), NEXENT_TEST_HOME=str(home), TEST_ROOT=str(home))
    return env


def d4_plan(case_path: Path, result_dir: Path) -> Path:
    source = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    case = source["case"]
    def numbered(values: list[str]) -> str:
        return "\n".join(f"{number}. {value}" for number, value in enumerate(values, 1))
    steps = [entry["action"] for entry in case["steps"]]
    source_ref = case.get("source") or {}
    item = {
        "id": case["case_id"], "stage": "D4", "kind": "journey", "priority": case["priority"],
        "title": case["title"], "source_sheet": source_ref.get("legacy_sheet", "case.yaml"),
        "source_row": source_ref.get("legacy_row", 0),
        "preconditions": numbered(case["preconditions"]),
        "steps": numbered(steps), "assertions": numbered(case["expected_results"]),
        "local_assets": str(case.get("test_data") or "case-local declared assets"),
        "blocking_rule": str(case.get("objective") or "All listed assertions must pass"),
    }
    plan = result_dir / "agent-input/execution-plan.json"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(json.dumps({"schema_version": 1, "mode": "local-targeted", "items": [item]},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return plan


def command_for(record: dict, repo: Path, result_dir: Path, env: dict[str, str]) -> tuple[list[list[str]], Path]:
    entry = record["execution"]["implementations"][0]
    script = repo / entry["file"]
    framework = entry["framework"]
    if framework == "pytest":
        return [[sys.executable, "-m", "pytest", "-c", str(repo / "test-e2e/pytest.ini"),
                 str(script), f"--junitxml={result_dir / 'junit.xml'}"]], repo
    if framework == "custom" and script.suffix in {".ts", ".js", ".mjs"}:
        node = shutil.which("node")
        if not node:
            raise ValueError("node is required for the case-local Node test")
        return [[node, "--test", str(script)]], repo
    if framework == "vitest":
        package = repo / "test-e2e/infra/automation/d1/frontend"
        binary = package / "node_modules/vitest/vitest.mjs"
        if not binary.is_file():
            raise ValueError(f"Vitest dependencies are not installed in {package}")
        node = shutil.which("node")
        if not node:
            raise ValueError("node is required for D1 frontend cases")
        return [[node, str(binary), "run", "--config", str(package / "vitest.config.ts"),
                 str(script), "--testNamePattern", entry["selector"],
                 "--reporter=junit", f"--outputFile={result_dir / 'junit.xml'}"]], package
    if framework == "playwright":
        package = repo / "test-e2e/infra/automation/d4"
        binary = package / "node_modules/playwright/cli.js"
        if not binary.is_file():
            binary = repo / "frontend/node_modules/playwright/cli.js"
        if not binary.is_file():
            raise ValueError("Playwright dependencies are not installed in the D4 or frontend package")
        node = shutil.which("node")
        if not node:
            raise ValueError("node is required for D4 browser cases")
        env["NODE_PATH"] = str(binary.parent.parent) + os.pathsep + env.get("NODE_PATH", "")
        env["FIXED_TEST_PYTHON"] = sys.executable
        env["D4_PLAYWRIGHT_OUTPUT_DIR"] = str(result_dir / "d4/.playwright-internal")
        control = repo / "test-e2e/infra/automation/d4/control.py"
        plan = d4_plan(repo / "test-e2e/cases" / record["case_id"] / "case.yaml", result_dir)
        queue = result_dir / "agent-input/d4-queue.json"
        results = result_dir / "checkpoints/results.jsonl"
        results.parent.mkdir(parents=True, exist_ok=True)
        env["D4_QUEUE"] = str(queue)
        env["D4_RESULTS"] = str(results)
        return [
            [sys.executable, str(control), "prepare", "--plan", str(plan), "--results", str(results),
             "--result-dir", str(result_dir), "--output", str(queue)],
            [node, str(binary), "test", "--config", str(package / "playwright.config.ts"),
             str(script), "--grep", entry["selector"]],
            [sys.executable, str(control), "audit", "--queue", str(queue), "--results", str(results),
             "--result-dir", str(result_dir)],
        ], repo
    raise ValueError(f"Unsupported execution framework for {record['case_id']}: {framework}")


def junit_outcome(path: Path) -> tuple[str, dict[str, int]]:
    if not path.is_file():
        return "AUTOMATION_ERROR", {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    try:
        cases = list(ElementTree.parse(path).getroot().iter("testcase"))
    except ElementTree.ParseError:
        return "AUTOMATION_ERROR", {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    counts = {
        "tests": len(cases),
        "failures": sum(case.find("failure") is not None for case in cases),
        "errors": sum(case.find("error") is not None for case in cases),
        "skipped": sum(case.find("skipped") is not None for case in cases),
    }
    if not counts["tests"]:
        return "AUTOMATION_ERROR", counts
    if counts["failures"] or counts["errors"]:
        return "FAIL", counts
    if counts["skipped"]:
        return "BLOCKED", counts
    return "PASS", counts


def tap_outcome(path: Path) -> tuple[str, dict[str, int]]:
    summary = dict((key, int(value)) for key, value in re.findall(
        r"(?m)^# (tests|pass|fail|skipped|todo) (\d+)\s*$", path.read_text(encoding="utf-8", errors="replace")))
    if not summary.get("tests"):
        return "AUTOMATION_ERROR", summary
    if summary.get("fail"):
        return "FAIL", summary
    if summary.get("skipped") or summary.get("todo"):
        return "BLOCKED", summary
    return ("PASS" if summary.get("pass") == summary["tests"] else "AUTOMATION_ERROR"), summary


def run_one(record: dict, repo: Path, home: Path, env: dict[str, str], *, result_dir: Path | None = None) -> tuple[str, str, Path]:
    case_id = record["case_id"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if result_dir is None:
        result_dir = home / "runs" / "repository-local" / f"{stamp}-{case_id}"
        result_dir.mkdir(parents=True, exist_ok=False)
    else:
        result_dir = result_dir.resolve()
        if not result_dir.is_relative_to(home.resolve() / "runs"):
            raise ValueError("Case result directory must stay under test-home/runs")
        result_dir.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        result_dir.chmod(0o700)
    run_env = dict(env, RESULT_DIR=str(result_dir))
    commands, cwd = command_for(record, repo, result_dir, run_env)
    framework = record["execution"]["implementations"][0]["framework"]
    exit_code = 0
    last_log = result_dir / "step-1.log"
    for number, command in enumerate(commands, 1):
        log = result_dir / f"step-{number}.log"
        last_log = log
        with log.open("w", encoding="utf-8") as output:
            result = subprocess.run(command, cwd=cwd, env=run_env, stdout=output, stderr=subprocess.STDOUT,
                                    check=False)
        if result.returncode:
            exit_code = result.returncode
            break
    status = "PASS" if exit_code == 0 else "EXECUTION_FAILED"
    summary = None
    if framework in {"pytest", "vitest"}:
        observed, summary = junit_outcome(result_dir / "junit.xml")
        if observed != "PASS" or exit_code == 0:
            status = observed
    elif framework == "custom":
        observed, summary = tap_outcome(last_log)
        if observed != "PASS" or exit_code == 0:
            status = observed
    elif framework == "playwright" and exit_code == 0:
        status_path = result_dir / "d4" / case_id / "status.json"
        try:
            status = "PASS" if json.loads(status_path.read_text(encoding="utf-8")).get("status") == "PASS" else "EXECUTION_FAILED"
        except (OSError, ValueError):
            status = "AUTOMATION_ERROR"
    (result_dir / "status.json").write_text(json.dumps({
        "schema_version": 1, "case_id": case_id,
        "stage": record["stage"], "status": status,
        "exit_code": exit_code, "steps_completed": number,
        **({"test_summary": summary} if summary is not None else {}),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return case_id, status, result_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_ids", nargs="*")
    parser.add_argument("--test-home", type=Path)
    parser.add_argument("--list", action="store_true", help="List case IDs and stages without running")
    args = parser.parse_args()
    repo = repository_root()
    issues, registry = inspect(repo)
    if issues:
        raise ValueError(f"Formal execution bindings contain {len(issues)} validation issue(s)")
    cases = {record["case_id"]: record for record in registry["cases"]}
    if args.list:
        for record in registry["cases"]:
            print(f"{record['case_id']}\t{record['stage']}\t{record['status']}\t"
                  f"{record['execution']['implementations'][0]['framework'] if record['execution'] else '-'}")
        return 0
    if not args.case_ids:
        parser.error("Pass one or more Case IDs, or --list")
    unknown = sorted(set(args.case_ids) - cases.keys())
    if unknown:
        parser.error("Unknown Case IDs: " + ", ".join(unknown))
    unavailable = [case_id for case_id in args.case_ids
                   if cases[case_id]["status"] != "active" or not cases[case_id]["execution"]]
    if unavailable:
        parser.error("Not executable: " + ", ".join(unavailable))
    home = args.test_home or Path(os.environ.get("NEXENT_TEST_HOME", ""))
    if not str(home) or str(home) == ".":
        parser.error("Set --test-home or NEXENT_TEST_HOME to a machine-local directory")
    home = home.resolve()
    if home.is_relative_to(repo):
        parser.error("Test home must be outside the Git checkout")
    env = machine_environment(home, repo)
    failed = 0
    for case_id in dict.fromkeys(args.case_ids):
        actual_id, status, result_dir = run_one(cases[case_id], repo, home, env)
        print(f"{actual_id}: {status}; local evidence: {result_dir}")
        failed += status != "PASS"
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"Runner configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
