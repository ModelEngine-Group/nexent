"""Unit tests for modality-specific gateway construction contexts."""

from nexent.core.gateway.model_context import LLMContext, VLMContext


def test_cache_key_uses_empty_defaults():
    context = VLMContext(
        model_name="qwen-vl-max",
        base_url="https://api.example.com",
        api_key="sk-key",
        modality="vlm",
        factory="openai",
    )

    assert context.cache_key() == ("", "vlm", "", "qwen-vl-max", "openai")


def test_cache_key_includes_tenant_and_slot():
    context = VLMContext(
        model_name="qwen-vl-max",
        base_url="https://api.example.com",
        api_key="sk-key",
        modality="vlm",
        factory="openai",
        tenant_id="tenant-1",
        slot="vlm3",
    )

    assert context.cache_key() == ("tenant-1", "vlm", "vlm3", "qwen-vl-max", "openai")


def test_subclass_fields_are_independent():
    llm = LLMContext(
        model_name="gpt-4o",
        base_url="https://api.example.com",
        api_key="sk-key",
        modality="llm",
        factory="openai",
        temperature=0.2,
        stream=True,
    )
    assert llm.temperature == 0.2
    assert llm.stream is True
    assert not hasattr(llm, "capabilities")