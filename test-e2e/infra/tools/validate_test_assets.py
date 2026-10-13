"""Validate the case-centric formal test assets and their generated views."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import generate_excel
import generate_feature_links
import validate_cases
import validate_changes
import validate_execution
import validate_features
import validate_traceability
from test_asset_lib import ValidationIssue, case_index, change_index, discover_documents, render_issues, repository_root


def validate(root: Path, phase: str, regenerate: bool,
             require_acceptance_cases: list[str] | None = None,
             require_ut_changes: list[str] | None = None) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    issues.extend(validate_features.validate(root))
    issues.extend(validate_cases.validate(root))
    issues.extend(validate_changes.validate(root))
    issues.extend(validate_traceability.validate(root))
    changes, _ = change_index(discover_documents(root, "changes"))
    for change_id in require_ut_changes or []:
        if change_id not in changes:
            issues.append(ValidationIssue(root / "test-e2e/changes", change_id, "Selected UT Change does not exist"))
        elif "traditional_ut" not in changes[change_id]:
            issues.append(ValidationIssue(root / "test-e2e/changes", change_id, "Current product Change requires traditional_ut assessment"))
    for change_id, change in changes.items():
        if "traditional_ut" in change:
            issues.extend(ValidationIssue(root / "test-e2e/changes", change_id, problem)
                          for problem in validate_changes.traditional_ut_issues(root, change["traditional_ut"], phase))
    if require_acceptance_cases:
        cases, _ = case_index(discover_documents(root, "cases"))
        for case_id in require_acceptance_cases:
            if case_id not in cases:
                issues.append(ValidationIssue(root / "test-e2e/cases", case_id, "Selected acceptance Case does not exist"))
            else:
                _, case, path = cases[case_id]
                if not case.get("acceptance"):
                    issues.append(ValidationIssue(path, "acceptance", "Current-change Case requires explicit acceptance obligations"))
    execution_issues, registry = validate_execution.inspect(root, phase)
    issues.extend(execution_issues)
    if issues:
        return issues
    for path, expected in generate_feature_links.expected_pages(root).items():
        if regenerate:
            path.write_text(expected, encoding="utf-8")
        elif not path.is_file() or path.read_text(encoding="utf-8") != expected:
            issues.append(ValidationIssue(path, "", "Generated Feature navigation is missing or stale"))
    registry_path = root / "test-e2e/infra/generated/registry.json"
    expected_registry = json.dumps(registry, ensure_ascii=False, indent=2) + "\n"
    if regenerate:
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(expected_registry, encoding="utf-8")
    elif registry_path.is_file() and registry_path.read_text(encoding="utf-8") != expected_registry:
        issues.append(ValidationIssue(registry_path, "", "Generated execution registry is stale"))
    excel_path = root / "test-e2e/infra/generated/Nexent_测试基线.xlsx"
    if regenerate:
        generate_excel.write_workbook(root, excel_path)
    else:
        with tempfile.TemporaryDirectory() as temporary_directory:
            expected = Path(temporary_directory) / "expected.xlsx"
            generate_excel.write_workbook(root, expected)
            if excel_path.is_file() and generate_excel.workbook_snapshot(expected) != generate_excel.workbook_snapshot(excel_path):
                issues.append(ValidationIssue(excel_path, "", "Generated Excel view is stale"))
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--phase", choices=("design", "implementation"), default="implementation")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--require-acceptance-case", action="append", default=[], metavar="CASE_ID",
                        help="Require obligation metadata for an added or acceptance-modified Case; repeat per Case")
    parser.add_argument("--require-ut-change", action="append", default=[], metavar="CHANGE_ID",
                        help="Require traditional UT assessment for a current product Change; repeat per Change")
    args = parser.parse_args()
    root = repository_root(args.root)
    issues = validate(root, args.phase, args.generate, args.require_acceptance_case, args.require_ut_change)
    if issues:
        print(render_issues(root, issues))
        print(f"Case-centric validation failed with {len(issues)} issue(s).")
        return 1
    print("Case-centric formal test asset validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
