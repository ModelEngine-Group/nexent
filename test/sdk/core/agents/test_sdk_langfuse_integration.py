"""Opt-in functional test for Nexent SDK real-model execution with Langfuse tracing."""
from __future__ import annotations

import base64
import os
import re
import time
import uuid
from pathlib import Path
from threading import Event
from urllib.parse import urlparse

import pytest
import requests


pytestmark = [
    pytest.mark.local_only,
    pytest.mark.functional,
    pytest.mark.real_model,
    pytest.mark.langfuse,
]

_RUN_FLAG = "NEXENT_RUN_SDK_LANGFUSE_FUNCTIONAL"
_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


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


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _model_env() -> tuple[str, str, str] | None:
    if os.getenv("LLM_API_KEY") and os.getenv("LLM_MODEL_NAME") and os.getenv("LLM_API_URL"):
        return os.environ["LLM_API_KEY"], os.environ["LLM_MODEL_NAME"], os.environ["LLM_API_URL"]
    if os.getenv("NEXENT_LLM_KEY") and os.getenv("NEXENT_LLM_NAME") and os.getenv("NEXENT_LLM_URL"):
        return os.environ["NEXENT_LLM_KEY"], os.environ["NEXENT_LLM_NAME"], os.environ["NEXENT_LLM_URL"]
    return None


def _langfuse_host_from_env() -> str | None:
    host = os.getenv("LANGFUSE_HOST")
    if host:
        return host.rstrip("/")
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if not endpoint:
        return None
    parsed = urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _configure_langfuse_env() -> bool:
    public = os.getenv("LANGFUSE_PUBLIC_KEY") or os.getenv("LANGFUSE_INIT_PROJECT_PUBLIC_KEY")
    secret = os.getenv("LANGFUSE_SECRET_KEY") or os.getenv("LANGFUSE_INIT_PROJECT_SECRET_KEY")
    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
        os.environ.setdefault("OTEL_EXPORTER_OTLP_PROTOCOL", "http")
        os.environ.setdefault("OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION", "4")
        if public and secret and not os.getenv("OTEL_EXPORTER_OTLP_AUTHORIZATION"):
            token = base64.b64encode(f"{public}:{secret}".encode()).decode()
            os.environ.setdefault("OTEL_EXPORTER_OTLP_AUTHORIZATION", "Basic " + token)
        return True
    host = _langfuse_host_from_env()
    if not (host and public and secret):
        return False
    token = base64.b64encode(f"{public}:{secret}".encode()).decode()
    os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", host.rstrip("/") + "/api/public/otel")
    os.environ.setdefault("OTEL_EXPORTER_OTLP_AUTHORIZATION", "Basic " + token)
    os.environ.setdefault("OTEL_EXPORTER_OTLP_PROTOCOL", "http")
    os.environ.setdefault("OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION", "4")
    os.environ.setdefault("OTEL_SERVICE_NAME", "nexent-sdk-functional-test")
    return True


def _configure_sdk_monitoring() -> None:
    from nexent.monitor import MonitoringConfig, get_monitoring_manager

    headers = {}
    authorization = os.getenv("OTEL_EXPORTER_OTLP_AUTHORIZATION")
    if authorization:
        headers["Authorization"] = authorization
    ingestion_version = os.getenv("OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION")
    if ingestion_version:
        headers["x-langfuse-ingestion-version"] = ingestion_version

    get_monitoring_manager().configure(
        MonitoringConfig(
            enable_telemetry=True,
            service_name=os.getenv("OTEL_SERVICE_NAME", "nexent-sdk-functional-test"),
            provider="langfuse",
            otlp_endpoint=os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"],
            otlp_traces_endpoint=os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or None,
            otlp_protocol=os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http"),
            otlp_headers=headers,
            export_metrics=False,
            instrument_requests=False,
        )
    )


def _force_flush_otel() -> None:
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        force_flush = getattr(provider, "force_flush", None)
        if callable(force_flush):
            force_flush(timeout_millis=10_000)
    except Exception:
        pass


