"""Validate formal Nexent D1-D5 case documents."""

from __future__ import annotations

import argparse
from pathlib import Path

from acceptance_integrity import contract_issues
from test_asset_lib import ValidationIssue, case_index, discover_documents, render_issues, repository_root, require_documents, validate_schema_documents


def validate(root: Path, allow_empty: bool = False):
    documents = discover_documents(root, "cases")
    issues = require_documents(root, "cases", documents, allow_empty)
    issues.extend(validate_schema_documents(root, "cases", documents))
    cases, semantic_issues = case_index(documents)
    issues.extend(semantic_issues)
    for _, case, path in cases.values():
        issues.extend(ValidationIssue(path, "acceptance", problem) for problem in contract_issues(case))
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
    print("D1-D5 case assets are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
