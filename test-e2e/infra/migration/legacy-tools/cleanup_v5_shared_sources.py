"""Remove only verified copied V5 test files superseded by per-case files.

Never touches the source suite. Every removable copy must be unreferenced by
the formal manifest and byte-for-byte identical to its source-suite original.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path

import yaml

from test_asset_lib import repository_root


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=repository_root())
    parser.add_argument("--source-suite", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    source = args.source_suite.resolve()
    branch = subprocess.run(
        ["git", "-C", str(root), "branch", "--show-current"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if branch != "djb/test-baseline":
        raise SystemExit(f"Refusing cleanup on unexpected branch: {branch}")
    manifest = yaml.safe_load((root / "test/manifests/v5-baseline.yaml").read_text(encoding="utf-8"))
    bound = {item["file"] for entry in manifest["cases"] for item in entry["implementation"]}
    automation = root / "test/automation"
    candidates = (
        list(automation.glob("d[1-5]/test_*.py"))
        + list(automation.glob("d1/frontend/tests/**/*.test.tsx"))
        + list(automation.glob("d4/specs/*.spec.ts"))
    )
    removable = []
    preserved = []
    for path in candidates:
        relative = path.relative_to(root).as_posix()
        if relative in bound or path.name == "test_agt_072.py":
            continue
        tail = path.relative_to(automation)
        if tail.parts[0] == "d1" and tail.parts[1] == "frontend":
            original = source / "auto_test" / Path(*tail.parts[1:])
        else:
            original = source / "auto_test" / tail
        if not original.is_file() or _hash(path) != _hash(original):
            preserved.append(relative)
            continue
        removable.append(path)
    if args.apply:
        for path in removable:
            path.unlink()
    print(f"verified_source_copies={len(removable)} removed={len(removable) if args.apply else 0} "
          f"preserved_unmatched={len(preserved)}")
    for path in removable:
        print(path.relative_to(root).as_posix())
    for path in preserved:
        print(f"PRESERVED {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
