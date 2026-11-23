"""Cross-check D4 workbook rows, formal cases, manifest, and actual Journey calls."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import yaml
from openpyxl import load_workbook

from migrate_v5_cases import clauses, text
from test_asset_lib import repository_root


JOURNEY = re.compile(r'\bjourney\("(?P<id>[A-Z][A-Z0-9-]+)"')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=repository_root())
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    workbook = load_workbook(args.workbook.resolve(), read_only=True, data_only=True)
    source_rows = [row for row in list(workbook["03_Playwright_Journey"].values)[1:] if row and row[0]]
    source = {text(row[0]): row for row in source_rows}
    if len(source) != len(source_rows):
        raise SystemExit("Duplicate Journey IDs in V5 workbook")
    formal_document = yaml.safe_load((root / "test/cases/d4/v5-baseline.yaml").read_text(encoding="utf-8"))
    formal = {case["case_id"]: case for case in formal_document["cases"]}
    if set(source) != set(formal):
        raise SystemExit(f"Workbook/formal ID mismatch: source_only={sorted(set(source)-set(formal))} "
                         f"formal_only={sorted(set(formal)-set(source))}")
    text_mismatches = []
    for case_id, row in source.items():
        case = formal[case_id]
        if case["title"] != text(row[2]) or case["priority"] != text(row[3]):
            text_mismatches.append(case_id + ": title or priority")
        if [step["action"] for step in case["steps"]] != clauses(row[11]):
            text_mismatches.append(case_id + ": UI steps")
        if case["expected_results"] != clauses(row[12]):
            text_mismatches.append(case_id + ": expected assertions")
    if text_mismatches:
        raise SystemExit("V5 workbook text was not preserved: " + ", ".join(text_mismatches))
    manifest = yaml.safe_load((root / "test/manifests/v5-baseline.yaml").read_text(encoding="utf-8"))
    bound = {entry["case_id"]: entry for entry in manifest["cases"] if entry["stage"] == "D4" and entry["status"] == "implemented"}
    script_ids = []
    for path in (root / "test/automation/d4/specs").rglob("*.spec.ts"):
        script_ids.extend(match.group("id") for match in JOURNEY.finditer(path.read_text(encoding="utf-8")))
    duplicates = [case_id for case_id, count in Counter(script_ids).items() if count != 1]
    if duplicates or set(script_ids) != set(bound):
        raise SystemExit(f"Script/manifest mismatch: duplicate={duplicates} "
                         f"script_only={sorted(set(script_ids)-set(bound))} manifest_only={sorted(set(bound)-set(script_ids))}")
    by_status = {status: sorted(case_id for case_id, case in formal.items() if case["status"] == status)
                 for status in sorted({case["status"] for case in formal.values()})}
    report = {
        "schema_version": 1,
        "raw_workbook_rows": len(source),
        "current_scope_excluding_retired": sum(case["status"] != "retired" for case in formal.values()),
        "fixed_playwright_scripts": len(script_ids),
        "status_counts": {status: len(ids) for status, ids in by_status.items()},
        "non_executable_ids": {status: ids for status, ids in by_status.items() if status != "active"},
        "workbook_title_steps_assertions_exact": True,
        "script_ids_match_implemented_manifest": True,
        "semantic_assertion_parity_verified": False,
    }
    if args.output:
        output = args.output.resolve()
        if not output.is_relative_to(root / "test/migration"):
            raise SystemExit("Output must stay within test/migration")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
