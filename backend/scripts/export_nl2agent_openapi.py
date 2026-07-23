"""Export the NL2AGENT subset of the Runtime FastAPI OpenAPI contract."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "sdk"))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from apps.app_factory import create_app  # noqa: E402 -- repository paths must precede app import
from apps.nl2agent_app import router as nl2agent_router  # noqa: E402
from consts.nl2agent_card import (  # noqa: E402
    Nl2AgentCardEnvelope,
    build_nl2agent_card_schema,
)


def _build_contract_app() -> FastAPI:
    """Build the Runtime-compatible app subset owned by the NL2AGENT contract."""
    app = create_app(
        title="Nexent Runtime API",
        description="Runtime APIs",
        enable_monitoring=False,
    )
    app.include_router(nl2agent_router)
    return app


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
    source = _build_contract_app().openapi()
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
    schemas: dict[str, Any] = {
        name: all_schemas[name] for name in sorted(required) if name in all_schemas
    }
    card_schema = Nl2AgentCardEnvelope.model_json_schema(
        ref_template="#/components/schemas/{model}"
    )
    schemas.update(card_schema.pop("$defs", {}))
    schemas["Nl2AgentCardEnvelope"] = card_schema
    return {
        "openapi": source["openapi"],
        "info": source["info"],
        "paths": paths,
        "components": {"schemas": schemas},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--card-output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    openapi_rendered = (
        json.dumps(
            build_nl2agent_openapi(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    card_rendered = (
        json.dumps(
            build_nl2agent_card_schema(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if args.check:
        try:
            current_openapi = json.loads(args.output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current_openapi = None
        try:
            current_card = json.loads(args.card_output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current_card = None
        if current_openapi != build_nl2agent_openapi():
            raise SystemExit(
                "NL2AGENT OpenAPI snapshot is out of date. Run pnpm contracts:generate."
            )
        if current_card != build_nl2agent_card_schema():
            raise SystemExit(
                "NL2AGENT card schema is out of date. Run pnpm contracts:generate."
            )
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.card_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(openapi_rendered.encode("utf-8"))
    args.card_output.write_bytes(card_rendered.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
