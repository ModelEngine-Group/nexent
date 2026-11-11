# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Native generations retain protocol structure without changing legacy trace output."""

import pytest
from test_model_service import Sender, complete
from test_model_service import setup as setup  # noqa: PLC0414 - Expose shared pytest fixture.


@pytest.mark.parametrize("purpose", ["native_agent", "agent"])
def test_completed_trace_output_preserves_native_contract_only_in_native_mode(setup, monkeypatch, purpose):
    profile, request, _limiter, service = setup
    sender = Sender([complete()])
    model = service(sender)
    captured = []
    monkeypatch.setattr(model._monitoring, "set_openinference_output", captured.append)
    result = model.invoke(request.model_copy(update={"purpose": purpose}), profile)
    assert captured == [result.model_dump(mode="json") if purpose == "native_agent" else "answer"]
    assert sender.closed == 0  # Nonstreaming sender has no stream lifetime.
