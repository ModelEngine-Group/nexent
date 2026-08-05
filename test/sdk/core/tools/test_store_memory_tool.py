import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

from nexent.memory.models import MemoryLayer, MemoryType, StoreMemoryResult


REPO_ROOT = Path(__file__).resolve().parents[4]
MODULE_PATH = (
    REPO_ROOT
    / "sdk"
    / "nexent"
    / "core"
    / "tools"
    / "store_memory_tool.py"
)


def _load_tool_module():
    spec = importlib.util.spec_from_file_location(
        "sdk.nexent.core.tools.store_memory_tool", str(MODULE_PATH)
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not build spec for store_memory_tool")
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "sdk.nexent.core.tools"
    sys.modules["sdk.nexent.core.tools.store_memory_tool"] = module
    spec.loader.exec_module(module)
    return module


STORE_TOOL = _load_tool_module()


def _make_tool(
    memory_service=None,
    observer=None,
    conversation_id="conversation-1",
    embedding_configured=True,
):
    return STORE_TOOL.StoreMemoryTool(
        memory_service=memory_service,
        tenant_id="tenant-1",
        user_id="user-1",
        agent_id="agent-1",
        conversation_id=conversation_id,
        observer=observer,
        embedding_configured=embedding_configured,
    )


def test_store_memory_calls_new_memory_service_with_isolated_scope(caplog):
    caplog.set_level("INFO")
    captured = {}

    async def store_memory(**kwargs):
        captured.update(kwargs)
        return StoreMemoryResult(
            memory_id="memory-1",
            event="ADD",
            content=kwargs["content"],
            layer=MemoryLayer.AGENT,
            memory_type=MemoryType.SHORT_TERM,
        )

    service = MagicMock()
    service.store_memory = store_memory
    tool = _make_tool(memory_service=service)

    result = tool.forward("Remember the deployment preference")

    assert captured == {
        "content": "Remember the deployment preference",
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "agent_id": "agent-1",
        "conversation_id": "conversation-1",
        "layer": MemoryLayer.AGENT,
        "memory_type": MemoryType.SHORT_TERM,
    }
    assert result == (
        "Stored successfully:\n"
        "[ADD] Remember the deployment preference"
    )
    assert tool.store_count == 1
    assert tool.invocation_count == 1
    assert tool.successful_store_count == 1
    assert tool.last_outcome == "completed"
    assert "event=memory_tool_invoked tool=store_memory" in caplog.text
    assert "event=memory_tool_completed tool=store_memory" in caplog.text
    assert "memory_id=memory-1" in caplog.text
    assert "Remember the deployment preference" not in caplog.text


def test_store_memory_normalizes_integer_conversation_id():
    captured = {}

    async def store_memory(**kwargs):
        captured.update(kwargs)
        return StoreMemoryResult(
            memory_id="memory-1",
            event="ADD",
            content=kwargs["content"],
            layer=MemoryLayer.AGENT,
            memory_type=MemoryType.SHORT_TERM,
        )

    service = MagicMock()
    service.store_memory = store_memory

    result = _make_tool(
        memory_service=service,
        conversation_id=167,
    ).forward("Remember this")

    assert result.startswith("Stored successfully")
    assert captured["conversation_id"] == "167"


def test_store_memory_does_not_emit_unstructured_tool_status():
    async def store_memory(**kwargs):
        return StoreMemoryResult(
            memory_id="memory-1",
            content=kwargs["content"],
            layer=MemoryLayer.AGENT,
            memory_type=MemoryType.SHORT_TERM,
        )

    observer = MagicMock()
    observer.lang = "zh"
    service = MagicMock()
    service.store_memory = store_memory

    _make_tool(memory_service=service, observer=observer).forward("记住偏好")

    observer.add_message.assert_not_called()


def test_store_memory_reports_unchanged_without_counting_a_write():
    async def store_memory(**kwargs):
        return StoreMemoryResult(
            memory_id="memory-1",
            event="UNCHANGED",
            content=kwargs["content"],
            layer=MemoryLayer.AGENT,
            memory_type=MemoryType.SHORT_TERM,
        )

    service = MagicMock()
    service.store_memory = store_memory
    tool = _make_tool(memory_service=service)

    result = tool.forward("Existing preference")

    assert result == "Memory already stored; no new memory was created."
    assert tool.store_count == 0
    assert tool.successful_store_count == 0
    assert tool.last_outcome == "duplicate"


def test_store_memory_requires_memory_service(caplog):
    tool = _make_tool()
    result = tool.forward("Remember this")

    assert "MemoryService is not configured" in result
    assert "reason=service_not_configured" in caplog.text
    assert tool.invocation_count == 1
    assert tool.successful_store_count == 0
    assert tool.last_outcome == "failed_service_not_configured"


def test_store_memory_fails_without_embedding_model(caplog):
    service = MagicMock()
    tool = _make_tool(
        memory_service=service,
        embedding_configured=False,
    )

    result = tool.forward("Remember this")

    assert "embedding model is not configured" in result
    service.store_memory.assert_not_called()
    assert "reason=embedding_not_configured" in caplog.text
    assert tool.last_outcome == "failed_embedding_not_configured"


def test_store_memory_enforces_per_run_limit(caplog):
    service = MagicMock()
    tool = _make_tool(memory_service=service)
    tool.store_count = tool.max_stores_per_run

    result = tool.forward("One more memory")

    assert result.startswith("Memory storage limit reached")
    service.store_memory.assert_not_called()
    assert "event=memory_tool_degraded tool=store_memory" in caplog.text
    assert "reason=store_limit" in caplog.text
    assert tool.last_outcome == "degraded_store_limit"


def test_store_memory_handles_policy_denial(caplog):
    async def store_memory(**kwargs):
        raise PermissionError("denied")

    service = MagicMock()
    service.store_memory = store_memory

    tool = _make_tool(memory_service=service)
    result = tool.forward("Remember this")

    assert "not allowed to write" in result
    assert "reason=policy_denied" in caplog.text
    assert tool.last_outcome == "policy_denied"


def test_store_memory_handles_backend_failure(caplog):
    async def store_memory(**kwargs):
        raise RuntimeError("backend unavailable")

    service = MagicMock()
    service.store_memory = store_memory

    tool = _make_tool(memory_service=service)
    result = tool.forward("Remember this")

    assert "backend unavailable" in result
    assert "Continuing without saving" in result
    assert "event=memory_tool_failed tool=store_memory" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "backend unavailable" not in caplog.text
    assert tool.last_outcome == "failed"
