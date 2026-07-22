import asyncio
import os
from pathlib import Path
import subprocess
import sys

import pytest

from backend.services.agent_runtime import registry


class FakeRuntime:
    def __init__(self, name: str) -> None:
        self.name = name
        self.shutdown_calls = 0

    async def shutdown(self) -> None:
        self.shutdown_calls += 1


@pytest.fixture(autouse=True)
def reset_registry():
    registry.reset_runtime_registry_for_test()
    yield
    registry.reset_runtime_registry_for_test()


def test_registry_lazily_constructs_only_selected_framework(monkeypatch):
    loaded_paths = []
    created = {}

    def load_factory(path):
        loaded_paths.append(path)

        def factory():
            runtime = FakeRuntime(path)
            created[path] = runtime
            return runtime

        return factory

    monkeypatch.setattr(registry, "_load_factory", load_factory)

    smolagents = registry.get_agent_runtime("smolagents")

    assert loaded_paths == [registry._FACTORY_PATHS["smolagents"]]
    assert registry.initialized_runtime_frameworks() == ("smolagents",)
    assert registry.get_agent_runtime("smolagents") is smolagents
    assert loaded_paths == [registry._FACTORY_PATHS["smolagents"]]

    openjiuwen = registry.get_agent_runtime("openjiuwen")

    assert openjiuwen is created[registry._FACTORY_PATHS["openjiuwen"]]
    assert loaded_paths == [
        registry._FACTORY_PATHS["smolagents"],
        registry._FACTORY_PATHS["openjiuwen"],
    ]
    assert registry.initialized_runtime_frameworks() == ("openjiuwen", "smolagents")


def test_registry_rejects_unknown_framework_without_fallback(monkeypatch):
    def load_factory(path):
        pytest.fail(f"Unexpected provider load: {path}")

    monkeypatch.setattr(registry, "_load_factory", load_factory)

    with pytest.raises(ValueError, match="Unsupported runtime_framework"):
        registry.get_agent_runtime("unknown")

    assert registry.initialized_runtime_frameworks() == ()


def test_shutdown_only_touches_initialized_runtimes(monkeypatch):
    runtimes = {}

    def load_factory(path):
        def factory():
            runtimes[path] = FakeRuntime(path)
            return runtimes[path]

        return factory

    monkeypatch.setattr(registry, "_load_factory", load_factory)
    registry.get_agent_runtime("smolagents")

    asyncio.run(registry.shutdown_initialized_runtimes())

    assert set(runtimes) == {registry._FACTORY_PATHS["smolagents"]}
    assert runtimes[registry._FACTORY_PATHS["smolagents"]].shutdown_calls == 1


def test_backend_adapter_package_does_not_import_openjiuwen_at_startup():
    root = Path(__file__).resolve().parents[4]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(root / "backend"), str(root / "sdk")]
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import adapters; assert not any("
            "name == 'openjiuwen' or name.startswith('openjiuwen.') for name in sys.modules)",
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
