"""Split multi-journey D4 spec files into one spec per Case ID."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from test_asset_lib import implementation_hash, repository_root


JOURNEY = re.compile(r'^journey\("(?P<id>[A-Z][A-Z0-9-]+)"', re.MULTILINE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=repository_root())
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    path = (root / args.file).resolve()
    specs = root / "test/automation/d4/specs"
    if path.parent != specs or not path.is_file() or not path.name.endswith(".spec.ts"):
        raise SystemExit("Expected a top-level D4 Playwright spec")
    source = path.read_text(encoding="utf-8")
    matches = list(JOURNEY.finditer(source))
    if len(matches) < 2:
        raise SystemExit("Expected at least two top-level journey calls")
    identifiers = [match.group("id") for match in matches]
    if len(identifiers) != len(set(identifiers)):
        raise SystemExit("Duplicate journey ID")
    manifest_path = root / "test/manifests/v5-baseline.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    source_relative = path.relative_to(root).as_posix()
    owners = {entry["case_id"]: entry for entry in manifest["cases"]
              if any(item["file"] == source_relative for item in entry["implementation"])}
    if not set(owners).issubset(identifiers):
        raise SystemExit(f"Source/manifest mismatch: code={identifiers}, manifest={sorted(owners)}")
    extra = set(identifiers) - set(owners)
    if extra:
        cases = yaml.safe_load((root / "test/cases/d4/v5-baseline.yaml").read_text(encoding="utf-8"))
        statuses = {item["case_id"]: item["status"] for item in cases["cases"]}
        if any(statuses.get(case_id) == "active" or case_id not in statuses for case_id in extra):
            raise SystemExit(f"Unbound active or unknown Journey IDs: {sorted(extra)}")
    preamble = source[:matches[0].start()]
    outputs = {}
    for position, match in enumerate(matches):
        case_id = match.group("id")
        if case_id not in owners:
            continue
        end = matches[position + 1].start() if position + 1 < len(matches) else len(source)
        code = preamble + source[match.start():end]
        if [item.group("id") for item in JOURNEY.finditer(code)] != [case_id]:
            raise SystemExit(f"Split did not isolate {case_id}")
        destination = specs / f"{case_id.lower()}.spec.ts"
        if destination.exists():
            raise SystemExit(f"Refusing to overwrite {destination}")
        outputs[case_id] = (destination, code)
    if args.apply:
        for case_id, (destination, code) in outputs.items():
            destination.write_text(code, encoding="utf-8")
            implementation = [{
                "framework": "playwright",
                "file": destination.relative_to(root).as_posix(),
                "selector": case_id,
            }]
            entry = owners[case_id]
            entry["implementation"] = implementation
            entry["implementation_hash"] = implementation_hash(root, implementation)
        manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"source={source_relative} cases={len(outputs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
