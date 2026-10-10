"""Copy formal test assets into the case-centric layout without deleting sources.

This is a one-time mechanical migration. It refuses to overwrite changed
targets. The old tree remains available for byte and collection parity checks
until the new runner is ready.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[3]
TARGET = REPO / "test-e2e"
SOURCE = REPO / "test"
IGNORED_PARTS = {"__pycache__", ".pytest_cache", "node_modules", "test-results", ".playwright-internal", "runs"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked_target(relative: str) -> Path:
    target = (TARGET / relative).resolve()
    if not target.is_relative_to(TARGET.resolve()):
        raise ValueError(f"Target escapes test-e2e: {relative}")
    return target


def put(relative: str, content: bytes, records: list[dict], source: Path | None = None) -> None:
    target = checked_target(relative)
    if target.exists():
        if target.read_bytes() != content:
            raise ValueError(f"Destination differs; refusing overwrite: {target}")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    records.append({
        "source": source.relative_to(REPO).as_posix() if source else None,
        "target": target.relative_to(REPO).as_posix(),
        "source_sha256": digest(source.read_bytes()) if source else None,
        "target_sha256": digest(content),
    })


def write_yaml(relative: str, value: dict, records: list[dict], source: Path) -> None:
    content = yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=120).encode("utf-8")
    put(relative, content, records, source)


def visible_files(prefix: str) -> list[Path]:
    command = ["git", "ls-files", "-z", "-c", "-o", "--exclude-standard", "--", prefix]
    output = subprocess.check_output(command, cwd=REPO)
    files = []
    for item in output.decode("utf-8", errors="surrogateescape").split("\0"):
        if not item:
            continue
        path = REPO / item
        if path.is_file() and not any(part in IGNORED_PARTS for part in path.parts):
            files.append(path)
    return sorted(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    args = parser.parse_args()
    if args.repo.resolve() != REPO.resolve() or not (REPO / ".git").exists():
        raise SystemExit("Migration must run in its own Nexent checkout")
    records: list[dict] = []
    features: dict[str, dict] = {}
    cases: dict[str, tuple[str, dict]] = {}
    changes: dict[str, dict] = {}

    for source in sorted((SOURCE / "features").glob("*.yaml")):
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
        for feature in document["features"]:
            feature_id = feature["feature_id"]
            if feature_id in features:
                raise ValueError(f"Duplicate Feature ID: {feature_id}")
            features[feature_id] = feature
            write_yaml(f"features/{feature_id}/feature.yaml", {
                "schema_version": document["schema_version"],
                "module": document["module"],
                "feature": feature,
            }, records, source)

    for source in sorted((SOURCE / "cases").rglob("*.yaml")):
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
        stage = document["stage"]
        for case in document["cases"]:
            case_id = case["case_id"]
            if case_id in cases:
                raise ValueError(f"Duplicate Case ID: {case_id}")
            cases[case_id] = (stage, case)
            write_yaml(f"cases/{case_id}/case.yaml", {
                "schema_version": document["schema_version"],
                "stage": stage,
                "module": document["module"],
                "case": case,
            }, records, source)

    for source in sorted((SOURCE / "changes").rglob("*.yaml")):
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
        for change in document["changes"]:
            change_id = change["change_id"]
            if change_id in changes:
                raise ValueError(f"Duplicate Change ID: {change_id}")
            changes[change_id] = change
            category = {
                "requirement": "requirements", "bugfix": "bugs",
                "refactor": "refactors", "test-fix": "test-fixes",
            }[change["change_type"]]
            write_yaml(f"changes/{category}/{change_id}.yaml", {
                "schema_version": document["schema_version"], "change": change,
            }, records, source)

    bindings: dict[str, dict] = {}
    primary_sources: set[Path] = set()
    for source in sorted((SOURCE / "manifests").glob("*.yaml")):
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
        for entry in document["cases"]:
            case_id = entry["case_id"]
            if case_id in bindings:
                raise ValueError(f"Duplicate manifest Case ID: {case_id}")
            bindings[case_id] = entry
    if set(bindings) - set(cases):
        raise ValueError(f"Unknown manifest IDs: {sorted(set(bindings)-set(cases))}")

    for case_id, entry in sorted(bindings.items()):
        implementations = entry.get("implementation", [])
        if not implementations:
            continue
        primary = implementations[0]
        source = REPO / primary["file"]
        if source in primary_sources or not source.is_file():
            raise ValueError(f"Missing or shared primary script: {source}")
        primary_sources.add(source)
        suffix = ".spec.ts" if source.name.endswith(".spec.ts") else ".test.tsx" if source.name.endswith(".test.tsx") else source.suffix
        filename = f"test{suffix}"
        content = source.read_bytes()
        if suffix == ".spec.ts":
            content = content.replace(b'from "../runner/', b'from "../../infra/automation/d4/runner/')
            content = content.replace(b"from '../../runner/", b"from '../../infra/automation/d4/runner/")
            content = content.replace(b'from "../../runner/', b'from "../../infra/automation/d4/runner/')
            content = content.replace(b'from "../pages/', b'from "../../infra/automation/d4/pages/')
            content = content.replace(b"from '../../pages/", b"from '../../infra/automation/d4/pages/")
            content = content.replace(b'from "../../pages/', b'from "../../infra/automation/d4/pages/')
            content = content.replace(b'from "../helpers/', b'from "../../infra/automation/d4/helpers/')
            content = content.replace(b"from '../../helpers/", b"from '../../infra/automation/d4/helpers/")
            content = content.replace(b'from "../../helpers/', b'from "../../infra/automation/d4/helpers/')
            content = content.replace(
                b'join(process.env.TEST_ROOT || "", "auto_test", "d4", "helpers", "seed_citation_source.py")',
                b'join(process.env.NEXENT_REPO || "", "test-e2e", "infra", "automation", "d4", "helpers", "seed_citation_source.py")',
            )
        put(f"cases/{case_id}/{filename}", content, records, source)
        implementations_out = [{
            "framework": primary["framework"],
            "file": filename,
            "selector": primary.get("selector", ""),
            **({"profiles": primary["profiles"]} if primary.get("profiles") else {}),
        }]
        for auxiliary in implementations[1:]:
            relative = Path(auxiliary["file"])
            if not (SOURCE / "automation").resolve() in (REPO / relative).resolve().parents:
                raise ValueError(f"Auxiliary path escapes formal automation: {relative}")
            implementations_out.append({
                "framework": auxiliary["framework"],
                "file": f"test-e2e/infra/automation/{relative.relative_to(Path('test/automation')).as_posix()}",
                "selector": auxiliary.get("selector", ""),
            })
        execution = {
            "schema_version": "1.0",
            "case_id": case_id,
            "implementations": implementations_out,
        }
        for key in ("required_assets", "required_mock_services", "notes"):
            if entry.get(key):
                execution[key] = entry[key]
        write_yaml(f"cases/{case_id}/execution.yaml", execution, records, SOURCE / "manifests" / "v5-baseline.yaml" if case_id.startswith(("AGT-", "API-", "CTR-", "PW-", "SEC-", "UT-", "PERF-", "DEP-")) else SOURCE / "manifests" / "chat-message-model-silent-retry.yaml")

    for source in visible_files("test/automation"):
        if source in primary_sources:
            continue
        relative = source.relative_to(SOURCE / "automation").as_posix()
        put(f"infra/automation/{relative}", source.read_bytes(), records, source)

    for prefix in ("test/mock-services", "test/compose"):
        for source in visible_files(prefix):
            if source.suffix in {".pyc", ".log"}:
                continue
            if prefix.endswith("compose"):
                relative = f"infra/mock-services/compose/{source.name}"
            else:
                relative = f"infra/mock-services/{source.relative_to(SOURCE/'mock-services').as_posix()}"
            content = source.read_bytes()
            if source.name == "deploy.py":
                content = content.replace(b"ROOT = Path(__file__).resolve().parents[2]", b"ROOT = Path(__file__).resolve().parents[3]")
            if source.name == "deployment.json":
                content = content.replace(b"test/compose/", b"test-e2e/infra/mock-services/compose/")
            put(relative, content, records, source)

    for prefix, destination in (
        ("test/schemas", "infra/schemas/legacy"),
        ("test/tools", "infra/migration/legacy-tools"),
        ("test/migration", "infra/migration/source-audits"),
    ):
        for source in visible_files(prefix):
            if source.suffix not in {".py", ".json", ".yaml", ".md"}:
                continue
            put(destination + "/" + source.relative_to(REPO / prefix).as_posix(), source.read_bytes(), records, source)

    report = {
        "schema_version": 1,
        "features": len(features), "cases": len(cases), "changes": len(changes),
        "case_statuses": dict(sorted(Counter(case["status"] for _, case in cases.values()).items())),
        "bindings": len(bindings), "primary_scripts": len(primary_sources),
        "files": records,
    }
    report_path = checked_target("infra/migration/layout-copy-report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "files"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
