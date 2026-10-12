"""Run the complete formal Nexent test-asset validation gate."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import generate_excel
import validate_cases
import validate_changes
import validate_features
import validate_manifest
import validate_traceability
from test_asset_lib import ValidationIssue, render_issues, repository_root


def validate_excel_view(root: Path, allow_empty: bool = False):
    output = root / "test/generated/Nexent_测试基线.xlsx"
    if not output.is_file():
        if allow_empty:
            return []
        return [ValidationIssue(output, "", "Generated Excel view is missing")]
    with tempfile.TemporaryDirectory() as temporary_directory:
        expected = Path(temporary_directory) / "expected.xlsx"
        generate_excel.write_workbook(root, expected)
        if generate_excel.workbook_snapshot(expected) != generate_excel.workbook_snapshot(output):
            return [ValidationIssue(output, "", "Generated Excel view is stale or manually modified")]
    return []


def validate(root: Path, allow_empty: bool = False, phase: str = "implementation", generate_excel_view: bool = False):
    issues = []
    issues.extend(validate_features.validate(root, allow_empty))
    issues.extend(validate_cases.validate(root, allow_empty))
    issues.extend(validate_changes.validate(root, allow_empty))
    issues.extend(validate_traceability.validate(root, allow_empty))
    if phase == "implementation":
        issues.extend(validate_manifest.validate(root, allow_empty))
    if generate_excel_view and not issues:
        output = root / "test/generated/Nexent_测试基线.xlsx"
        generate_excel.write_workbook(root, output)
    issues.extend(validate_excel_view(root, allow_empty))
    unique = {(issue.path, issue.location, issue.message): issue for issue in issues}
    return list(unique.values())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--allow-empty", action="store_true", help="Permit an empty phase-2 repository before formal assets are migrated")
    parser.add_argument("--phase", choices=("design", "implementation"), default="implementation")
    parser.add_argument("--generate-excel", action="store_true", help="Regenerate the deterministic Excel view after source validation succeeds")
    args = parser.parse_args()
    root = repository_root(args.root)
    issues = validate(root, args.allow_empty, args.phase, args.generate_excel)
    if issues:
        print(render_issues(root, issues))
        print(f"Formal test asset validation failed with {len(issues)} issue(s).")
        return 1
    print("Formal test asset validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
