"""Case-local plan, preflight and batch runner, independent of the old V5 controller."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import nullcontext
from functools import partial
import importlib.metadata
import json
import os
import shlex
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tomllib
import uuid

import yaml
from jsonschema import Draft202012Validator
from packaging.requirements import Requirement

from run_cases import machine_environment, run_one
from launch_runtime import test_python
from local_preflight import live_service_problems, static_config_problems
from static_assets import entries as static_entries, inventory as static_inventory
from suite_runtime import BatchLock, config_fingerprint, finalize, fingerprint, logged, now, save
from suite_resume import prepare_resume
from suite_services import controlled_services
from test_asset_lib import repository_root
from validate_execution import inspect

STAGES = [f"D{i}" for i in range(1, 6)]


def static_requirements(repo, records, *, daily):
    """Daily checks the full catalog; targeted runs check declared/direct references."""
    if daily:
        return None
    selected = set()
    for record in records:
        if not record.get("execution") or record.get("status") != "active":
            continue
        selected.update(record["execution"].get("required_assets") or [])
        case_path = repo / "test-e2e/cases" / record["case_id"] / "case.yaml"
        text = case_path.read_text(encoding="utf-8") if case_path.is_file() else ""
        primary = record["execution"]["implementations"][0]
        text += (repo / primary["file"]).read_text(encoding="utf-8")
        for item in static_entries():
            category = item["path"].split("/", 1)[0]
            if (item["asset_id"] in text or f"assets/{item['path']}" in text or
                    f"assets/{category}/" in text):
                selected.add(item["asset_id"])
    catalog_ids = {item["asset_id"] for item in static_entries()}
    catalog_paths = {item["path"] for item in static_entries()}
    return {value for value in selected if value in catalog_ids or value in catalog_paths}


def config(repo, home):
    path = home / "config/pipeline.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {
        "schema_version": 1, "case_timeout_seconds": 1800, "command_timeout_seconds": 3600, "hooks": {}}
    schema = json.loads((repo / "test-e2e/infra/config/pipeline.schema.json").read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda error: str(error.path))
    if errors:
        # Never echo arbitrary config values, which may contain credentials.
        raise ValueError("Invalid pipeline configuration at " + ", ".join(str(list(error.path)) for error in errors))
    return payload


def selection(repo, args):
    issues, registry = inspect(repo)
    if issues:
        raise ValueError(f"Invalid test assets: {len(issues)} binding issues")
    records = registry["cases"]
    selected_ids = set(args.case or [])
    if args.change:
        found = []
        for path in (repo / "test-e2e/changes").rglob("*.yaml"):
            change = yaml.safe_load(path.read_text(encoding="utf-8")).get("change", {})
            if change.get("change_id") == args.change:
                found.append(change)
        if len(found) != 1:
            raise ValueError("Change ID must match exactly one repository record")
        for values in found[0].get("affected_cases", {}).values():
            selected_ids.update(values)
        if not selected_ids:
            raise ValueError("Change has no affected Cases")
    unknown = selected_ids - {record["case_id"] for record in records}
    if unknown:
        raise ValueError("Unknown Case IDs: " + ", ".join(sorted(unknown)))
    result = [record for record in records
              if (not selected_ids or record["case_id"] in selected_ids)
              and (not args.stage or record["stage"] in args.stage)
              and (not args.feature or record["feature_id"] in args.feature)]
    if not result:
        raise ValueError("Selection contains no cases")
    return sorted(result, key=lambda record: (record["stage"], record["case_id"]))


def doctor(repo, home, records, *, live=False):
    problems = static_config_problems(home, records)
    expected_runtime = (home / "runtime/test-venv").resolve()
    if Path(sys.prefix).resolve() != expected_runtime or not test_python(home).is_file():
        problems.append("Run this suite with the dedicated <test-home>/runtime/test-venv Python")
    if sys.version_info[:2] != (3, 11):
        problems.append("Product runtime requires Python 3.11")
    for project in ("backend", "sdk"):
        data = tomllib.loads((repo / project / "pyproject.toml").read_text(encoding="utf-8"))
        for declaration in data["project"]["dependencies"]:
            req = Requirement(declaration)
            if req.marker and not req.marker.evaluate():
                continue
            try:
                version = importlib.metadata.version(req.name)
                # Backend owns the shared graph; SDK conflicting pins need separate review.
                if project == "backend" and req.specifier and version not in req.specifier:
                    problems.append(f"backend dependency mismatch: {req.name} {version} needs {req.specifier}")
            except importlib.metadata.PackageNotFoundError:
                problems.append(f"missing {project} dependency: {req.name}")
    frameworks = {record["execution"]["implementations"][0]["framework"] for record in records if record["execution"]}
    if frameworks & {"vitest", "playwright", "custom"}:
        node = shutil.which("node")
        if not node:
            problems.append("Node.js >=22 is required")
        else:
            version = subprocess.check_output([node, "--version"], text=True).strip()
            if int(version.lstrip("v").split(".")[0]) < 22:
                problems.append("Node.js >=22 is required")
    for framework, relative in (
        ("vitest", "d1/frontend/node_modules/vitest/vitest.mjs"),
        ("playwright", "d4/node_modules/playwright/cli.js"),
    ):
        if framework in frameworks and not (repo / "test-e2e/infra/automation" / relative).is_file():
            problems.append(f"missing locked {framework} toolchain")
    if live and not problems:
        problems.extend(live_service_problems(home))
    return sorted(set(problems))




def execute_hooks(name, settings, repo, home, directory, env):
    substitutions = {"{python}": sys.executable, "{repo}": str(repo), "{home}": str(home), "{run}": str(directory)}
    for index, command in enumerate(settings["hooks"].get(name, []), 1):
        expanded = []
        for value in command:
            for key, replacement in substitutions.items():
                value = value.replace(key, replacement)
            expanded.append(value)
        code = logged(expanded, repo, env, directory / "logs" / f"{name}-{index}.log", settings["command_timeout_seconds"])
        if code:
            raise RuntimeError(f"{name} command {index} failed with exit {code}; inspect local log")


def worker(repo, home, record, directory, settings):
    """Run one Case with its own asset registry; never clean another run's assets."""
    env = machine_environment(home, repo)
    # Keep all descendants in the worker group so the controller can terminate it.
    run_logged = partial(logged, new_session=False)
    automation = repo / "test-e2e/infra/automation"
    env["PYTHONPATH"] = os.pathsep.join([str(automation), str(repo / "backend"), str(repo / "sdk"), env.get("PYTHONPATH", "")])
    env["RESULT_DIR"] = str(directory)
    if (home / "runtime/playwright-browsers").is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(home / "runtime/playwright-browsers")
    directory.mkdir(parents=True, exist_ok=True)
    review = record["execution"].get("preparation")
    # Online preparation must not be guessed from names or run every factory.
    if record["stage"] != "D1" and review is None:
        save(directory / "receipt.json", {"case_id": record["case_id"], "stage": record["stage"],
             "result": "BLOCKED", "reason": "Missing per-case preparation declaration", "evidence": []})
        return 1
    outcome = "AUTOMATION_ERROR"
    reason = None
    services = controlled_services(repo, directory, env, bool((review or {}).get("anchors")))
    services_started = False
    try:
        services.__enter__()
        services_started = True
        if (review or {}).get("anchors"):
            code = run_logged([sys.executable, str(automation / "prepare_anchor_assets.py")], repo, env,
                          directory / "logs/prepare-anchors.log", settings["command_timeout_seconds"])
            if code:
                outcome = "TIMEOUT" if code == 124 else "BLOCKED"
                raise RuntimeError("Anchor preparation failed")
        for family in (review or {}).get("families", []):
            code = run_logged([sys.executable, "-m", "shared.prepare_local_assets", "--family", family],
                          repo, env, directory / "logs" / f"prepare-{family}.log", settings["command_timeout_seconds"])
            if code:
                outcome = "TIMEOUT" if code == 124 else "BLOCKED"
                raise RuntimeError("Asset preparation did not complete")
        if (review or {}).get("special_assets"):
            code = run_logged([sys.executable, str(automation / "prepare_special_assets.py"), "--case", record["case_id"]],
                          repo, env, directory / "logs/prepare-special.log", settings["command_timeout_seconds"])
            if code:
                outcome = "TIMEOUT" if code == 124 else "BLOCKED"
                raise RuntimeError("Special asset preparation failed")
        if (review or {}).get("d4_groups"):
            output = directory / "runtime/d4-shared-assets.env"
            command = [sys.executable, str(automation / "prepare_d4_shared_assets.py"), "--output", str(output)]
            for group in review["d4_groups"]:
                command += ["--group", group]
            code = run_logged(command, repo, env, directory / "logs/prepare-d4.log", settings["command_timeout_seconds"])
            if code:
                outcome = "TIMEOUT" if code == 124 else "BLOCKED"
                raise RuntimeError("D4 asset preparation failed")
            for line in output.read_text(encoding="utf-8").splitlines():
                parts = shlex.split(line.removeprefix("export "))
                if len(parts) != 1 or "=" not in parts[0]:
                    raise ValueError("Invalid prepared D4 environment")
                key, value = parts[0].split("=", 1)
                env[key] = value
        _, outcome, _ = run_one(record, repo, home, env, result_dir=directory)
    except Exception as exc:
        reason = type(exc).__name__
    finally:
        cleanup_code = 0
        registry = directory / "runtime/resolved-assets.yaml"
        if registry.exists():
            # Preserve failure evidence for the existing cleanup retention policy.
            checkpoint = directory / "checkpoints/results.jsonl"
            if not checkpoint.exists():
                checkpoint.parent.mkdir(parents=True, exist_ok=True)
                checkpoint.write_text(json.dumps({"case_id": record["case_id"], "result": outcome}) + "\n", encoding="utf-8")
            try:
                cleanup_code = run_logged([sys.executable, "-m", "shared.asset_cleanup", "--output",
                                       str(directory / "runtime/cleanup-results.jsonl")], repo, env,
                                      directory / "logs/cleanup.log", settings["command_timeout_seconds"])
            except Exception:
                cleanup_code = 2
        if services_started:
            try:
                services.__exit__(None, None, None)
            except Exception:
                cleanup_code = 2
        save(directory / "receipt.json", {"case_id": record["case_id"], "stage": record["stage"],
             "result": "CLEANUP_FAILED" if cleanup_code else outcome, "test_result": outcome,
             "cleanup_exit_code": cleanup_code, "reason": reason, "evidence": [directory.name]})
    return 0 if outcome == "PASS" and not cleanup_code else 1


