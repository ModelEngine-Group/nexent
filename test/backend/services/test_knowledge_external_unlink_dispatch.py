# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""One local unlink attempt reports uncertain commits without replaying writes."""

from unittest.mock import Mock

import pytest
from management.services.knowledge_base import external_unlink as service
from nexent.storage.errors import OutcomeUnknown, ScopeDenied


@pytest.fixture
def dispatch(monkeypatch):
    async def blocking(name, fn, *args, **kwargs):
        assert kwargs == {'lane': 'control-io', 'owner': 'management.knowledge_base'}
        assert args[-1].remaining() <= 10
        return fn(*args)

    monkeypatch.setattr(service, 'run_blocking', blocking)
    selector = Mock(return_value=[1, 2, 3])
    writer = Mock(side_effect=[{'knowledge_records_deleted': 1}, OutcomeUnknown(), ScopeDenied()])
    monkeypatch.setattr(service, '_select', selector)
    monkeypatch.setattr(service, '_unlink', writer)
    return selector, writer


async def test_unknown_write_is_pending_not_success_and_never_replayed(dispatch):
    selector, writer = dispatch
    assert await service.unlink_datamate_for_tenant('target', 'admin') == {
        'total': 3, 'succeeded': 1, 'failed': 1, 'pending': 1}
    assert [call.args[0] for call in writer.call_args_list] == [1, 2, 3]
    assert all(call.args[1].user_id == 'admin' and call.args[1].tenant_id == 'target'
               for call in writer.call_args_list)
    selector.assert_called_once()


async def test_selection_failure_is_logged_without_fake_counts_or_cleanup(dispatch, caplog):
    selector, writer = dispatch
    selector.side_effect = ScopeDenied()
    assert await service.unlink_datamate_for_tenant('target', 'admin') is None
    writer.assert_not_called()
    assert 'datamate_unlink_selection_failed' in caplog.text
