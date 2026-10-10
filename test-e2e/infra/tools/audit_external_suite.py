"""Read-only direct comparison with an external suite and extracted V5 values.

The workbook JSON is a read-only extraction, not an alternative case authority.
Script parity is a mechanical source comparison, never a live-test certificate.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test-e2e/infra/migration/legacy-tools"))
from migrate_v5_cases import GROUP_SHEETS, clauses, legacy_fields, text
from split_v5_direct_pytests import split_source
from split_v5_parameterized_pytests import _decorator, _transform_helper
from split_v5_frontend_vitest import parsed_module


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lf(value):
    return value.replace("\r\n", "\n").strip()


def ast_same(left, right):
    try:
        return ast.dump(ast.parse(left)) == ast.dump(ast.parse(right))
    except SyntaxError:
        return False


def direct_code(source, target, case_id, parsed_cache):
    """Reconstruct only the documented per-case split, not arbitrary rewrites."""
    original = source.read_text(encoding="utf-8-sig")
    actual = target.read_text(encoding="utf-8-sig")
    if lf(original) == lf(actual):
        return "identical"
    if source.suffix == ".py":
        try:
            expected = split_source(original)[case_id]
            if ast_same(expected, actual):
                return "python_case_split"
        except (KeyError, ValueError):
            pass
    elif source.name.endswith(".spec.ts"):
        matches = list(re.finditer(r'^journey\("(?P<id>[A-Z][A-Z0-9-]+)"', original, re.M))
        for index, match in enumerate(matches):
            if match["id"] == case_id:
                end = matches[index + 1].start() if index + 1 < len(matches) else len(original)
                expected = original[:matches[0].start()] + original[match.start():end]
                for quote in ('"', "'"):
                    for depth in ("../", "../../"):
                        for part in ("runner", "pages", "helpers"):
                            expected = expected.replace(f"from {quote}{depth}{part}/", f"from {quote}../../infra/automation/d4/{part}/")
                expected = expected.replace(
                    'join(process.env.TEST_ROOT || "", "auto_test", "d4", "helpers", "seed_citation_source.py")',
                    'join(process.env.NEXENT_REPO || "", "test-e2e", "infra", "automation", "d4", "helpers", "seed_citation_source.py")')
                if lf(expected) == lf(actual):
                    return "playwright_case_split_and_import_paths"
    elif source.name.endswith(".test.tsx"):
        if source not in parsed_cache:
            parsed_cache[source] = parsed_module(ROOT, source)
        parsed = parsed_cache[source]
        header = "".join(parsed["header"]).strip() + "\n\n"
        if len(parsed["groups"]) == 1:
            group = parsed["groups"][0]
            items = [item for item in group["items"] if case_id in item]
            if len(items) == 1:
                expected = header + f"describe({group['title']}, () => {{\n  {items[0]}\n}});\n"
                if lf(expected) == lf(actual):
                    return "vitest_case_split"
        chunks = []
        current = None
        for group in parsed["groups"]:
            ids = re.findall(r"UT-FE-[A-Z0-9-]+", group["code"])
            if ids:
                current = ids[0]
            if current == case_id:
                chunks.append(group["code"])
        if chunks and lf(header + "\n\n".join(chunks)) == lf(actual):
            return "vitest_case_split"
    return "different_needs_review"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--workbook-values", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source = args.source_root.resolve()
    workbook_path = source / "cases/Nexent_Develop_每日真实资产测试基线_v5.xlsx"
    workbook = json.loads(args.workbook_values.read_text(encoding="utf-8"))
    if digest(workbook_path) != workbook["sha256"]:
        raise SystemExit("Workbook changed after extraction; extract again")
    cases = {}
    bindings = {}
    for path in sorted((ROOT / "test-e2e/cases").glob("*/case.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        case_id = doc["case"]["case_id"]
        if case_id in cases:
            raise ValueError(f"Duplicate Case: {case_id}")
        cases[case_id] = doc
        execution = path.with_name("execution.yaml")
        if execution.exists():
            bindings[case_id] = yaml.safe_load(execution.read_text(encoding="utf-8"))
    rows = {}
    for group, sheet in GROUP_SHEETS.items():
        matrix = workbook["sheets"][sheet]
        for number, values in enumerate(matrix[1:], 2):
            if not values or not values[0]:
                continue
            row = {key: value for key, value in zip(matrix[0], values) if key}
            case_id = str(values[0]).strip()
            if case_id in rows:
                raise ValueError(f"Duplicate workbook Case: {case_id}")
            row.update(id=case_id, _workbook_row=number)
            rows[case_id] = (group, row)
    contract_diffs = []
    for case_id in sorted(rows.keys() & cases.keys()):
        group, row = rows[case_id]
        title, before, actions, expected, assets, _ = legacy_fields(row, group)
        case = cases[case_id]["case"]
        stage = re.match(r"^(D[1-5])\b", str(row.get("每日CI阶段") or ""))
        checks = {
            "title": title, "priority": text(row.get("优先级")),
            "preconditions": clauses(before),
            "expected_results": clauses(expected) or [title or case_id],
        }
        fields = [key for key, value in checks.items() if case.get(key) != value]
        if [step["action"] for step in case["steps"]] != (clauses(actions) or [title or case_id]):
            fields.append("steps")
        if not stage or cases[case_id]["stage"] != stage[1]:
            fields.append("stage")
        if case.get("test_data", {}).get("legacy_asset_declaration", "") != assets:
            fields.append("asset_declaration")
        if fields:
            contract_diffs.append({"case_id": case_id, "fields": fields, "sheet": GROUP_SHEETS[group], "row": row["_workbook_row"]})
    features = {path.parent.name: yaml.safe_load(path.read_text(encoding="utf-8"))["feature"]
                for path in (ROOT / "test-e2e/features").glob("*/feature.yaml")}
    feature_rows = [row for row in workbook["sheets"]["01_代码功能清单"][1:] if row and row[0]]
    feature_diffs = []
    for row in feature_rows:
        feature_id = text(row[0])
        expected = f"{text(row[1])} / {text(row[2])}: {text(row[3])}"
        if feature_id not in features or features[feature_id]["name"] != text(row[3]) or features[feature_id]["description"] != expected:
            feature_diffs.append(feature_id)
    manifest_path = source / "auto_test/implementation-manifest.json"
    old_entries = json.loads(manifest_path.read_text(encoding="utf-8"))["cases"]
    old = {entry["case_id"]: entry for entry in old_entries}
    if len(old) != len(old_entries):
        raise ValueError("Duplicate source bindings")
    scripts = []
    parsed_cache = {}
    for case_id in sorted(rows.keys() & bindings.keys()):
        entry = old.get(case_id)
        new = bindings[case_id]
        target = ROOT / "test-e2e/cases" / case_id / new["implementations"][0]["file"]
        outcome = "no_source_binding"
        source_paths = []
        if entry:
            source_paths = [source / "auto_test" / name for name in entry["implementation"]]
            for path in source_paths:
                if not path.is_file():
                    outcome = "source_file_missing"
                    continue
                outcome = direct_code(path, target, case_id, parsed_cache)
                if outcome != "different_needs_review":
                    break
                if path.suffix == ".py" and len(new["implementations"]) > 1:
                    original = path.read_text(encoding="utf-8-sig")
                    tree = ast.parse(original)
                    tests = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("test_")]
                    if len(tests) == 1 and _decorator(tests[0]):
                        decorator, _ = _decorator(tests[0])
                        transformed = _transform_helper(original, tests[0], decorator).replace(
                            "from d5.test_security_reliability_deployment import", "from d5.scenarios.scenario_security_reliability_deployment import")
                        helper = ROOT / new["implementations"][1]["file"]
                        if helper.is_file() and ast_same(transformed, helper.read_text(encoding="utf-8")):
                            outcome = "scenario_body_preserved_wrapper_requires_runtime_check"
                            break
        scripts.append({"case_id": case_id, "outcome": outcome,
                        "source_files": [path.relative_to(source).as_posix() for path in source_paths],
                        "target": target.relative_to(ROOT).as_posix(),
                        "target_sha256": digest(target),
                        "source_sha256": {path.relative_to(source).as_posix(): digest(path) for path in source_paths if path.is_file()}})
    stages = {}
    for stage in ("D1", "D2", "D3", "D4", "D5"):
        ids = {key for key in rows.keys() & cases.keys() if cases[key]["stage"] == stage}
        stages[stage] = {"source_cases": len(ids), "target_bound": len(ids & bindings.keys()),
                         "target_statuses": dict(Counter(cases[key]["case"]["status"] for key in ids)),
                         "unbound": sorted(ids - bindings.keys())}
    catalog = json.loads((source / "auto_test/case_catalog.json").read_text(encoding="utf-8"))
    catalog_rows = {row["id"]: row for group in GROUP_SHEETS for row in catalog[group]}
    catalog_drift = [key for key, (_, row) in rows.items() if key not in catalog_rows or any(
        text(value) != text(catalog_rows[key].get(field)) for field, value in row.items() if field not in {"id", "_workbook_row"})]
    source_inventory = []
    root_support = []
    for name, target_name in (("conftest.py", "nexent_formal_pytest.py"), ("pytest.ini", "pytest.ini"),
                              ("database-test-policy.json", "database-test-policy.json"),
                              ("feature-test-policy.json", "feature-test-policy.json")):
        path = source / "auto_test" / name
        target = ROOT / "test-e2e/infra/automation" / target_name
        root_support.append({"source": name, "target": target.relative_to(ROOT).as_posix(),
                             "classification": "missing" if not path.is_file() or not target.is_file()
                             else "identical" if lf(path.read_text(encoding="utf-8-sig")) == lf(target.read_text(encoding="utf-8-sig"))
                             else "changed_for_repository_runner"})
    bound_files = {name for entry in old.values() for name in entry["implementation"]}
    snapshot = json.loads((ROOT / "test-e2e/infra/migration/source-audits/v5-source-audit.json").read_text(encoding="utf-8"))
    snapshot_drift = []
    for name, receipt in snapshot["source_files"].items():
        path = source / "auto_test" / name
        if not path.is_file() or digest(path) != receipt["sha256"]:
            snapshot_drift.append(name)
    for folder in ("d1", "d2", "d3", "d4", "d5", "frontend", "shared"):
        for path in sorted((source / "auto_test" / folder).rglob("*")):
            relative = path.relative_to(source / "auto_test")
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx", ".mjs", ".json"}:
                continue
            if any(part in {"node_modules", "__pycache__", ".pytest_cache", "logs", "state", "uploads", "test-results", "runs"} for part in relative.parts):
                continue
            if any(token in path.name for token in ("sync-conflict", ".backup", ".bak")):
                continue
            name = relative.as_posix()
            counterpart = ROOT / "test-e2e/infra/automation" / ("d1/" + name if folder == "frontend" else name)
            if name in bound_files:
                state = "covered_by_case_script_comparison"
            elif counterpart.is_file():
                state = "same_support_file" if lf(path.read_text(encoding="utf-8-sig")) == lf(counterpart.read_text(encoding="utf-8-sig")) else "changed_support_file"
            else:
                state = "no_same_path_counterpart"
            source_inventory.append({"source": name, "classification": state,
                                     "target": counterpart.relative_to(ROOT).as_posix() if counterpart.is_file() else None})
    report = {
        "workbook_sha256": workbook["sha256"], "source_manifest_sha256": digest(manifest_path),
        "source_case_count": len(rows), "target_case_count": len(cases),
        "missing_source_case_ids": sorted(rows.keys() - cases.keys()),
        "repository_only_case_ids": sorted(cases.keys() - rows.keys()),
        "contract_differences": contract_diffs,
        "source_feature_count": len(feature_rows), "target_feature_count": len(features),
        "feature_differences": feature_diffs, "catalog_stale_case_ids": sorted(catalog_drift),
        "source_binding_count": len(old), "source_bound_target_unbound": sorted((old.keys() & rows.keys()) - bindings.keys()),
        "stages": stages, "script_outcomes": dict(Counter(item["outcome"] for item in scripts)),
        "scripts": scripts, "live_execution_parity_verified": False,
        "source_scripts_changed_since_migration_snapshot": snapshot_drift,
        "source_code_inventory": source_inventory,
        "source_code_inventory_counts": dict(Counter(item["classification"] for item in source_inventory)),
        "root_support": root_support,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"scripts", "stages", "source_code_inventory"}}, ensure_ascii=False, indent=2))
    return int(bool(report["missing_source_case_ids"] or contract_diffs or feature_diffs))


if __name__ == "__main__":
    raise SystemExit(main())
