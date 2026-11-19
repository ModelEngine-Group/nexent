# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Prompt proposals reject invalid transitions and resume only unchanged approvals."""

from copy import deepcopy
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from services import nl2agent_prompt_service as prompts
from services.nl2agent_state_service import ResourceScope, ResourceStateError


@pytest.fixture
def boundary(mocker):
    scope = ResourceScope("tenant", "user", 42, "7", "run")
    store = {}
    current = {"prompt": "Original", "bindings": "revision"}

    async def read(key):
        return deepcopy(store.get(key.key))

    async def update(key, change):
        store[key.key] = deepcopy(change(deepcopy(store.get(key.key))))
        return deepcopy(store[key.key])

    mocker.patch.object(prompts, "read_resource_state", new=AsyncMock(side_effect=read))
    mocker.patch.object(prompts, "update_resource_state", new=AsyncMock(side_effect=update))
    mocker.patch.object(prompts, "snapshot", new=AsyncMock(side_effect=lambda _: deepcopy(current)))
    mocker.patch.object(prompts, "read_continuation", new=AsyncMock(return_value=True))

    async def save(_scope, basis, text):
        current["prompt"] = text

    writer = mocker.patch.object(prompts, "_save", new=AsyncMock(side_effect=save))
    return scope, store, current, writer


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [None, 4, "", " \n "])
async def test_invalid_proposal_text_never_creates_pending_card(boundary, text):
    scope, store, _, writer = boundary
    await prompts.begin_run(scope)
    with pytest.raises(ResourceStateError, match="invalid_prompt"):
        await prompts.propose(scope, text)
    assert prompts._key(scope).key not in store
    writer.assert_not_awaited()


@pytest.mark.asyncio
async def test_proposal_requires_generation_context(boundary):
    scope, _, _, writer = boundary
    with pytest.raises(ResourceStateError, match="prompt_context_required"):
        await prompts.propose(scope, "New")
    writer.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_run_proposal_is_idempotent_but_different_text_requires_confirmation(boundary):
    scope, _, _, writer = boundary
    await prompts.begin_run(scope)
    card = await prompts.propose(scope, "New")
    assert await prompts.propose(scope, "New") == card
    with pytest.raises(ResourceStateError, match="prompt_confirmation_required"):
        await prompts.propose(scope, "Different")
    writer.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_inflight_prompt_application_blocks_new_proposal(boundary, empty):
    scope, store, current, writer = boundary
    current["prompt"] = "" if empty else "Original"
    await prompts.begin_run(scope)
    store[prompts._key(scope).key] = {"status": "applying"}
    with pytest.raises(ResourceStateError, match="prompt_application_in_progress") as error:
        await prompts.propose(scope, "New")
    assert error.value.retryable
    writer.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_draft_supersedes_previous_pending_card(boundary):
    scope, store, current, writer = boundary
    current["prompt"] = ""
    await prompts.begin_run(scope)
    store[prompts._key(scope).key] = {"status": "pending", "card_id": "old"}
    assert (await prompts.propose(scope, "New"))["updated_fields"] == ["prompt"]
    assert store[prompts._key(scope).key] == {"status": "superseded", "card_id": "old"}
    writer.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "applying", "applied", "cancelled"])
async def test_pending_confirmation_guard_is_conversation_scoped(boundary, status):
    scope, store, _, _ = boundary
    store[prompts._key(scope).key] = {"status": status, "conversation_id": "7"}
    if status in {"pending", "applying"}:
        with pytest.raises(ResourceStateError, match="prompt_confirmation_required"):
            await prompts.require_no_pending(scope)
    else:
        await prompts.require_no_pending(scope)
    await prompts.require_no_pending(replace(scope, conversation_id="other"))


@pytest.mark.asyncio
async def test_unknown_and_superseded_actions_do_not_save(boundary):
    scope, store, _, writer = boundary
    with pytest.raises(ResourceStateError, match="invalid_prompt_action"):
        await prompts._apply_action(scope, "unknown", {})
    await prompts.begin_run(scope)
    card = await prompts.propose(scope, "New")
    store[prompts._key(scope).key]["status"] = "superseded"
    with pytest.raises(ResourceStateError, match="prompt_card_stale"):
        await prompts._apply_action(scope, "apply", {"card_id": card["card_id"], "prompt_revision": card["prompt_revision"]})
    writer.assert_not_awaited()


