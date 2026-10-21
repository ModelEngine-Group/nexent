# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Explicit versioned adapter registration without HTTP or service orchestration."""

import pytest
from nexent.core.model_service.adapters.openai_chat import ModelAdapterError, OpenAIChatAdapter
from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.registry import AdapterRegistry


def test_default_registry_resolves_only_real_explicit_versioned_adapter():
    registry = AdapterRegistry()
    adapter = registry.resolve(VersionedReference(ref="openai_chat_v1", version=1))
    assert isinstance(adapter, OpenAIChatAdapter)
    assert registry.references == (adapter.reference,)
    assert registry.protocol_references == (adapter.protocol_reference,)
    for ref in [
        VersionedReference(ref="openai_chat_v1", version=2),
        VersionedReference(ref="os.system", version=1),
        "openai_chat_v1",
    ]:
        with pytest.raises(ModelAdapterError, match="^MODEL_ADAPTER_UNREGISTERED$"):
            registry.resolve(ref)


def test_registration_directory_is_detached_and_duplicates_are_rejected():
    adapter = OpenAIChatAdapter()
    source = [adapter]
    registry = AdapterRegistry(source)
    source.clear()
    assert registry.resolve(adapter.reference) is adapter
    with pytest.raises(TypeError):
        registry._entries[("new", 1)] = adapter
    with pytest.raises(
        ModelAdapterError, match="^MODEL_ADAPTER_REGISTRATION_DUPLICATE$"
    ):
        AdapterRegistry([adapter, adapter])


def test_empty_or_invalid_directory_does_not_claim_unimplemented_adapters():
    assert AdapterRegistry([]).references == ()
    assert AdapterRegistry([]).protocol_references == ()
    with pytest.raises(ModelAdapterError, match="^MODEL_ADAPTER_REGISTRATION_INVALID$"):
        AdapterRegistry([object()])
    incomplete = type(
        "Incomplete",
        (),
        {"reference": VersionedReference(ref="not_implemented", version=1)},
    )()
    with pytest.raises(ModelAdapterError, match="^MODEL_ADAPTER_REGISTRATION_INVALID$"):
        AdapterRegistry([incomplete])

