"""Unit tests for MultimodalGateway caching and delegation."""

import pytest
from nexent.core.gateway.model_context import VLMContext
from nexent.core.gateway.multimodal_adapter import ModelInfo, MultimodalAdapter
from nexent.core.gateway.multimodal_gateway import MultimodalGateway, get_gateway
from nexent.core.gateway.registry import AdapterRegistry


class _FakeAdapter(MultimodalAdapter):
    """Concrete adapter used to observe gateway delegation."""

    modality = "vlm"
    factory = "fake"

    async def invoke(self, request):
        return ("invoke", request)

    async def stream(self, request):
        return ("stream", request)

    async def health_check(self):
        return True

    def get_model_info(self):
        return ModelInfo(
            model_id=self._context.model_name,
            display_name="fake",
            provider=self.factory,
            capabilities={"image": True},
        )


def _make_registry():
    registry = AdapterRegistry()
    registry.register("fake", "vlm")(_FakeAdapter)
    return registry


def _make_context(model_name="dummy-model"):
    return VLMContext(
        model_name=model_name,
        base_url="https://api.example.com",
        api_key="sk-key",
        modality="vlm",
        factory="fake",
        tenant_id="tenant-1",
        slot="vlm",
    )


def test_get_adapter_builds_and_caches_by_context():
    gateway = MultimodalGateway(_make_registry())
    context = _make_context()

    first = gateway.get_adapter(context)
    second = gateway.get_adapter(context)

    assert isinstance(first, _FakeAdapter)
    assert first is second
    assert first._context is context


def test_get_adapter_builds_separate_instance_for_different_key():
    gateway = MultimodalGateway(_make_registry())

    first = gateway.get_adapter(_make_context("model-a"))
    second = gateway.get_adapter(_make_context("model-b"))

    assert first is not second


def test_gateway_defaults_to_process_registry():
    gateway = MultimodalGateway()
    context = VLMContext(
        model_name="gpt-4o",
        base_url="https://api.example.com",
        api_key="sk-key",
        modality="vlm",
        factory="openai",
    )

    adapter = gateway.get_adapter(context)
    assert adapter.factory == "openai"


@pytest.mark.asyncio
async def test_invoke_delegates_to_adapter(gateway, context):
    result = await gateway.invoke(context, {"media": "request"})

    assert result == ("invoke", {"media": "request"})


@pytest.mark.asyncio
async def test_stream_delegates_to_adapter(gateway, context):
    result = gateway.stream(context, {"media": "request"})

    assert await result == ("stream", {"media": "request"})


@pytest.mark.asyncio
async def test_health_check_delegates_to_adapter(gateway, context):
    assert await gateway.health_check(context) is True


def test_invalidate_single_context(gateway, context):
    cached = gateway.get_adapter(context)
    assert gateway.get_adapter(context) is cached

    gateway.invalidate(context)
    assert gateway.get_adapter(context) is not cached


def test_invalidate_all_contexts(gateway, context):
    other_context = _make_context("model-other")
    first_cached = gateway.get_adapter(context)
    other_cached = gateway.get_adapter(other_context)

    gateway.invalidate()

    assert gateway.get_adapter(context) is not first_cached
    assert gateway.get_adapter(other_context) is not other_cached


def test_get_gateway_is_lazy_singleton():
    from nexent.core.gateway import multimodal_gateway as gateway_module

    gateway_module._gateway = None
    first = get_gateway()
    second = get_gateway()

    assert first is second
    assert isinstance(first, MultimodalGateway)


@pytest.fixture
def gateway():
    return MultimodalGateway(_make_registry())


@pytest.fixture
def context():
    return _make_context()