# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Empty sampling compatibility across the real HTTP sender/adapter boundary."""
import pytest

from nexent.core.model_service.profiles.protocol_parameters import ensure_outlet_sampling_rules


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("values", [{"temperature": None}, {"top_p": None},
    {"temperature": None, "top_p": None}, {"temperature": 0, "top_p": None},
    {"temperature": 0.4, "top_p": 0.8}])
@pytest.mark.asyncio
async def test_optional_sampling_reaches_http_peer_without_null(peer, request, asynchronous, values):
    main = request.module
    service, call, profile, limiter, journal, credential_reads = main.setup(peer, "normal")
    profile = ensure_outlet_sampling_rules(profile)
    data = profile.model_dump(mode="json")
    data["parameter_values"].update(values)
    profile = profile.__class__.model_validate(data)
    original = profile.model_dump()
    result = await service.ainvoke(call, profile) if asynchronous else service.invoke(call, profile)
    assert result.content_parts == [{"type": "text", "text": "answer"}]
    captured = main.records(journal)
    assert len(captured) == 1
    for key, value in values.items():
        if value is None:
            assert key not in captured[0]["body"]
        else:
            assert captured[0]["body"][key] == value
    assert profile.model_dump() == original
    assert len(credential_reads) == 1
    assert not limiter._entries
