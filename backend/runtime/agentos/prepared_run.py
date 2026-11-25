# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute signed conversation snapshots and retain Runtime observer events."""

import asyncio
import json
import logging
from concurrent.futures import Future
from contextlib import aclosing
from dataclasses import dataclass
from functools import partial
from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from contracts.agentos import BODY_KEY, PRINCIPAL_KEY, AgentOperation, AgentRunReference, PreparedAgentRun
from contracts.constants.environment import RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS, RUNTIME_CANCEL_POLL_INTERVAL_SECONDS
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.agent_execution import (
    ActiveExecutionError, RunIdentity, begin_execution, finish_execution, mark_running, stop_requested, track_execution,
)
from infrastructure.rdb.conversation_state import load_execution_result_record
from infrastructure.redis.agent_events import RunJournal
from infrastructure.redis.run_state import runtime_state_service
from nexent.core.concurrency import run_blocking
from nexent.core.agents.context.execution_history import ExecutionHistory
from nexent.core.agents.context.native_history import decode_history_event
from nexent.monitor import AgentRunMetadata, agent_monitoring_context
from runtime.adapters.nexent.runner import agent_run
from runtime.agentos.prepared_automation import request_automation_proposal
from runtime.agentos.prepared_evaluation import (
    discard_prepared_workspace, load_prepared_run, prepare_run_snapshot, release_prepared_run,
)
from runtime.agentos.history_sources import discover_summary_sources
from runtime.executions import AgentRunConcurrencyExceededError, agent_run_manager
from runtime.thread_management import agent_stream_producer_tasks, runtime_thread_manager

logger = logging.getLogger(__name__)


@dataclass
class _AdmissionSlot:
    """Hold one runtime slot for the lifetime of its worker."""

    token: str
    worker: Future | None = None
    cleanup: Callable[[], None] | None = None

    def release(self, _completed=None):
        if self.worker is not None and not self.worker.done():
            self.worker.add_done_callback(self.release)
            return
        agent_run_manager.release_agent_capacity(self.token)


async def _control_io(task, function, *args):
    return await run_blocking(task, function, *args, lane="control-io", owner="runtime")


async def _wait_for_stop(identity):
    while not await _control_io("agentos-prepared-stop", stop_requested, identity):
        await asyncio.sleep(RUNTIME_CANCEL_POLL_INTERVAL_SECONDS)


async def _snapshot_chunks(info):
    for event in info.agent_config.pre_run_tool_events:
        yield json.dumps(event, ensure_ascii=False)
    async with aclosing(agent_run(info, thread_manager=runtime_thread_manager)) as chunks:
        async for chunk in chunks:
            yield chunk


def _read_execution_result(user_id, tenant_id, conversation_id, message_id, unit_index):
    record = load_execution_result_record(user_id, tenant_id, conversation_id, message_id, unit_index)
    if record["record_type"] == "tool_result":
        event = decode_history_event(record)
        if event is None or not event.get("call_id"):
            raise ValueError("Invalid persisted native execution result")
        return event["result"]
    payload = json.loads(record["content"])
    if not isinstance(payload, dict) or not isinstance(payload.get("content"), str):
        raise ValueError("Invalid persisted execution content")
    return payload["content"]


async def _automation_proposal_chunks(info, payload, actor):
    reference = AgentRunReference(conversation_id=payload.conversation_id, run_id=payload.run_id)
    try:
        result = await request_automation_proposal(reference, actor)
        message = result.get("user_message")
        if not isinstance(message, str) or not message:
            raise RuntimeError("Scheduled-task proposal response is missing its message")
        if result["status"] == "proposal_ready":
            proposal = result.get("proposal")
            if not isinstance(proposal, dict) or not proposal.get("proposal_id"):
                raise RuntimeError("Scheduled-task proposal response is missing its proposal")
            yield json.dumps({
                "type": "automation_proposal",
                "content": json.dumps(proposal, ensure_ascii=False),
            }, ensure_ascii=False)
        elif result["status"] == "error":
            info.attempt_outcome = "failed"
    except RuntimeError:
        logger.warning("Scheduled-task proposal request failed for run %s", reference.run_id)
        info.attempt_outcome = "failed"
        message = (
            "暂时无法生成定时任务提案，请稍后重试。"
            if payload.language == "zh"
            else "The scheduled-task proposal could not be generated. Try again shortly."
        )
    yield json.dumps({"type": "final_answer", "content": message}, ensure_ascii=False)


def _execution_record(history, event):
    value = event.get("content")
    try:
        value = json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return None, None
    key = value.get("execution_key") if isinstance(value, dict) else None
    record = history.get(key) if isinstance(key, str) else None
    return (key, record) if record is not None and record.reference is None else (None, None)


