# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Authorized resource conversion is usable independently of an HTTP adapter."""

import pytest
from nexent.core.model_service.resource_conversion import ResourceConverterRegistry, ResourceRequestConverter
from test.sdk.core.model_service.resource_fixtures import resources


@pytest.mark.parametrize("status", ["supported", "unsupported", "unknown"])
@pytest.mark.parametrize("native", [False, True])
def test_conversion_preserves_authorization_and_detaches_inputs(protocol_profile, status, native):
    data = protocol_profile.model_dump()
    data["capabilities"]["tools"]["status"] = status
    profile = protocol_profile.__class__.model_validate(data)
    view = resources()
    before = view.model_dump()
    converted = ResourceRequestConverter(native=native).convert(view, profile, request_id="controlled")
    assert converted.request.request_id == "controlled"
    assert converted.tool_protocol == ("native" if native and status == "supported" else "text_block")
    assert bool(converted.request.tools) == (native and status == "supported")
    assert view.model_dump() == before
    if converted.tool_protocol == "text_block":
        assert all(not message.tool_calls and message.tool_call_id is None for message in converted.request.messages)
    view.history[0].message.content_parts[0]["text"] = "changed"
    assert all(part.get("text") != "changed" for message in converted.request.messages for part in message.content_parts)


def test_converter_registry_rejects_unregistered_modes_and_versions():
    registry = ResourceConverterRegistry()
    for mode in ("code_converter", "native_converter"):
        reference, = registry.references(mode)
        assert registry.resolve(reference).reference == reference
        with pytest.raises(ValueError, match="UNREGISTERED"):
            registry.resolve(reference.model_copy(update={"version": 99}))
    with pytest.raises(ValueError, match="mode"):
        registry.references("arbitrary")
    with pytest.raises(TypeError, match="boolean"):
        ResourceRequestConverter(native="yes")
