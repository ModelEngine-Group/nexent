"""Refresh V5 manifest hashes for one explicitly changed implementation file."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from test_asset_lib import implementation_hash, repository_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=repository_root())
    parser.add_argument("--file", required=True, help="Repository-relative implementation path")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    source = (root / args.file).resolve()
    if not source.is_file() or not source.is_relative_to(root / "test/automation"):
        raise SystemExit("Implementation must be an existing test/automation file")
    relative = source.relative_to(root).as_posix()
    manifest_path = root / "test/manifests/v5-baseline.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    changed = []
    for entry in manifest["cases"]:
        if not any(item["file"] == relative for item in entry["implementation"]):
            continue
        expected = implementation_hash(root, entry["implementation"])
        if entry["implementation_hash"] == expected:
            continue
        entry["implementation_hash"] = expected
        changed.append(entry["case_id"])
    if args.apply and changed:
        manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"file={relative} refreshed={len(changed)} case_ids={','.join(changed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
