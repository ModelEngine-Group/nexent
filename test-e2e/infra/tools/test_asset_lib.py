"""Shared loading, hashing, and validation for formal Nexent test assets."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml
from jsonschema import Draft202012Validator


ASSET_DIRECTORIES = {
    "features": Path("test-e2e/features"),
    "cases": Path("test-e2e/cases"),
    "changes": Path("test-e2e/changes"),
    "manifests": Path("test-e2e/cases"),
}
SCHEMA_FILES = {
    "features": "feature.schema.json",
    "cases": "test-case.schema.json",
    "changes": "change.schema.json",
    "manifests": "d1-d5-manifest.schema.json",
}
LEGACY_PREFIXES = ("test/backend/", "test/sdk/", "test/ext_components/")
WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
SQL_PATH = re.compile(r"(?:^|[/\\])[^/\\]+\.sql$", re.IGNORECASE)


@dataclass(frozen=True)
class AssetDocument:
    path: Path
    data: dict[str, Any]


@dataclass(frozen=True)
class ValidationIssue:
    path: Path
    location: str
    message: str

    def render(self, root: Path) -> str:
        try:
            display_path = self.path.relative_to(root).as_posix()
        except ValueError:
            display_path = self.path.as_posix()
        suffix = f":{self.location}" if self.location else ""
        return f"{display_path}{suffix}: {self.message}"


def repository_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists() and (candidate / "test-e2e").exists():
            return candidate
    raise ValueError(f"Cannot locate repository root from {current}")


def load_structured_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        value = json.loads(text)
    else:
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError("The document root must be an object")
    return value


def discover_documents(root: Path, kind: str) -> list[AssetDocument]:
    directory = root / ASSET_DIRECTORIES[kind]
    if not directory.exists():
        return []
    if kind == "features":
        paths = sorted(directory.glob("*/feature.yaml"))
    elif kind == "cases":
        paths = sorted(directory.glob("*/case.yaml"))
    elif kind == "changes":
        paths = sorted(directory.glob("*/*.yaml"))
    else:
        paths = sorted(directory.glob("*/execution.yaml"))
    documents: list[AssetDocument] = []
    for path in paths:
        raw = load_structured_file(path)
        if kind == "features":
            if set(raw) != {"schema_version", "module", "feature"}:
                raise ValueError(f"Unexpected feature wrapper fields: {path}")
            data = {"schema_version": raw["schema_version"], "module": raw["module"], "features": [raw["feature"]]}
        elif kind == "cases":
            if set(raw) != {"schema_version", "stage", "module", "case"}:
                raise ValueError(f"Unexpected case wrapper fields: {path}")
            data = {"schema_version": raw["schema_version"], "stage": raw["stage"],
                    "module": raw["module"], "cases": [raw["case"]]}
        elif kind == "changes":
            if set(raw) != {"schema_version", "change"}:
                raise ValueError(f"Unexpected change wrapper fields: {path}")
            data = {"schema_version": raw["schema_version"], "changes": [raw["change"]]}
        else:
            case_path = path.with_name("case.yaml")
            case_document = load_structured_file(case_path)
            case = case_document["case"]
            implementations = []
            for index, item in enumerate(raw.get("implementations", [])):
                name = item["file"]
                if index == 0:
                    resolved = (path.parent / name).resolve()
                    if resolved.parent != path.parent.resolve():
                        raise ValueError(f"Primary script must be inside its case directory: {path}")
                    relative = resolved.relative_to(root.resolve()).as_posix()
                else:
                    resolved = (root / name).resolve()
                    if not resolved.is_relative_to((root / "test-e2e/infra").resolve()):
                        raise ValueError(f"Shared implementation escapes infra: {path}")
                    relative = resolved.relative_to(root.resolve()).as_posix()
                implementations.append({"framework": item["framework"], "file": relative,
                                        "selector": item.get("selector", ""),
                                        **({"profiles": item["profiles"]} if item.get("profiles") else {})})
            stage = case_document["stage"]
            entry = {"case_id": raw["case_id"], "stage": stage, "status": "implemented",
                     "contract_hash": case_contract_hash(stage, case),
                     "implementation_hash": implementation_hash(root, implementations)
                     if implementations and all((root / part["file"]).is_file() for part in implementations) else "",
                     "implementation": implementations}
            for key in ("required_assets", "required_mock_services", "notes"):
                if key in raw:
                    entry[key] = raw[key]
            data = {"schema_version": "1.0", "cases": [entry]}
        documents.append(AssetDocument(path=path, data=data))
    return documents


def schema_validator(root: Path, kind: str) -> Draft202012Validator:
    schema_path = root / "test-e2e/infra/schemas/legacy" / SCHEMA_FILES[kind]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_schema_documents(root: Path, kind: str, documents: Iterable[AssetDocument]) -> list[ValidationIssue]:
    validator = schema_validator(root, kind)
    issues: list[ValidationIssue] = []
    for document in documents:
        for error in sorted(validator.iter_errors(document.data), key=lambda item: list(item.absolute_path)):
            location = "/".join(str(part) for part in error.absolute_path)
            issues.append(ValidationIssue(document.path, location, error.message))
    return issues


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_value(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_json(value)).hexdigest()}"


def case_contract_hash(stage: str, case: dict[str, Any]) -> str:
    return sha256_value({"stage": stage, "case": case})


def implementation_hash(root: Path, implementations: list[dict[str, Any]]) -> str:
    fingerprints = []
    for implementation in sorted(implementations, key=lambda item: (item["file"], item["selector"])):
        path = root / implementation["file"]
        # Git text files may be checked out as CRLF on Windows and LF on Linux.
        digest = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        fingerprints.append({"file": implementation["file"], "sha256": digest})
    return sha256_value(fingerprints)


def feature_index(documents: Iterable[AssetDocument]) -> tuple[dict[str, dict[str, Any]], dict[str, str], list[ValidationIssue]]:
    features: dict[str, dict[str, Any]] = {}
    rules: dict[str, str] = {}
    issues: list[ValidationIssue] = []
    for document in documents:
        for index, feature in enumerate(document.data.get("features", [])):
            feature_id = feature.get("feature_id")
            if document.path.parent.name != feature_id:
                issues.append(ValidationIssue(document.path, "feature_id", "Feature folder name must equal Feature ID"))
            if feature_id in features:
                issues.append(ValidationIssue(document.path, f"features/{index}/feature_id", f"Duplicate feature ID {feature_id}"))
            else:
                features[feature_id] = feature
            for rule_index, rule in enumerate(feature.get("business_rules", [])):
                rule_id = rule.get("rule_id")
                if rule_id in rules:
                    issues.append(ValidationIssue(document.path, f"features/{index}/business_rules/{rule_index}/rule_id", f"Duplicate business rule ID {rule_id}"))
                else:
                    rules[rule_id] = feature_id
    return features, rules, issues


def case_index(documents: Iterable[AssetDocument]) -> tuple[dict[str, tuple[str, dict[str, Any], Path]], list[ValidationIssue]]:
    cases: dict[str, tuple[str, dict[str, Any], Path]] = {}
    issues: list[ValidationIssue] = []
    for document in documents:
        stage = document.data.get("stage")
        for index, case in enumerate(document.data.get("cases", [])):
            case_id = case.get("case_id")
            if document.path.parent.name != case_id:
                issues.append(ValidationIssue(document.path, "case_id", "Case folder name must equal Case ID"))
            if case_id in cases:
                issues.append(ValidationIssue(document.path, f"cases/{index}/case_id", f"Duplicate case ID {case_id}"))
            else:
                cases[case_id] = (stage, case, document.path)
            issues.extend(_validate_portable_case(document.path, index, case))
            step_orders = [step.get("order") for step in case.get("steps", [])]
            if step_orders != list(range(1, len(step_orders) + 1)):
                issues.append(
                    ValidationIssue(
                        document.path,
                        f"cases/{index}/steps",
                        "Step order must be unique, consecutive, and start at 1",
                    )
                )
            profile_names = [profile.get("name") for profile in case.get("execution", {}).get("profiles", [])]
            if len(profile_names) != len(set(profile_names)):
                issues.append(
                    ValidationIssue(
                        document.path,
                        f"cases/{index}/execution/profiles",
                        "Execution profile names must be unique",
                    )
                )
            status = case.get("status")
            automation = case.get("automation")
            if status == "manual" and automation != "manual":
                issues.append(ValidationIssue(document.path, f"cases/{index}", "Manual cases must use automation=manual"))
            if status == "skipped_by_policy" and automation != "not_applicable":
                issues.append(
                    ValidationIssue(
                        document.path,
                        f"cases/{index}",
                        "Policy-skipped cases must use automation=not_applicable",
                    )
                )
            if status == "active" and automation == "not_applicable":
                issues.append(
                    ValidationIssue(
                        document.path,
                        f"cases/{index}",
                        "Active cases cannot use automation=not_applicable",
                    )
                )
            if stage == "D5" and case.get("type") != case.get("risk_type"):
                issues.append(
                    ValidationIssue(
                        document.path,
                        f"cases/{index}/risk_type",
                        "D5 type and risk_type must match",
                    )
                )
    return cases, issues


def change_index(documents: Iterable[AssetDocument]) -> tuple[dict[str, dict[str, Any]], list[ValidationIssue]]:
    changes: dict[str, dict[str, Any]] = {}
    issues: list[ValidationIssue] = []
    for document in documents:
        for index, change in enumerate(document.data.get("changes", [])):
            change_id = change.get("change_id")
            if change_id in changes:
                issues.append(ValidationIssue(document.path, f"changes/{index}/change_id", f"Duplicate change ID {change_id}"))
            else:
                changes[change_id] = change
    return changes, issues


def manifest_index(documents: Iterable[AssetDocument]) -> tuple[dict[str, dict[str, Any]], list[ValidationIssue]]:
    manifest: dict[str, dict[str, Any]] = {}
    issues: list[ValidationIssue] = []
    for document in documents:
        for index, entry in enumerate(document.data.get("cases", [])):
            case_id = entry.get("case_id")
            if case_id in manifest:
                issues.append(ValidationIssue(document.path, f"cases/{index}/case_id", f"Duplicate manifest case ID {case_id}"))
            else:
                manifest[case_id] = entry
    return manifest, issues


def _validate_portable_case(path: Path, index: int, case: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    stack: list[tuple[str, Any]] = [("", case)]
    while stack:
        location, value = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                normalized_key = re.sub(r"([a-z])([A-Z])", r"\1_\2", key).lower().replace("-", "_")
                secret_field = any(token in normalized_key for token in ("password", "secret", "api_key", "token_value")) or normalized_key in {"token", "access_token", "refresh_token", "id_token", "authorization"}
                reference = isinstance(child, dict) and set(child) == {"asset_ref"} and isinstance(child["asset_ref"], str) and bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", child["asset_ref"]))
                if secret_field and not reference:
                    issues.append(ValidationIssue(path, f"cases/{index}/{location}/{key}", "Secret-shaped fields are not allowed in formal test data"))
                stack.append((f"{location}/{key}", child))
        elif isinstance(value, list):
            stack.extend((f"{location}/{child_index}", child) for child_index, child in enumerate(value))
        elif isinstance(value, str):
            normalized = value.replace("\\", "/")
            if WINDOWS_ABSOLUTE.match(value) or normalized.startswith(("/home/", "/root/", "/tmp/", "/Users/", "//")):
                issues.append(ValidationIssue(path, f"cases/{index}/{location}", "Developer- or runner-local absolute paths are not allowed"))
            if SQL_PATH.search(value):
                issues.append(ValidationIssue(path, f"cases/{index}/{location}", "Business tests must not depend on SQL file paths"))
    return issues


def require_documents(root: Path, kind: str, documents: list[AssetDocument], allow_empty: bool) -> list[ValidationIssue]:
    if documents or allow_empty:
        return []
    return [ValidationIssue(root / ASSET_DIRECTORIES[kind], "", f"No {kind} documents found")]


def render_issues(root: Path, issues: Iterable[ValidationIssue]) -> str:
    return "\n".join(issue.render(root) for issue in issues)
