"""Run repository D1 and optional Legacy UT at the same source version."""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from xml.etree import ElementTree

from launch_runtime import selected_python

if __name__ == "__main__":
    runtime = selected_python(["run", *sys.argv[1:]], Path(sys.executable))
    if runtime is not None:
        raise SystemExit(subprocess.call([str(runtime), str(Path(__file__).resolve()), *sys.argv[1:]]))

import yaml

from coverage_support import frontend_arguments, python_arguments, python_inventory, python_report
from run_cases import command_for, junit_outcome, machine_environment, run_one
from suite_runtime import logged
from test_asset_lib import repository_root
from validate_execution import inspect


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_snapshot(repo: Path) -> dict:
    """Hash actual source bytes as well as HEAD, allowing uncommitted local work."""
    hashes = {}
    for name in ("backend", "sdk", "frontend", "test"):
        digest = hashlib.sha256()
        for root, directories, filenames in os.walk(repo / name):
            directories[:] = sorted(part for part in directories if part not in {
                ".venv", "node_modules", "__pycache__", ".next", "generated", "coverage_html", ".pytest_cache"})
            for filename in sorted(filenames):
                path = Path(root) / filename
                if path.suffix not in {".py", ".ts", ".tsx", ".js", ".jsx", ".yaml", ".toml", ".ini"}:
                    continue
                digest.update(path.relative_to(repo).as_posix().encode())
                digest.update(path.read_bytes())
        hashes[name] = digest.hexdigest()
    return {
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=repo, text=True).strip(),
        "source_hashes": hashes,
    }


def worker(repo: Path, home: Path, directory: Path, task: dict) -> int:
    env = machine_environment(home, repo)
    env["PYTHONPATH"] = os.pathsep.join([str(repo), str(repo / "backend"), str(repo / "sdk"), env.get("PYTHONPATH", "")])
    target = directory / task["directory"]
    target.mkdir(parents=True, exist_ok=True)
    env["RESULT_DIR"] = str(target)
    if task["suite"] == "d1-python" or task["suite"] == "d1-node":
        _, status, _ = run_one(task["record"], repo, home, env, result_dir=target,
                              coverage=task["suite"] == "d1-python")
        return 0 if status == "PASS" else 1
    if task["suite"] == "legacy":
        command = [sys.executable, "-m", "pytest", task["file"], "-q", "--disable-warnings",
                   f"--junitxml={target / 'junit.xml'}", *python_arguments(repo, target / "coverage/python", env)]
        cwd = repo
    else:
        representative = task["records"][0]
        commands, cwd = command_for(representative, repo, target, env)
        # Execute only the registered active frontend scripts, with one instrumented V8 run.
        command = commands[0]
        command.remove(str(repo / representative["execution"]["implementations"][0]["file"]))
        command += [str(repo / record["execution"]["implementations"][0]["file"]) for record in task["records"]]
        command += frontend_arguments(target / "coverage/frontend")
    with (target / "step-1.log").open("w", encoding="utf-8") as output:
        code = subprocess.call(command, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT)
    status, counts = junit_outcome(target / "junit.xml")
    if status == "PASS" and code:
        status = "AUTOMATION_ERROR"
    save(target / "status.json", {"status": status, "exit_code": code, "test_summary": counts})
    return code or (0 if status == "PASS" else 1)


def relative_files(report: dict, repo: Path) -> dict:
    files = {}
    for name, value in report["files"].items():
        path = Path(name)
        path = path if path.is_absolute() else repo / path
        files[path.resolve().relative_to(repo.resolve()).as_posix()] = value
    return files


