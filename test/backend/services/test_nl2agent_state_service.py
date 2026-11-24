# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Redis persistence, optimistic retries and scope boundaries for resource cards."""

import json
from dataclasses import replace
from unittest.mock import MagicMock

import pytest
from redis.exceptions import RedisError, WatchError

from contracts.nl2agent_resources import ResourceCardAction
from services import nl2agent_state_service as service


@pytest.fixture
def scope():
    return service.ResourceScope("tenant", "user", 42, "7", "run")


@pytest.fixture
def redis(mocker):
    client = MagicMock()
    mocker.patch.object(service, "get_redis_client", return_value=client)
    client.pipeline.return_value.__enter__.return_value = client.pipeline.return_value
    return client


@pytest.mark.parametrize("raw,expected", [(None, None), ('{"query":"中文"}', {"query": "中文"})])
def test_read_deserializes_state(redis, scope, raw, expected):
    redis.get.return_value = raw
    assert service._read(scope) == expected
    assert redis.get.call_args_list[0].args == (scope.key,)
    assert redis.get.call_count == (1 if raw else 2)


@pytest.mark.parametrize("operation", ["read", "update"])
@pytest.mark.parametrize("failure", ["missing", "connection", "json"])
def test_storage_failures_are_retryable(mocker, redis, scope, operation, failure):
    if failure == "missing":
        mocker.patch.object(service, "get_redis_client", return_value=None)
    elif failure == "connection":
        redis.get.side_effect = RedisError("unavailable")
        redis.pipeline.side_effect = RedisError("unavailable")
    else:
        redis.get.return_value = "broken json"
        redis.pipeline.return_value.get.return_value = "broken json"
    with pytest.raises(service.ResourceStateError) as error:
        if operation == "read":
            service._read(scope)
        else:
            service._update(scope, lambda state: {})
    assert error.value.code == "resource_state_unavailable"
    assert error.value.retryable is True


@pytest.mark.parametrize("raw", [None, '{"version":2}'])
def test_update_persists_callback_result_with_expiration(redis, scope, raw):
    pipe = redis.pipeline.return_value
    pipe.get.return_value = raw
    seen = []

    def change(state):
        seen.append(state)
        return {"version": 3, "query": "中文"}

    result = service._update(scope, change)
    assert seen == [json.loads(raw) if raw else None]
    assert result == {"version": 3, "query": "中文"}
    assert pipe.watch.call_args_list[0].args == (scope.key,)
    assert pipe.watch.call_count == (1 if raw else 2)
    pipe.multi.assert_called_once()
    pipe.set.assert_called_once_with(scope.key, json.dumps(result, ensure_ascii=False),
                                     ex=service.NL2AGENT_RESOURCE_STATE_TTL_SECONDS)
    pipe.execute.assert_called_once()


def test_watch_conflict_rereads_latest_state(redis, scope):
    pipe = redis.pipeline.return_value
    pipe.get.side_effect = ['{"version":1}', '{"version":5}']
    pipe.execute.side_effect = [WatchError(), None]
    assert service._update(scope, lambda state: {"version": state["version"] + 1}) == {"version": 6}
    assert pipe.watch.call_count == pipe.get.call_count == pipe.execute.call_count == 2


def test_watch_retry_budget_is_bounded(redis, scope):
    pipe = redis.pipeline.return_value
    pipe.get.return_value = None
    pipe.execute.side_effect = WatchError()
    with pytest.raises(service.ResourceStateError, match="resource_state_conflict") as error:
        service._update(scope, lambda state: {})
    assert error.value.retryable
    assert pipe.execute.call_count == 4


def test_domain_rejection_never_starts_transaction(redis, scope):
    pipe = redis.pipeline.return_value
    pipe.get.return_value = None

    def reject(state):
        raise service.ResourceStateError("resource_card_stale")

    with pytest.raises(service.ResourceStateError, match="resource_card_stale"):
        service._update(scope, reject)
    pipe.multi.assert_not_called()
    pipe.set.assert_not_called()
    pipe.execute.assert_not_called()


