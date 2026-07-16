"""Export the NL2AGENT subset of the Runtime FastAPI OpenAPI contract."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.runtime_app import app


def _referenced_schema_names(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/components/schemas/"):
            names.add(reference.rsplit("/", 1)[-1])
        for item in value.values():
            names.update(_referenced_schema_names(item))
    elif isinstance(value, list):
        for item in value:
            names.update(_referenced_schema_names(item))
    return names


def build_nl2agent_openapi() -> dict[str, Any]:
    """Return NL2AGENT paths plus their transitive component schemas."""
    source = app.openapi()
    paths = {
        path: definition
        for path, definition in source.get("paths", {}).items()
        if path.startswith("/nl2agent")
    }
    all_schemas = source.get("components", {}).get("schemas", {})
    required = _referenced_schema_names(paths)
    pending = list(required)
    while pending:
        name = pending.pop()
        for dependency in _referenced_schema_names(all_schemas.get(name, {})):
            if dependency not in required:
                required.add(dependency)
                pending.append(dependency)
    schemas = {
        name: all_schemas[name] for name in sorted(required) if name in all_schemas
    }
    return {
        "openapi": source["openapi"],
        "info": source["info"],
        "paths": paths,
        "components": {"schemas": schemas},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = (
        json.dumps(
            build_nl2agent_openapi(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if args.check:
        current = (
            args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        )
        if current != rendered:
            raise SystemExit(
                "NL2AGENT OpenAPI snapshot is out of date. Run pnpm contracts:generate."
            )
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    newline = "\r\n" if args.output.exists() and b"\r\n" in args.output.read_bytes() else "\n"
    args.output.write_bytes(rendered.replace("\n", newline).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