def compare_python(repo: Path, directory: Path) -> dict:
    """Compare exact executed lines and arcs, never infer assertion quality from hits."""
    old = relative_files(json.loads((directory / "legacy/python/coverage.json").read_text(encoding="utf-8")), repo)
    new = relative_files(json.loads((directory / "d1/python/coverage.json").read_text(encoding="utf-8")), repo)
    rows = []
    for name in sorted(old.keys() | new.keys()):
        before, after = old.get(name, {}), new.get(name, {})
        old_lines, new_lines = set(before.get("executed_lines", [])), set(after.get("executed_lines", []))
        old_arcs = {tuple(arc) for arc in before.get("executed_branches", [])}
        new_arcs = {tuple(arc) for arc in after.get("executed_branches", [])}
        rows.append({"file": name, "legacy_only_lines": sorted(old_lines - new_lines),
                     "d1_only_lines": sorted(new_lines - old_lines),
                     "both_lines": len(old_lines & new_lines),
                     "legacy_only_branches": sorted(old_arcs - new_arcs),
                     "d1_only_branches": sorted(new_arcs - old_arcs),
                     "both_missing_lines": sorted(set(before.get("missing_lines", [])) & set(after.get("missing_lines", []))),
                     "same_statement_inventory": before.get("summary", {}).get("num_statements") ==
                                                 after.get("summary", {}).get("num_statements")})
    result = {"files": rows, "legacy_only_lines": sum(len(row["legacy_only_lines"]) for row in rows),
              "d1_only_lines": sum(len(row["d1_only_lines"]) for row in rows),
              "legacy_only_branches": sum(len(row["legacy_only_branches"]) for row in rows),
              "d1_only_branches": sum(len(row["d1_only_branches"]) for row in rows),
              "comparable_inventory": all(row["same_statement_inventory"] for row in rows)}
    save(directory / "python-comparison.json", result)
    return result


def legacy_assertions(path: Path) -> dict:
    """Extract assertions once per test definition, retaining class qualification."""
    text = path.read_text(encoding="utf-8-sig")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    templates, classes = {}, []
    lines = text.splitlines(keepends=True)

    def segment(node):
        # AST columns are UTF-8 byte offsets. Avoid rescanning the entire file
        # for every assertion in large legacy modules.
        selected = lines[node.lineno - 1:node.end_lineno]
        if not selected:
            return ""
        if len(selected) == 1:
            return selected[0].encode("utf-8")[node.col_offset:node.end_col_offset].decode("utf-8")
        selected[0] = selected[0].encode("utf-8")[node.col_offset:].decode("utf-8")
        selected[-1] = selected[-1].encode("utf-8")[:node.end_col_offset].decode("utf-8")
        return "".join(selected)

    class Collector(ast.NodeVisitor):
        def visit_ClassDef(self, node):
            classes.append(node.name)
            self.generic_visit(node)
            classes.pop()

        def visit_FunctionDef(self, node):
            if not node.name.startswith("test"):
                return
            body = segment(node)
            assertions = [item for item in ast.walk(node) if isinstance(item, ast.Assert) or
                (isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute) and
                 (item.func.attr.startswith("assert") or item.func.attr in {"raises", "warns"}))]
            templates["::".join([*classes, node.name])] = {
                "line": node.lineno,
                "assertions": [segment(item)[:500] for item in assertions[:8]],
                "boundary_or_error_hint": any(token in (node.name + " " + body).lower()
                    for token in ("raises", "error", "invalid", "empty", "none", "timeout", "boundary")),
            }

        visit_AsyncFunctionDef = visit_FunctionDef

    Collector().visit(tree)
    return templates


