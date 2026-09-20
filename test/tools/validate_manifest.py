"""Validate D1-D5 manifest bindings, selectors, and content hashes."""

from __future__ import annotations

import argparse
from pathlib import Path

from test_asset_lib import (
    LEGACY_PREFIXES,
    ValidationIssue,
    case_contract_hash,
    case_index,
    discover_documents,
    implementation_hash,
    manifest_index,
    render_issues,
    repository_root,
    require_documents,
    validate_schema_documents,
)


def validate(root: Path, allow_empty: bool = False):
    documents = discover_documents(root, "manifests")
    case_documents = discover_documents(root, "cases")
    issues = require_documents(root, "manifests", documents, allow_empty)
    issues.extend(validate_schema_documents(root, "manifests", documents))
    manifest, semantic_issues = manifest_index(documents)
    cases, case_issues = case_index(case_documents)
    issues.extend(semantic_issues)
    issues.extend(case_issues)

    for case_id, entry in manifest.items():
        if case_id not in cases:
            issues.append(ValidationIssue(root / "test/manifests", case_id, "Manifest entry references an unknown case"))
            continue
        stage, case, _ = cases[case_id]
        if entry.get("stage") != stage:
            issues.append(ValidationIssue(root / "test/manifests", case_id, f"Manifest stage {entry.get('stage')} does not match case stage {stage}"))
        expected_contract_hash = case_contract_hash(stage, case)
        if entry.get("contract_hash") != expected_contract_hash:
            issues.append(ValidationIssue(root / "test/manifests", case_id, f"Contract hash must be {expected_contract_hash}"))

        implementations = entry.get("implementation", [])
        all_files_exist = True
        for implementation in implementations:
            relative_file = implementation.get("file", "")
            if relative_file.startswith(LEGACY_PREFIXES):
                issues.append(ValidationIssue(root / "test/manifests", case_id, f"Legacy test path is not a formal implementation: {relative_file}"))
            file_path = root / relative_file
            if not file_path.is_file():
                all_files_exist = False
                issues.append(ValidationIssue(root / "test/manifests", case_id, f"Implementation file does not exist: {relative_file}"))
                continue
            selector = implementation.get("selector", "")
            if selector and selector not in file_path.read_text(encoding="utf-8", errors="replace"):
                issues.append(ValidationIssue(root / "test/manifests", case_id, f"Selector is not present in {relative_file}: {selector}"))
        if all_files_exist and implementations:
            expected_implementation_hash = implementation_hash(root, implementations)
            if entry.get("implementation_hash") != expected_implementation_hash:
                issues.append(ValidationIssue(root / "test/manifests", case_id, f"Implementation hash must be {expected_implementation_hash}"))

    for case_id, (_, case, path) in cases.items():
        requires_implementation = case.get("status") == "active" and case.get("automation") == "automated"
        if requires_implementation and case_id not in manifest:
            issues.append(ValidationIssue(path, case_id, "Active automated case has no manifest entry"))
        if requires_implementation and case_id in manifest and manifest[case_id].get("status") != "implemented":
            issues.append(ValidationIssue(path, case_id, "Active automated case must have an implemented manifest entry"))
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
    print("D1-D5 manifest is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
