"""Align migrated D4 dependency inventory source paths with per-case specs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from test_asset_lib import repository_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=repository_root())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    inventory_path = root / "test/automation/d4/asset-dependencies.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    manifest = yaml.safe_load((root / "test/manifests/v5-baseline.yaml").read_text(encoding="utf-8"))
    entries = {entry["case_id"]: entry for entry in manifest["cases"]}
    changed = []
    retained = []
    for row in inventory["cases"]:
        case_id = row["case_id"]
        if case_id not in entries or entries[case_id]["status"] != "implemented":
            continue
        retained.append(row)
        primary = entries[case_id]["implementation"][0]["file"]
        if not primary.startswith("test/automation/d4/"):
            raise SystemExit(f"Unexpected D4 implementation for {case_id}: {primary}")
        relative = primary.removeprefix("test/automation/")
        digest = hashlib.sha256((root / primary).read_bytes()).hexdigest()
        if row["source"] != relative or row["source_sha256"] != digest:
            row["source"] = relative
            row["source_sha256"] = digest
            changed.append(case_id)
    removed = len(inventory["cases"]) - len(retained)
    inventory["cases"] = retained
    if args.apply and (changed or removed):
        inventory_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"dependencies={len(inventory['cases'])} aligned={len(changed)} excluded_inactive={removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
