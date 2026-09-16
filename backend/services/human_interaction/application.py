"""Composition root: authorized Agent preparation, durable scheduling, and SSE delivery."""

import asyncio
import json
import time
from functools import lru_cache

from fastapi.responses import StreamingResponse
from nexent.core.concurrency import run_blocking
from nexent.core.human_interaction.contracts import RecoveryRequired, RunTerminated
from nexent.core.human_interaction.live_runtime import LiveHumanInteractionRuntime
from nexent.core.human_interaction.runtime import HumanInteractionRuntime

from consts.const import (
    HITL_ACCEPT_NEW_RUNS,
    HITL_ENABLED,
    HITL_ENCRYPTION_KEY,
    HITL_MAX_CONCURRENCY,
    HITL_TOOL_APPROVAL_ENABLED,
    HITL_WAIT_SECONDS,
)
from database.human_interaction_db import HumanInteractionRepository
from nexent.scheduler import ClaimedJob, LeaseScheduler, SchedulerConfig

from .crypto import PayloadCipher
from .models import InteractionError
from .runtime_port import RuntimeInteractionPort
from .service import TERMINAL_STATUSES, HumanInteractionService


@lru_cache(maxsize=1)
def get_service():
    return HumanInteractionService(HumanInteractionRepository(), PayloadCipher(HITL_ENCRYPTION_KEY), HITL_WAIT_SECONDS)


def require_enabled():
    if not HITL_ENABLED:
        raise InteractionError("Human interaction is not enabled on this deployment", 503)
    return get_service()


def _stable_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        transient = {"workspace_path", "run_id", "workspace_run_id", "observer", "stop_event", "redis_client",
                     "context_manager_config", "pre_run_tool_events", "context_items", "minio_client"}
        return {key: _stable_value(item) for key, item in value.items() if key not in transient and not callable(item)}
    if isinstance(value, (list, tuple)):
        return [_stable_value(item) for item in value]
    return type(value).__module__ + "." + type(value).__qualname__


def _allowed_tool_names(tools, *, approval_enabled=HITL_TOOL_APPROVAL_ENABLED):
    if not approval_enabled:
        allowed = {tool.name for tool in tools if tool.name}
        allowed.add("final_answer")
        return frozenset(allowed)
    trusted_plan_classes = {"CreatePlanTool", "UpdatePlanStepTool"}
    allowed = {
        tool.name
        for tool in tools
        if tool.name and tool.source == "local" and tool.class_name in trusted_plan_classes
    }
    allowed.add("final_answer")
    return frozenset(allowed)


async def authorize_run(payload, tenant_id, user_id):
    from database.user_tenant_db import get_user_tenant_by_user_id
    from management.services.agent.management import list_all_agent_info_impl
    from services.conversation_management_service import get_conversation_service

    membership = await run_blocking(
        "hitl-get_user_tenant_by_user_id", get_user_tenant_by_user_id, user_id, lane="control-io",
        owner=__name__,
    )
    if not membership or str(membership.get("tenant_id")) != tenant_id:
        raise InteractionError("The run owner no longer belongs to this tenant", 403)
    conversation = await run_blocking(
        "hitl-get_conversation_service", get_conversation_service, payload["conversation_id"], user_id,
        tenant_id, lane="control-io", owner=__name__,
    )
    if conversation is None:
        raise InteractionError("Conversation is no longer accessible", 403)
    agents = await list_all_agent_info_impl(tenant_id, user_id)
    if not any(item.get("agent_id") == payload["agent_id"] for item in agents):
        raise InteractionError("Agent is no longer accessible", 403)


