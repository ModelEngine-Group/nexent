"""Lazy in-process runtime registry keyed by persisted Agent framework."""

import importlib
from threading import RLock
from typing import Any, Callable

from consts.agent_runtime import normalize_agent_runtime_framework


RuntimeFactory = Callable[[], Any]

_FACTORY_PATHS = {
    "smolagents": ".providers.smolagents:create_runtime",
    "openjiuwen": ".providers.openjiuwen_in_process:create_runtime",
}
_instances: dict[str, Any] = {}
_lock = RLock()


def _load_factory(path: str) -> RuntimeFactory:
    module_name, attribute = path.split(":", 1)
    module = importlib.import_module(module_name, package=__package__)
    factory = getattr(module, attribute)
    if not callable(factory):
        raise TypeError(f"Runtime factory is not callable: {path}")
    return factory


def get_agent_runtime(framework: str):
    """Return one lazily constructed provider without loading the other framework."""
    normalized = normalize_agent_runtime_framework(framework, default=None)
    if normalized is None:
        raise ValueError("runtime_framework is required before Agent execution.")
    with _lock:
        instance = _instances.get(normalized)
        if instance is None:
            instance = _load_factory(_FACTORY_PATHS[normalized])()
            _instances[normalized] = instance
        return instance


def initialized_runtime_frameworks() -> tuple[str, ...]:
    """Return initialized provider names without causing imports."""
    with _lock:
        return tuple(sorted(_instances))


async def shutdown_initialized_runtimes() -> None:
    """Shutdown only providers that were selected during this process lifetime."""
    with _lock:
        instances = list(_instances.values())
    for instance in instances:
        await instance.shutdown()


def reset_runtime_registry_for_test() -> None:
    """Clear cached providers for isolated unit tests."""
    with _lock:
        _instances.clear()


__all__ = [
    "get_agent_runtime",
    "initialized_runtime_frameworks",
    "reset_runtime_registry_for_test",
    "shutdown_initialized_runtimes",
]
