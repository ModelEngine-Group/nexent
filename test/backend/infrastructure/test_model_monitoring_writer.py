# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Monitoring records must carry the model configuration id when resolvable."""

from unittest.mock import MagicMock

import pytest

from infrastructure.rdb import model_monitoring
from infrastructure.rdb.model_monitoring import (
    resolve_model_id,
    write_model_monitoring_record,
)


@pytest.fixture(autouse=True)
def _clear_model_id_cache():
    model_monitoring._model_id_cache.clear()
    yield
    model_monitoring._model_id_cache.clear()


def _session(rows_per_query):
    session = MagicMock()
    responses = [MagicMock(all=MagicMock(return_value=rows)) for rows in rows_per_query]
    session.execute.side_effect = responses
    return session


def _record(**overrides):
    record = {
        "tenant_id": "tenant-a",
        "model_type": "llm",
        "model_name": "deepseek-ai/DeepSeek-V4-Flash",
        "display_name": "DeepSeek-V4-Flash",
    }
    record.update(overrides)
    return record


def test_explicit_model_id_is_preserved():
    session = MagicMock()

    assert resolve_model_id(session, _record(model_id=9)) == 9
    session.execute.assert_not_called()


def test_display_name_resolves_unique_configuration():
    session = _session([[(3,)]])

    assert resolve_model_id(session, _record()) == 3


def test_ambiguous_display_name_stays_null():
    session = _session([[(1,), (2,)]])

    assert resolve_model_id(session, _record()) is None


def test_embedding_path_is_used_when_display_name_is_the_model_path():
    session = _session([[], [(2,)]])

    record = _record(
        model_type="multi_embedding",
        model_name="Qwen/Qwen3-VL-Embedding-8B",
        display_name="Qwen/Qwen3-VL-Embedding-8B",
    )

    assert resolve_model_id(session, record) == 2


def test_rows_without_names_stay_null():
    session = MagicMock()

    assert resolve_model_id(session, _record(display_name="", model_name="")) is None
    session.execute.assert_not_called()


def test_writer_persists_resolved_model_id(mocker):
    session = _session([[(5,)]])
    session_factory = mocker.patch(
        "infrastructure.rdb.client.get_monitoring_db_session")
    session_factory.return_value.__enter__.return_value = session

    write_model_monitoring_record(_record())

    added = session.add.call_args[0][0]
    assert added.model_id == 5
    session.flush.assert_called_once()