async def execute_attempt(job, lease):
    from consts.model import AgentRequest
    from management.services.agent.run import (
        _stream_agent_chunks,
        _unregister_agent_run_after_execution,
        prepare_agent_run,
    )

    service = get_service()
    identity = job.payload
    loop = asyncio.get_running_loop()
    run_info = None
    port = None
    try:
        # Authorization is re-evaluated on every dispatch, including result replay.
        def authorize():
            try:
                asyncio.run_coroutine_threadsafe(
                    authorize_run(port.request_payload["request"], identity["tenant_id"], identity["user_id"]), loop,
                ).result(timeout=30)
            except Exception as exc:
                raise RunTerminated("Run authorization could not be revalidated") from exc

        port = RuntimeInteractionPort(service, identity, lease.owner_id, authorize, live_resume=True)
        saved = port.request_payload
        if saved.get("runtime_mode") == "native-live-v1" and port.checkpoint:
            raise RecoveryRequired("The original native execution is no longer available")
        request = AgentRequest.model_validate(saved["request"])
        request.__dict__["_runtime_metadata_snapshot"] = saved["runtime_metadata"]
        request.__dict__["_runtime_metadata_version"] = saved["runtime_metadata_version"]
        request.__dict__["_runtime_knowledge_context"] = saved.get("runtime_knowledge_context")
        await authorize_run(saved["request"], identity["tenant_id"], identity["user_id"])
        run_info, memory_context = await prepare_agent_run(
            agent_request=request, user_id=identity["user_id"], tenant_id=identity["tenant_id"],
            language=saved["language"], allow_memory_search=True,
        )
        port.stop_event = getattr(run_info, "stop_event", None)
        config = run_info.agent_config
        native = saved.get("runtime_mode") == "native-live-v1"
        runtime_type = LiveHumanInteractionRuntime if native else HumanInteractionRuntime
        if not native:
            if config.managed_agents or config.external_a2a_agents or request.minio_files:
                # A legacy strict approval policy must never be silently bypassed.
                raise RecoveryRequired("The frozen approval executor cannot safely execute this configuration")
            # Legacy durable runs retain their frozen executor contract. New chat
            # runs preserve the native sandbox, attachment workspace and tool registry.
            run_info.sandbox_config = None
            run_info.workspace_path = None
            run_info.minio_files = None
        from nexent.core.agents.context import ContextItemInput
        from nexent.core.agents.context_input import ContextInput
        prepared_items = [item.model_dump(mode="json") for item in run_info.context_input.items]
        prepared_items.append(ContextItemInput(
            id="system:human_interaction", type="system", source=("runtime",), priority=100,
            content={"text": runtime_type.instructions},
        ).model_dump(mode="json"))
        context_items = await run_blocking(
            "hitl-port-context_snapshot", port.context_snapshot, prepared_items, lane="control-io",
            owner=__name__,
        )
        run_info.context_input = ContextInput(
            items=tuple(ContextItemInput.model_validate(item) for item in context_items)
        )
        catalog = _stable_value({
            "agent": config.model_dump(),
            "models": [item.model_dump() for item in run_info.model_config_list],
            "metadata": run_info.runtime_metadata,
        })
        await run_blocking("hitl-port-bind_catalog", port.bind_catalog, catalog, lane="control-io", owner=__name__)
        # Clarification and action approval share one suspension mechanism, but
        # enabling clarification must not silently turn every tool into a high-risk action.
        # Deployments opt into the conservative approval gate independently.
        port.allowed_tools = _allowed_tool_names(config.tools)
        run_info.human_interaction = runtime_type(port)
        buffered_chunks = []
        last_flush = time.monotonic()
        async for chunk in _stream_agent_chunks(
            agent_request=request, user_id=identity["user_id"], tenant_id=identity["tenant_id"],
            agent_run_info=run_info, memory_ctx=memory_context,
        ):
            buffered_chunks.append(chunk)
            if len(buffered_chunks) >= 32 or time.monotonic() - last_flush >= 0.25:
                await run_blocking(
                    "hitl-port-emit_chunks", port.emit_chunks, buffered_chunks, lane="control-io",
                    owner=__name__,
                )
                buffered_chunks = []
                last_flush = time.monotonic()
        if buffered_chunks:
            await run_blocking(
                "hitl-port-emit_chunks", port.emit_chunks, buffered_chunks, lane="control-io",
                owner=__name__,
            )
        await run_blocking(
            "hitl-port-finish", port.finish, run_info.attempt_outcome or "failed", lane="control-io",
            owner=__name__,
        )
    except asyncio.CancelledError:
        if run_info is not None:
            if run_info.cancellation_scope is not None:
                run_info.cancellation_scope.cancel()
            else:
                run_info.stop_event.set()
        raise
    except RunTerminated:
        if port is not None:
            try:
                await run_blocking("hitl-port-finish", port.finish, "stopped", lane="control-io", owner=__name__)
            except RunTerminated:
                pass
    except RecoveryRequired:
        if port is not None:
            await run_blocking(
                "hitl-port-finish", port.finish, "recovery_required", lane="control-io", owner=__name__,
            )
    except Exception:
        if port is not None:
            await run_blocking("hitl-port-finish", port.finish, "failed", lane="control-io", owner=__name__)
        raise
    finally:
        if run_info is not None:
            _unregister_agent_run_after_execution(
                identity["conversation_id"], identity["user_id"],
                run_info.attempt_outcome or "failed", agent_run_info=run_info,
            )


def is_conversation_running(conversation_id, user_id):
    """Return whether an owner has an active durable run in this conversation."""
    from database.user_tenant_db import get_user_tenant_by_user_id

    if not HITL_ENABLED:
        return False
    membership = get_user_tenant_by_user_id(user_id) or {}
    tenant_id = membership.get("tenant_id")
    return bool(tenant_id) and get_service().repository.latest(
        str(tenant_id), user_id, conversation_id, active_only=True,
    ) is not None


