#!/usr/bin/env python3
"""Render exported Agent YAML into a benchmark-reconstructed parity snapshot."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml


GENERIC_DIR = Path(__file__).resolve().parent.parent
BENCHMARK_DIR = GENERIC_DIR.parent
sys.path.insert(0, str(GENERIC_DIR))
sys.path.insert(0, str(BENCHMARK_DIR))

from agent_runner import (  # noqa: E402
    build_agent_run_info,
    build_tools_from_yaml,
    inject_production_managed_tools,
)
from provenance.parity_snapshot import build_agent_run_info_parity_snapshot  # noqa: E402


def export_snapshot(
    *,
    agent_config_path: Path,
    output_path: Path,
    language: str,
    tenant_id: str,
    skills_path: str | None,
) -> dict:
    config = yaml.safe_load(agent_config_path.read_text(encoding="utf-8")) or {}
    prompts = config.get("prompts", {})
    agent_config = config.get("agent_config", {})
    tools_yaml = config.get("tools", [])
    tools = build_tools_from_yaml(tools_yaml, include_runtime_metadata=False)
    agent_info = config.get("agent_info", {})
    tools = inject_production_managed_tools(
        tools,
        agent_id=int(agent_info.get("agent_id", 0) or 0),
        tenant_id=tenant_id,
        version_no=int(agent_config.get("version_no", 0) or 0),
        local_skills_dir=skills_path,
    )
    run_info = build_agent_run_info(
        query="parity snapshot render only",
        history=[],
        duty_prompt=prompts.get("duty_prompt", ""),
        constraint_prompt=prompts.get("constraint_prompt", ""),
        few_shots_prompt=prompts.get("few_shots_prompt", ""),
        tools=tools,
        language=language,
        user_id="user_id",
        prompt_components=config.get("prompt_components"),
    )
    snapshot = build_agent_run_info_parity_snapshot(
        run_info,
        language=language,
        template_version=str(agent_config.get("prompt_template_id", "")),
        template_source=str(agent_config_path.resolve()),
        producer_kind="benchmark_reconstructed",
        producer_component="sdk.benchmark.generic.tools.export_parity_snapshot",
        resource_support={
            "tools": True,
            "skills": True,
            "managed_agents": True,
            "external_agents": False,
            "memory": False,
            "knowledge_base": False,
        },
        intentional_empty_resources={
            "skills": not bool(config.get("skills")),
            "managed_agents": not bool(config.get("sub_agents")),
        },
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--language", choices=("en", "zh"), required=True)
    parser.add_argument("--tenant-id", default="tenant_id")
    parser.add_argument("--skills-path")
    args = parser.parse_args()
    snapshot = export_snapshot(
        agent_config_path=args.agent_config,
        output_path=args.output,
        language=args.language,
        tenant_id=args.tenant_id,
        skills_path=args.skills_path or os.getenv("SKILLS_PATH"),
    )
    print(
        f"Wrote parity snapshot: {args.output} "
        f"(items={len(snapshot['context_items'])}, tools={snapshot['tools']['count']})"
    )


if __name__ == "__main__":
    main()
