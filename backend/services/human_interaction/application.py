"""Composition root: authorized Agent preparation, durable scheduling, and SSE delivery."""

import asyncio
import json
import time
from functools import lru_cache

from fastapi.responses import StreamingResponse

from consts.const import HITL_ACCEPT_NEW_RUNS, HITL_ENABLED, HITL_ENCRYPTION_KEY, HITL_MAX_CONCURRENCY, HITL_WAIT_SECONDS
from database.human_interaction_db import HumanInteractionRepository
from nexent.core.human_interaction.contracts import RecoveryRequired, RunTerminated
from nexent.core.human_interaction.runtime import HumanInteractionRuntime
from nexent.scheduler import ClaimedJob, LeaseScheduler, SchedulerConfig

from .crypto import PayloadCipher
from .models import InteractionError
from .runtime_port import RuntimeInteractionPort
from .service import HumanInteractionService, TERMINAL_STATUSES


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


async def authorize_run(payload, tenant_id, user_id):
    from services.agent_service import get_conversation_service, list_all_agent_info_impl
    from database.user_tenant_db import get_user_tenant_by_user_id

    membership = await asyncio.to_thread(get_user_tenant_by_user_id, user_id)
    if not membership or str(membership.get("tenant_id")) != tenant_id:
        raise InteractionError("The run owner no longer belongs to this tenant", 403)
    conversation = await asyncio.to_thread(
        get_conversation_service, payload["conversation_id"], user_id, tenant_id,
    )
    if conversation is None:
        raise InteractionError("Conversation is no longer accessible", 403)
    agents = await list_all_agent_info_impl(tenant_id, user_id)
    if not any(item.get("agent_id") == payload["agent_id"] for item in agents):
        raise InteractionError("Agent is no longer accessible", 403)


async def execute_attempt(job, lease):
    from agents.agent_run_manager import agent_run_manager
    from consts.model import AgentRequest
    from services.agent_service import _stream_agent_chunks, prepare_agent_run

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

        port = RuntimeInteractionPort(service, identity, lease.owner_id, authorize)
        saved = port.request_payload
        request = AgentRequest.model_validate(saved["request"])
        request.__dict__["_runtime_metadata_snapshot"] = saved["runtime_metadata"]
        request.__dict__["_runtime_metadata_version"] = saved["runtime_metadata_version"]
        request.__dict__["_runtime_knowledge_context"] = saved.get("runtime_knowledge_context")
        await authorize_run(saved["request"], identity["tenant_id"], identity["user_id"])
        run_info, memory_context = await prepare_agent_run(
            agent_request=request, user_id=identity["user_id"], tenant_id=identity["tenant_id"],
            language=saved["language"], allow_memory_search=True,
        )
        config = run_info.agent_config
        if config.managed_agents or config.external_a2a_agents or request.minio_files:
            raise InteractionError("HITL requires a root Agent without sub-agents or attached workspace files", 422)
        # Execution uses the JSON interpreter; no sandbox or workspace side channels.
        run_info.sandbox_config = None
        run_info.workspace_path = None
        run_info.minio_files = None
        from nexent.core.agents.context import ContextItemInput
        from nexent.core.agents.context_input import ContextInput
        prepared_items = [item.model_dump(mode="json") for item in run_info.context_input.items]
        prepared_items.append(ContextItemInput(
            id="system:human_interaction", type="system", source=("runtime",), priority=100,
            content={"text": (
                "Durable human interaction is enabled. Registered tool: "
                "ask_user(question: str, options: list[str] | None = None) -> str. "
                "Proactively call it when information is missing or the goal is ambiguous. "
                "The validated human answer is returned to the same call on resume. Never request credentials. "
                "Code execution supports only linear assignments, JSON values, registered tool calls and print. "
                "Imports, attributes, loops, nested calls, subprocesses and arbitrary Python are unavailable. "
                "Split complex work into separate steps. Only registered tool calls can perform external actions."
            )},
        ).model_dump(mode="json"))
        context_items = await asyncio.to_thread(
            port.context_snapshot, prepared_items,
        )
        run_info.context_input = ContextInput(items=tuple(ContextItemInput.model_validate(item) for item in context_items))
        catalog = _stable_value({
            "agent": config.model_dump(),
            "models": [item.model_dump() for item in run_info.model_config_list],
            "metadata": run_info.runtime_metadata,
        })
        await asyncio.to_thread(port.bind_catalog, catalog)
        # Only built-in control tools are automatically allowed. Third-party annotations
        # and model-provided names never grant trust. All other tools require approval.
        allowed = {"final_answer"}
        trusted_plan_classes = {"CreatePlanTool", "UpdatePlanStepTool"}
        for tool in config.tools:
            if tool.source == "local" and tool.class_name in trusted_plan_classes:
                allowed.add(tool.name)
        port.allowed_tools = frozenset(allowed)
        run_info.human_interaction = HumanInteractionRuntime(port)
        buffered_chunks = []
        last_flush = time.monotonic()
        async for chunk in _stream_agent_chunks(
            agent_request=request, user_id=identity["user_id"], tenant_id=identity["tenant_id"],
            agent_run_info=run_info, memory_ctx=memory_context,
        ):
            buffered_chunks.append(chunk)
            if len(buffered_chunks) >= 32 or time.monotonic() - last_flush >= 0.25:
                await asyncio.to_thread(port.emit_chunks, buffered_chunks)
                buffered_chunks = []
                last_flush = time.monotonic()
        if buffered_chunks:
            await asyncio.to_thread(port.emit_chunks, buffered_chunks)
        await asyncio.to_thread(port.finish, run_info.attempt_outcome or "failed")
    except asyncio.CancelledError:
        if run_info is not None:
            run_info.stop_event.set()
        raise
    except RunTerminated:
        if port is not None:
            try:
                await asyncio.to_thread(port.finish, "stopped")
            except RunTerminated:
                pass
    except RecoveryRequired:
        if port is not None:
            await asyncio.to_thread(port.finish, "recovery_required")
    except Exception:
        if port is not None:
            await asyncio.to_thread(port.finish, "failed")
        raise
    finally:
        if run_info is not None:
            agent_run_manager.unregister_agent_run(identity["conversation_id"], identity["user_id"],
                                                   agent_run_info=run_info)


