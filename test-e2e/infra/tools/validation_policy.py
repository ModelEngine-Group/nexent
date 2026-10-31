# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Classify only explicitly typed, safely scoped Daily asset problems."""
from __future__ import annotations

CASE_CODES = {"CASE_EXECUTION_MISSING", "CASE_SCRIPT_MISSING", "CASE_SELECTOR_MISSING", "CASE_PREPARATION_MISSING"}
WARNING_CODES = {"UT_REFERENCE_MISSING", "DERIVED_VIEW_STALE", "FEATURE_RESPONSIBILITY_UNRESOLVED"}
CASE_WARNING_CODES = {"CASE_RESPONSIBILITY_UNRESOLVED"}


def report(root, issues, records):
    known = {record["case_id"] for record in records}
    rows = []
    for issue in issues:
        severity = "FATAL"
        if issue.code in WARNING_CODES and issue.case_id is None:
            severity = "WARNING"
        elif issue.code in CASE_WARNING_CODES and issue.case_id in known:
            severity = "WARNING"
        elif issue.code in CASE_CODES and issue.case_id in known:
            severity = "CASE_BLOCKED"
        rows.append({"code": issue.code, "severity": severity, "case_id": issue.case_id,
                     "location": issue.location, "detail": issue.render(root)})
    return {"schema_version": 1, "ready": not any(row["severity"] == "FATAL" for row in rows),
            "status": "INVALID" if any(row["severity"] == "FATAL" for row in rows)
            else "INCOMPLETE" if rows else "VALID", "issues": rows,
            "blocked_cases": sorted({row["case_id"] for row in rows if row["severity"] == "CASE_BLOCKED"})}


def apply_blocks(records, validation):
    if not validation["ready"]:
        raise ValueError("Global or unclassified asset validation failure")
    blocked = set(validation["blocked_cases"])
    return [{**record, "execution": None, "asset_blocked": True} if record["case_id"] in blocked
            else dict(record) for record in records]


def evaluate(root):
    from validate_execution import inspect
    from validate_test_assets import validate

    issues = validate(root, "implementation", False, daily=True)
    execution_issues, registry = inspect(root)
    issues = list(dict.fromkeys([*issues, *execution_issues]))
    validation = report(root, issues, registry["cases"])
    return validation, apply_blocks(registry["cases"], validation)