def _find_langfuse_trace(marker: str) -> dict:
    host = _langfuse_host_from_env()
    public = os.getenv("LANGFUSE_PUBLIC_KEY") or os.getenv("LANGFUSE_INIT_PROJECT_PUBLIC_KEY")
    secret = os.getenv("LANGFUSE_SECRET_KEY") or os.getenv("LANGFUSE_INIT_PROJECT_SECRET_KEY")
    if not (host and public and secret):
        pytest.skip("Set LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY or init project keys to verify trace via API")

    auth = (public, secret)
    deadline = time.time() + float(os.getenv("LANGFUSE_TRACE_POLL_SECONDS", "45"))
    last_error = None
    while time.time() < deadline:
        try:
            response = requests.get(
                host.rstrip("/") + "/api/public/traces",
                auth=auth,
                params={"limit": 50, "page": 1},
                timeout=10,
            )
            if response.status_code == 404:
                response = requests.get(
                    host.rstrip("/") + "/api/public/traces",
                    auth=auth,
                    params={"pageSize": 50, "page": 1},
                    timeout=10,
                )
            response.raise_for_status()
            payload = response.json()
            traces = payload.get("data") or payload.get("traces") or []
            for trace_data in traces:
                blob = str(trace_data)
                if marker in blob:
                    return trace_data
        except Exception as exc:
            last_error = exc
        time.sleep(3)
    raise AssertionError(f"Langfuse trace containing marker {marker!r} was not found; last_error={last_error}")


def test_sdk_real_agent_run_emits_langfuse_trace():
    project_root = Path(__file__).resolve().parents[4]
    _load_dotenv_no_override(project_root)
    if not _truthy_env(_RUN_FLAG):
        pytest.skip(f"Set {_RUN_FLAG}=1 to run the real SDK Langfuse functional test")

    model = _model_env()
    if model is None:
        pytest.skip("Set LLM_API_KEY/LLM_MODEL_NAME/LLM_API_URL or NEXENT_LLM_KEY/NEXENT_LLM_NAME/NEXENT_LLM_URL")
    if not _configure_langfuse_env():
        pytest.skip("Set OTLP Langfuse env or LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY")

    _configure_sdk_monitoring()

    api_key, model_name, api_url = model
    marker = f"sdk-langfuse-functional-{uuid.uuid4()}"

    from nexent.core.agents.agent_model import (
        AgentConfig,
        ExternalAgentsComponent,
        KnowledgeBaseComponent,
        ManagedAgentsComponent,
        MemoryComponent,
        ModelConfig,
        SkillsComponent,
        SystemPromptComponent,
        ToolsComponent,
    )
    from nexent.core.agents.nexent_agent import NexentAgent
    from nexent.core.agents.summary_config import ContextManagerConfig
    from nexent.core.utils.observer import MessageObserver
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
            ToolsComponent(tools=[{"name": "synthetic_lookup", "description": "Synthetic tool context only."}], formatted_description="Tool: synthetic_lookup - Synthetic tool context only."),
            SkillsComponent(skills=[{"name": "functional-skill", "description": "Synthetic skill context for tracing."}], formatted_description="Skill: functional-skill - Synthetic skill context for tracing."),
            MemoryComponent(formatted_content="Memory: user prefers concise answers."),
            KnowledgeBaseComponent(summary="KB: Nexent SDK agents assemble context through ContextManager."),
            ManagedAgentsComponent(managed_agents={"local_helper": {"description": "Synthetic local helper context."}}, formatted_description="Managed agent local_helper: Synthetic local helper context."),
            ExternalAgentsComponent(external_a2a_agents={"external_helper": {"name": "external_helper", "description": "Synthetic external A2A context."}}, formatted_description="External A2A external_helper: Synthetic external A2A context."),
        ],
    )
    agent = factory.create_single_agent(config)
    factory.set_agent(agent)
    factory.agent_run_with_observer(f"Return exactly this marker and one short sentence: {marker}")

    _force_flush_otel()
    time.sleep(float(os.getenv("LANGFUSE_TRACE_FLUSH_SECONDS", "5")))
    trace_data = _find_langfuse_trace(marker)
    trace_blob = str(trace_data)
    assert marker in trace_blob
    assert "sdk_langfuse_functional_agent" in trace_blob or "agent" in trace_blob.lower()
