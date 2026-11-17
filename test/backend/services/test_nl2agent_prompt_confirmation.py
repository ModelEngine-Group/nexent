# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Prompt replacement requires explicit, revision-scoped consent."""

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from services import nl2agent_prompt_service as prompts
from services.nl2agent_state_service import ResourceScope, ResourceStateError


@pytest.fixture
def fixture(mocker):
    scope = ResourceScope("tenant", "user", 42, "7", "run")
    store = {}
    draft = {"prompt": "Original", "description": "Keep"}
    facts = []

    async def read(key):
        return deepcopy(store.get(key.key))

    async def update(key, change):
        store[key.key] = deepcopy(change(deepcopy(store.get(key.key))))
        return deepcopy(store[key.key])

    async def snapshot(_scope):
        return {"prompt": draft["prompt"], "bindings": prompts.revision(facts)}

    def save(*, agent_id, tenant_id, fields, expected_fields):
        if draft["prompt"] != expected_fields["prompt"]:
            return 0
        draft.update({key: value for key, value in fields.items() if key != "updated_by"})
        return 1

    mocker.patch.object(prompts, "read_resource_state", side_effect=read)
    mocker.patch.object(prompts, "update_resource_state", side_effect=update)
    mocker.patch.object(prompts, "snapshot", side_effect=snapshot)
    writer = mocker.patch.object(prompts, "update_agent_draft_fields", side_effect=save)
    async def blocking(_name, fn, *args, **kwargs):
        return await _call(fn, args, kwargs)
    mocker.patch.object(prompts, "run_blocking", new=blocking)
    mocker.patch.object(prompts, "read_continuation", new=AsyncMock(return_value=False))
    held = False

    @contextmanager
    def lock(*args):
        nonlocal held
        acquired = not held
        if acquired:
            held = True
        try:
            yield acquired
        finally:
            if acquired:
                held = False

    mocker.patch.object(prompts, "agent_draft_operation_lock", new=lock, create=True)
    return scope, draft, facts, writer


async def _call(fn, args, kwargs):
    for key in ("lane", "owner"):
        kwargs.pop(key, None)
    return fn(*args, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("original", [None, "", " \n\t"])
async def test_empty_prompt_saves_directly(fixture, original):
    scope, draft, _, writer = fixture
    draft["prompt"] = original
    await prompts.begin_run(scope)
    result = await prompts.propose(scope, "New\nFull text")
    assert result["status"] == "success"
    assert draft == {"prompt": "New\nFull text", "description": "Keep"}
    writer.assert_called_once()


@pytest.mark.asyncio
async def test_existing_prompt_waits_then_applies_exact_server_text_once(fixture):
    scope, draft, _, writer = fixture
    await prompts.begin_run(scope)
    card = await prompts.propose(scope, "New\nFull text")
    assert card["subtype"] == "prompt_generation"
    assert draft["prompt"] == "Original"
    writer.assert_not_called()
    action = {"card_id": card["card_id"], "prompt_revision": card["prompt_revision"]}
    applied = await prompts.apply_action(scope, "apply", action)
    assert applied["card"]["status"] == "applied"
    assert applied["saved"] is True and applied["resume"] is False
    assert draft["prompt"] == card["proposed_prompt"]
    again = await prompts.apply_action(scope, "apply", action)
    assert again["card"]["status"] == "applied" and not again["resume"]
    writer.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_preserves_original_and_never_resumes(fixture):
    scope, draft, _, writer = fixture
    await prompts.begin_run(scope)
    card = await prompts.propose(scope, "New")
    result = await prompts.apply_action(scope, "cancel", {
        "card_id": card["card_id"], "prompt_revision": card["prompt_revision"],
    })
    assert result["card"]["status"] == "cancelled"
    assert not result["saved"] and not result["resume"]
    assert draft["prompt"] == "Original"
    writer.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["prompt", "bindings", "conversation", "tenant", "user", "agent", "new_card", "revision", "extra_text"])
