"""Copy canonical fixed V5 sources and create the repository manifest.

Only exact code/config support files are copied. Source runs, machine settings,
secrets, sync conflicts, historical backups, and Legacy UT are excluded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

import yaml
from openpyxl import load_workbook

from migrate_v5_cases import CASE_GROUPS, workbook_cases
from test_asset_lib import case_contract_hash, case_index, discover_documents, implementation_hash, repository_root


COPY_ROOTS = ("d1", "d2", "d3", "d4", "d5", "frontend", "shared")
COPY_SUFFIXES = {".py", ".ts", ".tsx", ".json", ".mjs"}
ROOT_SUPPORT = ("conftest.py", "pytest.ini", "database-test-policy.json", "feature-test-policy.json")
EXCLUDED_NAMES = ("sync-conflict", ".backup-", ".bak-")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def destination(relative: Path) -> Path:
    if relative.parts[0] == "frontend":
        return Path("test/automation/d1") / relative
    return Path("test/automation") / relative


def source_files(auto_root: Path) -> dict[Path, Path]:
    files: dict[Path, Path] = {}
    for root_name in COPY_ROOTS:
        for path in (auto_root / root_name).rglob("*"):
            if not path.is_file() or path.suffix not in COPY_SUFFIXES:
                continue
            relative = path.relative_to(auto_root)
            if any(part in {"__pycache__", ".pytest_cache", "node_modules", "logs", "state", "uploads"} for part in relative.parts):
                continue
            if any(token in path.name for token in EXCLUDED_NAMES):
                continue
            files[relative] = destination(relative)
    for name in ROOT_SUPPORT:
        files[Path(name)] = Path("test/automation") / name
    return files


def build_manifest(repo_root: Path, old_manifest: dict) -> tuple[dict, dict]:
    cases, case_issues = case_index(discover_documents(repo_root, "cases"))
    if case_issues:
        raise ValueError("Formal case IDs are invalid or duplicated")
    old = {entry["case_id"]: entry for entry in old_manifest["cases"]}
    entries = []
    excluded = []
    for case_id, (stage, case, _) in sorted(cases.items()):
        if case.get("source", {}).get("legacy_sheet") is None:
            continue
        if case.get("status") != "active" or case.get("automation") != "automated":
            excluded.append(case_id)
            continue
        if case_id not in old:
            raise ValueError(f"Active V5 case has no old implementation binding: {case_id}")
        source = old[case_id]
        if source["stage"] != stage:
            raise ValueError(f"Stage drift in source manifest: {case_id}")
        implementations = []
        for name in source["implementation"]:
            target = destination(Path(name)).as_posix()
            framework = "pytest" if name.endswith(".py") else "vitest" if name.endswith(".tsx") else "playwright"
            implementations.append({"framework": framework, "file": target, "selector": source["selector"]})
        entries.append({
            "case_id": case_id,
            "stage": stage,
            "status": "implemented",
            "contract_hash": case_contract_hash(stage, case),
            "implementation_hash": implementation_hash(repo_root, implementations),
            "implementation": implementations,
            "notes": "V5 source binding migrated; runtime parity is not yet certified.",
        })
    return {"schema_version": "1.0", "cases": entries}, {
        "migrated_bindings": len(entries),
        "not_bound_due_to_case_status": len(excluded),
        "excluded_case_ids": excluded,
        "by_stage": dict(sorted(Counter(entry["stage"] for entry in entries).items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=repository_root())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    repo_root = args.repo_root.resolve()
    auto_root = source_root / "auto_test"
    catalog = json.loads((auto_root / "case_catalog.json").read_text(encoding="utf-8"))
    baseline = source_root / "cases/Nexent_Develop_每日真实资产测试基线_v5.xlsx"
    if catalog.get("source_sha256", "").lower() != digest(baseline):
        raise SystemExit("Source V5 workbook and catalog are not the same snapshot")
    workbook = load_workbook(baseline, read_only=True, data_only=True)
    canonical = workbook_cases(workbook)
    canonical_ids = {case["id"] for group in CASE_GROUPS for case in canonical[group]}
    catalog_ids = {case["id"] for group in CASE_GROUPS for case in catalog[group]}
    if canonical_ids != catalog_ids:
        raise SystemExit("Source V5 workbook and catalog Case IDs differ")
    old_manifest = json.loads((auto_root / "implementation-manifest.json").read_text(encoding="utf-8"))
    unknown_bindings = {entry["case_id"] for entry in old_manifest["cases"]} - canonical_ids
    if unknown_bindings:
        raise SystemExit(f"Old manifest binds IDs absent from V5 workbook: {sorted(unknown_bindings)}")
    files = source_files(auto_root)
    referenced = {Path(name) for entry in old_manifest["cases"] for name in entry["implementation"]}
    if not referenced.issubset(files):
        raise SystemExit(f"Referenced files are not in the copy allowlist: {sorted(str(x) for x in referenced - set(files))}")
    for relative, target in files.items():
        source = auto_root / relative
        output = repo_root / target
        if not source.is_file():
            raise SystemExit(f"Source support file is missing: {relative}")
        if output.exists() and digest(output) != digest(source):
            raise SystemExit(f"Destination exists with different content: {target}")
    manifest_path = repo_root / "test/manifests/v5-baseline.yaml"
    if args.apply and manifest_path.exists():
        raise SystemExit(f"Formal migration manifest already exists: {manifest_path}")
    if args.apply:
        for relative, target in files.items():
            output = repo_root / target
            if output.exists():
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(auto_root / relative, output)
        formal_manifest, summary = build_manifest(repo_root, old_manifest)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(yaml.safe_dump(formal_manifest, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    else:
        summary = {"referenced_bindings": len(old_manifest["cases"])}
    print(json.dumps({"copied_source_files": len(files), **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