def execute(repo, home, records, settings, *, daily=False, resume=None):
    directory = home / "runs/repository-daily" / (now().replace(":", "").replace("+", "-") + "-" + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=False)
    if os.name != "nt":
        directory.chmod(0o700)
    required_static = static_requirements(repo, records, daily=daily)
    provenance = {**fingerprint(repo), "config_sha256": config_fingerprint(home),
                  "batch_mode": "daily" if daily else "run", "full_static_assets": daily,
                  "required_static_assets": sorted(required_static or []),
                  "resumed_from": str(resume["source"]) if resume else None}
    if resume:
        marker = resume["source"] / "resume-child.json"
        with os.fdopen(os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as output:
            json.dump({"child": str(directory), "at": now()}, output)
    save(directory / "provenance.json", provenance)
    save(directory / "plan.json", {"cases": records})
    save(directory / "pipeline.json", settings)
    reused_rows = {row["case_id"]: row for row in resume["rows"]} if resume else {}
    rows, error = [], None
    previous_handler = signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    state = {"status": "RUNNING", "started_at": now(), "stages": {f"D{i}": "PENDING" for i in range(7)}}
    save(directory / "status.json", state)
    print(f"Local batch: {directory}", flush=True)
    try:
        env = machine_environment(home, repo)
        if (home / "state/deployment-guard/pending.json").exists():
            raise RuntimeError("Pending deployment recovery exists; recover the owned environment before running")
        state["stages"]["D0"] = "RUNNING"
        save(directory / "status.json", state)
        validation = logged([sys.executable, str(repo / "test-e2e/infra/tools/validate_test_assets.py"),
                             "--phase", "implementation"], repo, env, directory / "logs/validate.log", 180)
        if validation:
            raise RuntimeError("Formal asset validation failed")
        static_rows = static_inventory(home, selected=required_static)
        save(directory / "d0/static-assets.json", {"scope": "full" if daily else "selected",
                                                   "assets": static_rows})
        if any(row["destination"] != "READY" for row in static_rows):
            raise RuntimeError("Static assets are missing or differ from the catalog; inspect d0/static-assets.json")
        if daily:
            if any(not settings["hooks"].get(name) for name in ("build", "deploy", "preflight")):
                raise RuntimeError("Daily build/deploy/preflight hooks must be explicitly configured")
            dirty = subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=normal"], text=True)
            if dirty.strip():
                raise RuntimeError("Daily requires a clean committed checkout; local mode supports developer changes")
            for name in ("build", "deploy", "preflight"):
                execute_hooks(name, settings, repo, home, directory, env)
        state["stages"]["D0"] = "COMPLETE"
        for stage in STAGES:
            state["stages"][stage] = "RUNNING"
            save(directory / "status.json", state)
            for record in [item for item in records if item["stage"] == stage]:
                current = fingerprint(repo)
                if any(current.get(key) != provenance.get(key) for key in
                       ("head", "test_assets_sha256", "tracked_product_diff_sha256", "untracked_product_sha256")) or \
                        config_fingerprint(home) != provenance["config_sha256"]:
                    raise RuntimeError("Product source, test assets or machine config changed during batch")
                case_id = record["case_id"]
                reused = reused_rows.get(case_id)
                if reused:
                    row = reused
                    if record["status"] == "active" and record.get("execution"):
                        save(directory / "cases" / case_id / "receipt.json", {
                            "case_id": case_id, "stage": record["stage"], "result": row["result"],
                            "cleanup_exit_code": 0, "reused_from": row["reused_from"]})
                elif record["status"] != "active" or not record["execution"]:
                    result = {"retired": "RETIRED", "skipped_by_policy": "SKIPPED_BY_POLICY"}.get(record["status"], "BLOCKED")
                    row = {"case_id": case_id, "stage": stage, "result": result, "reason": record["status"], "evidence": []}
                else:
                    case_dir = directory / "cases" / case_id
                    code = logged([sys.executable, str(Path(__file__)), "worker", "--test-home", str(home),
                                   "--case", case_id, "--batch-dir", str(directory)], repo, env,
                                  directory / "logs" / f"{case_id}.log",
                                  record["execution"].get("timeout_seconds", settings["case_timeout_seconds"]))
                    receipt = case_dir / "receipt.json"
                    row = json.loads(receipt.read_text(encoding="utf-8")) if receipt.exists() else {
                        "case_id": case_id, "stage": stage, "result": "TIMEOUT" if code == 124 else "AUTOMATION_ERROR",
                        "reason": "Worker ended without a terminal receipt; inspect asset registry before retry",
                        "evidence": [f"logs/{case_id}.log"]}
                    if code and row["result"] == "PASS":
                        row["result"] = "AUTOMATION_ERROR"
                    row["evidence"] = [f"cases/{case_id}", f"logs/{case_id}.log"]
                rows.append(row)
                save(directory / "progress.json", {"finished": len(rows), "planned": len(records), "last_case": case_id})
                with (directory / "results.journal.jsonl").open("a", encoding="utf-8") as output:
                    output.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"{len(rows)}/{len(records)} {case_id}: {row['result']}" +
                      (" (reused)" if reused else ""), flush=True)
                if (home / "state/deployment-guard/pending.json").exists() or (
                    stage == "D5" and row["result"] in {"TIMEOUT", "CLEANUP_FAILED"}
                ):
                    raise RuntimeError("Environment recovery needs verification before continuing")
            state["stages"][stage] = "COMPLETE"
        current = fingerprint(repo)
        if any(current.get(key) != provenance.get(key) for key in
               ("head", "test_assets_sha256", "tracked_product_diff_sha256", "untracked_product_sha256")) or \
                config_fingerprint(home) != provenance["config_sha256"]:
            raise RuntimeError("Source or machine config changed before finalization")
    except KeyboardInterrupt:
        error = "Interrupted"
    except Exception as exc:
        error = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
    finally:
        summary = finalize(directory, records, rows, error)
        for stage, status in state["stages"].items():
            if status in {"PENDING", "RUNNING"}:
                state["stages"][stage] = "NOT_EXECUTED" if status == "PENDING" else "INTERRUPTED"
        state["stages"]["D6"] = "COMPLETE"
        state.update(status=summary["status"], finished_at=now(), error=error)
        save(directory / "status.json", state)
        save(home / "reports/repository-latest.json", {"batch": str(directory), "status": summary["status"]})
        signal.signal(signal.SIGTERM, previous_handler)
    if daily and settings.get("notify") and summary["execution_complete"]:
        from suite_notify import send_report
        send_report(directory, env)
    return 0 if summary["status"] == "PASSED" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "doctor", "bootstrap", "run", "daily", "resume", "worker"))
    parser.add_argument("--test-home", type=Path, required=True)
    parser.add_argument("--case", action="append")
    parser.add_argument("--stage", action="append", choices=STAGES)
    parser.add_argument("--feature", action="append")
    parser.add_argument("--change")
    parser.add_argument("--execute", action="store_true", help="Actually run tests or install dependencies")
    parser.add_argument("--live", action="store_true", help="Doctor: probe configured local HTTP services")
    parser.add_argument("--batch-dir", type=Path, help="Existing local batch directory for resume")
    args = parser.parse_args(argv)
    repo, home = repository_root(), args.test_home.resolve()
    if home == repo or home.is_relative_to(repo) or repo.is_relative_to(home):
        parser.error("Test home must be outside, and must not contain, the Git checkout")
    try:
        settings = config(repo, home)
        if args.mode == "bootstrap":
            from bootstrap_runtime import main as bootstrap_main
            return bootstrap_main(["--test-home", str(home)] + (["--execute"] if args.execute else []))
        if args.mode == "resume":
            if not args.batch_dir or args.case or args.stage or args.feature or args.change:
                parser.error("Resume requires --batch-dir and does not accept Case selectors")
            with (BatchLock(home / "state/daily.lock") if args.execute else nullcontext()):
                issues, registry = inspect(repo)
                if issues:
                    raise ValueError(f"Invalid test assets: {len(issues)} binding issues")
                resume = prepare_resume(repo, home, args.batch_dir, settings, registry["cases"])
                records = resume["records"]
                if not args.execute:
                    print(json.dumps({"mode": "resume", "execution_requested": False,
                                      "source": str(resume["source"]), "planned": len(records),
                                      "reused": len(resume["rows"]), "remaining": len(records) - len(resume["rows"])},
                                     ensure_ascii=False, indent=2))
                    return 0
                problems = doctor(repo, home, records)
                if problems:
                    print(json.dumps({"ready": False, "problems": problems}, ensure_ascii=False, indent=2))
                    return 2
                return execute(repo, home, records, settings, resume=resume)
        records = selection(repo, args)
        if args.mode == "worker":
            if not args.batch_dir or len(records) != 1:
                parser.error("Worker requires one Case and a batch directory")
            directory = args.batch_dir.resolve()
            if not directory.is_relative_to(home / "runs/repository-daily"):
                parser.error("Worker batch path escapes local batch root")
            settings = json.loads((directory / "pipeline.json").read_text(encoding="utf-8"))
            return worker(repo, home, records[0], directory / "cases" / records[0]["case_id"], settings)
        if args.mode == "doctor":
            problems = doctor(repo, home, records, live=args.live)
            print(json.dumps({"ready": not problems, "problems": problems}, ensure_ascii=False, indent=2))
            return 2 if problems else 0
        if args.mode == "plan" or not args.execute:
            print(json.dumps({"mode": args.mode, "execution_requested": False, "cases": len(records),
                              "stages": dict(Counter(record["stage"] for record in records)),
                              "statuses": dict(Counter(record["status"] for record in records)),
                              "online_cases_without_preparation_declaration": sum(
                                  record["stage"] != "D1" and record["status"] == "active" and bool(record["execution"])
                                  and not record["execution"].get("preparation") for record in records),
                              "case_ids": [record["case_id"] for record in records]}, ensure_ascii=False, indent=2))
            return 0
        if args.mode == "daily" and (args.case or args.stage or args.feature or args.change):
            parser.error("Daily must use the full registry; select cases with run")
        problems = doctor(repo, home, records)
        if problems:
            print(json.dumps({"ready": False, "problems": problems}, ensure_ascii=False, indent=2))
            return 2
        with BatchLock(home / "state/daily.lock"):
            return execute(repo, home, records, settings, daily=args.mode == "daily")
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 3 if str(exc) == "another daily run is active" else 2
    except (ValueError, OSError) as exc:
        print(f"Configuration error: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