class HumanRunLeaseStore:
    async def recover(self):
        await asyncio.to_thread(get_service().expire_waiting)

    async def claim_due(self, owner_id, limit, lease_seconds):
        await self.recover()
        rows = await asyncio.to_thread(get_service().repository.claim, owner_id, limit, lease_seconds)
        return [ClaimedJob(job_id=row["run_id"], payload=row) for row in rows]

    async def renew(self, job_id, owner_id, lease_seconds):
        return await asyncio.to_thread(get_service().repository.renew, job_id, owner_id, lease_seconds)

    async def release(self, job_id, owner_id):
        return await asyncio.to_thread(get_service().repository.release, job_id, owner_id)


human_run_scheduler = LeaseScheduler(HumanRunLeaseStore(), execute_attempt, SchedulerConfig(
    poll_interval_seconds=1, lease_seconds=120, max_concurrency=HITL_MAX_CONCURRENCY,
))


async def stream_run(run_id, tenant_id, user_id, *, after=0):
    service = require_enabled()
    snapshot = await asyncio.to_thread(service.snapshot, run_id, tenant_id, user_id)

    async def events():
        cursor = after
        yield "data: " + json.dumps({"type": "human_run", "content": snapshot}) + "\n\n"
        while True:
            # Re-check ownership and deadlines for reconnecting subscribers.
            current = await asyncio.to_thread(service.snapshot, run_id, tenant_id, user_id)
            rows = await asyncio.to_thread(service.repository.events, run_id, cursor)
            for row in rows:
                cursor = row["seq"]
                payload = row["payload"]
                if "chunk_cipher" in payload:
                    yield service.cipher.open(payload["chunk_cipher"])
                else:
                    yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
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


async def start_run(request, tenant_id, user_id, language):
    from agents.agent_run_manager import agent_run_manager
    from services.agent_service import save_messages

    service = require_enabled()
    if not HITL_ACCEPT_NEW_RUNS:
        raise InteractionError("New human interaction runs are disabled; existing runs can still be resolved", 503)
    if request.is_debug or request.minio_files:
        raise InteractionError("HITL is available for normal chat without workspace attachments", 422)
    payload = {
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
        run_id = await asyncio.to_thread(service.create, tenant_id, user_id, request.conversation_id, payload, ready=False)
        save_messages(request, "user", user_id, tenant_id)
        await asyncio.to_thread(service.initialized, run_id, tenant_id, user_id, succeeded=True)
    except Exception:
        if run_id:
            await asyncio.to_thread(service.initialized, run_id, tenant_id, user_id, succeeded=False)
        raise
    finally:
        agent_run_manager.release_agent_run_reservation(request.conversation_id, user_id, reservation)
    return await stream_run(run_id, tenant_id, user_id)
