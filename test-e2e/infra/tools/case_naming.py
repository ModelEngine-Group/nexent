# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Require readable new Case IDs while preserving frozen historical identifiers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator

from test_asset_lib import ValidationIssue


NEW_CASE_ID = re.compile(
    r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+-(?P<stage>D[1-5])-(?!000)[0-9]{3}"
)
LEGACY_CATALOG = Path("test-e2e/infra/config/case-naming-legacy.json")
LEGACY_SCHEMA = Path("test-e2e/infra/schemas/case-naming-legacy.schema.json")
FROZEN_CATALOG_SHA256 = "aba2812fb4517c30acc3de33523771397e47fc8ac04ca3fac2bb96228e9d81b2"


def naming_issues(root: Path, cases: dict) -> list[ValidationIssue]:
    """Validate all Cases without Git access, rewriting assets, or learning new exemptions."""
    catalog_path = root / LEGACY_CATALOG
    try:
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
        schema = json.loads((root / LEGACY_SCHEMA).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return [ValidationIssue(catalog_path, "", "Cannot read frozen Case naming catalog or its schema")]
    errors = list(Draft202012Validator(schema).iter_errors(raw))
    if errors:
        return [ValidationIssue(catalog_path, "", "Invalid frozen Case naming catalog: " + errors[0].message)]
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if digest != FROZEN_CATALOG_SHA256:
        return [ValidationIssue(catalog_path, "", "Frozen Case naming catalog differs from its reviewed baseline")]
    legacy = set(raw["case_ids"])
    if any(NEW_CASE_ID.fullmatch(case_id) for case_id in legacy):
        return [ValidationIssue(catalog_path, "case_ids", "Only historical nonstandard IDs belong in the frozen naming catalog")]
    issues = []
    for case_id, (stage, case, path) in cases.items():
        if case_id in legacy:
            continue
        match = NEW_CASE_ID.fullmatch(case_id) if isinstance(case_id, str) else None
        if not match:
            issues.append(ValidationIssue(
                path, "case_id",
                "New Case ID must use <MODULE>-<SCENARIO>-D1..D5-<001..999>; "
                "preserve existing IDs, do not add new naming exemptions",
            ))
        elif match["stage"] != stage:
            issues.append(ValidationIssue(path, "stage", "Case ID stage must match the declared stage"))
        title = case.get("title")
        if isinstance(title, str) and not title.strip():
            issues.append(ValidationIssue(path, "title", "New Case title must describe a scenario and expected behavior, not whitespace"))
    return issues
