"""Unit tests for modality-specific gateway construction contexts."""

from nexent.core.gateway.model_context import LLMContext, VLMContext


def test_context_carries_full_connection_config():
    """Guards the fields the removed gateway cache key used to drop.

    ``base_url``, ``api_key``, ``ssl_verify`` and ``timeout_seconds`` are part
    of a model's identity: two records sharing a repo/name but differing here
    are different endpoints, so they must never resolve to one shared adapter.
    """
    context = VLMContext(
        model_name="qwen-vl-max",
        base_url="https://api.example.com",
        api_key="sk-key",
        modality="vlm",
        factory="openai",
        tenant_id="tenant-1",
        slot="vlm3",
        ssl_verify=False,
        timeout_seconds=12.5,
    )

    assert context.base_url == "https://api.example.com"
    assert context.api_key == "sk-key"
    assert context.ssl_verify is False
    assert context.timeout_seconds == 12.5
    assert (context.tenant_id, context.slot) == ("tenant-1", "vlm3")


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
