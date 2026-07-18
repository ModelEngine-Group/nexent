"""Low-dependency tests for the ContextManager runtime."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4] / "sdk" / "nexent"
_BOOTSTRAP_MODULES = (
    "nexent",
    "nexent.core",
    "nexent.core.agents",
    "nexent.core.agents.context",
    "nexent.core.agents.context.manager",
    "nexent.core.agents.context.models",
    "nexent.core.agents.context.runtime",
    "nexent.core.agents.context.summary_step",
    "nexent.core.context_runtime",
    "nexent.core.context_runtime.contracts",
    "smolagents.memory",
    "smolagents.models",
    "smolagents.tools",
)


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _bootstrap():
    snapshot = {name: sys.modules.get(name) for name in _BOOTSTRAP_MODULES}
    for name, path in (
        ("nexent", ROOT),
        ("nexent.core", ROOT / "core"),
        ("nexent.core.agents", ROOT / "core" / "agents"),
        ("nexent.core.agents.context", ROOT / "core" / "agents" / "context"),
        ("nexent.core.context_runtime", ROOT / "core" / "context_runtime"),
    ):
        package = types.ModuleType(name)
        package.__path__ = [str(path)]
        sys.modules[name] = package

    memory_module = types.ModuleType("smolagents.memory")

    class SystemPromptStep:
        def __init__(self, system_prompt):
            self.system_prompt = system_prompt

        def to_messages(self):
            return [{"role": "system", "content": self.system_prompt}]

    memory_module.SystemPromptStep = SystemPromptStep
    memory_module.AgentMemory = type("AgentMemory", (), {})
    memory_module.MemoryStep = type("MemoryStep", (), {})
    sys.modules["smolagents.memory"] = memory_module

    models_module = types.ModuleType("smolagents.models")
    models_module.ChatMessage = type("ChatMessage", (), {})
    models_module.Model = type("Model", (), {})
    sys.modules["smolagents.models"] = models_module
    tools_module = types.ModuleType("smolagents.tools")
    tools_module.Tool = type("Tool", (), {})
    sys.modules["smolagents.tools"] = tools_module

    manager_module = types.ModuleType("nexent.core.agents.context.manager")
    manager_module.ContextManager = type("ContextManager", (), {})
    sys.modules[manager_module.__name__] = manager_module
    models_module = types.ModuleType("nexent.core.agents.context.models")
    models_module.ContextItem = type("ContextItem", (), {})
    models_module.ContextItemInput = type("ContextItemInput", (), {})
    sys.modules[models_module.__name__] = models_module
    summary_module = types.ModuleType("nexent.core.agents.context.summary_step")
    summary_module.ManagedRunContext = type("ManagedRunContext", (), {})
    sys.modules[summary_module.__name__] = summary_module

    _load("nexent.core.context_runtime.contracts", "core/context_runtime/contracts.py")
    managed = _load("nexent.core.agents.context.runtime", "core/agents/context/runtime.py")
    return managed, snapshot


def _restore(snapshot):
    for name in _BOOTSTRAP_MODULES:
        previous = snapshot.get(name)
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


class _Memory:
    def __init__(self):
        self.system_prompt = None
        self.steps = []


class _ContextManager:
    class _Config:
        chars_per_token = 1.5
        max_observation_length = 0
        token_threshold = 1024

    config = _Config()

    def __init__(self):
        self.calls = []

    def prepare_run_context(self, *, memory, fallback_system_prompt, items=None):
        self.calls.append(("prepare_run_context", fallback_system_prompt, items))
        memory.system_prompt = types.SimpleNamespace(
            to_messages=lambda: [{"role": "system", "content": "managed stable"}]
        )
        return types.SimpleNamespace(
            stable_messages=({"role": "system", "content": "managed stable"},),
            dynamic_messages=(),
            selected_item_types=tuple(str(getattr(item, "type", "unknown")) for item in items or ()),
            items=tuple(items or ()),
        )

    def assemble_final_context(self, **kwargs):
        self.calls.append(("assemble_final_context", kwargs["purpose"], kwargs.get("tools")))
        contracts = sys.modules["nexent.core.context_runtime.contracts"]
        return contracts.FinalContext(
            messages=[{"role": "system", "content": kwargs["purpose"]}],
            tools=list(kwargs.get("tools") or ()),
            evidence=contracts.ContextEvidence(stable_message_count=1),
        )

    def get_step_compression_stats(self):
        return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_hits": 0, "cache_types": []}

    def render_memory_messages(self, memory):
        return []


def test_managed_runtime_is_thin_context_manager_adapter():
    managed_module, snapshot = _bootstrap()
    try:
        manager = _ContextManager()
        item = types.SimpleNamespace(type="system_prompt")
        runtime = managed_module.ManagedContextRuntime(manager, items=[item])
        memory = _Memory()

        runtime.prepare_run(memory=memory, fallback_system_prompt="fallback")
        final = runtime.prepare_step(
            model=None,
            memory=memory,
            current_run_start_idx=0,
            tools=[{"name": "z"}],
        )
        final_answer = runtime.prepare_final_answer(
            model=None,
            memory=memory,
            current_run_start_idx=0,
            task="task",
            final_answer_templates={"final_answer": {}},
        )

        assert manager.calls == [
            ("prepare_run_context", "fallback", [item]),
            ("assemble_final_context", "step", [{"name": "z"}]),
            ("assemble_final_context", "final_answer", None),
        ]
        assert final.messages == [{"role": "system", "content": "step"}]
        assert final_answer.messages == [{"role": "system", "content": "final_answer"}]
        evidence = runtime.finalize_evidence(status="completed")
        assert evidence.model_call_count == 2
        assert evidence.loop_status == "completed"
        assert runtime.finalize_evidence(status="error") is evidence
    finally:
        _restore(snapshot)

def test_managed_runtime_replaces_items_without_mutating_context_manager():
    managed_module, snapshot = _bootstrap()
    try:
        manager = _ContextManager()
        runtime = managed_module.ManagedContextRuntime(manager)
        item = types.SimpleNamespace(type="memory")

        runtime.replace_items([item])
        runtime.prepare_run(memory=_Memory(), fallback_system_prompt="fallback")

        assert manager.calls[0] == ("prepare_run_context", "fallback", [item])
    finally:
        _restore(snapshot)


def test_managed_runtime_uses_item_snapshot_without_explicit_prepare_run():
    managed_module, snapshot = _bootstrap()
    try:
        manager = _ContextManager()
        item = types.SimpleNamespace(type="knowledge")
        runtime = managed_module.ManagedContextRuntime(manager, items=[item])

        runtime.prepare_step(model=None, memory=_Memory(), current_run_start_idx=0)

        assert manager.calls[0] == ("prepare_run_context", "", [item])
    finally:
        _restore(snapshot)
