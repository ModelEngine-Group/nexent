"""Validate feature, rule, change, case, and stage traceability."""

from __future__ import annotations

import argparse
from pathlib import Path

from test_asset_lib import ValidationIssue, case_index, change_index, discover_documents, feature_index, render_issues, repository_root


def validate(root: Path, allow_empty: bool = False):
    feature_documents = discover_documents(root, "features")
    case_documents = discover_documents(root, "cases")
    change_documents = discover_documents(root, "changes")
    features, rules, issues = feature_index(feature_documents)
    cases, case_issues = case_index(case_documents)
    _, change_issues = change_index(change_documents)
    issues.extend(case_issues)
    issues.extend(change_issues)

    if not allow_empty and (not features or not cases):
        if not features:
            issues.append(ValidationIssue(root / "test/features", "", "Traceability requires at least one feature"))
        if not cases:
            issues.append(ValidationIssue(root / "test/cases", "", "Traceability requires at least one case"))

    covered_stages: dict[str, set[str]] = {feature_id: set() for feature_id in features}
    for case_id, (stage, case, path) in cases.items():
        feature_id = case.get("feature_id")
        if feature_id not in features:
            issues.append(ValidationIssue(path, case_id, f"Unknown feature ID {feature_id}"))
            continue
        if case.get("status") != "retired":
            covered_stages[feature_id].add(stage)
        for rule_id in case.get("business_rule_ids", []):
            if rule_id not in rules:
                issues.append(ValidationIssue(path, case_id, f"Unknown business rule ID {rule_id}"))
            elif rules[rule_id] != feature_id:
                issues.append(ValidationIssue(path, case_id, f"Business rule {rule_id} belongs to feature {rules[rule_id]}, not {feature_id}"))

    for feature_id, feature in features.items():
        if feature.get("status") != "active":
            continue
        missing = set(feature.get("required_test_stages", [])) - covered_stages[feature_id]
        if missing:
            issues.append(ValidationIssue(root / "test/features", feature_id, f"Missing required case stages: {', '.join(sorted(missing))}"))

    for document in change_documents:
        for index, change in enumerate(document.data.get("changes", [])):
            for state, ids in change.get("affected_features", {}).items():
                for feature_id in ids:
                    if feature_id not in features:
                        issues.append(ValidationIssue(document.path, f"changes/{index}/affected_features/{state}", f"Unknown feature ID {feature_id}"))
            for state, ids in change.get("affected_cases", {}).items():
                for case_id in ids:
                    if case_id not in cases:
                        issues.append(ValidationIssue(document.path, f"changes/{index}/affected_cases/{state}", f"Unknown case ID {case_id}"))
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
    print("Formal test asset traceability is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