async def _append_event(journal, sequence, kind, payload):
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    await _control_io("agentos-prepared-event", journal.append, sequence, f"event: {kind}\ndata: {data}\n\n")


async def _run_snapshot(payload, actor, identity, journal, slot=None):
    info = await load_prepared_run(payload, actor, prepare_run_snapshot)
    try:
        agent_run_manager.register_agent_run(identity.conversation_id, info, identity.user_id)
    except BaseException:
        discard_prepared_workspace(info)
        raise

    status = "failed"
    facts = {}
    index = 0
    try:
        versions = {
            "agent_id": payload.resource.agent_id,
            "agent_version_no": payload.resource.version_no,
            "model_id": payload.models.llm.model_id,
            "model_revision": payload.models.llm.revision,
            "mounted_agents": [
                {"agent_id": item.agent_id, "version_no": item.version_no}
                for item in payload.resource.subagents
            ],
        }
        if payload.runtime_metadata_version is not None:
            versions["runtime_metadata_version"] = payload.runtime_metadata_version
        if payload.workbench_config_version is not None:
            versions["workbench_config_version"] = payload.workbench_config_version
        if not versions["mounted_agents"]:
            del versions["mounted_agents"]
        if not await _control_io("agentos-prepared-running", mark_running, identity, versions):
            status = "stopped"
            return status
        metadata = AgentRunMetadata(
            user_id=actor.user_id, tenant_id=actor.tenant_id, conversation_id=identity.conversation_id,
            agent_id=payload.resource.agent_id, query=payload.input.trace_query, language=payload.language,
            is_debug=False, memory_enabled=bool(payload.memory_enabled), history_count=len(payload.input.history),
            minio_files_count=len(payload.input.attachment_refs), extra_metadata={"agentos_run_id": identity.run_id},
        )
        checkpoint = payload.historical_context.history_summary if payload.historical_context is not None else None
        history = ExecutionHistory(read_conversation_result=partial(
            _read_execution_result, actor.user_id, actor.tenant_id, identity.conversation_id,
        ), discover_summary_sources=(partial(
            discover_summary_sources, actor.user_id, actor.tenant_id, identity.conversation_id,
            checkpoint.unit_id, checkpoint.covered_through_message_id,
        ) if checkpoint is not None else None))
        info.observer.execution_history = history
        facts = {}
        index = 0
        with agent_monitoring_context(metadata):
            stream = (
                _automation_proposal_chunks(info, payload, actor)
                if payload.automation_proposal_only else _snapshot_chunks(info)
            )
            async with aclosing(stream) as chunks:
                async for chunk in chunks:
                    # Re-encode JSON to keep each payload within one SSE data line.
                    observer_event = json.loads(chunk)
                    if observer_event.get("type") == "skill_artifact":
                        raise ValueError("Prepared runs cannot journal local skill artifact paths")
                    if observer_event.get("type") == "execution_result":
                        key, record = _execution_record(history, observer_event)
                        if record is None:
                            continue
                        index += 1
                        fact = record.payload()
                        for field in ("invocation_id", "tool_call_id", "step_id"):
                            if isinstance(observer_event.get(field), str):
                                fact[field] = observer_event[field]
                        await _append_event(journal, index, "agentos_execution_fact", fact)
                        history.bind_run(key, identity.run_id, index)
                        facts[index] = (record, fact.get("summary"), fact.get("model_view"))
                        continue
                    index += 1
                    await _append_event(journal, index, "agentos_observer", observer_event)
        status = info.attempt_outcome or "completed"
        return status
    except asyncio.CancelledError:
        status = "stopped"
        raise
    finally:
        try:
            for fact_index, (record, original_summary, original_view) in facts.items():
                update = {}
                if record.summary and record.summary != original_summary:
                    update["summary"] = record.summary
                if record.model_view is not None and record.model_view != original_view:
                    update["model_view"] = record.model_view
                if update:
                    index += 1
                    await _append_event(journal, index, "agentos_execution_summary", {
                        "fact_sequence": fact_index, **update,
                    })
        finally:
            if slot is None:
                release_prepared_run(info, identity.conversation_id, identity.user_id, status)
            else:
                slot.worker = info.thread_future
                slot.cleanup = partial(release_prepared_run, info, identity.conversation_id, identity.user_id, status)


