# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Summary admission snapshots reject credentials and ambiguous terminal outcomes."""

import pytest
from contracts.knowledge_summary import SummarySchedule
from pydantic import ValidationError


def snapshot():
    return {'schema_version':1,'user_id':'actual-user','configuration_id':'a'*32,
        'attempt':{'attempt_id':'b'*32,'user_id':'actual-user','data_revision':'c'*64,'knowledge_revision':'d'*64,
                   'model_id':5,'started_at':'2026-11-18T01:00:00+00:00','status':'admitted'}}


@pytest.mark.parametrize('change', ['credential','version','actor','model','naive-time','completed','failed','error'])
def test_invalid_or_sensitive_state_is_not_persistable(change):
    value=snapshot()
    if change=='credential':value['api_key']='forbidden'
    elif change=='version':value['schema_version']=2
    elif change=='actor':value['user_id']=''
    elif change=='model':value['attempt']['model_id']=True
    elif change=='naive-time':value['attempt']['started_at']='2026-11-18T01:00:00'
    elif change=='completed':value['attempt']['status']='completed'
    elif change=='failed':value['attempt'].update(status='failed',completed_at='2026-11-18T02:00:00+00:00')
    else:value['attempt']['error_code']='UNEXPECTED'
    with pytest.raises(ValidationError):SummarySchedule.model_validate(value)


def test_known_completed_and_failed_outcomes_round_trip_without_provider_setup():
    for status,error in [('completed',None),('failed','MODEL_FAILED')]:
        value=snapshot()
        value['attempt'].update(status=status,error_code=error,completed_at='2026-11-18T02:00:00+00:00')
        schedule=SummarySchedule.model_validate(value)
        assert SummarySchedule.model_validate_json(schedule.model_dump_json())==schedule


async def test_expired_settings_request_does_not_open_storage(monkeypatch, caplog):
    from time import monotonic
    from unittest.mock import Mock

    from management.services.knowledge_base import summary_settings
    from nexent.storage.errors import DeadlineExceeded
    from nexent.storage.models import OperationContext

    ports = Mock(side_effect=AssertionError('Expired request opened storage'))
    monkeypatch.setattr(summary_settings, 'summary_ports', ports)
    with pytest.raises(DeadlineExceeded):
        await summary_settings.configure_summary_schedule('kb-one','3h','tenant-a','user-a',
            context=OperationContext('expired-summary',monotonic()-1))
    ports.assert_not_called()
    assert 'knowledge_summary_settings_timeout' in caplog.text and 'threshold_seconds=0.0' in caplog.text
