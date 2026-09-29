"""Validate case-local execution metadata and build the derived registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from jsonschema import Draft202012Validator

from test_asset_lib import (
    ValidationIssue, case_index, discover_documents, implementation_hash,
    render_issues, repository_root, case_contract_hash,
)


FRAMEWORKS = {"pytest", "vitest", "playwright", "custom"}
EXECUTION_FIELDS = {"schema_version", "case_id", "implementations", "required_assets", "required_mock_services", "notes", "preparation"}
IMPLEMENTATION_FIELDS = {"framework", "file", "selector", "profiles"}


def inspect(root: Path, phase: str = "implementation") -> tuple[list[ValidationIssue], dict]:
    cases, issues = case_index(discover_documents(root, "cases"))
    entries = {}
    entrypoints: dict[str, str] = {}
    for case_id, (stage, case, case_path) in sorted(cases.items()):
        execution_path = case_path.with_name("execution.yaml")
        record = {
            "case_id": case_id, "feature_id": case.get("feature_id"), "stage": stage,
            "status": case.get("status"), "automation": case.get("automation"),
            "contract_hash": case_contract_hash(stage, case), "execution": None,
        }
        entries[case_id] = record
        if not execution_path.is_file():
            if phase == "implementation" and case.get("status") == "active" and case.get("automation") == "automated":
                issues.append(ValidationIssue(case_path, case_id, "Active automated case has no execution.yaml"))
            continue
        raw = __import__("yaml").safe_load(execution_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or set(raw) - EXECUTION_FIELDS or raw.get("schema_version") != "1.0":
            issues.append(ValidationIssue(execution_path, "", "Invalid execution document fields or version"))
            continue
        if raw.get("case_id") != case_id:
            issues.append(ValidationIssue(execution_path, "case_id", "Execution Case ID differs from its directory"))
        if case.get("status") in {"retired", "skipped_by_policy", "manual"}:
            issues.append(ValidationIssue(execution_path, "", "Inactive or manual case must not have executable metadata"))
        implementations = raw.get("implementations")
        if not isinstance(implementations, list) or not implementations:
            issues.append(ValidationIssue(execution_path, "implementations", "At least one implementation is required"))
            continue
        normalized = []
        for index, item in enumerate(implementations):
            if not isinstance(item, dict) or set(item) - IMPLEMENTATION_FIELDS or not {"framework", "file", "selector"}.issubset(item):
                issues.append(ValidationIssue(execution_path, f"implementations/{index}", "Invalid implementation fields"))
                continue
            if item["framework"] not in FRAMEWORKS or not isinstance(item["file"], str) or not isinstance(item["selector"], str):
                issues.append(ValidationIssue(execution_path, f"implementations/{index}", "Invalid framework, file or selector"))
                continue
            if index == 0:
                resolved = (execution_path.parent / item["file"]).resolve()
                allowed = resolved.parent == execution_path.parent.resolve()
            else:
                resolved = (root / item["file"]).resolve()
                allowed = resolved.is_relative_to((root / "test-e2e/infra").resolve())
            if not allowed or not resolved.is_relative_to(root.resolve()):
                issues.append(ValidationIssue(execution_path, f"implementations/{index}", "Script path escapes its allowed directory"))
                continue
            if not resolved.is_file():
                issues.append(ValidationIssue(execution_path, f"implementations/{index}", "Implementation file does not exist"))
                continue
            content = resolved.read_text(encoding="utf-8", errors="replace")
            if index == 0 and item["selector"] not in content:
                issues.append(ValidationIssue(execution_path, f"implementations/{index}", "Primary script lacks its selector"))
            relative = resolved.relative_to(root).as_posix()
            if index == 0:
                previous = entrypoints.setdefault(relative, case_id)
                if previous != case_id:
                    issues.append(ValidationIssue(execution_path, relative, f"Primary script is also owned by {previous}"))
            normalized.append({"framework": item["framework"], "file": relative,
                               "selector": item["selector"],
                               **({"profiles": item["profiles"]} if item.get("profiles") else {})})
        if normalized and len(normalized) == len(implementations):
            record["execution"] = {
                "implementations": normalized,
                "implementation_hash": implementation_hash(root, normalized),
                "required_assets": raw.get("required_assets", []),
                "required_mock_services": raw.get("required_mock_services", []),
            }
            if "preparation" in raw:
                schema = json.loads((root / "test-e2e/infra/schemas/preparation.schema.json").read_text(encoding="utf-8"))
                errors = list(Draft202012Validator(schema).iter_errors(raw["preparation"]))
                if errors:
                    issues.append(ValidationIssue(execution_path, "preparation", "Invalid preparation declaration"))
                else:
                    record["execution"]["preparation"] = raw["preparation"]
    registry = {"schema_version": "1.0", "cases": [entries[key] for key in sorted(entries)]}
    return issues, registry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--phase", choices=("design", "implementation"), default="implementation")
    parser.add_argument("--write-registry", action="store_true")
    args = parser.parse_args()
    root = repository_root(args.root)
    issues, registry = inspect(root, args.phase)
    if issues:
        print(render_issues(root, issues))
        return 1
    if args.write_registry:
        output = root / "test-e2e/infra/generated/registry.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Execution metadata valid: {len(registry['cases'])} cases, "
          f"{sum(bool(item['execution']) for item in registry['cases'])} implementations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
