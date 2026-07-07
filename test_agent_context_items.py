"""Integration test: run a real agent with use_context_items=True and OTel tracing to Langfuse."""
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).parent / "sdk"))
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from dotenv import load_dotenv
load_dotenv(override=True)

from nexent.core.utils.observer import MessageObserver
from nexent.core.agents.agent_model import (
    ModelConfig, AgentConfig, AgentRunInfo, SystemPromptComponent,
)
from nexent.core.agents.summary_config import ContextManagerConfig
from nexent.core.agents.run_agent import agent_run
from utils.monitoring import monitoring_manager
from nexent.monitor import agent_monitoring_context, AgentRunMetadata


def build_model_config() -> ModelConfig:
    return ModelConfig(
        cite_name="main_model",
        api_key=os.environ["DEFAULT_MODEL_API_KEY"],
        model_name=os.environ["DEFAULT_MODEL"],
        url=os.environ["DEFAULT_MODEL_ENDPOINT"],
        temperature=0.1,
        top_p=0.95,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )


def build_agent_config() -> AgentConfig:
    cm_config = ContextManagerConfig(
        enabled=True,
        use_context_items=True,
        token_threshold=32768,
        strategy="full",
    )

    system_prompt = SystemPromptComponent(
        content=(
            "You are a helpful assistant. Answer questions concisely and accurately. "
            "If you are unsure, say so. Always respond in English."
        ),
    )

    return AgentConfig(
        name="context_test_agent",
        description="Test agent with context items enabled",
        model_name="main_model",
        tools=[],
        max_steps=5,
        context_manager_config=cm_config,
        context_components=[system_prompt],
        conversation_id=99999,
    )


async def run_agent(query: str) -> str:
    model_cfg = build_model_config()
    agent_cfg = build_agent_config()
    observer = MessageObserver(lang="en")
    stop_event = Event()

    run_info = AgentRunInfo(
        query=query,
        model_config_list=[model_cfg],
        observer=observer,
        agent_config=agent_cfg,
        stop_event=stop_event,
    )

    metadata = AgentRunMetadata(
        agent_name="context_test_agent",
        query=query,
        tenant_id="test",
        user_id="integration_test",
        conversation_id=99999,
        model_name=model_cfg.model_name,
        memory_enabled=False,
    )

    final_answer = ""
    with agent_monitoring_context(metadata):
        async for message in agent_run(run_info):
            msg = json.loads(message) if isinstance(message, str) else message
            msg_type = msg.get("type", "")
            content = msg.get("content", "")

            if msg_type == "final_answer":
                final_answer = content
                print(f"  [FINAL] {content[:200]}")
            elif msg_type == "model_output_code":
                print(f"  [CODE] {content[:100]}")
            elif msg_type == "execution_logs":
                print(f"  [EXEC] {content[:100]}")
            elif msg_type == "step_count":
                print(f"  [STEP] {content}")
            elif msg_type == "error":
                print(f"  [ERROR] {content}")

    return final_answer


async def main():
    print("=" * 70)
    print("Agent Integration Test: use_context_items=True + Langfuse OTel")
    print("=" * 70)

    monitor = monitoring_manager
    print(f"\nMonitoring enabled: {monitor.is_enabled}")
    if monitor.is_enabled:
        cfg = monitor._config
        print(f"  endpoint: {cfg.otlp_endpoint}")
        print(f"  provider: {cfg.provider}")

    query = "What is the capital of France? Answer in one sentence."
    print(f"\nQuery: {query}")
    print("-" * 70)

    start = time.time()
    answer = await run_agent(query)
    elapsed = time.time() - start

    print("-" * 70)
    print(f"\nAnswer: {answer}")
    print(f"Elapsed: {elapsed:.1f}s")

    print("\nFlushing OTel traces...")
    if monitor._tracer_provider:
        monitor._tracer_provider.force_flush()
    time.sleep(2)

    print("\nDone. Check Langfuse UI for traces:")
    print("  https://jp.cloud.langfuse.com -> Traces -> 'context_test_agent'")
    print("\nExpected spans:")
    print("  - agent.run (AGENT)")
    print("  - context.prepare_step (CHAIN)")
    print("  - context.assemble_final_context (CHAIN)")
    print("  - context.project_items (CHAIN, component_count attribute)")


if __name__ == "__main__":
    asyncio.run(main())
