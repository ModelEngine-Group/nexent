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
    )


def _make_context(records_by_layer=None):
    """Build a stubbed ``MemorySearchContext`` with duck-typed records.

    Keys may be either ``MemoryLayer`` enum values (tenant/user/agent) or
    the literal string ``"external"`` to populate the pipeline's separate
    external bucket.
    """
    from nexent.memory.models import MemoryLayer, MemorySearchContext

    context = MemorySearchContext()
    if not records_by_layer:
        return context
    layer_attr = {
        MemoryLayer.TENANT: "tenant_long_term",
        MemoryLayer.USER: "user_long_term",
        MemoryLayer.AGENT: "agent_short_term",
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
        # Only AGENT layer is queried — tenant/user are full-context.
        assert kwargs["layers"] == ["agent"]

        # Output formatting includes the section header and per-record lines.
        assert "Found 2 relevant memories" in result
        assert "#### Agent Short-term Memory" in result
        assert "Likes dark mode" in result
        assert "Owns two cats" in result

    def test_pipeline_path_renders_all_layer_buckets(self):
        """All four layer buckets render their own section header when populated."""
        service = _async_context_service(_make_context({
            "tenant": [_StubRecord("Global policy X", score=0.99, source="es")],
            "user": [_StubRecord("Loves cats", score=0.88, source="es")],
            "agent": [_StubRecord("Active thread Y", score=0.77, source="es")],
            "external": [_StubRecord("Web hit Z", score=0.66, source="external:web")],
        }))
        t = _make_tool(memory_context_service=service)

        out = t.forward(query="anything", top_k=5)

        for header in (
            "#### Tenant Long-term Memory",
            "#### User Long-term Memory",
            "#### Agent Short-term Memory",
            "#### External Memory",
        ):
            assert header in out
        assert "Global policy X" in out
        assert "Loves cats" in out
        assert "Active thread Y" in out
        assert "Web hit Z" in out

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

    def test_pipeline_path_emits_running_prompt(self, observer):
        """A running prompt is reported via the observer when wired."""
        service = _async_context_service(_make_context({}))
        t = _make_tool(memory_context_service=service, observer=observer)

        t.forward(query="anything")

        observer.add_message.assert_called_once()
        # First positional arg is the agent name (empty here), second is
        # the ProcessType enum.
        from sdk.nexent.core.utils.observer import ProcessType
        call_args = observer.add_message.call_args.args
        assert call_args[1] == ProcessType.TOOL

    def test_pipeline_exception_falls_back_to_legacy_memory_service(self, observer):
        """When the pipeline raises, the tool falls back to the
        ``memory_service.search_memory`` legacy path."""
        bad_service = AsyncMock(name="bad_service")
        bad_service.build_context = AsyncMock(
            side_effect=RuntimeError("pipeline exploded"),
        )
        legacy_records = [_StubRecord("Fallback hit", score=0.42, source="es")]

        async def _search(**kwargs):
            return legacy_records

        legacy_service = MagicMock(name="legacy_memory_service")
        legacy_service.search_memory = _search

        t = _make_tool(
            memory_service=legacy_service,
            memory_context_service=bad_service,
            observer=observer,
        )

        out = t.forward(query="anything", top_k=3)

        # Legacy path produced one record with the standard formatting.
        assert "Found 1 relevant memories" in out
        assert "Fallback hit" in out


class TestSearchMemoryToolLegacyFallback:
    """The legacy path remains intact when no ``memory_context_service``."""

    def test_no_services_configured(self, observer):
        """With neither backend service wired, the tool returns the
        explicit configuration-error message rather than raising."""
        t = _make_tool(observer=observer)
        out = t.forward(query="anything")
        assert "Memory search failed" in out
        assert "MemoryService" in out

    def test_legacy_memory_service_path(self, observer):
        """The legacy direct ``memory_service.search_memory`` path still
        produces the historical output format."""
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
        # Legacy format did not render the per-layer section header.
        assert "#### Agent Short-term Memory" not in out

    def test_legacy_exception_returns_graceful_error(self, observer):
        """A failure in the legacy path still surfaces as a soft error."""
        async def _boom(**kwargs):
            raise RuntimeError("backend unreachable")

        service = MagicMock(name="legacy_memory_service")
        service.search_memory = _boom

        t = _make_tool(memory_service=service, observer=observer)
        out = t.forward(query="anything")
        assert "Memory search failed" in out
        assert "backend unreachable" in out