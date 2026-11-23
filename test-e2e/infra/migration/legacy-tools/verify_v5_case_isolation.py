"""Verify every implemented V5 Case ID owns one unique executable file."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
from collections import defaultdict
from pathlib import Path

import yaml

from test_asset_lib import repository_root


TYPESCRIPT_CHECK = r"""
const fs = require('fs');
const ts = require(process.argv[1]);
const paths = process.argv.slice(2);
const failures = [];
for (const path of paths) {
  const code = fs.readFileSync(path, 'utf8');
  const type = path.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const parsed = ts.createSourceFile(path, code, ts.ScriptTarget.Latest, true, type);
  for (const diagnostic of parsed.parseDiagnostics)
    failures.push({path, message: ts.flattenDiagnosticMessageText(diagnostic.messageText, ' ')});
}
process.stdout.write(JSON.stringify({checked: paths.length, failures}));
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=repository_root())
    args = parser.parse_args()
    root = args.repo_root.resolve()
    manifest = yaml.safe_load((root / "test/manifests/v5-baseline.yaml").read_text(encoding="utf-8"))
    entrypoints: dict[str, list[str]] = defaultdict(list)
    auxiliary: set[Path] = set()
    for entry in manifest["cases"]:
        if entry["status"] != "implemented":
            continue
        case_id = entry["case_id"]
        implementations = entry["implementation"]
        if not implementations:
            raise SystemExit(f"No implementation for {case_id}")
        primary = implementations[0]
        entrypoints[primary["file"]].append(case_id)
        if case_id not in (root / primary["file"]).read_text(encoding="utf-8"):
            raise SystemExit(f"Case ID {case_id} missing from entrypoint {primary['file']}")
        auxiliary.update(root / item["file"] for item in implementations[1:])
    shared = {file: cases for file, cases in entrypoints.items() if len(cases) > 1}
    if shared:
        raise SystemExit(f"Shared executable entrypoints: {shared}")
    python_files = [root / path for path in entrypoints if path.endswith(".py")]
    ts_files = [root / path for path in entrypoints if path.endswith((".ts", ".tsx"))]
    for path in python_files:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for path in auxiliary:
        if path.suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    if ts_files:
        typescript = root / "frontend/node_modules/typescript"
        if not typescript.is_dir():
            raise SystemExit("TypeScript parser dependency is missing")
        completed = subprocess.run(
            ["node", "-e", TYPESCRIPT_CHECK, str(typescript), *map(str, ts_files)],
            cwd=root, capture_output=True, text=True, encoding="utf-8", check=True,
        )
        result = json.loads(completed.stdout)
        if result["failures"]:
            raise SystemExit(json.dumps(result["failures"], ensure_ascii=False))
    print(f"implemented={sum(map(len, entrypoints.values()))} unique_entrypoints={len(entrypoints)} "
          f"python_parsed={len(python_files)} typescript_parsed={len(ts_files)} "
          f"auxiliary_modules={len(auxiliary)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
