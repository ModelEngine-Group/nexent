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
    "nexent.core.context_runtime",
    "nexent.core.context_runtime.managed",
    "nexent.core.context_runtime.contracts",
    "nexent.core.context_runtime.managed.runtime",
    "smolagents.memory",
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
        ("nexent.core.context_runtime", ROOT / "core" / "context_runtime"),
        ("nexent.core.context_runtime.managed", ROOT / "core" / "context_runtime" / "managed"),
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
    sys.modules["smolagents.memory"] = memory_module
    _load("nexent.core.context_runtime.contracts", "core/context_runtime/contracts.py")
    managed = _load("nexent.core.context_runtime.managed.runtime", "core/context_runtime/managed/runtime.py")
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

    def prepare_run_context(self, *, memory, fallback_system_prompt, components=None):
        self.calls.append(("prepare_run_context", fallback_system_prompt, components))
        memory.system_prompt = types.SimpleNamespace(
            to_messages=lambda: [{"role": "system", "content": "managed stable"}]
        )
        return types.SimpleNamespace(
            stable_messages=({"role": "system", "content": "managed stable"},),
            dynamic_messages=(),
            selected_component_types=tuple(getattr(component, "component_type", "unknown") for component in components or ()),
            components=tuple(components or ()),
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


def test_managed_runtime_is_thin_context_manager_adapter():
    managed_module, snapshot = _bootstrap()
    try:
        manager = _ContextManager()
        component = types.SimpleNamespace(component_type="system_prompt")
        runtime = managed_module.ManagedContextRuntime(manager, components=[component])
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
            ("prepare_run_context", "fallback", [component]),
            ("assemble_final_context", "step", [{"name": "z"}]),
            ("assemble_final_context", "final_answer", None),
        ]
        assert final.messages == [{"role": "system", "content": "step"}]
        assert final_answer.messages == [{"role": "system", "content": "final_answer"}]
    finally:
        _restore(snapshot)

def test_managed_runtime_replaces_components_without_mutating_context_manager():
    managed_module, snapshot = _bootstrap()
    try:
        manager = _ContextManager()
        runtime = managed_module.ManagedContextRuntime(manager)
        component = types.SimpleNamespace(component_type="memory")

        runtime.replace_components([component])
        runtime.prepare_run(memory=_Memory(), fallback_system_prompt="fallback")

        assert manager.calls[0] == ("prepare_run_context", "fallback", [component])
    finally:
        _restore(snapshot)


def test_managed_runtime_uses_component_snapshot_without_explicit_prepare_run():
    managed_module, snapshot = _bootstrap()
    try:
        manager = _ContextManager()
        component = types.SimpleNamespace(component_type="knowledge")
        runtime = managed_module.ManagedContextRuntime(manager, components=[component])

        runtime.prepare_step(model=None, memory=_Memory(), current_run_start_idx=0)

        assert manager.calls[0] == ("prepare_run_context", "", [component])
    finally:
        _restore(snapshot)