@pytest.mark.asyncio
async def test_async_operations_dispatch_to_control_lane(mocker, scope):
    from unittest.mock import AsyncMock

    dispatch = mocker.patch.object(service, "run_blocking", new=AsyncMock(return_value={"version": 1}))
    assert await service.read_resource_state(scope) == {"version": 1}
    dispatch.assert_awaited_once_with("nl2agent-read-resource-state", service._read, scope,
                                      lane="control-io", owner="services.nl2agent_state_service")
    dispatch.reset_mock()
    change = lambda state: {}
    await service.update_resource_state(scope, change)
    dispatch.assert_awaited_once_with("nl2agent-resource-state", service._update, scope, change,
                                      lane="control-io", owner="services.nl2agent_state_service")


@pytest.mark.parametrize("state,code", [
    (None, "resource_state_expired"),
    ({"conversation_id": "other"}, "resource_state_expired"),
    ({"conversation_id": "7", "run_id": "other"}, "resource_state_conflict"),
])
def test_require_current_run_rejects_stale_scope(scope, state, code):
    with pytest.raises(service.ResourceStateError, match=code):
        service.require_current_run(state, scope)


def test_issue_card_increments_version_without_mutating_previous(scope):
    state = {"conversation_id": "7", "run_id": "run", "version": 2, "card": None}
    assert service.require_current_run(state, scope) is state
    issued = service.issue_card(state, "requirement_resources")
    assert state["version"] == 2 and state["card"] is None
    assert issued["version"] == 3 and issued["card"]["subtype"] == "requirement_resources"
    action = ResourceCardAction(card_id=issued["card"]["id"], state_version=3)
    assert service.require_current_card(issued, scope, "requirement_resources", action) is issued
    with pytest.raises(service.ResourceStateError, match="resource_card_stale"):
        service.require_current_card(issued, scope, "installed_resource_binding", action)
    with pytest.raises(service.ResourceStateError, match="resource_state_expired"):
        service.require_current_card(None, scope, "requirement_resources", action)


def test_conversations_have_independent_keys_but_runs_share_state(scope):
    assert replace(scope, conversation_id="8").key != scope.key
    assert replace(scope, run_id="next").key == scope.key


def test_delayed_other_conversation_cannot_replace_current_card(redis, scope):
    values = {}
    pipe = redis.pipeline.return_value
    pipe.get.side_effect = values.get
    pipe.set.side_effect = lambda key, value, **kwargs: values.__setitem__(key, value)
    redis.get.side_effect = values.get
    other = replace(scope, conversation_id="8", run_id="other")

    def start(current):
        return {"conversation_id": scope.conversation_id, "run_id": scope.run_id,
                "version": 1, "card": {"id": "current", "subtype": "installed_resource_binding"}}

    service._update(scope, start)
    service._update(other, lambda current: {**start(current), "conversation_id": "8"})
    action = ResourceCardAction(card_id="current", state_version=1)
    assert service.require_current_card(service._read(scope), scope, "installed_resource_binding", action)
    assert service._read(other)["conversation_id"] == "8"


@pytest.mark.parametrize("conversation", ["7", "other"])
def test_legacy_state_is_only_read_and_migrated_for_matching_conversation(redis, scope, conversation):
    legacy = {"conversation_id": conversation, "version": 2, "card": None}
    values = {scope.legacy_key: json.dumps(legacy)}
    redis.get.side_effect = values.get
    pipe = redis.pipeline.return_value
    pipe.get.side_effect = values.get
    pipe.set.side_effect = lambda key, value, **kwargs: values.__setitem__(key, value)
    expected = legacy if conversation == scope.conversation_id else None
    assert service._read(scope) == expected
    seen = []

    def change(current):
        seen.append(current)
        return {"conversation_id": "7", "version": 3, "card": None}

    updated = service._update(scope, change)
    assert seen == [expected]
    assert [call.args for call in pipe.watch.call_args_list] == [(scope.key,), (scope.legacy_key,)]
    assert service._read(scope) == updated
    assert json.loads(values[scope.legacy_key]) == legacy
    assert json.loads(values[scope.key]) == updated
