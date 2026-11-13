# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from runtime import identity, sandbox_runtime


@pytest.mark.parametrize('distributed,lost', [(False, True), (True, False), (True, True)])
def test_admission_still_rejects_lost_coordination_without_an_exit_controller(monkeypatch, distributed, lost):
    monkeypatch.setattr(identity, 'uses_distributed_runtime', lambda: distributed)
    lookup = Mock(return_value=SimpleNamespace(lost_coordination=SimpleNamespace(is_set=lambda: lost)))
    monkeypatch.setattr(sandbox_runtime, 'get_coordinator', lookup)
    if distributed and lost:
        with pytest.raises(HTTPException) as error:
            sandbox_runtime.require_business_admission()
        assert error.value.status_code == 503
        assert error.value.headers == {'Retry-After': '1'}
    else:
        sandbox_runtime.require_business_admission()
    assert lookup.call_count == int(distributed)
