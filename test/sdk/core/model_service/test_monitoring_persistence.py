# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Legacy monitoring keeps writing after the backend package split."""

from unittest.mock import MagicMock

import pytest

from infrastructure.rdb.model_monitoring import ModelMonitoringRecord, write_model_monitoring_record
from nexent.monitor.monitoring import MonitoringRecordBuffer


@pytest.mark.parametrize("size,fail_first", [(0, False), (2, False), (2, True)])
def test_buffer_uses_the_current_model_and_isolates_record_failures(mocker, size, fail_first):
    session = MagicMock()
    factory = mocker.patch("infrastructure.rdb.client.get_monitoring_db_session")
    factory.return_value.__enter__.return_value = session
    mocker.patch("infrastructure.rdb.model_monitoring.resolve_model_id", return_value=17)
    if fail_first:
        session.flush.side_effect = [RuntimeError("isolated record failure"), None]
    batch = [{"model_name": f"model-{index}", "tenant_id": "tenant"} for index in range(size)]

    buffer = MonitoringRecordBuffer.__new__(MonitoringRecordBuffer)
    buffer._write_record = write_model_monitoring_record
    buffer._write_batch(batch)

    assert factory.call_count == session.add.call_count == session.flush.call_count == size
    rows = [call.args[0] for call in session.add.call_args_list]
    assert all(isinstance(row, ModelMonitoringRecord) for row in rows)
    assert [row.model_name for row in rows] == [record["model_name"] for record in batch]
    assert all(row.model_id == 17 for row in rows)
