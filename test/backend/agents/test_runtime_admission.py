# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from runtime import sandbox_runtime


@pytest.mark.parametrize("distributed,lost", [(False, True), (True, False), (True, True)])
def test_admission_rejects_lost_agentos_coordination(monkeypatch, distributed, lost):
    state = Mock()
    state.is_set.return_value = lost
    coordinator = SimpleNamespace(lost_coordination=state) if distributed else None
    monkeypatch.setattr(sandbox_runtime, "get_coordinator", lambda: coordinator)
    if distributed and lost:
        with pytest.raises(HTTPException) as error:
            sandbox_runtime.check_agentos_admission()
        assert error.value.status_code == 503
        assert error.value.detail == {"code": "AGENTOS_SANDBOX_OWNERSHIP_UNKNOWN"}
    else:
        sandbox_runtime.check_agentos_admission()
    assert state.is_set.call_count == int(distributed)
