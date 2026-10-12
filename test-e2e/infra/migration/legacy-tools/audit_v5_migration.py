"""Inventory the external V5 baseline before copying formal test assets.

This is deliberately read-only with respect to the source suite. It records
identities and hashes, never machine configuration values or credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

from migrate_v5_cases import workbook_cases, text


CASE_GROUPS = ("main_cases", "journeys", "special_cases")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def audit(source_root: Path) -> dict:
    source_root = source_root.resolve()
    baseline = source_root / "cases/Nexent_Develop_每日真实资产测试基线_v5.xlsx"
    auto_root = source_root / "auto_test"
    catalog = read_json(auto_root / "case_catalog.json")
    manifest = read_json(auto_root / "implementation-manifest.json")
    policy_path = source_root / "config/test-policy.yaml"
    if not baseline.is_file() or not policy_path.is_file():
        raise ValueError("Canonical V5 workbook or test policy is missing")
    baseline_hash = digest(baseline)
    if catalog.get("source_sha256", "").lower() != baseline_hash:
        raise ValueError("case_catalog.json does not match the canonical V5 workbook")

    workbook = load_workbook(baseline, read_only=True, data_only=True)
    feature_rows = [row for row in list(workbook.worksheets[1].values)[1:] if row and row[0]]
    feature_ids = {str(row[0]) for row in feature_rows}
    if len(feature_ids) != len(feature_rows):
        raise ValueError("Duplicate Feature IDs in V5 workbook")
    workbook_groups = workbook_cases(workbook)
    cases = [case for group in CASE_GROUPS for case in workbook_groups[group]]
    case_ids = [str(case["id"]) for case in cases]
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("Duplicate Case IDs in V5 workbook")
    catalog_by_id = {case["id"]: case for group in CASE_GROUPS for case in catalog[group]}
    if set(catalog_by_id) != set(case_ids):
        raise ValueError("V5 workbook/catalog Case IDs differ")
    catalog_content_drift = sorted(
        case["id"] for case in cases
        if any(text(case.get(key)) != text(catalog_by_id[case["id"]].get(key))
               for key in case if key not in {"id", "stage", "_workbook_row"})
    )
    bindings = manifest["cases"]
    binding_ids = [str(entry["case_id"]) for entry in bindings]
    if len(set(binding_ids)) != len(binding_ids):
        raise ValueError("Duplicate Case IDs in implementation manifest")

    case_by_id = {case["id"]: case for case in cases}
    binding_by_id = {entry["case_id"]: entry for entry in bindings}
    source_files: dict[str, dict] = {}
    for entry in bindings:
        for relative in entry["implementation"]:
            path = (auto_root / relative).resolve()
            if not path.is_relative_to(auto_root.resolve()) or not path.is_file():
                raise ValueError(f"Missing or out-of-tree implementation: {relative}")
            source_files[relative] = {"sha256": digest(path), "bytes": path.stat().st_size}

    asset_manifest_path = source_root / "assets/manifest.json"
    asset_manifest = read_json(asset_manifest_path)
    assets = []
    for item in asset_manifest.get("assets", []):
        relative = str(item["path"])
        path = (source_root / "assets" / relative).resolve()
        if not path.is_relative_to((source_root / "assets").resolve()):
            raise ValueError(f"Out-of-tree static asset: {relative}")
        exists = path.is_file()
        size = path.stat().st_size if exists else None
        assets.append({
            "asset_id": item["asset_id"],
            "path": relative,
            "exists": exists,
            "bytes": size,
            "sha256_matches": exists and digest(path) == item.get("sha256"),
            "migration_class": "large_file" if size is not None and size > 1_000_000 else "static_review",
        })

    missing = sorted(set(case_ids) - set(binding_ids))
    return {
        "schema_version": 1,
        "source": {
            "baseline_sha256": baseline_hash,
            "catalog_sha256": digest(auto_root / "case_catalog.json"),
            "manifest_sha256": digest(auto_root / "implementation-manifest.json"),
            "policy_sha256": digest(policy_path),
        },
        "counts": {
            "features": len(feature_rows),
            "cases": len(cases),
            "cases_by_stage": dict(sorted(Counter(case["stage"] for case in cases).items())),
            "bound_cases": len(bindings),
            "unique_implementation_files": len(source_files),
            "static_assets": len(assets),
        },
        "catalog_content_drift_ids": catalog_content_drift,
        "missing_bindings": [{"case_id": case_id, "stage": case_by_id[case_id]["stage"]} for case_id in missing],
        "orphan_bindings": sorted(set(binding_ids) - set(case_ids)),
        "missing_feature_links": sorted(
            case["id"] for case in catalog["main_cases"]
            if not case.get("功能ID") or str(case["功能ID"]) not in feature_ids
        ),
        "source_files": source_files,
        "assets": assets,
        "source_sync_conflicts": sorted(
            str(path.relative_to(source_root)).replace("\\", "/")
            for base in (source_root / "cases", auto_root)
            for path in base.rglob("*sync-conflict*") if path.is_file()
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(args.source_root)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
