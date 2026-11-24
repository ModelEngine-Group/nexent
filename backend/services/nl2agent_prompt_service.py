# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Server-owned generated prompts, separate from resource recommendation state."""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from uuid import uuid4

from nexent.core.concurrency import run_blocking

from management.db.agent.repository import agent_draft_operation_lock, update_agent_draft_fields
from services.nl2agent_state_service import (
    ResourceScope, ResourceStateError, read_resource_state, update_resource_state,
)


@dataclass(frozen=True)
class PromptScope(ResourceScope):
    suffix: str = "pending"

    @property
    def key(self):
        return super().key.replace("nl2agent:resources:", "nl2agent:prompts:") + ":" + self.suffix


def _key(scope, suffix="pending"):
    return PromptScope(scope.tenant_id, scope.user_id, scope.agent_id,
                       scope.conversation_id, scope.run_id, suffix)


def revision(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def binding_revision(facts, tools, skills):
    # Only the digest is retained server-side; private configuration never enters model/card data.
    records = [
        ["tool", row.get("tool_instance_id"), row.get("tool_id"), row.get("params")]
        for row in tools
    ] + [
        ["skill", row.get("skill_instance_id"), row.get("skill_id"), row.get("config_values"), row.get("config_schemas")]
        for row in skills
    ]
    return revision({"facts": facts, "instances": sorted(records, key=lambda row: str(row[:3]))})


async def snapshot(scope):
    from management.services.agent.nl2agent import read_generation_state

    state = await read_generation_state(
        agent_id=scope.agent_id, tenant_id=scope.tenant_id, user_id=scope.user_id,
        include_binding_revision=True,
    )
    return {"prompt": state["draft_fields"].get("prompt"), "bindings": state["binding_revision"]}


async def begin_run(scope):
    """Capture the generation basis before the model can request a write."""
    basis = await snapshot(scope)
    await update_resource_state(_key(scope, "run:" + scope.run_id), lambda _: basis)


async def refresh_basis(scope, state, *, complete_generation=False):
    """An explicit context read establishes the latest facts used for generation."""
    basis = {"prompt": state["draft_fields"].get("prompt"), "bindings": state["binding_revision"]}
    pending = await read_resource_state(_key(scope))
    if (pending and pending.get("conversation_id") == scope.conversation_id
            and pending.get("status") == "pending"):
        complete_generation = complete_generation or pending.get("resume", False)
    await update_resource_state(_key(scope, "run:" + scope.run_id),
                                lambda _: {**basis, "complete_generation": complete_generation})


async def read_pending(scope):
    state = await read_resource_state(_key(scope))
    if state and state.get("conversation_id") == scope.conversation_id and state.get("status") == "pending":
        return card_payload(scope, state)
    return None


async def read_continuation(scope):
    state = await read_resource_state(scope)
    return bool(state and state.get("conversation_id") == scope.conversation_id
                and state.get("run_id") == scope.run_id and state.get("purpose") == "generate"
                and state.get("card") is None)


def card_payload(scope, state):
    return {
        "subtype": "prompt_generation", "agent_id": scope.agent_id,
        "conversation_id": state["conversation_id"], "run_id": state["run_id"],
        "card_id": state["card_id"], "prompt_revision": state["prompt_revision"],
        "proposed_prompt": state["proposed_prompt"], "status": state["status"],
    }


async def _save(scope, basis, text):
    try:
        count = await run_blocking(
            "nl2agent-apply-prompt", update_agent_draft_fields,
            agent_id=scope.agent_id, tenant_id=scope.tenant_id,
            fields={"prompt": text, "updated_by": scope.user_id},
            expected_fields={"prompt": basis["prompt"]}, lane="control-io", owner=__name__,
        )
    except Exception as exc:
        raise ResourceStateError("prompt_save_failed", retryable=True) from exc
    if count != 1:
        raise ResourceStateError("prompt_revision_conflict")


async def propose(scope, text):
    basis = await read_resource_state(_key(scope, "run:" + scope.run_id))
    if basis is None:
        raise ResourceStateError("prompt_context_required")
    complete_generation = bool(basis and basis.get("complete_generation"))
    if basis is not None:
        basis = {key: basis[key] for key in ("prompt", "bindings")}
    current = await snapshot(scope)
    if basis is None or basis != current:
        raise ResourceStateError("prompt_revision_conflict")
    if not isinstance(text, str) or not text.strip():
        raise ResourceStateError("invalid_prompt")
    if not str(current["prompt"] or "").strip():
        def invalidate(previous):
            if previous and previous.get("status") == "applying":
                raise ResourceStateError("prompt_application_in_progress", retryable=True)
            if previous and previous.get("status") == "pending":
                return {**previous, "status": "superseded"}
            return previous or {}
        await update_resource_state(_key(scope), invalidate)
        await _save(scope, basis, text)
        return {"status": "success", "agent_id": scope.agent_id, "created": False, "updated_fields": ["prompt"]}
    state = {
        "card_id": uuid4().hex, "prompt_revision": revision(basis), "basis": basis,
        "proposed_prompt": text, "conversation_id": scope.conversation_id, "run_id": scope.run_id,
        "status": "pending", "resume": complete_generation or await read_continuation(scope),
    }

    def publish(previous):
        if previous and previous.get("status") == "applying":
            raise ResourceStateError("prompt_application_in_progress", retryable=True)
        if previous and previous.get("run_id") == scope.run_id and previous.get("status") == "pending":
            if previous["proposed_prompt"] == text:
                return previous
            raise ResourceStateError("prompt_confirmation_required")
        return state

    published = await update_resource_state(_key(scope), publish)
    return card_payload(scope, published)


def _require_card(scope, state, data):
    if (not isinstance(data, dict) or not {"card_id", "prompt_revision"} <= set(data)
            or set(data) - {"card_id", "prompt_revision", "prompt"}
            or not state or state["conversation_id"] != scope.conversation_id
            or state["card_id"] != data.get("card_id")
            or state["prompt_revision"] != data.get("prompt_revision")):
        raise ResourceStateError("prompt_card_stale")
    return state


async def apply_action(scope, action, data, *, resume_confirmation=False):
    # Keep serialization until the database worker finishes, even on disconnect.
    task = asyncio.create_task(_serialized_action(scope, action, data, resume_confirmation))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        finally:
            raise


async def _serialized_action(scope, action, data, resume_confirmation):
    lock = agent_draft_operation_lock(scope.agent_id, scope.tenant_id, "prompt-confirmation")
    acquired = await run_blocking("nl2agent-prompt-lock", lock.__enter__, lane="control-io", owner=__name__)
    try:
        if not acquired:
            raise ResourceStateError("prompt_application_in_progress", retryable=True)
        return await _apply_action(scope, action, data, resume_confirmation=resume_confirmation)
    finally:
        await run_blocking("nl2agent-prompt-unlock", lock.__exit__, None, None, None,
                           lane="control-io", owner=__name__)


async def _apply_action(scope, action, data, *, resume_confirmation=False):
    if action not in {"apply", "cancel"}:
        raise ResourceStateError("invalid_prompt_action")
    state = _require_card(scope, await read_resource_state(_key(scope)), data)
    if "prompt" in data and (action != "apply" or not isinstance(data["prompt"], str) or not data["prompt"].strip()):
        raise ResourceStateError("invalid_prompt")
    if state["status"] == "superseded":
        raise ResourceStateError("prompt_card_stale")
    submitted = state.get("submitted_prompt", state["proposed_prompt"])
    text = data.get("prompt", submitted)
    target_status = "applied" if action == "apply" else "cancelled"
    # Acquiring the database lock proves that no earlier confirmation is still
    # writing. Reconcile its outcome before allowing either retries or cancellation.
    current = await snapshot(scope) if action == "apply" or state["status"] == "applying" else None
    if state["status"] == "applying":
        if current == {**state["basis"], "prompt": submitted}:
            def recover(previous):
                previous = _require_card(scope, previous, data)
                return {**previous, "status": "applied", "proposed_prompt": submitted,
                        "resume_run_id": scope.run_id}
            state = await update_resource_state(_key(scope), recover)
            if action == "apply" and text == submitted:
                return {"card": card_payload(scope, state), "saved": True, "resume": state["resume"]}
        elif current == state["basis"]:
            state = await update_resource_state(_key(scope), lambda previous: {
                **_require_card(scope, previous, data), "status": "pending",
            })
        else:
            raise ResourceStateError("prompt_revision_conflict")
    if state["status"] in {"applied", "cancelled"}:
        if state["status"] != target_status:
            raise ResourceStateError("prompt_card_stale")
        if action == "apply" and text != state["proposed_prompt"]:
            raise ResourceStateError("prompt_revision_conflict")
        if action == "apply" and state["resume"] and resume_confirmation:
            if await snapshot(scope) != {**state["basis"], "prompt": state["proposed_prompt"]}:
                raise ResourceStateError("prompt_revision_conflict")
            def retry(current_state):
                current_state = _require_card(scope, current_state, data)
                return {**current_state, "resume_run_id": scope.run_id}
            state = await update_resource_state(_key(scope), retry)
            return {"card": card_payload(scope, state), "saved": False, "resume": True}
        return {"card": card_payload(scope, state), "saved": False, "resume": False}

    token = uuid4().hex

    def claim(current):
        current = _require_card(scope, current, data)
        if current["status"] != "pending":
            raise ResourceStateError("prompt_application_in_progress", retryable=True)
        return {**current, "status": "applying" if action == "apply" else "cancelled", "claim": token,
                **({"submitted_prompt": text} if action == "apply" else {})}

    state = await update_resource_state(_key(scope), claim)
    if action == "cancel":
        return {"card": card_payload(scope, state), "saved": False, "resume": False}
    try:
        if current != state["basis"]:
            raise ResourceStateError("prompt_revision_conflict")
        await _save(scope, state["basis"], text)
    except ResourceStateError as exc:
        # A failed readback leaves a recoverable applying state, never an unsafe
        # permission to overwrite. The next serialized request reconciles it.
        try:
            persisted = await snapshot(scope) if exc.code == "prompt_save_failed" else None
        except Exception:
            raise exc
        if persisted != {**state["basis"], "prompt": text}:
            def release(current_state):
                current_state = _require_card(scope, current_state, data)
                return ({**current_state, "status": "pending"}
                        if current_state.get("claim") == token else current_state)
            await update_resource_state(_key(scope), release)
            raise

    def finish(current_state):
        current_state = _require_card(scope, current_state, data)
        if current_state["status"] == "applied":
            return current_state
        return {**current_state, "status": "applied", "proposed_prompt": text, "resume_run_id": scope.run_id}

    state = await update_resource_state(_key(scope), finish)
    return {"card": card_payload(scope, state), "saved": True,
            "resume": state["resume"] and state.get("resume_run_id") == scope.run_id}


async def require_no_pending(scope):
    state = await read_resource_state(_key(scope))
    if (state and state.get("conversation_id") == scope.conversation_id
            and state.get("status") in {"pending", "applying"}):
        raise ResourceStateError("prompt_confirmation_required")
