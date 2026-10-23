"""Split a V5 parametrized scenario into per-case pytest entrypoints.

The original behavior becomes a non-collected scenario helper. Each collected
file owns exactly one Case ID; its manifest hash covers both the entrypoint
and the shared scenario implementation. No test assertions are rewritten.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

import yaml

from test_asset_lib import implementation_hash, repository_root


def _decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[ast.Call, str] | None:
    for item in node.decorator_list:
        if not isinstance(item, ast.Call) or not isinstance(item.func, ast.Attribute):
            continue
        if item.func.attr != "parametrize" or len(item.args) != 2:
            continue
        call = item.args[1]
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            continue
        if call.func.id not in {"case_params", "special_case_params"}:
            continue
        return item, call.func.id
    return None


def _transform_helper(source: str, node: ast.FunctionDef | ast.AsyncFunctionDef, decorator: ast.Call) -> str:
    lines = source.splitlines(keepends=True)
    if decorator.lineno != decorator.end_lineno:
        raise ValueError("Multiline parameter decorator needs a reviewed split")
    lines[decorator.lineno - 1] = ""
    definition = lines[node.lineno - 1]
    expected = f"def {node.name}("
    if expected not in definition:
        raise ValueError(f"Unexpected definition layout for {node.name}")
    lines[node.lineno - 1] = definition.replace(expected, f"def execute_{node.name[5:]}(", 1)
    result = "".join(lines)
    ast.parse(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=repository_root())
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    path = (root / args.file).resolve()
    if not path.is_file() or not path.is_relative_to(root / "test/automation"):
        raise SystemExit("Source must be an automation Python file")
    stage = path.relative_to(root / "test/automation").parts[0]
    if stage not in {"d3", "d5"}:
        raise SystemExit("This splitter covers D3 and D5 parameterized scenarios")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    tests = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")]
    if len(tests) != 1:
        raise SystemExit("Source must have exactly one top-level test function")
    node = tests[0]
    selected = _decorator(node)
    if selected is None or not isinstance(node, ast.AsyncFunctionDef):
        raise SystemExit("Source must have one async test using case_params or special_case_params")
    param_decorator, param_factory = selected
    if not node.args.args or node.args.args[0].arg != "case":
        raise SystemExit("First argument must be the case parameter")
    args_names = [item.arg for item in node.args.args]
    if node.args.posonlyargs or node.args.kwonlyargs or node.args.vararg or node.args.kwarg:
        raise SystemExit("Complex test signature requires manual review")

    manifest_path = root / "test/manifests/v5-baseline.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    old_relative = path.relative_to(root).as_posix()
    owners = {entry["case_id"]: entry for entry in manifest["cases"]
              if any(item["file"] == old_relative for item in entry["implementation"])}
    if len(owners) < 2:
        raise SystemExit("Source must bind multiple implemented cases")

    stem = path.stem.removeprefix("test_")
    helper = root / "test/automation" / stage / "scenarios" / f"scenario_{stem}.py"
    helper_relative = helper.relative_to(root).as_posix()
    helper_code = _transform_helper(source, node, param_decorator)
    if stage == "d5" and stem in {"security_special", "reliability_deployment_special"}:
        helper_code = helper_code.replace(
            "from d5.test_security_reliability_deployment import",
            "from d5.scenarios.scenario_security_reliability_deployment import",
        )
    outputs: dict[str, tuple[Path, str]] = {}
    for case_id in sorted(owners):
        destination = root / "test/automation" / stage / "cases" / f"test_{case_id.lower().replace('-', '_')}.py"
        function = f"test_{case_id.lower().replace('-', '_')}"
        call = ", ".join(args_names)
        params = f'case_params("{stage.upper()}", ["{case_id}"])' if param_factory == "case_params" else f'special_case_params(["{case_id}"])'
        code = (
            f'"""V5 {case_id} independently collected scenario."""\n\n'
            "import pytest\n"
            f"from {stage}.scenarios import scenario_{stem} as scenario\n"
            f"from shared.cases import {param_factory}\n\n"
            f'@pytest.mark.parametrize("case", {params})\n'
            "@pytest.mark.asyncio\n"
            f"async def {function}({call}):\n"
            f"    await scenario.execute_{node.name[5:]}({call})\n"
        )
        ast.parse(code)
        outputs[case_id] = (destination, code)
    if helper.exists() or any(destination.exists() for destination, _ in outputs.values()):
        raise SystemExit("Refusing to overwrite existing helper or per-case entrypoint")
    if args.apply:
        helper.parent.mkdir(parents=True, exist_ok=True)
        helper.write_text(helper_code, encoding="utf-8")
        for case_id, (destination, code) in outputs.items():
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(code, encoding="utf-8")
            implementations = [
                {"framework": "pytest", "file": destination.relative_to(root).as_posix(), "selector": case_id},
                {"framework": "pytest", "file": helper_relative, "selector": case_id},
            ]
            # The case ID remains in the old scenario's list/dispatch table.
            if case_id not in helper_code:
                raise SystemExit(f"Case ID {case_id} not found in shared scenario logic")
            entry = owners[case_id]
            entry["implementation"] = implementations
            entry["implementation_hash"] = implementation_hash(root, implementations)
        manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"source={old_relative} cases={len(owners)} helper={helper_relative}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
