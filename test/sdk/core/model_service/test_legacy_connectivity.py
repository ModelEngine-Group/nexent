# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Connection-only probes retain outlet defaults and cancellation semantics."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [None, RuntimeError('unavailable')])
async def test_probe_uses_saved_parameters_without_invented_output_cap(openai_profile, failure):
    invoke = AsyncMock(side_effect=failure)
    model = LegacyChatModel(openai_profile, SimpleNamespace(ainvoke=invoke))
    assert await model.check_connectivity() is (failure is None)
    request, profile = invoke.call_args.args
    assert not request.stream and not request.tools
    assert request.messages[0].content_parts == [{'type': 'text', 'text': 'Hello'}]
    assert profile.parameter_values == openai_profile.parameter_values
    assert invoke.call_args.kwargs['scope'] is model.cancellation_scope
    assert model.last_response_diagnostics is None


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [RunTerminated(), asyncio.CancelledError()])
async def test_probe_does_not_convert_cancellation_to_unavailable(openai_profile, failure):
    invoke = AsyncMock(side_effect=failure)
    model = LegacyChatModel(openai_profile, SimpleNamespace(ainvoke=invoke))
    with pytest.raises(type(failure)):
        await model.check_connectivity()
    assert invoke.await_count == 1