def audit_behaviors(repo: Path, directory: Path, comparison: dict, records: list[dict]) -> None:
    """Produce review leads with test assertions and source locations, not equivalence claims."""
    from coverage import CoverageData

    data = CoverageData(basename=str(directory / "legacy/python/.coverage"))
    data.read()
    measured = {Path(name).resolve(): name for name in data.measured_files()}
    new_data = CoverageData(basename=str(directory / "d1/python/.coverage"))
    new_data.read()
    new_measured = {Path(name).resolve(): name for name in new_data.measured_files()}
    outcomes = {}
    plan = json.loads((directory / "plan.json").read_text(encoding="utf-8"))
    for task in plan["tasks"]:
        junit = directory / task["directory"] / "junit.xml"
        if task["suite"] != "legacy" or not junit.is_file():
            continue
        for test in ElementTree.parse(junit).getroot().iter("testcase"):
            outcome = next((name.upper() for name in ("failure", "error", "skipped") if test.find(name) is not None), "PASS")
            key = (task["file"], test.attrib.get("name", ""))
            outcomes.setdefault(key, set()).add(outcome)
    leads = []
    test_cache = {}
    formal_records = {record["case_id"]: record for record in records}
    for row in comparison["files"]:
        path = repo / row["file"]
        if not row["legacy_only_lines"] or not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeError):
            continue
        contexts = data.contexts_by_lineno(measured[path.resolve()]) if path.resolve() in measured else {}
        new_contexts = new_data.contexts_by_lineno(new_measured[path.resolve()]) if path.resolve() in new_measured else {}
        functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for function in functions:
            exclusive = [line for line in row["legacy_only_lines"] if function.lineno <= line <= function.end_lineno]
            if not exclusive:
                continue
            test_ids = sorted({context.split("|", 1)[0] for line in exclusive
                               for context in contexts.get(line, []) if context.endswith("|run") and "::" in context})
            assertions = []
            for test_id in test_ids:
                filename, *parts = test_id.split("::")
                test_path = repo / filename
                if not test_path.is_file():
                    # Legacy pytest.ini makes test/ the root of its node IDs.
                    test_path = repo / "test" / filename
                if not test_path.is_file():
                    continue
                filename = test_path.relative_to(repo).as_posix()
                test_id = "::".join([filename, *parts])
                if filename not in test_cache:
                    test_cache[filename] = legacy_assertions(test_path)
                name = parts[-1].split("[", 1)[0]
                template = test_cache[filename].get("::".join([*parts[:-1], name]))
                if template:
                    assertions.append({"test_id": test_id, **template,
                                       "execution_outcome": sorted(outcomes.get((filename, parts[-1]), {"UNKNOWN"}))})
            related = []
            related_ids = set()
            # Executing a def/decorator while importing does not call its body.
            body_start = function.body[0].lineno if function.body else function.end_lineno + 1
            for line in range(body_start, function.end_lineno + 1):
                for context in new_contexts.get(line, []):
                    if not context.endswith("|run"):
                        continue
                    parts = context.split("::", 1)[0].replace("\\", "/").split("/")
                    if len(parts) > 1 and parts[0] == "cases" and parts[1] in formal_records:
                        related_ids.add(parts[1])
            for case_id in sorted(related_ids):
                case = yaml.safe_load((repo / "test-e2e/cases" / case_id / "case.yaml").read_text(encoding="utf-8"))["case"]
                related.append({"case_id": case_id, "title": case["title"], "expected_results": case["expected_results"],
                                "match_basis": "D1 runtime test context within this function; assertions still require review"})
            leads.append({"file": row["file"], "function": function.name, "line": function.lineno,
                          "legacy_only_lines": exclusive, "legacy_tests": assertions,
                          "related_formal_cases": related,
                          "classification": "review_required; coverage hits alone do not prove business assertions"})
    leads.sort(key=lambda lead: (not any(test["boundary_or_error_hint"] for test in lead["legacy_tests"]),
                                 -len(lead["legacy_only_lines"]), lead["file"], lead["line"]))
    save(directory / "legacy-exclusive-behaviors.json", {"review_leads": leads})


