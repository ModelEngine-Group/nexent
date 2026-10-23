"""Validate formal Nexent test-asset change records."""

from __future__ import annotations

import argparse
from pathlib import Path

from test_asset_lib import (
    ValidationIssue,
    change_index,
    discover_documents,
    render_issues,
    repository_root,
    require_documents,
    validate_schema_documents,
)


CHANGE_DIRECTORIES = {
    "requirement": "requirements",
    "bugfix": "bugs",
    "refactor": "refactors",
    "test-fix": "test-fixes",
}


def traditional_ut_issues(root: Path, plan: object, phase: str) -> list[str]:
    """Check UT intent/selectors, not execution or whether an exemption is justified."""
    if not isinstance(plan, dict):
        return ["Current product change requires a traditional_ut responsibility record"]
    issues = []
    if not isinstance(plan.get("decision"), str) or plan["decision"] not in {"reuse", "strengthen", "add", "exempt"}:
        issues.append("Invalid traditional_ut decision")
    if not isinstance(plan.get("reason"), str) or not plan["reason"].strip():
        issues.append("traditional_ut requires a rationale; unavailable execution is not an exemption")
    if plan.get("decision") == "exempt":
        if plan.get("test_selectors"):
            issues.append("A UT exemption cannot also declare selected tests")
        return issues
    if not plan.get("behaviors"):
        issues.append("traditional_ut must identify unit behaviors or regressions")
    selectors = plan.get("test_selectors", [])
    if not isinstance(selectors, list) or any(not isinstance(value, str) for value in selectors):
        return issues + ["traditional_ut test_selectors must be a list of reported repository selectors"]
    if phase == "implementation" and not selectors:
        issues.append("Confirm actual traditional UT selectors after implementation")
    allowed = [root / "test" / name for name in ("backend", "sdk", "ext_components")]
    allowed.append(root / "frontend")
    for selector in selectors:
        filename = selector.split("::", 1)[0]
        path = (root / filename).resolve()
        if not filename or not any(path.is_relative_to(directory.resolve()) for directory in allowed):
            issues.append("UT selector must stay in traditional test/ or frontend/, never test-e2e or a local absolute path")
        elif Path(filename).is_absolute() or ":" in filename or "\\" in filename:
            issues.append("UT selectors must use repository-relative forward-slash paths")
        elif phase == "implementation" and not path.is_file():
            issues.append(f"Traditional UT file does not exist: {filename}")
    return issues


def validate(root: Path, allow_empty: bool = False):
    documents = discover_documents(root, "changes")
    issues = require_documents(root, "changes", documents, allow_empty)
    issues.extend(validate_schema_documents(root, "changes", documents))
    _, semantic_issues = change_index(documents)
    issues.extend(semantic_issues)
    change_root = root / "test-e2e/changes"
    for document in documents:
        relative_parts = document.path.relative_to(change_root).parts
        actual_directory = relative_parts[0] if len(relative_parts) > 1 else None
        for index, change in enumerate(document.data.get("changes", [])):
            change_type = change.get("change_type")
            expected_directory = CHANGE_DIRECTORIES.get(change_type)
            if expected_directory and actual_directory != expected_directory:
                actual_display = actual_directory or "test-e2e/changes root"
                issues.append(
                    ValidationIssue(
                        document.path,
                        f"changes/{index}/change_type",
                        f"Change type {change_type} must be stored under test-e2e/changes/{expected_directory}/, not {actual_display}",
                    )
                )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--allow-empty", action="store_true")
    args = parser.parse_args()
    root = repository_root(args.root)
    issues = validate(root, args.allow_empty)
    if issues:
        print(render_issues(root, issues))
        return 1
    print("Change assets are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