class HumanRunLeaseStore:
    async def recover(self):
        await run_blocking(
            "hitl-get_service-expire_waiting", get_service().expire_waiting, lane="control-io",
            owner=__name__,
        )

    async def claim_due(self, owner_id, limit, lease_seconds):
        await self.recover()
        rows = await run_blocking(
            "hitl-get_service-repository-claim", get_service().repository.claim, owner_id, limit,
            lease_seconds, lane="control-io", owner=__name__,
        )
        return [ClaimedJob(job_id=row["run_id"], payload=row) for row in rows]

    async def renew(self, job_id, owner_id, lease_seconds):
        return await run_blocking(
            "hitl-get_service-repository-renew", get_service().repository.renew, job_id, owner_id,
            lease_seconds, lane="control-io", owner=__name__,
        )

    async def release(self, job_id, owner_id):
        return await run_blocking(
            "hitl-get_service-repository-release", get_service().repository.release, job_id, owner_id,
            lane="control-io", owner=__name__,
        )


human_run_scheduler = LeaseScheduler(HumanRunLeaseStore(), execute_attempt, SchedulerConfig(
    poll_interval_seconds=1, lease_seconds=120, max_concurrency=HITL_MAX_CONCURRENCY,
))


async def stream_run(run_id, tenant_id, user_id, *, after=0):
    service = require_enabled()
    snapshot = await run_blocking(
        "hitl-service-snapshot", service.snapshot, run_id, tenant_id, user_id, lane="control-io",
        owner=__name__,
    )
    if after > snapshot["event_seq"]:
        raise InteractionError("Event cursor is ahead of the run", 422)

    async def events():
        cursor = after
        yield "data: " + json.dumps({"type": "human_run", "content": snapshot}) + "\n\n"
        while True:
            # Re-check ownership and deadlines for reconnecting subscribers.
            current = await run_blocking(
                "hitl-service-snapshot", service.snapshot, run_id, tenant_id, user_id, lane="control-io",
                owner=__name__,
            )
            rows = await run_blocking(
                "hitl-service-repository-events", service.repository.events, run_id, cursor,
                lane="control-io", owner=__name__,
            )
            for row in rows:
                cursor = row["seq"]
                payload = row["payload"]
                if "chunk_cipher" in payload:
                    yield f"id: {cursor}\n" + service.cipher.open(payload["chunk_cipher"])
                else:
                    yield f"id: {cursor}\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
            if cursor >= current["event_seq"] and (current["status"] in TERMINAL_STATUSES or (
                    current["status"] == "WAITING_HUMAN" and not current["attempt_active"] and not rows)):
                yield "data: " + json.dumps({"type": "human_run", "content": current}) + "\n\n"
                break
            if not rows:
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.5)

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "Connection": "keep-alive", "run_id": run_id,
        "conversation_id": str(snapshot["conversation_id"]),
    })


async def start_run(request, tenant_id, user_id, language, *, skip_user_save=False):
    from agents.agent_run_manager import agent_run_manager
    from management.services.agent.run import save_messages

    # Optional chat enhancement must not reject debug or deployments draining HITL.
    # Existing runs still use their owner-scoped resume/decision APIs.
    if request.is_debug or not HITL_ENABLED or not HITL_ACCEPT_NEW_RUNS:
        return None
    service = require_enabled()
    payload = {
        "runtime_mode": "linear-json-v1" if HITL_TOOL_APPROVAL_ENABLED else "native-live-v1",
        "request": request.model_dump(mode="json"), "language": language,
        "runtime_metadata": getattr(request, "_runtime_metadata_snapshot", {}),
        "runtime_metadata_version": getattr(request, "_runtime_metadata_version", None),
        "runtime_knowledge_context": getattr(request, "_runtime_knowledge_context", None),
    }
    await authorize_run(payload["request"], tenant_id, user_id)
    if service.repository.latest(tenant_id, user_id, request.conversation_id, active_only=True):
        raise InteractionError("This conversation already has an active run")
    reservation = agent_run_manager.reserve_agent_run(request.conversation_id, user_id)
    run_id = None
    try:
        run_id = await run_blocking(
            "hitl-service-create", service.create, tenant_id, user_id, request.conversation_id, payload,
            ready=False, lane="control-io", owner=__name__,
        )
        if not skip_user_save:
            save_messages(request, "user", user_id, tenant_id)
        await run_blocking(
            "hitl-service-initialized", service.initialized, run_id, tenant_id, user_id, succeeded=True,
            lane="control-io", owner=__name__,
        )
    except Exception:
        if run_id:
            await run_blocking(
                "hitl-service-initialized", service.initialized, run_id, tenant_id, user_id, succeeded=False,
                lane="control-io", owner=__name__,
            )
        raise
    finally:
        agent_run_manager.release_agent_run_reservation(request.conversation_id, user_id, reservation)
    return await stream_run(run_id, tenant_id, user_id)
