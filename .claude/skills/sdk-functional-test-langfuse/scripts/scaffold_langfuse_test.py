#!/usr/bin/env python3
"""Write a starting pytest scaffold for Nexent SDK real-model Langfuse tests."""
from __future__ import annotations

import argparse
from pathlib import Path

TEMPLATE = '''"""Opt-in functional test for Nexent SDK real-model execution with Langfuse tracing."""
from __future__ import annotations

import base64
import os
import re
import time
import uuid
from pathlib import Path

import pytest


_VAR_PATTERN = re.compile(r"\\$\\{([A-Za-z_][A-Za-z0-9_]*)\\}")


def _expand_env_refs(values: dict[str, str]) -> dict[str, str]:
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


def _load_dotenv_no_override(project_root: Path) -> None:
    file_values: dict[str, str] = {}
    for rel in (".env", "backend/.env", "sdk/.env", "deploy/env/.env", "docker/.env"):
        path = project_root / rel
        if not path.exists():
            continue
        for raw in path.read_text(errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().removeprefix("export ").strip()
            value = value.strip().strip('"').strip("'")
            file_values[key] = value
    merged = dict(file_values)
    merged.update({key: value for key, value in os.environ.items() if value})
    for key, value in _expand_env_refs(merged).items():
        os.environ.setdefault(key, value)


def _model_env() -> tuple[str, str, str] | None:
    if os.getenv("LLM_API_KEY") and os.getenv("LLM_MODEL_NAME") and os.getenv("LLM_API_URL"):
        return os.environ["LLM_API_KEY"], os.environ["LLM_MODEL_NAME"], os.environ["LLM_API_URL"]
    if os.getenv("NEXENT_LLM_KEY") and os.getenv("NEXENT_LLM_NAME") and os.getenv("NEXENT_LLM_URL"):
        return os.environ["NEXENT_LLM_KEY"], os.environ["NEXENT_LLM_NAME"], os.environ["NEXENT_LLM_URL"]
    return None


def _configure_langfuse_env() -> bool:
    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
        os.environ.setdefault("OTEL_EXPORTER_OTLP_PROTOCOL", "http")
        os.environ.setdefault("OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION", "4")
        return True
    host = os.getenv("LANGFUSE_HOST")
    public = os.getenv("LANGFUSE_PUBLIC_KEY") or os.getenv("LANGFUSE_INIT_PROJECT_PUBLIC_KEY")
    secret = os.getenv("LANGFUSE_SECRET_KEY") or os.getenv("LANGFUSE_INIT_PROJECT_SECRET_KEY")
    if not (host and public and secret):
        return False
    token = base64.b64encode(f"{public}:{secret}".encode()).decode()
    os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", host.rstrip("/") + "/api/public/otel")
    os.environ.setdefault("OTEL_EXPORTER_OTLP_AUTHORIZATION", "Basic " + token)
    os.environ.setdefault("OTEL_EXPORTER_OTLP_PROTOCOL", "http")
    os.environ.setdefault("OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION", "4")
    os.environ.setdefault("OTEL_SERVICE_NAME", "nexent-sdk-functional-test")
    return True


@pytest.mark.functional
@pytest.mark.real_model
@pytest.mark.langfuse
def test_sdk_real_agent_run_emits_langfuse_trace():
    project_root = Path(__file__).resolve().parents[4]
    _load_dotenv_no_override(project_root)
    model = _model_env()
    if model is None:
        pytest.skip("Set LLM_API_KEY/LLM_MODEL_NAME/LLM_API_URL or NEXENT_LLM_KEY/NEXENT_LLM_NAME/NEXENT_LLM_URL")
    if not _configure_langfuse_env():
        pytest.skip("Set OTLP Langfuse env or LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY")

    api_key, model_name, api_url = model
    marker = f"sdk-langfuse-functional-{uuid.uuid4()}"

    from sdk.nexent.core.agents.agent_model import AgentConfig, ModelConfig, SystemPromptComponent, MemoryComponent, KnowledgeBaseComponent, SkillsComponent
    from sdk.nexent.core.agents.nexent_agent import NexentAgent
    from sdk.nexent.core.agents.summary_config import ContextManagerConfig
    from sdk.nexent.core.utils.observer import MessageObserver
    from threading import Event

    factory = NexentAgent(
        observer=MessageObserver(),
        model_config_list=[ModelConfig(cite_name="functional_llm", api_key=api_key, model_name=model_name, url=api_url)],
        stop_event=Event(),
    )
    config = AgentConfig(
        name="sdk_langfuse_functional_agent",
        description="Functional test agent with representative context",
        model_name="functional_llm",
        tools=[],
        max_steps=2,
        context_manager_config=ContextManagerConfig(enabled=True, token_threshold=12000),
        context_components=[
            SystemPromptComponent(content=f"You are a concise SDK functional test agent. Marker: {marker}"),
            SkillsComponent(skills=[{"name": "functional-skill", "description": "Synthetic skill context for tracing."}], formatted_description="Skill: functional-skill - Synthetic skill context for tracing."),
            MemoryComponent(formatted_content="Memory: user prefers concise answers."),
            KnowledgeBaseComponent(summary="KB: Nexent SDK agents assemble context through ContextManager."),
        ],
    )
    agent = factory.create_single_agent(config)
    factory.set_agent(agent)
    factory.agent_run_with_observer(f"Return exactly this marker and one short sentence: {marker}")

    time.sleep(float(os.getenv("LANGFUSE_TRACE_FLUSH_SECONDS", "5")))
    assert marker
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, help="Path to write pytest scaffold")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing file")
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists() and not args.force:
        raise SystemExit(f"Refusing to overwrite existing file: {output} (use --force)")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(TEMPLATE)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
