# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Progress is bounded, run-scoped and optional when Redis is unavailable."""

import json
from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from services import nl2agent_retrieval_progress as progress
from services.nl2agent_state_service import ResourceScope


@pytest.fixture
def scope():
    return ResourceScope("tenant", "user", 42, "7", "run")


@pytest.mark.parametrize("completed,total,valid", [(0, 2, True), (2, 2, True), (-1, 2, False),
    (3, 2, False), (True, 2, False), (None, 2, False), (0, 0, False)])
def test_publisher_bounds_event_history_and_reports_only_valid_counts(mocker, scope, completed, total, valid):
    client = MagicMock()
    client.incr.return_value = 3
    mocker.patch.object(progress, "get_redis_client", return_value=client)
    progress.ProgressPublisher(scope).publish("searching_text", completed, total)
    key = progress._key(scope)
    pipe = client.pipeline.return_value
    event = json.loads(pipe.rpush.call_args.args[1])
    assert event == {"event": "resource_retrieval_progress", "agent_id": 42, "run_id": "run", "sequence": 3,
                     "stage": "searching_text", **({"completed": completed, "total": total} if valid else {})}
    pipe.ltrim.assert_called_once_with(key, -32, -1)
    assert pipe.expire.call_args_list[0].args == (key, 900)
    assert pipe.expire.call_args_list[1].args == (key + ":sequence", 900)
    pipe.execute.assert_called_once()


@pytest.mark.parametrize("failure", ["missing", "unavailable", "corrupt"])
def test_optional_progress_failures_do_not_break_workflow(mocker, scope, failure):
    client = MagicMock()
    if failure == "missing":
        client = None
    elif failure == "unavailable":
        client.incr.side_effect = client.lrange.side_effect = client.delete.side_effect = ConnectionError()
    else:
        client.lrange.return_value = ["broken json"]
    mocker.patch.object(progress, "get_redis_client", return_value=client)
    progress.ProgressPublisher(scope).publish("fallback_to_text")
    assert progress.read_progress(scope, 0) == []
    progress.clear_progress(scope)


def test_read_orders_new_events_and_cleanup_deletes_both_keys(mocker, scope):
    client = MagicMock()
    client.lrange.return_value = [json.dumps({"sequence": number}) for number in (3, 1, 2)]
    mocker.patch.object(progress, "get_redis_client", return_value=client)
    assert progress.read_progress(scope, 1) == [{"sequence": 2}, {"sequence": 3}]
    progress.clear_progress(scope)
    client.delete.assert_called_once_with(progress._key(scope), progress._key(scope) + ":sequence")
    assert progress._key(scope) != progress._key(replace(scope, run_id="other"))
    with pytest.raises(ValueError, match="Unknown retrieval stage"):
        progress.ProgressPublisher(scope).publish("untrusted-stage")