async def test_conflicts_and_forged_actions_do_not_write(fixture, change):
    scope, draft, facts, writer = fixture
    await prompts.begin_run(scope)
    card = await prompts.propose(scope, "New")
    action = {"card_id": card["card_id"], "prompt_revision": card["prompt_revision"]}
    if change == "prompt":
        draft["prompt"] = "Manual edit"
    elif change == "bindings":
        facts.append({"tool_id": 9})
    elif change == "conversation":
        scope = ResourceScope("tenant", "user", 42, "other", "run")
    elif change == "tenant":
        scope = ResourceScope("other", "user", 42, "7", "run")
    elif change == "user":
        scope = ResourceScope("tenant", "other", 42, "7", "run")
    elif change == "agent":
        scope = ResourceScope("tenant", "user", 43, "7", "run")
    elif change == "new_card":
        scope_new = ResourceScope("tenant", "user", 42, "7", "new-run")
        await prompts.begin_run(scope_new)
        await prompts.propose(scope_new, "Newer")
    elif change == "revision":
        action["prompt_revision"] = "forged"
    else:
        action["unexpected"] = "forged"
    with pytest.raises(ResourceStateError):
        await prompts.apply_action(scope, "apply", action)
    writer.assert_not_called()
    assert draft["prompt"] != "New"


@pytest.mark.asyncio
async def test_edit_during_generation_cannot_use_empty_fast_path(fixture):
    scope, draft, _, writer = fixture
    draft["prompt"] = ""
    await prompts.begin_run(scope)
    draft["prompt"] = "Manual edit"
    with pytest.raises(ResourceStateError, match="prompt_revision_conflict"):
        await prompts.propose(scope, "Generated")
    writer.assert_not_called()


@pytest.mark.asyncio
async def test_failed_save_retries_and_full_generation_resumes_only_after_save(fixture, mocker):
    scope, draft, _, writer = fixture
    mocker.patch.object(prompts, "read_continuation", new=AsyncMock(return_value=True))
    await prompts.begin_run(scope)
    card = await prompts.propose(scope, "New")
    action = {"card_id": card["card_id"], "prompt_revision": card["prompt_revision"]}
    save = writer.side_effect
    writer.side_effect = RuntimeError("storage failure")
    with pytest.raises(ResourceStateError, match="prompt_save_failed"):
        await prompts.apply_action(scope, "apply", action)
    assert draft["prompt"] == "Original"
    writer.side_effect = save
    assert (await prompts.apply_action(scope, "apply", action))["resume"] is True
    assert (await prompts.apply_action(scope, "apply", action))["resume"] is False


@pytest.mark.asyncio
async def test_dialogue_refinement_reads_pending_text_and_retains_original_full_task(fixture, mocker):
    scope, draft, facts, writer = fixture
    mocker.patch.object(prompts, "read_continuation", new=AsyncMock(return_value=True))
    mocker.patch.object(prompts, "_bindings", new=AsyncMock(return_value=prompts.revision(facts)))
    await prompts.begin_run(scope)
    card = await prompts.propose(scope, "Full proposal to refine")
    next_scope = ResourceScope("tenant", "user", 42, "7", "next-run")
    assert (await prompts.read_pending(next_scope))["proposed_prompt"] == card["proposed_prompt"]
    await prompts.refresh_basis(next_scope, {"draft_fields": draft, "bound_resources": facts})
    newer = await prompts.propose(next_scope, "Refined full proposal")
    assert newer["card_id"] != card["card_id"]
    writer.assert_not_called()
    assert (await prompts.apply_action(next_scope, "apply", {
        "card_id": newer["card_id"], "prompt_revision": newer["prompt_revision"],
    }))["resume"] is True


@pytest.mark.asyncio
async def test_lost_database_acknowledgement_reconciles_without_rewriting(fixture):
    scope, draft, _, writer = fixture
    await prompts.begin_run(scope)
    card = await prompts.propose(scope, "Committed text")
    original = writer.side_effect

    def committed_then_failed(**kwargs):
        original(**kwargs)
        raise RuntimeError("acknowledgement lost")

    writer.side_effect = committed_then_failed
    result = await prompts.apply_action(scope, "apply", {
        "card_id": card["card_id"], "prompt_revision": card["prompt_revision"],
    })
    assert result["card"]["status"] == "applied"
    assert draft["prompt"] == "Committed text"
    writer.assert_called_once()


@pytest.mark.asyncio
async def test_concurrent_confirmation_has_one_writer(fixture, mocker):
    scope, _, _, writer = fixture
    await prompts.begin_run(scope)
    card = await prompts.propose(scope, "One application")
    data = {"card_id": card["card_id"], "prompt_revision": card["prompt_revision"]}
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocking(_name, fn, *args, **kwargs):
        if _name == "nl2agent-apply-prompt":
            entered.set()
            await release.wait()
        return await _call(fn, args, kwargs)

    mocker.patch.object(prompts, "run_blocking", new=blocking)
    first = asyncio.create_task(prompts.apply_action(scope, "apply", data))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        other = ResourceScope("tenant", "user", 42, "7", "concurrent-run")
        with pytest.raises(ResourceStateError, match="prompt_application_in_progress"):
            await prompts.apply_action(other, "apply", data)
    finally:
        release.set()
        result = await first
    assert result["card"]["status"] == "applied"
    writer.assert_called_once()


