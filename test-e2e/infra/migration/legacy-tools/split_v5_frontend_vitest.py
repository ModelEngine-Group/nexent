"""Split shared V5 frontend Vitest modules by formal Case ID.

Uses the product's installed TypeScript parser so nested JSX and callbacks are
not divided by fragile textual brace matching.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import yaml

from test_asset_lib import implementation_hash, repository_root


PARSER = r"""
const fs = require('fs');
const ts = require(process.argv[1]);
const path = process.argv[2];
const source = fs.readFileSync(path, 'utf8');
const tree = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const result = { header: [], groups: [] };
for (const statement of tree.statements) {
  const expression = statement.expression;
  if (ts.isExpressionStatement(statement) && ts.isCallExpression(expression)
      && expression.expression.getText(tree) === 'describe') {
    const callback = expression.arguments[1];
    if (!callback || !callback.body || !ts.isBlock(callback.body)) throw new Error('Unsupported describe block');
    result.groups.push({
      title: expression.arguments[0].getText(tree),
      code: statement.getText(tree),
      items: callback.body.statements.map(item => item.getText(tree))
    });
  } else {
    result.header.push(statement.getFullText(tree));
  }
}
process.stdout.write(JSON.stringify(result));
"""


def parsed_module(root: Path, path: Path) -> dict:
    typescript = root / "frontend/node_modules/typescript"
    if not typescript.is_dir():
        raise SystemExit("Product frontend TypeScript dependency is required for safe AST splitting")
    completed = subprocess.run(
        ["node", "-e", PARSER, str(typescript), str(path)],
        cwd=root, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return json.loads(completed.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=repository_root())
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    path = (root / args.file).resolve()
    tests_root = root / "test/automation/d1/frontend/tests"
    if not path.is_relative_to(tests_root) or not path.is_file() or not path.name.endswith(".test.tsx"):
        raise SystemExit("Expected a D1 frontend Vitest TSX file")
    source_relative = path.relative_to(root).as_posix()
    manifest_path = root / "test/manifests/v5-baseline.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    owners = {entry["case_id"]: entry for entry in manifest["cases"]
              if any(item["file"] == source_relative for item in entry["implementation"])}
    if len(owners) < 2:
        raise SystemExit("Source must bind multiple formal cases")
    parsed = parsed_module(root, path)
    header = "".join(parsed["header"]).strip() + "\n\n"
    outputs: dict[str, str] = {}
    if len(parsed["groups"]) == 1 and len(owners) > 2:
        group = parsed["groups"][0]
        for item in group["items"]:
            identifiers = [identifier for identifier in owners if identifier in item]
            if len(identifiers) != 1:
                raise SystemExit(f"Expected exactly one Case ID in Vitest assertion: {identifiers}")
            identifier = identifiers[0]
            outputs[identifier] = header + f"describe({group['title']}, () => {{\n  {item}\n}});\n"
    else:
        current = None
        groups: dict[str, list[str]] = {identifier: [] for identifier in owners}
        for group in parsed["groups"]:
            explicit = [identifier for identifier in owners if identifier in group["code"]]
            if len(explicit) > 1:
                raise SystemExit(f"A describe group contains multiple formal IDs: {explicit}")
            if explicit:
                current = explicit[0]
            if current is None:
                raise SystemExit("A describe group precedes its formal Case ID")
            groups[current].append(group["code"])
        outputs = {identifier: header + "\n\n".join(chunks) + "\n" for identifier, chunks in groups.items() if chunks}
    if set(outputs) != set(owners):
        raise SystemExit(f"Case mapping mismatch: outputs={sorted(outputs)}, manifest={sorted(owners)}")
    destinations = {identifier: path.parent / f"case_{identifier.lower().replace('-', '_')}.test.tsx" for identifier in outputs}
    if any(destination.exists() for destination in destinations.values()):
        raise SystemExit("Refusing to overwrite existing per-case Vitest file")
    if args.apply:
        for identifier, code in outputs.items():
            destination = destinations[identifier]
            destination.write_text(code, encoding="utf-8")
            implementation = [{
                "framework": "vitest",
                "file": destination.relative_to(root).as_posix(),
                "selector": identifier,
            }]
            entry = owners[identifier]
            entry["implementation"] = implementation
            entry["implementation_hash"] = implementation_hash(root, implementation)
        manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"source={source_relative} cases={len(outputs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
