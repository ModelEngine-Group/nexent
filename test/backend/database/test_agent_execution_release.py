# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Validate the Runtime fence for disabled Agent versions."""

from contextlib import nullcontext
from unittest.mock import MagicMock

import pytest

from infrastructure.rdb import agent_execution


@pytest.mark.parametrize("disabled", [True, False, None])
def test_mark_running_observes_the_release_row_before_recording_a_version(monkeypatch, disabled):
    session = MagicMock()
    session.scalar.return_value = disabled
    session.execute.return_value.rowcount = 1
    monkeypatch.setattr(agent_execution, "get_db_session", lambda: nullcontext(session))
    identity = agent_execution.RunIdentity("tenant-a", "owner", 5, "a" * 32)

    assert agent_execution.mark_running(identity, {"agent_id": 7, "agent_version_no": 2}) is (disabled is not True)
    lookup, params = session.scalar.call_args.args
    assert "FOR SHARE" in str(lookup)
    assert params == {"tenant": "tenant-a", "agent": 7, "version": 2}
    assert session.execute.call_count == (0 if disabled is True else 1)
