"""Audit D1-D5 migration against the workbook, not the old manifest alone."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import yaml
from openpyxl import load_workbook

from migrate_v5_cases import GROUP_SHEETS, clauses, legacy_fields, text, workbook_cases
from test_asset_lib import repository_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=repository_root())
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    workbook_path = args.workbook.resolve()
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    source = workbook_cases(workbook)
    catalog = json.loads(args.catalog.resolve().read_text(encoding="utf-8"))
    formal = {}
    for stage in ("D1", "D2", "D3", "D4", "D5"):
        document = yaml.safe_load((root / f"test/cases/{stage.lower()}/v5-baseline.yaml").read_text(encoding="utf-8"))
        for case in document["cases"]:
            if case["case_id"] in formal:
                raise SystemExit(f"Duplicate formal Case ID: {case['case_id']}")
            formal[case["case_id"]] = case
    manifest_document = yaml.safe_load((root / "test/manifests/v5-baseline.yaml").read_text(encoding="utf-8"))
    bound = {entry["case_id"]: entry for entry in manifest_document["cases"] if entry["status"] == "implemented"}
    source_by_id = {row["id"]: (group, row) for group in GROUP_SHEETS for row in source[group]}
    if len(source_by_id) != sum(len(source[group]) for group in GROUP_SHEETS):
        raise SystemExit("Duplicate workbook Case IDs")
    if set(source_by_id) != set(formal):
        raise SystemExit(f"Workbook/formal IDs differ: source_only={sorted(set(source_by_id)-set(formal))} "
                         f"formal_only={sorted(set(formal)-set(source_by_id))}")
    text_mismatch = []
    stale_catalog = []
    catalog_by_id = {row["id"]: row for group in GROUP_SHEETS for row in catalog[group]}
    if set(catalog_by_id) != set(source_by_id):
        raise SystemExit("Workbook/catalog Case IDs differ")
    for case_id, (group, row) in source_by_id.items():
        case = formal[case_id]
        title, before, actions, expected, _, _ = legacy_fields(row, group)
        if case["title"] != title or case["priority"] != text(row.get("优先级")):
            text_mismatch.append(case_id + ": title/priority")
        if case["preconditions"] != clauses(before):
            text_mismatch.append(case_id + ": preconditions")
        if [step["action"] for step in case["steps"]] != (clauses(actions) or [title or case_id]):
            text_mismatch.append(case_id + ": steps")
        if case["expected_results"] != (clauses(expected) or [title or case_id]):
            text_mismatch.append(case_id + ": expected_results")
        old = catalog_by_id[case_id]
        if any(text(row.get(key)) != text(old.get(key))
               for key in row if key not in {"id", "stage", "_workbook_row"}):
            stale_catalog.append(case_id)
    if text_mismatch:
        raise SystemExit("Workbook/formal text mismatch: " + ", ".join(text_mismatch))
    executable = {case_id for case_id, case in formal.items()
                  if case["status"] == "active" and case["automation"] == "automated"}
    if executable != set(bound):
        raise SystemExit(f"Executable/manifest IDs differ: no_binding={sorted(executable-set(bound))} "
                         f"unexpected_binding={sorted(set(bound)-executable)}")
    primary = [entry["implementation"][0]["file"] for entry in bound.values()]
    if len(primary) != len(set(primary)):
        raise SystemExit("Multiple Case IDs share one primary test script")
    if any(not (root / path).is_file() for path in primary):
        raise SystemExit("A primary test script is missing")
    stage_rows = {}
    for stage in ("D1", "D2", "D3", "D4", "D5"):
        cases = [case for case in formal.values() if source_by_id[case["case_id"]][1]["stage"] == stage]
        stage_rows[stage] = {
            "workbook_rows": len(cases),
            "current_scope_excluding_retired": sum(case["status"] != "retired" for case in cases),
            "implemented": sum(case["case_id"] in bound for case in cases),
            "status_counts": dict(sorted(Counter(case["status"] for case in cases).items())),
            "not_executable_ids": sorted(case["case_id"] for case in cases if case["case_id"] not in bound),
        }
    report = {
        "schema_version": 1,
        "source_workbook_sha256": hashlib.sha256(workbook_path.read_bytes()).hexdigest(),
        "workbook_rows": len(source_by_id),
        "implemented": len(bound),
        "unique_primary_scripts": len(set(primary)),
        "stale_old_catalog_case_ids": sorted(stale_catalog),
        "stages": stage_rows,
        "workbook_identity_steps_expected_preconditions_exact": True,
        "script_identity_binding_verified": True,
        "script_behavior_parity_verified": False,
    }
    if args.output:
        output = args.output.resolve()
        if not output.is_relative_to(root / "test/migration"):
            raise SystemExit("Output must stay inside test/migration")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "stages"}, ensure_ascii=False, indent=2))
    for stage, row in stage_rows.items():
        print(stage, row["workbook_rows"], row["current_scope_excluding_retired"], row["implemented"], row["status_counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
