"""Unit tests for the multimodal adapter root ABC and ModelInfo."""

import pytest
from nexent.core.gateway.model_context import VLMContext
from nexent.core.gateway.multimodal_adapter import ModelInfo, MultimodalAdapter


class _ConcreteAdapter(MultimodalAdapter):
    """Minimal concrete adapter for instance-level tests."""

    modality = "vlm"
    factory = "openai"

    async def invoke(self, request):
        return ("invoke", request)

    async def stream(self, request):
        return ("stream", request)

    async def health_check(self):
        return True

    def get_model_info(self):
        return ModelInfo(
            model_id=self._context.model_name,
            display_name="dummy",
            provider=self.factory,
            capabilities={"image": True},
        )


def _make_context(**overrides):
    fields = {
        "model_name": "dummy-model",
        "base_url": "https://api.example.com",
        "api_key": "sk-key",
        "modality": "vlm",
        "factory": "openai",
    }
    fields.update(overrides)
    return VLMContext(**fields)


def test_model_info_declaration():
    info = ModelInfo(
        model_id="dummy-model",
        display_name="Dummy VLM",
        provider="openai",
        capabilities={"image": True, "audio": False},
    )

    assert info.model_id == "dummy-model"
    assert info.display_name == "Dummy VLM"
    assert info.provider == "openai"
    assert info.capabilities == {"image": True, "audio": False}


def test_init_stores_context():
    context = _make_context()
    adapter = _ConcreteAdapter(context)

    assert adapter._context is context


@pytest.mark.asyncio
async def test_abstract_contract_methods_raise_not_implemented():
    saved_abstractmethods = MultimodalAdapter.__abstractmethods__
    MultimodalAdapter.__abstractmethods__ = frozenset()
    try:
        adapter = MultimodalAdapter(_make_context())
        adapter.modality = "vlm"

        with pytest.raises(NotImplementedError):
            await adapter.invoke({"media": "request"})
        with pytest.raises(NotImplementedError, match="does not support streaming"):
            await adapter.stream({"media": "request"})
        with pytest.raises(NotImplementedError):
            await adapter.health_check()
        with pytest.raises(NotImplementedError):
            adapter.get_model_info()
    finally:
        MultimodalAdapter.__abstractmethods__ = saved_abstractmethods