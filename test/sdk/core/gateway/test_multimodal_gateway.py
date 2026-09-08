"""Unit tests for MultimodalGateway adapter construction and delegation."""

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


def test_get_adapter_builds_a_new_instance_on_every_call():
    gateway = MultimodalGateway(_make_registry())
    context = _make_context()

    first = gateway.get_adapter(context)
    second = gateway.get_adapter(context)

    assert isinstance(first, _FakeAdapter)
    assert first is not second
    assert first._context is context
    assert second._context is context


def test_get_adapter_builds_separate_instances_for_different_models():
    gateway = MultimodalGateway(_make_registry())

    first = gateway.get_adapter(_make_context("model-a"))
    second = gateway.get_adapter(_make_context("model-b"))

    assert first is not second


def test_get_adapter_does_not_share_endpoint_or_credentials():
    """Regression guard for the removed identity-keyed adapter cache.

    The old key was ``(tenant_id, modality, slot, model_name, factory)``, so
    rotating an api_key or repointing base_url on a model record kept serving
    the adapter built from the previous config.
    """
    gateway = MultimodalGateway(_make_registry())

    stale = gateway.get_adapter(_make_context())
    rotated_context = _make_context()
    rotated_context.base_url = "https://rotated.example.com"
    rotated_context.api_key = "sk-rotated"
    rotated = gateway.get_adapter(rotated_context)

    assert stale is not rotated
    assert rotated._context.base_url == "https://rotated.example.com"
    assert rotated._context.api_key == "sk-rotated"
    assert stale._context.api_key == "sk-key"


def test_gateway_keeps_no_adapter_cache():
    gateway = MultimodalGateway(_make_registry())
    gateway.get_adapter(_make_context())

    assert not hasattr(gateway, "_adapter_cache")
    assert not hasattr(gateway, "invalidate")


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
