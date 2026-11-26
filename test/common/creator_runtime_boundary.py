# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Isolate creator worker/storage collaborators in endpoint contract UT."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock


def isolate_creator_runtime(monkeypatch, execution):
    """Keep real turn orchestration while replacing managed I/O boundaries."""
    control = SimpleNamespace(
        generation="endpoint-test-generation",
        admit=AsyncMock(),
        cancel=Mock(),
        close_transport=Mock(),
        guard_preparation=Mock(return_value=None),
    )
    monkeypatch.setattr(execution, "CreatorControl", Mock(return_value=control))
    monkeypatch.setattr(execution, "claim_creator", AsyncMock(return_value="reservation"))
    monkeypatch.setattr(execution, "claim_request", AsyncMock(return_value=True))
    monkeypatch.setattr(execution, "release_request", AsyncMock())
    monkeypatch.setattr(
        execution, "run_blocking",
        AsyncMock(side_effect=lambda _name, function, *args, **kwargs: function(*args, **kwargs)),
    )
    save = Mock(return_value=101)
    checkpoint = Mock(side_effect=lambda stream, **kwargs: stream)
    launch = AsyncMock(side_effect=lambda stream, **kwargs: stream)
    monkeypatch.setattr(execution, "save_message", save)
    monkeypatch.setattr(execution, "checkpoint_creator_stream", checkpoint)
    monkeypatch.setattr(execution, "launch_creator", launch)
    monkeypatch.setattr(execution, "runtime_state_service", SimpleNamespace(
        _run_managed=AsyncMock(), mark_run_finished=Mock(),
    ))
    return SimpleNamespace(control=control, save=save, checkpoint=checkpoint, launch=launch)