async def _finish_producer(runner, monitor, identity, journal, status, slot):
    for task in (runner, monitor):
        if not task.done():
            task.cancel()
    await asyncio.gather(runner, monitor, return_exceptions=True)
    if slot is not None and slot.cleanup is not None:
        # Keep the persisted conversation reservation until local cleanup finishes.
        if slot.worker is not None:
            await asyncio.gather(asyncio.wrap_future(slot.worker), return_exceptions=True)
        slot.cleanup()
    try:
        finished = await _control_io("agentos-prepared-finish", finish_execution, identity, status)
        if finished:
            await _control_io("agentos-prepared-terminal", journal.repair_terminal, status)
    except (RedisError, SQLAlchemyError, RuntimeError):
        logger.exception("Prepared AgentOS terminal will be reconciled run_id=%s", identity.run_id)


async def _produce(payload, actor, identity, journal, slot=None):
    status = "failed"
    runner = asyncio.create_task(_run_snapshot(payload, actor, identity, journal, slot))
    monitor = asyncio.create_task(_wait_for_stop(identity))
    try:
        done, _ = await asyncio.wait((runner, monitor), return_when=asyncio.FIRST_COMPLETED)
        if runner in done:
            status = "stopped" if runner.cancelled() else runner.result()
        else:
            monitor.result()
            status = "stopped"
    except asyncio.CancelledError:
        status = "stopped"
        raise
    except Exception:
        logger.exception("Prepared AgentOS run failed run_id=%s", identity.run_id)
    finally:
        # Keep joining the owned worker and terminal write during repeated shutdown cancellation.
        cleanup = asyncio.create_task(_finish_producer(runner, monitor, identity, journal, status, slot))
        cancelled = False
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled = True
        cleanup.result()
        if cancelled:
            raise asyncio.CancelledError


async def _start_journal(identity):
    try:
        await _control_io("agentos-prepared-begin", begin_execution, identity)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"}) from exc
    except ActiveExecutionError as exc:
        raise HTTPException(status_code=409, detail={"code": "AGENTOS_RUN_ALREADY_ACTIVE"}) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail={"code": "AGENTOS_EXECUTION_STORE_UNAVAILABLE"}) from exc

    track_execution(identity)
    journal = RunJournal(
        identity.tenant_id, identity.user_id, identity.conversation_id, identity.run_id, retain_for_projection=True,
    )
    try:
        await _control_io("agentos-prepared-journal", journal.start)
    except (RedisError, RuntimeError) as exc:
        try:
            await _control_io("agentos-prepared-reject", finish_execution, identity, "failed")
        except (SQLAlchemyError, RuntimeError):
            logger.exception("Prepared AgentOS admission cleanup will be reconciled run_id=%s", identity.run_id)
        raise HTTPException(status_code=503, detail={"code": "AGENTOS_EVENT_STORE_UNAVAILABLE"}) from exc
    return journal


async def _admit(payload, actor):
    identity = RunIdentity(actor.tenant_id, actor.user_id, payload.conversation_id, payload.run_id)
    key = payload.resource.agent_id
    if payload.workbench_config_version is not None:
        key = f"{actor.tenant_id}:workbench_main"
    slot = _AdmissionSlot(agent_run_manager.reserve_agent_capacity(key, RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS))
    try:
        journal = await _start_journal(identity)
        producer = asyncio.create_task(_produce(payload, actor, identity, journal, slot), name=f"agentos-run:{identity.run_id}")
    except BaseException:
        slot.release()
        raise
    producer.add_done_callback(slot.release)
    agent_stream_producer_tasks.add(producer)
    producer.add_done_callback(agent_stream_producer_tasks.discard)
    return AgentRunReference(conversation_id=identity.conversation_id, run_id=identity.run_id)


async def start_prepared_run(payload: PreparedAgentRun, actor: ServicePrincipal) -> AgentRunReference:
    if not runtime_state_service.enabled:
        raise HTTPException(status_code=503, detail={"code": "AGENTOS_EVENT_STORE_UNAVAILABLE"})

    # Settle an admitted run even if the caller drops the acknowledgement.
    admission = asyncio.create_task(_admit(payload, actor))
    try:
        return await asyncio.shield(admission)
    except asyncio.CancelledError:
        await asyncio.gather(admission, return_exceptions=True)
        raise


def create_prepared_run_router() -> APIRouter:
    router = APIRouter()

    @router.post(AgentOperation.RUN.value, status_code=202, include_in_schema=False)
    async def submit(request: Request):
        actor = request.scope.get(PRINCIPAL_KEY)
        if actor is None:
            return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
        try:
            payload = PreparedAgentRun.model_validate_json(request.scope[BODY_KEY])
        except ValidationError:
            return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)
        try:
            return await start_prepared_run(payload, actor)
        except AgentRunConcurrencyExceededError:
            return JSONResponse({
                "code": "RUNTIME_CAPACITY_FULL", "message": "Agent runtime is at capacity.", "retryable": True,
            }, status_code=429, headers={"Retry-After": "1"})

    return router