@pytest.mark.asyncio
async def test_applied_prompt_retry_resumes_new_run_without_rewriting(boundary):
    scope, store, current, writer = boundary
    await prompts.begin_run(scope)
    card = await prompts.propose(scope, "New")
    data = {"card_id": card["card_id"], "prompt_revision": card["prompt_revision"]}
    assert (await prompts._apply_action(scope, "apply", data))["saved"]
    next_scope = replace(scope, run_id="next")
    result = await prompts._apply_action(next_scope, "apply", data, resume_confirmation=True)
    assert result["resume"] and not result["saved"]
    assert store[prompts._key(scope).key]["resume_run_id"] == "next"
    writer.assert_awaited_once()
    current["bindings"] = "changed"
    with pytest.raises(ResourceStateError, match="prompt_revision_conflict"):
        await prompts._apply_action(next_scope, "apply", data, resume_confirmation=True)
    writer.assert_awaited_once()


@pytest.mark.asyncio
async def test_interrupted_application_with_unrelated_draft_cannot_overwrite(boundary):
    scope, store, current, writer = boundary
    await prompts.begin_run(scope)
    card = await prompts.propose(scope, "New")
    store[prompts._key(scope).key]["status"] = "applying"
    current["prompt"] = "Manual edit"
    with pytest.raises(ResourceStateError, match="prompt_revision_conflict"):
        await prompts._apply_action(scope, "apply", {"card_id": card["card_id"], "prompt_revision": card["prompt_revision"]})
    writer.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_optimistic_conflict_is_not_reported_as_success(mocker):
    scope = ResourceScope("tenant", "user", 42, "7", "run")
    dispatch = mocker.patch.object(prompts, "run_blocking", new=AsyncMock(return_value=0))
    with pytest.raises(ResourceStateError, match="prompt_revision_conflict"):
        await prompts._save(scope, {"prompt": "Original"}, "New")
    assert dispatch.call_args.kwargs["expected_fields"] == {"prompt": "Original"}


@pytest.mark.asyncio
async def test_snapshot_retains_prompt_and_only_digest_of_private_bindings(mocker):
    from services import nl2agent_service as legacy

    scope = ResourceScope("tenant", "user", 42, "7", "run")
    read = mocker.patch.object(legacy, "read_generation_state", new=AsyncMock(return_value={
        "draft_fields": {"prompt": "Original"}, "bound_resources": [{"resource_type": "tool", "resource_id": 9}],
        "binding_revision": "a" * 64,
    }))
    mocker.patch.object(legacy, "query_all_enabled_tool_instances", return_value=[
        {"tool_instance_id": 1, "tool_id": 9, "params": {"token": "private-tool-token"}},
    ])
    mocker.patch.object(legacy, "query_enabled_skill_instances", return_value=[
        {"skill_instance_id": 2, "skill_id": 8, "config_values": {"key": "private-skill-key"}},
    ])

    async def run(_task, function, *args, **kwargs):
        return function(*args)

    mocker.patch.object(prompts, "run_blocking", new=run)
    result = await prompts.snapshot(scope)
    assert set(result) == {"prompt", "bindings"} and result["prompt"] == "Original"
    assert len(result["bindings"]) == 64
    assert "private-tool-token" not in str(result) and "private-skill-key" not in str(result)
    read.assert_awaited_once()
    assert read.call_args.kwargs["tenant_id"] == "tenant" and read.call_args.kwargs["user_id"] == "user"


@pytest.mark.asyncio
@pytest.mark.parametrize("change,expected", [
    ({}, True), ({"conversation_id": "other"}, False), ({"run_id": "other"}, False),
    ({"purpose": "bind"}, False), ({"card": {"id": "pending"}}, False),
])
async def test_continuation_requires_current_generation_with_no_card(mocker, change, expected):
    scope = ResourceScope("tenant", "user", 42, "7", "run")
    state = {"conversation_id": "7", "run_id": "run", "purpose": "generate", "card": None, **change}
    mocker.patch.object(prompts, "read_resource_state", new=AsyncMock(return_value=state))
    assert await prompts.read_continuation(scope) is expected