def write_report(directory: Path, summary: dict) -> None:
    lines = ["# D1 / Legacy UT coverage comparison", "",
             f"Branch: `{summary['source']['branch']}`; HEAD: `{summary['source']['head']}`.", "",
             f"Source stable throughout run: **{summary['source_stable']}**.",
             "Failures, collection errors and timeouts produce partial coverage; they never certify replacement.", "",
             "| Suite | Lines | Branches | Outcomes |", "|---|---:|---:|---|"]
    for suite in ("legacy", "d1"):
        coverage = summary.get(suite, {}).get("coverage") or {}
        line = coverage.get("lines", {})
        branch = coverage.get("branches", {})
        lines.append(f"| {suite} Python | {line.get('percent', '-')}% ({line.get('covered', '-')}/{line.get('total', '-')}) | "
                     f"{branch.get('percent', '-')}% ({branch.get('covered', '-')}/{branch.get('total', '-')}) | "
                     f"{summary.get(suite, {}).get('outcomes', {})} |")
    lines += ["", "Frontend coverage is separate: `d1-frontend/coverage/frontend/index.html` and `coverage-summary.json`.",
              "Node custom tests retain test results but do not contribute to either percentage.", ""]
    if summary.get("comparison"):
        compare = summary["comparison"]
        lines += [f"Legacy-only executed lines: {compare['legacy_only_lines']}; D1-only: {compare['d1_only_lines']}.",
                  f"Legacy-only executed branches: {compare['legacy_only_branches']}; D1-only: {compare['d1_only_branches']}.",
                  "", "See `python-comparison.json` for missing lines and branches, and",
                  "`legacy-exclusive-behaviors.json` for legacy test assertions and related formal cases.",
                  "These are review leads, not automatically confirmed requirement gaps."]
    lines += ["", "Every task's status, JUnit and step log remain in this local batch."]
    (directory / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def finish(repo: Path, directory: Path, rows: list[dict], initial: dict, records: list[dict]) -> dict:
    final = source_snapshot(repo)
    _, final_registry = inspect(repo)
    selected_ids = set(initial["formal_d1_hashes"])
    final["formal_d1_hashes"] = {record["case_id"]: [record["contract_hash"], record["execution"]["implementation_hash"]]
        for record in final_registry["cases"] if record["case_id"] in selected_ids and record["execution"]}
    summary = {"source": initial, "source_stable": initial == final, "final_source": final,
               "planned_tasks": len(json.loads((directory / "plan.json").read_text(encoding="utf-8"))["tasks"]),
               "completed_tasks": len(rows), "formal_cases": len(records)}
    suites = {name: [row for row in rows if row["suite"] == name] for name in ("legacy", "d1-python")}
    files = {name: [directory / row["directory"] / "coverage/python/.coverage" for row in selected]
             for name, selected in suites.items()}
    # Some benchmark/example files are discovered only when imported by Legacy UT.
    # Touch their union in both reports so neither suite gets a smaller denominator.
    inventory = python_inventory(repo, [path for paths in files.values() for path in paths])
    for name, label in (("legacy", "legacy"), ("d1-python", "d1")):
        selected = suites[name]
        if not selected:
            continue
        value = {"outcomes": dict(Counter(row["result"] for row in selected)),
                 "partial": any(row["result"] != "PASS" for row in selected)}
        try:
            value["coverage"] = python_report(repo, directory / label / "python", files[name], inventory=inventory)
        except Exception as exc:
            value["coverage_error"] = str(exc)
        summary[label] = value
    summary["frontend"] = [row for row in rows if row["suite"] == "d1-frontend"]
    summary["node"] = [row for row in rows if row["suite"] == "d1-node"]
    if summary.get("legacy", {}).get("coverage") and summary.get("d1", {}).get("coverage"):
        comparison = compare_python(repo, directory)
        summary["comparison"] = {key: value for key, value in comparison.items() if key != "files"}
        audit_behaviors(repo, directory, comparison, records)
    save(directory / "summary.json", summary)
    write_report(directory, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-home", type=Path, required=True)
    parser.add_argument("--compare-legacy", action="store_true")
    parser.add_argument("--framework", action="append", choices=("pytest", "vitest", "custom"),
                        help="Limit a diagnostic rerun to selected D1 frameworks")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=300, help="Per Python file timeout in seconds")
    parser.add_argument("--worker-index", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--batch-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--report-batch", type=Path, help="Regenerate reports from existing local evidence without rerunning tests")
    args = parser.parse_args()
    repo, home = repository_root(), args.test_home.resolve()
    if home.is_relative_to(repo) or repo.is_relative_to(home):
        parser.error("Test home must be outside and must not contain the checkout")
    if args.workers < 1 or args.timeout < 1:
        parser.error("Workers and timeout must be positive")
    if args.worker_index is not None:
        if not args.batch_dir or not args.batch_dir.resolve().is_relative_to(home / "runs/d1-coverage"):
            parser.error("Invalid coverage worker directory")
        plan = json.loads((args.batch_dir / "plan.json").read_text(encoding="utf-8"))
        return worker(repo, home, args.batch_dir, plan["tasks"][args.worker_index])
    issues, registry = inspect(repo)
    if issues:
        raise ValueError(f"Invalid formal bindings: {len(issues)} issue(s)")
    records = [record for record in registry["cases"] if record["stage"] == "D1" and record["status"] == "active" and record["execution"]]
    if args.report_batch:
        directory = args.report_batch.resolve()
        if not directory.is_relative_to(home / "runs/d1-coverage"):
            parser.error("Report batch must stay under test-home/runs/d1-coverage")
        plan = json.loads((directory / "plan.json").read_text(encoding="utf-8"))
        selected_ids = set(plan["formal_case_ids"])
        selected = [record for record in records if record["case_id"] in selected_ids]
        rows = [json.loads(line) for line in (directory / "results.jsonl").read_text(encoding="utf-8").splitlines()]
        summary = finish(repo, directory, rows, plan["source"], selected)
        print(f"Coverage report: {directory / 'report.md'}", flush=True)
        return 0 if summary["source_stable"] and summary["completed_tasks"] == summary["planned_tasks"] and not any(
            value.get("coverage_error") for value in (summary.get("legacy", {}), summary.get("d1", {}))) else 1
    if args.framework:
        records = [record for record in records if record["execution"]["implementations"][0]["framework"] in args.framework]
    if not records:
        parser.error("No active D1 Cases match the selection")
    if args.compare_legacy and args.framework and "pytest" not in args.framework:
        parser.error("Legacy Python comparison requires Python D1")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = home / "runs/d1-coverage" / stamp
    directory.mkdir(parents=True)
    tasks, frontend = [], []
    for record in records:
        framework = record["execution"]["implementations"][0]["framework"]
        if framework == "vitest":
            frontend.append(record)
        else:
            if framework not in {"pytest", "custom"}:
                raise ValueError(f"Unsupported D1 framework: {framework}")
            tasks.append({"suite": "d1-python" if framework == "pytest" else "d1-node",
                          "id": record["case_id"], "record": record,
                          "directory": f"d1-cases/{record['case_id']}"})
    if frontend:
        tasks.append({"suite": "d1-frontend", "id": "D1-FRONTEND", "records": frontend, "directory": "d1-frontend"})
    if args.compare_legacy:
        old = []
        for name in ("backend", "sdk", "ext_components"):
            for path in sorted((repo / "test" / name).rglob("test_*.py")):
                filename = path.relative_to(repo).as_posix()
                old.append({"suite": "legacy", "id": filename, "file": filename,
                            "directory": "legacy-files/" + hashlib.sha256(filename.encode()).hexdigest()[:16]})
        # Interleave the independent suites to compare the same live source version.
        tasks = [item for index in range(max(len(tasks), len(old)))
                 for item in ([tasks[index]] if index < len(tasks) else []) + ([old[index]] if index < len(old) else [])]
    initial = source_snapshot(repo)
    initial["formal_d1_hashes"] = {record["case_id"]: [record["contract_hash"], record["execution"]["implementation_hash"]]
                                 for record in records}
    save(directory / "plan.json", {"source": initial, "formal_case_ids": [record["case_id"] for record in records], "tasks": tasks})
    print(f"Local coverage batch: {directory}", flush=True)
    env = dict(os.environ)
    if os.name == "nt":
        # Repository text is UTF-8; match the Linux CI's text decoding in children.
        env.setdefault("PYTHONUTF8", "1")
    rows = []

    def run_task(index: int, task: dict) -> dict:
        target = directory / task["directory"]
        started = time.monotonic()
        code = logged([sys.executable, str(Path(__file__).resolve()), "--test-home", str(home),
                       "--worker-index", str(index), "--batch-dir", str(directory)], repo, env,
                      target / "worker.log", args.timeout if task["suite"] != "d1-frontend" else max(args.timeout, 900))
        status_path = target / "status.json"
        status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
        outcome = "TIMEOUT" if code == 124 else status.get("status", "AUTOMATION_ERROR")
        if code and outcome == "PASS":
            outcome = "AUTOMATION_ERROR"
        return {"suite": task["suite"], "id": task["id"], "directory": task["directory"],
                "result": outcome, "exit_code": code, "duration_seconds": round(time.monotonic() - started, 3),
                "test_summary": status.get("test_summary", {})}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_task, index, task): task for index, task in enumerate(tasks)}
        for future in as_completed(futures):
            task = futures[future]
            try:
                row = future.result()
            except Exception as exc:
                row = {"suite": task["suite"], "id": task["id"], "directory": task["directory"],
                       "result": "AUTOMATION_ERROR", "reason": type(exc).__name__}
            rows.append(row)
            save(directory / "progress.json", {"finished": len(rows), "planned": len(tasks), "last": row,
                                              "outcomes": dict(Counter(item["result"] for item in rows))})
            with (directory / "results.jsonl").open("a", encoding="utf-8") as output:
                output.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"{len(rows)}/{len(tasks)} {row['suite']} {row['id']}: {row['result']}", flush=True)
    summary = finish(repo, directory, rows, initial, records)
    print(f"Coverage report: {directory / 'report.md'}", flush=True)
    return 0 if summary["source_stable"] and all(row["result"] == "PASS" for row in rows) and not any(
        value.get("coverage_error") for value in (summary.get("legacy", {}), summary.get("d1", {}))) else 1


if __name__ == "__main__":
    raise SystemExit(main())
