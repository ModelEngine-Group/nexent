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


def validate(root: Path, allow_empty: bool = False):
    documents = discover_documents(root, "changes")
    issues = require_documents(root, "changes", documents, allow_empty)
    issues.extend(validate_schema_documents(root, "changes", documents))
    _, semantic_issues = change_index(documents)
    issues.extend(semantic_issues)
    change_root = root / "test/changes"
    for document in documents:
        relative_parts = document.path.relative_to(change_root).parts
        actual_directory = relative_parts[0] if len(relative_parts) > 1 else None
        for index, change in enumerate(document.data.get("changes", [])):
            change_type = change.get("change_type")
            expected_directory = CHANGE_DIRECTORIES.get(change_type)
            if expected_directory and actual_directory != expected_directory:
                actual_display = actual_directory or "test/changes root"
                issues.append(
                    ValidationIssue(
                        document.path,
                        f"changes/{index}/change_type",
                        f"Change type {change_type} must be stored under test/changes/{expected_directory}/, not {actual_display}",
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
