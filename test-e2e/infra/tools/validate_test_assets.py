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
from test_asset_lib import ValidationIssue, render_issues, repository_root


def validate(root: Path, phase: str, regenerate: bool) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    issues.extend(validate_features.validate(root))
    issues.extend(validate_cases.validate(root))
    issues.extend(validate_changes.validate(root))
    issues.extend(validate_traceability.validate(root))
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
    args = parser.parse_args()
    root = repository_root(args.root)
    issues = validate(root, args.phase, args.generate)
    if issues:
        print(render_issues(root, issues))
        print(f"Case-centric validation failed with {len(issues)} issue(s).")
        return 1
    print("Case-centric formal test asset validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
