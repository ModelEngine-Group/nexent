"""Refresh selected V5 manifest contract hashes after reviewed case migration."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from test_asset_lib import case_contract_hash, case_index, discover_documents, repository_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=repository_root())
    parser.add_argument("--case-id", action="append", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    cases, issues = case_index(discover_documents(root, "cases"))
    if issues:
        raise SystemExit("Formal case index has errors")
    manifest_path = root / "test/manifests/v5-baseline.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    entries = {entry["case_id"]: entry for entry in manifest["cases"]}
    changed = []
    for case_id in args.case_id:
        if case_id not in entries or case_id not in cases:
            raise SystemExit(f"Not a migrated, bound V5 case: {case_id}")
        stage, case, path = cases[case_id]
        if path.name != "v5-baseline.yaml":
            raise SystemExit(f"Case is not owned by a V5 document: {case_id}")
        expected = case_contract_hash(stage, case)
        if entries[case_id]["contract_hash"] != expected:
            entries[case_id]["contract_hash"] = expected
            changed.append(case_id)
    if args.apply and changed:
        manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"refreshed={len(changed)} case_ids={','.join(changed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
