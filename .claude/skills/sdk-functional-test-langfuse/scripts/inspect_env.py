#!/usr/bin/env python3
"""Inspect Nexent real-model and Langfuse env readiness without printing secrets."""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

SECRET_MARKERS = ("KEY", "SECRET", "TOKEN", "AUTHORIZATION", "PASSWORD")
ENV_FILES = (".env", "backend/.env", "sdk/.env", "deploy/env/.env", "docker/.env")
MODEL_GROUPS = (
    ("LLM_API_KEY", "LLM_MODEL_NAME", "LLM_API_URL"),
    ("NEXENT_LLM_KEY", "NEXENT_LLM_NAME", "NEXENT_LLM_URL"),
)
LANGFUSE_API = ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
OTEL_KEYS = (
    "OTEL_SERVICE_NAME",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_EXPORTER_OTLP_AUTHORIZATION",
    "OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION",
)

_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_env_refs(values: dict[str, str]) -> dict[str, str]:
    expanded = dict(values)
    for _ in range(10):
        changed = False
        for key, value in list(expanded.items()):
            def replace(match: re.Match[str]) -> str:
                ref_key = match.group(1)
                return expanded.get(ref_key, os.environ.get(ref_key, match.group(0)))

            new_value = _VAR_PATTERN.sub(replace, value)
            if new_value != value:
                expanded[key] = new_value
                changed = True
        if not changed:
            break
    return expanded



def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        values[key] = value
    return values


def load_env(project_root: Path) -> tuple[dict[str, str], list[Path]]:
    merged: dict[str, str] = {}
    found: list[Path] = []
    for rel in ENV_FILES:
        path = project_root / rel
        parsed = parse_env_file(path)
        if parsed:
            found.append(path)
            merged.update(parsed)
    merged.update({key: value for key, value in os.environ.items() if value})
    return expand_env_refs(merged), found


def redact(key: str, value: str | None) -> str:
    if not value:
        return "<missing>"
    if any(marker in key.upper() for marker in SECRET_MARKERS):
        return f"<set:{len(value)} chars>"
    return value


def complete(env: dict[str, str], keys: tuple[str, ...]) -> bool:
    return all(env.get(key) for key in keys)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".", help="Nexent repository root")
    args = parser.parse_args()
    project_root = Path(args.project_root).resolve()
    env, found = load_env(project_root)

    print(f"project_root={project_root}")
    print("env_files=" + (", ".join(str(path) for path in found) if found else "<none>"))

    selected_model = next((group for group in MODEL_GROUPS if complete(env, group)), None)
    print("model_source=" + ("/".join(selected_model) if selected_model else "<incomplete>"))
    for group in MODEL_GROUPS:
        for key in group:
            print(f"{key}={redact(key, env.get(key))}")

    has_otel = bool(env.get("OTEL_EXPORTER_OTLP_ENDPOINT") or env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"))
    has_langfuse_api = complete(env, LANGFUSE_API)
    print(f"langfuse_otel_ready={has_otel}")
    print(f"langfuse_api_ready={has_langfuse_api}")
    for key in OTEL_KEYS + LANGFUSE_API:
        print(f"{key}={redact(key, env.get(key))}")

    if has_langfuse_api and not env.get("OTEL_EXPORTER_OTLP_AUTHORIZATION"):
        print("derived_OTEL_EXPORTER_OTLP_AUTHORIZATION=present")

    if not selected_model:
        print("status=model-env-missing")
        return 2
    if not (has_otel or has_langfuse_api):
        print("status=langfuse-env-missing")
        return 3
    print("status=ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