@pytest.mark.asyncio
async def test_edited_confirmation_saves_exact_text_and_rejects_different_replay(fixture):
    scope, draft, _, writer = fixture
    await prompts.begin_run(scope)
    card = await prompts.propose(scope, "Generated")
    action = {"card_id": card["card_id"], "prompt_revision": card["prompt_revision"],
              "prompt": " User edits\nKeep whitespace \n"}
    result = await prompts.apply_action(scope, "apply", action)
    assert draft["prompt"] == action["prompt"]
    assert result["card"]["proposed_prompt"] == action["prompt"]
    await prompts.apply_action(scope, "apply", action)
    writer.assert_called_once()
    with pytest.raises(ResourceStateError, match="prompt_revision_conflict"):
        await prompts.apply_action(scope, "apply", {**action, "prompt": "Different"})


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["", " \n", None, 42, {}, []])
async def test_invalid_edited_text_does_not_write(fixture, text):
    scope, _, _, writer = fixture
    await prompts.begin_run(scope)
    card = await prompts.propose(scope, "Generated")
    with pytest.raises(ResourceStateError, match="invalid_prompt"):
        await prompts.apply_action(scope, "apply", {
            "card_id": card["card_id"], "prompt_revision": card["prompt_revision"], "prompt": text,
        })
    writer.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["apply", "cancel"])
@pytest.mark.parametrize("committed", [False, True])
async def test_interrupted_claim_recovers_from_database_facts(fixture, action, committed):
    scope, draft, _, writer = fixture
    await prompts.begin_run(scope)
    card = await prompts.propose(scope, "Generated")
    await prompts.update_resource_state(prompts._key(scope), lambda state: {
        **state, "status": "applying", "submitted_prompt": "Edited before interruption", "claim": "abandoned",
    })
    if committed:
        draft["prompt"] = "Edited before interruption"
    data = {"card_id": card["card_id"], "prompt_revision": card["prompt_revision"]}
    if committed and action == "cancel":
        with pytest.raises(ResourceStateError, match="prompt_card_stale"):
            await prompts.apply_action(scope, action, data)
        writer.assert_not_called()
        return
    result = await prompts.apply_action(scope, action, data)
    assert result["card"]["status"] == ("applied" if action == "apply" else "cancelled")
    assert draft["prompt"] == ("Edited before interruption" if action == "apply" else "Original")
    assert writer.call_count == (1 if action == "apply" and not committed else 0)


@pytest.mark.asyncio
async def test_failed_save_and_failed_readback_remain_recoverable(fixture, mocker):
    scope, draft, _, writer = fixture
    await prompts.begin_run(scope)
    card = await prompts.propose(scope, "Generated")
    action = {"card_id": card["card_id"], "prompt_revision": card["prompt_revision"], "prompt": "Edited"}
    original_save = writer.side_effect
    snapshot = prompts.snapshot.side_effect
    prompts.snapshot.side_effect = [await snapshot(scope), RuntimeError("read unavailable")]
    writer.side_effect = RuntimeError("write unavailable")
    with pytest.raises(ResourceStateError, match="prompt_save_failed"):
        await prompts.apply_action(scope, "apply", action)
    prompts.snapshot.side_effect = snapshot
    writer.side_effect = original_save
    assert (await prompts.apply_action(scope, "apply", action))["saved"]
    assert draft["prompt"] == "Edited"


@pytest.mark.asyncio
async def test_disconnect_holds_lock_until_database_write_finishes(fixture, mocker):
    scope, draft, _, writer = fixture
    await prompts.begin_run(scope)
    card = await prompts.propose(scope, "Generated")
    data = {"card_id": card["card_id"], "prompt_revision": card["prompt_revision"], "prompt": "Edited"}
    entered, release = asyncio.Event(), asyncio.Event()
    original = prompts._save

    async def save(*args):
        entered.set()
        await release.wait()
        return await original(*args)

    mocker.patch.object(prompts, "_save", side_effect=save)
    task = asyncio.create_task(prompts.apply_action(scope, "apply", data))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    await asyncio.sleep(0)
    try:
        with pytest.raises(ResourceStateError, match="prompt_application_in_progress"):
            await prompts.apply_action(scope, "cancel", {key: data[key] for key in ("card_id", "prompt_revision")})
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert draft["prompt"] == "Edited"
    await prompts.apply_action(scope, "apply", data)
    writer.assert_called_once()
