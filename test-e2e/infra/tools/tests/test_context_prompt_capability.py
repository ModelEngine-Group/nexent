# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Keep capability prerequisites distinct from product validation failures."""
import importlib.util
from pathlib import Path
import sys

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'test-e2e/infra/automation'))
spec = importlib.util.spec_from_file_location('prompt_capability_case', ROOT / 'test-e2e/cases/AGT-012/test.py')
case = importlib.util.module_from_spec(spec)
spec.loader.exec_module(case)


@pytest.mark.parametrize('status,calls,message,blocked', [
    (400, 0, 'Auto optimize from debug requires Jiuwen SDK to be enabled.', True),
    (400, 1, 'Auto optimize from debug requires Jiuwen SDK to be enabled.', False),
    (400, 0, 'Invalid feedback', False),
    (500, 0, 'Internal server error, please try again later.', False),
])
def test_only_explicit_capability_rejection_blocks(status, calls, message, blocked):
    response = httpx.Response(status, json={'message': message},
                              request=httpx.Request('POST', 'http://fixture/prompt/optimize/from_debug'))
    if blocked:
        with pytest.raises(case.AssetDependencyError, match='NEXENT_ENABLE_JIUWEN_SDK'):
            case.require_prompt_sdk(response, {'calls': calls})
    else:
        case.require_prompt_sdk(response, {'calls': calls})
        with pytest.raises(AssertionError):
            case.assert_fault(response, {'calls': calls, 'mode': 'unavailable'}, {}, {}, 1, 'unavailable')
