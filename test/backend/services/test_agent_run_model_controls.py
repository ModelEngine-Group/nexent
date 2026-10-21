# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Model preflight stays ahead of persistence after Agent module splitting."""

from unittest.mock import MagicMock

import pytest

from test.backend.services import test_agent_service as legacy


@pytest.mark.asyncio
@pytest.mark.parametrize('rejected_stage', ['selection', 'controls'])
async def test_model_preflight_rejection_precedes_conversation_writes(monkeypatch, rejected_stage):
    from contracts.exceptions import RunModelControlsError
    from management.services.model import run_controls
    subscription = legacy.agent_subscription
    request = legacy.AgentRequest(agent_id=7, query='fixture', model_id=9)
    stages = []
    error = RunModelControlsError('model_controls_invalid')

    def check(stage):

        def validate(actual_request, tenant, lookup):
            assert actual_request is request
            assert tenant == 'tenant-fixture'
            assert lookup is subscription.search_agent_info_by_agent_id
            stages.append(stage)
            if stage == rejected_stage:
                raise error
        return validate
    monkeypatch.setattr(run_controls, 'validate_agent_model_selection', check('selection'))
    monkeypatch.setattr(run_controls, 'preflight_agent_turn_controls', check('controls'))
    monkeypatch.setattr(subscription, '_resolve_user_tenant_language', lambda **kwargs: ('user-fixture', 'tenant-fixture', 'en'))
    monkeypatch.setattr(subscription, 'prepend_current_time', lambda query, *args, **kwargs: query)
    create = MagicMock(side_effect=AssertionError('Preflight must run before conversation creation'))
    save = MagicMock(side_effect=AssertionError('Preflight must run before message persistence'))
    monkeypatch.setattr(subscription, 'create_new_conversation', create)
    monkeypatch.setattr(subscription, 'save_messages', save)
    with pytest.raises(RunModelControlsError) as raised:
        await subscription.run_agent_stream(request, MagicMock(), user_id='test_user', tenant_id='test_tenant')
    assert raised.value is error
    assert stages == (['selection'] if rejected_stage == 'selection' else ['selection', 'controls'])
    create.assert_not_called()
    save.assert_not_called()
