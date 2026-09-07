"""Unit tests for ``SearchMemoryTool`` focusing on the Phase 4
``MemoryContextService`` integration path.

These tests are scoped to the new wiring added in P0 (search_memory tool
bypass fix) and do not exercise unrelated tool concerns.

Notes on the tool construction conventions:

The tool declares all constructor parameters as ``Field(...)`` with
``exclude=True`` so that Pydantic treats them as configuration metadata
for the smolagents ``Tool`` schema. When no kwarg is supplied for a
parameter, the FieldInfo placeholder remains on the instance, matching
the production wiring in ``sdk.nexent.core.agents.nexent_agent`` which
constructs the tool bare and then assigns every attribute manually.
These tests follow that pattern so they stay in sync with the real
runtime path.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
MODULE_PATH = (
    REPO_ROOT
    / "sdk"
    / "nexent"
    / "core"
    / "tools"
    / "search_memory_tool.py"
)


# Make the project root importable so ``nexent`` (== ``sdk.nexent`` via the
# repo's symlink-free layout) resolves correctly for both the SDK code
# under test and the test bootstrap.
PROJECT_ROOT = REPO_ROOT  # C:\Project\nexent — already exposes both packages.
for entry in (str(PROJECT_ROOT), str(PROJECT_ROOT / "sdk"), str(PROJECT_ROOT / "backend")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

# --------------------------------------------------------------------------- #
# Module bootstrapping                                                         #
# --------------------------------------------------------------------------- #

# ``smolagents.tools.Tool`` performs Pydantic-style validation in its
# ``__init__`` which we don't care about for unit tests; the real Tool
# already accepts the kwargs SearchMemoryTool forwards, so we import it
# directly and only override the schema-validation bit if necessary.

def _load_tool_module():
    spec = importlib.util.spec_from_file_location(
        "sdk.nexent.core.tools.search_memory_tool", str(MODULE_PATH)
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not build spec for search_memory_tool")
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "sdk.nexent.core.tools"
    sys.modules["sdk.nexent.core.tools.search_memory_tool"] = module
    spec.loader.exec_module(module)
    return module


SMTOOL = _load_tool_module()


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

class _StubRecord:
    """Mimics the duck-typed surface used by ``_format_context``."""

    def __init__(self, content, score=0.5, source="es", layer="agent"):
        self.content = content
        self.score = score
        self.source = source
        self.layer = layer


def _async_context_service(context_value):
    """Build an async stub ``MemoryContextService`` whose ``build_context``
    coroutine resolves to ``context_value``. Mirrors the real backend API
    where ``build_context`` is an ``async`` method."""
    service = AsyncMock(name="memory_context_service")
    service.build_context = AsyncMock(return_value=context_value)
    return service


def _make_tool(
    *,
    memory_service=None,
    memory_context_service=None,
    tenant_id="t1",
    user_id="u1",
    agent_id="a1",
    conversation_id="c1",
    observer=None,
    embedding_configured=True,
    external_results=None,
):
    """Construct the tool with every constructor kwarg supplied explicitly,
    matching how ``nexent_agent`` wires the runtime instance."""
    return SMTOOL.SearchMemoryTool(
        memory_service=memory_service,
        memory_context_service=memory_context_service,
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        observer=observer,
        embedding_configured=embedding_configured,
        external_results=external_results,
    )


def _make_context(records_by_layer=None):
    """Build a stubbed ``MemorySearchContext`` with duck-typed records.

    String keys populate the corresponding prompt buckets.
    """
    context = SimpleNamespace(
        tenant_long_term=[],
        user_long_term=[],
        agent_short_term=[],
        external=[],
    )
    if not records_by_layer:
        return context
    layer_attr = {
        "tenant": "tenant_long_term",
        "user": "user_long_term",
        "agent": "agent_short_term",
        "external": "external",
    }
    for layer_enum, items in records_by_layer.items():
        attr = layer_attr[layer_enum]
        for item in items:
            context.__getattribute__(attr).append(item)
    return context


@pytest.fixture
def observer():
    obs = MagicMock(spec=SMTOOL.MessageObserver)
    obs.lang = "en"
    return obs


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #

class TestSearchMemoryToolPipelinePath:
    """The new path added by the P0 fix: pipeline via MemoryContextService."""

    def test_constructor_accepts_memory_context_service(self):
        """Tool accepts ``memory_context_service`` as a kwarg and stores it
        on the instance."""
        service = MagicMock(name="memory_context_service")
        t = _make_tool(memory_context_service=service)
        assert t.memory_context_service is service
        assert t.tenant_id == "t1"
        assert t.user_id == "u1"
        assert t.agent_id == "a1"

    def test_pipeline_path_calls_build_context(self, observer):
        """When ``memory_context_service`` is wired, ``forward`` invokes
        ``build_context`` instead of ``memory_service.search_memory``."""
        service = _async_context_service(_make_context({
            "agent": [
                _StubRecord("Likes dark mode", score=0.91, source="es"),
                _StubRecord("Owns two cats", score=0.78, source="es"),
            ],
        }))
        legacy_service = MagicMock(name="legacy_memory_service")
        legacy_service.search_memory = MagicMock(
            side_effect=AssertionError(
                "legacy path should not be invoked when pipeline is wired"
            )
        )

        t = _make_tool(
            memory_service=legacy_service,
            memory_context_service=service,
            observer=observer,
        )

        result = t.forward(query="user preferences", top_k=5)

        service.build_context.assert_called_once()
        kwargs = service.build_context.call_args.kwargs
        assert kwargs["tenant_id"] == "t1"
        assert kwargs["user_id"] == "u1"
        assert kwargs["agent_id"] == "a1"
        assert kwargs["query"] == "user preferences"
        assert kwargs["top_k"] == 5
        assert kwargs["layers"] == ["agent"]

        # Output formatting includes the section header and per-record lines.
        assert "Found 2 relevant memories" in result
        assert "#### Agent Short-term Memory" in result
        assert "Likes dark mode" in result
        assert "Owns two cats" in result

    def test_ac_p3_18_pipeline_path_preserves_external_bucket(self):
        """AC-P3-18: fixed search includes prefetched external hits."""
        service = _async_context_service(_make_context({
            "tenant": [_StubRecord("Global policy X", score=0.99, source="es")],
            "user": [_StubRecord("Loves cats", score=0.88, source="es")],
            "agent": [_StubRecord("Active thread Y", score=0.77, source="es")],
            "external": [_StubRecord("Web hit Z", score=0.66, source="external:web")],
        }))
        t = _make_tool(memory_context_service=service)

        out = t.forward(query="anything", top_k=5)

        assert "#### Agent Short-term Memory" in out
        assert "Tenant Long-term Memory" not in out
        assert "User Long-term Memory" not in out
        assert "#### External Memory" in out
        assert "Global policy X" not in out
        assert "Loves cats" not in out
        assert "Active thread Y" in out
        assert "Web hit Z" in out

    def test_ac_p3_18_passes_prefetched_external_results_to_context_service(self):
        """AC-P3-18: runtime-prefetched hits reach context assembly unchanged."""
        service = _async_context_service(_make_context({}))
        external_results = [object()]
        tool = _make_tool(
            memory_context_service=service,
            external_results=external_results,
        )

        tool.forward(query="sister Jules", top_k=5)

        assert service.build_context.call_args.kwargs["external_results"] is external_results

    def test_ac_p3_22_restores_external_results_dropped_by_global_top_k(self):
        """Mixed-source output keeps prefetched external hits after fusion truncation."""
        service = _async_context_service(_make_context({
            "agent": [_StubRecord(f"Internal {index}", score=0.9 - index / 100)
                      for index in range(5)],
        }))
        external = _StubRecord("Jules uses COMET-913", score=0.39, source="mem0")
        tool = _make_tool(
            memory_context_service=service,
            external_results=[external],
        )

        out = tool.forward(query="ORBIT-742 and COMET-913", top_k=5)

        assert "Found 6 relevant memories" in out
        assert "#### External Memory" in out
        assert "Jules uses COMET-913" in out

    def test_pipeline_path_no_results_renders_empty_message(self):
        """Empty context surfaces the standard empty marker."""
        service = _async_context_service(_make_context({}))
        t = _make_tool(memory_context_service=service)

        out = t.forward(query="nothing")
        assert out == "No relevant memories found."

    def test_pipeline_path_passes_conversation_id_when_present(self, observer):
        """Conversation ID is propagated to the context service when set."""
        service = _async_context_service(_make_context({}))
        t = _make_tool(
            memory_context_service=service,
            conversation_id="c-42",
            observer=observer,
        )

        t.forward(query="something", top_k=7)

        kwargs = service.build_context.call_args.kwargs
        assert kwargs["conversation_id"] == "c-42"
        assert kwargs["top_k"] == 7

    def test_pipeline_path_does_not_emit_legacy_running_prompt(self, observer):
        """Fixed retrieval visibility is emitted by the streaming service."""
        service = _async_context_service(_make_context({}))
        t = _make_tool(memory_context_service=service, observer=observer)

        t.forward(query="anything")

        observer.add_message.assert_not_called()

    def test_pipeline_exception_does_not_switch_to_direct_service(self, observer, caplog):
        """A pipeline failure degrades to no memory without changing modes."""
        bad_service = AsyncMock(name="bad_service")
        bad_service.build_context = AsyncMock(
            side_effect=RuntimeError("pipeline exploded"),
        )
        async def _search(**kwargs):
            raise AssertionError("direct service must not be called")

        legacy_service = MagicMock(name="legacy_memory_service")
        legacy_service.search_memory = _search

        t = _make_tool(
            memory_service=legacy_service,
            memory_context_service=bad_service,
            observer=observer,
        )

        out = t.forward(query="anything", top_k=3)

        assert out == "Memory search failed. Continuing without memory results."
        assert "event=memory_tool_failed tool=search_memory" in caplog.text
        assert "path=pipeline" in caplog.text
        assert "fallback=memory_service" not in caplog.text
        assert "pipeline exploded" not in caplog.text


class TestSearchMemoryToolDirectMode:
    """Direct mode remains available when explicitly configured by callers."""

    def test_no_services_configured(self, observer, caplog):
        """With neither backend service wired, the tool returns the
        explicit configuration-error message rather than raising."""
        t = _make_tool(observer=observer)
        out = t.forward(query="anything")
        assert "Memory search failed" in out
        assert "MemoryService" in out
        assert "event=memory_tool_failed tool=search_memory" in caplog.text
        assert "reason=service_not_configured" in caplog.text

    def test_embedding_not_configured_returns_empty_list(self, observer, caplog):
        caplog.set_level("INFO")
        service = MagicMock(name="legacy_memory_service")
        t = _make_tool(
            memory_service=service,
            observer=observer,
            embedding_configured=False,
        )

        assert t.forward(query="anything") == "[]"
        service.search_memory.assert_not_called()
        assert "reason=embedding_not_configured" in caplog.text

    def test_direct_memory_service_path(self, observer, caplog):
        """Explicit direct mode preserves its established output format."""
        caplog.set_level("INFO")
        legacy_records = [
            _StubRecord("Legacy alpha", score=0.55, source="es"),
            _StubRecord("Legacy beta", score=0.33, source="es"),
        ]

        async def _search(**kwargs):
            assert kwargs["query"] == "agent query"
            assert kwargs["top_k"] == 2
            return legacy_records

        service = MagicMock(name="legacy_memory_service")
        service.search_memory = _search

        t = _make_tool(memory_service=service, observer=observer)
        out = t.forward(query="agent query", top_k=2)

        assert "Found 2 relevant memories" in out
        assert "Legacy alpha" in out
        assert "Legacy beta" in out
        # Direct mode does not render the per-layer section header.
        assert "#### Agent Short-term Memory" not in out
        assert "event=memory_tool_invoked tool=search_memory" in caplog.text
        assert "event=memory_tool_completed tool=search_memory" in caplog.text
        assert "path=memory_service result_count=2" in caplog.text
        assert "agent query" not in caplog.text

    def test_direct_mode_exception_returns_graceful_error(self, observer, caplog):
        """A failure in direct mode still surfaces as a soft error."""
        async def _boom(**kwargs):
            raise RuntimeError("backend unreachable")

        service = MagicMock(name="legacy_memory_service")
        service.search_memory = _boom

        t = _make_tool(memory_service=service, observer=observer)
        out = t.forward(query="anything")
        assert "Memory search failed" in out
        assert "backend unreachable" in out
        assert "event=memory_tool_failed tool=search_memory" in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert "backend unreachable" not in caplog.text
