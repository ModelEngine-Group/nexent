"""Split a directly marked V5 pytest module into one file per Case ID.

This mechanical pass handles modules whose test functions each carry an exact
``pytest.mark.case_id`` decorator. Parametrized scenario modules need a
separate, behavior-reviewed transformation and are intentionally rejected.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
from pathlib import Path

import yaml

from test_asset_lib import implementation_hash, repository_root


def marked_case_id(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        name = decorator.func
        if isinstance(name, ast.Attribute) and name.attr == "case_id" and decorator.args:
            value = decorator.args[0]
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
    return None


def split_source(source: str) -> dict[str, str]:
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    tests = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")]
    if not tests:
        raise ValueError("No top-level pytest functions found")
    identifiers = [marked_case_id(node) for node in tests]
    if any(identifier is None for identifier in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError("Every test function must have one unique literal case_id marker")
    for node in tests:
        if any(isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
               and decorator.func.attr == "parametrize" for decorator in node.decorator_list):
            raise ValueError("Parametrized pytest modules require a dedicated split strategy")
    result = {}
    for selected, identifier in zip(tests, identifiers, strict=True):
        omitted = set()
        for node in tests:
            if node is selected:
                continue
            start = min([node.lineno] + [decorator.lineno for decorator in node.decorator_list])
            omitted.update(range(start, node.end_lineno + 1))
        result[identifier] = "".join(line for number, line in enumerate(lines, start=1) if number not in omitted)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=repository_root())
    parser.add_argument("--file", type=Path, required=True, help="Repository-relative shared pytest module")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    source_path = (root / args.file).resolve()
    automation_root = root / "test/automation"
    if not source_path.is_relative_to(automation_root) or not source_path.is_file():
        raise SystemExit("This pass accepts only existing automation pytest modules")
    stage = source_path.relative_to(automation_root).parts[0]
    if stage not in {"d1", "d2", "d3", "d4", "d5"}:
        raise SystemExit("Source must be inside a D1-D5 stage")
    stage_root = automation_root / stage
    pieces = split_source(source_path.read_text(encoding="utf-8"))
    manifest_path = root / "test/manifests/v5-baseline.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    relative_file = source_path.relative_to(root).as_posix()
    owners = {entry["case_id"]: entry for entry in manifest["cases"]
              if any(item["file"] == relative_file for item in entry["implementation"])}
    if not set(owners).issubset(pieces):
        raise SystemExit(f"Source/manifest Case ID mismatch: code={sorted(pieces)}, manifest={sorted(owners)}")
    extra = set(pieces) - set(owners)
    if extra:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        skipped = {
            marked_case_id(node)
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == "skip" for decorator in node.decorator_list)
        }
        if not extra.issubset(skipped):
            raise SystemExit(f"Unbound tests must be explicitly skipped: {sorted(extra - skipped)}")
    outputs = {
        identifier: stage_root / "cases" / f"test_{identifier.lower().replace('-', '_')}.py"
        for identifier in pieces
    }
    for path in outputs.values():
        if path.exists():
            raise SystemExit(f"Refusing to overwrite existing split file: {path}")
    if args.apply:
        (stage_root / "cases").mkdir(parents=True, exist_ok=True)
        for identifier, path in outputs.items():
            content = pieces[identifier]
            ast.parse(content)
            path.write_text(content, encoding="utf-8")
            if identifier not in owners:
                continue
            entry = owners[identifier]
            entry["implementation"] = [{
                "framework": "pytest",
                "file": path.relative_to(root).as_posix(),
                "selector": identifier,
            }]
            entry["implementation_hash"] = implementation_hash(root, entry["implementation"])
        manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"source={args.file.as_posix()} cases={len(pieces)}")
    print("case_ids=" + ",".join(sorted(pieces)))
    print("source_sha256=" + hashlib.sha256(source_path.read_bytes()).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
