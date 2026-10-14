"""Check primary-script copy parity against the legacy formal source tree."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "test-e2e/infra/migration/layout-copy-report.json"


def migrated_script(source: Path, target: Path) -> bytes:
    content = source.read_bytes()
    if target.name == "test.spec.ts":
        for quote in ('"', "'"):
            for depth in ("../", "../../"):
                for part in ("runner", "pages", "helpers"):
                    before = f"from {quote}{depth}{part}/".encode()
                    after = f"from {quote}../../infra/automation/d4/{part}/".encode()
                    content = content.replace(before, after)
        content = content.replace(
            b'join(process.env.TEST_ROOT || "", "auto_test", "d4", "helpers", "seed_citation_source.py")',
            b'join(process.env.NEXENT_REPO || "", "test-e2e", "infra", "automation", "d4", "helpers", "seed_citation_source.py")',
        )
    return content


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT,
                        help="Repository or archive root containing the old test directory")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    source_cache: dict[Path, dict] = {}
    semantic_counts = {"features": 0, "cases": 0, "changes": 0}
    semantic_differences = []
    for item in data["files"]:
        target = ROOT / item["target"]
        source = source_root / item["source"] if item["source"] else None
        category = next((name for name in semantic_counts
                         if item["target"].startswith(f"test-e2e/{name}/")
                         and target.name in {"feature.yaml", "case.yaml"}), None)
        if item["target"].startswith("test-e2e/changes/") and target.suffix == ".yaml":
            category = "changes"
        if category is None or source is None:
            continue
        if not source.is_file() or not target.is_file():
            semantic_differences.append(item["target"])
            continue
        if source not in source_cache:
            source_cache[source] = yaml.safe_load(source.read_text(encoding="utf-8"))
        old = source_cache[source]
        new = yaml.safe_load(target.read_text(encoding="utf-8"))
        if category == "features":
            original = next((entry for entry in old["features"]
                             if entry["feature_id"] == new["feature"]["feature_id"]), None)
            matching = (original == new["feature"] and old["module"] == new["module"])
        elif category == "cases":
            original = next((entry for entry in old["cases"]
                             if entry["case_id"] == new["case"]["case_id"]), None)
            matching = (original == new["case"] and old["stage"] == new["stage"]
                        and old["module"] == new["module"])
        else:
            original = next((entry for entry in old["changes"]
                             if entry["change_id"] == new["change"]["change_id"]), None)
            matching = original == new["change"]
        if not matching:
            semantic_differences.append(item["target"])
        semantic_counts[category] += 1
    if semantic_differences:
        print(f"{len(semantic_differences)} Feature/Case/change documents differ from source")
        for path in semantic_differences[:30]:
            print(path)
        return 1
    print("Structured-asset migration parity passed: " + ", ".join(
        f"{count} {name}" for name, count in semantic_counts.items()))
    scripts = [item for item in data["files"]
               if item["target"].startswith("test-e2e/cases/")
               and Path(item["target"]).name.startswith("test.")]
    differences = []
    for item in scripts:
        source, target = source_root / item["source"], ROOT / item["target"]
        if not source.is_file() or not target.is_file() or migrated_script(source, target) != target.read_bytes():
            differences.append(item["target"])
    if differences:
        print(f"{len(differences)} primary scripts differ from their declared source transformation")
        for path in differences[:30]:
            print(path)
        return 1
    print(f"Primary-script migration parity passed: {len(scripts)} unique scripts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
