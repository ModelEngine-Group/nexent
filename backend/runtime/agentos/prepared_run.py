# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute signed conversation snapshots and retain Runtime observer events."""

import asyncio
import json
import logging
from contextlib import aclosing

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from contracts.agentos import BODY_KEY, PRINCIPAL_KEY, AgentOperation, AgentRunReference, PreparedAgentRun
from contracts.constants.environment import RUNTIME_CANCEL_POLL_INTERVAL_SECONDS
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.agent_execution import (
    ActiveExecutionError, RunIdentity, begin_execution, finish_execution, mark_running, stop_requested, track_execution,
)
from infrastructure.redis.agent_events import RunJournal
from infrastructure.redis.run_state import runtime_state_service
from nexent.core.concurrency import run_blocking
from runtime.adapters.nexent.runner import agent_run
from runtime.agentos.prepared_evaluation import (
    discard_prepared_workspace, load_prepared_run, prepare_run_snapshot, release_prepared_run,
)
from runtime.executions import agent_run_manager
from runtime.thread_management import agent_stream_producer_tasks, runtime_thread_manager

logger = logging.getLogger(__name__)


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


async def _run_snapshot(payload, actor, identity, journal):
    info = await load_prepared_run(payload, actor, prepare_run_snapshot)
    try:
        agent_run_manager.register_agent_run(identity.conversation_id, info, identity.user_id)
    except BaseException:
        discard_prepared_workspace(info)
        raise

    status = "failed"
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
        index = 0
        async with aclosing(_snapshot_chunks(info)) as chunks:
            async for chunk in chunks:
                # Re-encode JSON to keep each payload within one SSE data line.
                observer_event = json.loads(chunk)
                if observer_event.get("type") == "skill_artifact":
                    raise ValueError("Prepared runs cannot journal local skill artifact paths")
                event = json.dumps(observer_event, ensure_ascii=False, separators=(",", ":"))
                index += 1
                await _control_io(
                    "agentos-prepared-event", journal.append, index, f"event: agentos_observer\ndata: {event}\n\n",
                )
        status = info.attempt_outcome or "completed"
        return status
    except asyncio.CancelledError:
        status = "stopped"
        raise
    finally:
        release_prepared_run(info, identity.conversation_id, identity.user_id, status)


async def _produce(payload, actor, identity, journal):
    status = "failed"
    runner = asyncio.create_task(_run_snapshot(payload, actor, identity, journal))
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
        for task in (runner, monitor):
            if not task.done():
                task.cancel()
        await asyncio.gather(runner, monitor, return_exceptions=True)
        try:
            finished = await _control_io("agentos-prepared-finish", finish_execution, identity, status)
            if finished:
                await _control_io("agentos-prepared-terminal", journal.repair_terminal, status)
        except (RedisError, SQLAlchemyError, RuntimeError):
            logger.exception("Prepared AgentOS terminal will be reconciled run_id=%s", identity.run_id)


async def _admit(payload, actor):
    identity = RunIdentity(actor.tenant_id, actor.user_id, payload.conversation_id, payload.run_id)
    try:
        await _control_io("agentos-prepared-begin", begin_execution, identity)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"}) from exc
    except ActiveExecutionError as exc:
        raise HTTPException(status_code=409, detail={"code": "AGENTOS_RUN_ALREADY_ACTIVE"}) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail={"code": "AGENTOS_EXECUTION_STORE_UNAVAILABLE"}) from exc

    track_execution(identity)
    journal = RunJournal(identity.tenant_id, identity.user_id, identity.conversation_id, identity.run_id)
    try:
        await _control_io("agentos-prepared-journal", journal.start)
    except (RedisError, RuntimeError) as exc:
        try:
            await _control_io("agentos-prepared-reject", finish_execution, identity, "failed")
        except (SQLAlchemyError, RuntimeError):
            logger.exception("Prepared AgentOS admission cleanup will be reconciled run_id=%s", identity.run_id)
        raise HTTPException(status_code=503, detail={"code": "AGENTOS_EVENT_STORE_UNAVAILABLE"}) from exc

    producer = asyncio.create_task(_produce(payload, actor, identity, journal), name=f"agentos-run:{identity.run_id}")
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
        return await start_prepared_run(payload, actor)

    return router
