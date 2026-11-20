# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Creator worker ownership and recoverable subscriptions, independent of HTTP."""

import asyncio
import json
import logging
import time
import uuid
from contextlib import suppress
from threading import Event
from types import SimpleNamespace

from redis.exceptions import RedisError

from contracts.errors.exceptions import (
    RuntimeCapacityExceededError,
    RuntimeCoordinationUnavailableError,
    RuntimeQueueTimeoutError,
)
from management.services.agent.control import get_owned_execution
from management.services.agent.replay import ExecutionReplayUnavailable, follow_execution_replay
from runtime.thread_management import runtime_thread_manager
from management.services.agent.channels import streaming_channel_manager
from management.services.conversation.runtime_output import is_runtime_event
from management.services.conversation.creator_events import unit_event
from management.services.conversation.creator_replay import creator_checkpoint_stream
from management.db.conversation.repository import (
    checkpoint_creator_message,
    get_conversation_history,
    get_message_units,
)
from management.services.agent.lifecycle import (
    AgentRunAlreadyActiveError,
    agent_run_manager,
)
from infrastructure.redis.run_state import runtime_state_service
from nexent.core.agents.orchestration.entry import DeferredAgentRun
from nexent.core.concurrency import ManagedTaskSpec, RunCancellationScope, run_blocking
from nexent.core.concurrency.errors import ThreadCapacityExceeded, ThreadManagerError, ThreadQueueTimedOut

logger = logging.getLogger(__name__)
_producers: set[asyncio.Task] = set()
_request_claims: dict[str, float] = {}


async def wait_creator_step(operation):
    """Let a submitted preparation write settle before unwinding its owner."""
    task = asyncio.create_task(operation)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled():
            task.exception()
        raise


async def required_creator_redis(operation, *args, **kwargs):
    try:
        if not runtime_state_service.enabled:
            raise RuntimeError("Runtime Redis is disabled")
        return await operation(*args, **kwargs)
    except Exception as exc:
        raise RuntimeCoordinationUnavailableError("Creator Redis coordination is unavailable") from exc


async def claim_request(key, ttl):
    if runtime_state_service.enabled:
        return await runtime_state_service.acquire_idempotency_async(key, ttl)
    now = time.monotonic()
    for expired in [k for k, deadline in _request_claims.items() if deadline <= now]:
        del _request_claims[expired]
    if key in _request_claims:
        return False
    _request_claims[key] = now + ttl
    return True


async def release_request(key):
    if runtime_state_service.enabled:
        await runtime_state_service.release_idempotency_async(key)
    else:
        _request_claims.pop(key, None)


class CreatorControl:
    """One admitted generation; all cancellation paths share its scope."""

    def __init__(self):
        self.generation = uuid.uuid4().hex
        self.stop_event = Event()
        self.scope = RunCancellationScope(self.stop_event)
        self.deferred = DeferredAgentRun()
        self.execution = None
        self.info = None
        self.durable = None
        self.producer_started = False

    def bind_reservation(self, reservation):
        self.durable = reservation
        self.generation = f"execution:{reservation.execution_id}"

    async def is_cancelled(self, conversation_id, user_id):
        if self.durable is not None:
            return await runtime_state_service.is_execution_cancelled_async(
                user_id, conversation_id, self.durable.execution_id, self.generation,
            )
        return await runtime_state_service.is_cancelled_async(user_id, conversation_id)

    def configure(self, info):
        self.info = info
        info.stop_event = self.stop_event
        info.cancellation_scope = self.scope
        info.__dict__["_automation_runtime_generation"] = self.generation

    def guard_preparation(self, conversation_id, user_id):
        """Renew ownership while async target/model preparation is still pending."""
        if not runtime_state_service.enabled:
            return None
        owner = asyncio.current_task()

        async def renew():
            try:
                while await runtime_state_service.creator_lease_async(
                    user_id, conversation_id, self.generation, True
                ):
                    await asyncio.sleep(0.25)
            except Exception:
                logger.exception(
                    "Creator preparation heartbeat failed conversation_id=%s",
                    conversation_id,
                )
            self.cancel()
            owner.cancel()

        return asyncio.create_task(renew())

    async def admit(self, *, early=False):
        if self.execution is not None or (self.info is None and not early):
            return
        try:
            self.execution = runtime_thread_manager.submit(
                "agent-run",
                ManagedTaskSpec(
                    task_name="creator-run",
                    owner=__name__,
                    run_id=self.generation,
                    close_hook=self.deferred.cancel,
                    pass_cancel_event=True,
                ),
                self.deferred.run,
            )
            await runtime_thread_manager.wait_until_started(self.execution)
        except ThreadCapacityExceeded as exc:
            raise RuntimeCapacityExceededError() from exc
        except ThreadQueueTimedOut as exc:
            self.cancel()
            raise RuntimeQueueTimeoutError(exc.timeout_seconds) from exc

    def cancel(self):
        self.scope.cancel()
        self.deferred.cancel()
        if self.execution is not None:
            runtime_thread_manager.cancel(
                self.execution.execution_id,
                reason="creator execution cancelled",
                wait_timeout=0,
                mark_stuck_on_timeout=False,
            )

    def registered_info(self):
        return self.info or SimpleNamespace(
            stop_event=self.stop_event,
            cancellation_scope=self.scope,
            _automation_runtime_generation=self.generation,
        )


async def claim_creator(conversation_id, user_id, generation, *, execution_id=None):
    reservation = agent_run_manager.reserve_agent_run(conversation_id, user_id)
    try:
        claim = runtime_state_service.claim_creator_run_async
        args = (user_id, conversation_id, generation)
        claimed = (
            await required_creator_redis(claim, *args, execution_id=execution_id)
            if execution_id is not None else await claim(*args)
        )
        if not claimed:
            raise AgentRunAlreadyActiveError(
                "Creator conversation already has an active execution"
            )
        return reservation
    except BaseException:
        agent_run_manager.release_agent_run_reservation(
            conversation_id, user_id, reservation
        )
        raise


async def launch_creator(stream, *, control, conversation_id, user_id, reservation):
    # Replacing a completed channel cannot affect subscribers holding its object.
    previous = streaming_channel_manager.get_channel(conversation_id, user_id)
    if previous is not None:
        await streaming_channel_manager.remove_channel(
            conversation_id, user_id, expected_channel=previous
        )
    channel = await streaming_channel_manager.get_or_create_channel(
        conversation_id, user_id
    )
    channel.generation = control.generation
    info = control.registered_info()
    agent_run_manager.register_agent_run(conversation_id, info, user_id, reservation)
    started = asyncio.Event()

    async def produce():
        status = "completed"
        producer = asyncio.current_task()

        async def finalize():
            nonlocal status

            def release(_future=None):
                agent_run_manager.unregister_agent_run(
                    conversation_id, user_id, status, agent_run_info=info
                )

            try:
                if control.durable is not None:
                    try:
                        await control.durable.finalizing()
                    except Exception:
                        status = "failed"
                        control.cancel()
                        logger.exception("Creator finalizing transition failed run_id=%s", control.generation)
                try:
                    await stream.aclose()
                except Exception:
                    status = "failed"
                    logger.exception("Creator stream cleanup failed conversation_id=%s", conversation_id)
                channel.complete(status)
                event_count = channel.durable_event_count
                await runtime_state_service.mark_stream_completed_async(
                    user_id, conversation_id, status, generation=control.generation,
                    **({"event_count": event_count} if event_count is not None else {}),
                )
            finally:
                try:
                    await streaming_channel_manager.remove_channel(
                        conversation_id, user_id, expected_channel=channel
                    )
                finally:
                    try:
                        if control.execution is not None and not control.execution.future.done():
                            control.execution.future.add_done_callback(release)
                        else:
                            release()
                    finally:
                        if control.durable is not None:
                            control.durable.outcome = status
                            control.durable.close()

        async def watch_cancel():
            try:
                while True:
                    alive = await runtime_state_service.creator_lease_async(
                        user_id, conversation_id, control.generation, True
                    )
                    if (
                        not alive
                        or control.stop_event.is_set()
                        or await control.is_cancelled(conversation_id, user_id)
                    ):
                        control.cancel()
                        producer.cancel()
                        return
                    await asyncio.sleep(0.25)
            except Exception:
                logger.exception(
                    "Creator ownership heartbeat failed run_id=%s", control.generation
                )
                control.cancel()
                producer.cancel()

        watcher = asyncio.create_task(watch_cancel())
        try:
            started.set()
            async for event in stream:
                if control.stop_event.is_set():
                    raise asyncio.CancelledError()
                if not await runtime_state_service.creator_lease_async(
                    user_id, conversation_id, control.generation
                ):
                    raise asyncio.CancelledError()
                for line in event.splitlines():
                    if not line.startswith("data: "):
                        continue
                    chunk = json.loads(line[6:])
                    if chunk.get("type") == "error":
                        status = "failed"
                    elif (is_runtime_event(chunk) and chunk.get("type") == "run_terminal"
                          and not chunk.get("invocation_id")
                          and chunk.get("status") in {"completed", "failed", "stopped"}):
                        status = chunk["status"]
                await channel.publish(event)
        except asyncio.CancelledError:
            status = "stopped"
            control.cancel()
        except Exception:
            status = "failed"
            control.cancel()
            logger.exception(
                "Creator producer failed conversation_id=%s run_id=%s",
                conversation_id,
                control.generation,
            )
            await channel.publish(
                'data: {"type":"error","content":"Creator execution failed."}\n\n'
            )
        finally:
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher
            if control.durable is not None:
                await wait_creator_step(finalize())
            else:
                await finalize()

    task = asyncio.create_task(produce())
    control.producer_started = True
    _producers.add(task)

    def finished(completed):
        _producers.discard(completed)
        if not completed.cancelled() and (error := completed.exception()) is not None:
            logger.error(
                "Creator finalization failed conversation_id=%s",
                conversation_id,
                exc_info=(type(error), error, error.__traceback__),
            )

    task.add_done_callback(finished)
    # Enter the checkpoint generator before accepting the request, so even an
    # immediate shutdown executes its terminal persistence and ownership cleanup.
    await started.wait()
    return channel.subscribe_with_history(0, include_replay_checkpoint=True)


async def resume_owned_creator(conversation_id, user_id, tenant_id, execution_id, snapshot, message_id):
    """Replay an owned Creator generation without ever recovering or mutating the producer."""
    last_index = -1
    unavailable = False

    async def is_active():
        current = await get_owned_execution(tenant_id, user_id, conversation_id, active_only=True)
        return current is not None and current[0] == execution_id and await runtime_state_service.creator_lease_async(
            user_id, conversation_id, snapshot["generation"],
        )

    if snapshot is not None and (snapshot["checkpoint"] is not None or not snapshot["terminal_status"]):
        try:
            async for frame, _outcome in follow_execution_replay(
                runtime_state_service, user_id, conversation_id, execution_id, snapshot, is_active=is_active,
            ):
                if frame is None:
                    return
                for line in frame.splitlines():
                    if line.startswith("data: "):
                        last_index = max(last_index, json.loads(line[6:]).get("unit_index", -1))
                yield frame
        except (RedisError, ThreadManagerError, RuntimeCoordinationUnavailableError, ExecutionReplayUnavailable):
            unavailable = True

    if message_id is not None:
        units = await run_blocking("creator-owned-resume-units", get_message_units, message_id)
        context = {}
        for unit in units:
            event = unit_event(unit, context)
            if unit["unit_index"] > last_index:
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
    if unavailable:
        yield 'data: {"type":"error","content":"Shared Creator replay unavailable; showing saved history."}\n\n'


async def resume_creator(conversation_id, user_id):
    """Replay complete local/shared events, using durable units as the fallback."""
    history = await run_blocking(
        "creator-resume-history", get_conversation_history, conversation_id, user_id
    )
    assistants = [
        m for m in history.get("message_records", []) if m.get("role") == "assistant"
    ]
    if not assistants:
        raise ValueError("Creator has no answer to resume")
    message = max(assistants, key=lambda m: m["message_id"])
    message_id = message["message_id"]
    state = await runtime_state_service.get_run_state_async(user_id, conversation_id)
    generation = state.get("generation")
    channel = streaming_channel_manager.get_channel(conversation_id, user_id)
    preferred = await creator_checkpoint_stream(
        runtime_state_service, channel, generation, user_id, conversation_id
    )

    async def replay():
        last_index = -1
        if preferred is not None:
            try:
                async for frame in preferred:
                    for line in frame.splitlines():
                        if line.startswith("data: "):
                            last_index = max(last_index, json.loads(line[6:]).get("unit_index", -1))
                    yield frame
                return
            except (RedisError, RuntimeError):
                logger.warning("Creator replay checkpoint unavailable conversation_id=%s", conversation_id)
        units = await run_blocking("creator-resume-units", get_message_units, message_id)
        context = {}
        for unit in units:
            event = unit_event(unit, context)
            if unit["unit_index"] > last_index:
                if unit["unit_index"] != last_index + 1:
                    raise RuntimeError("Creator replay checkpoint has a gap")
                last_index = unit["unit_index"]
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        if message.get("status") != "streaming":
            return

        async def persisted(until=None):
            nonlocal last_index
            latest = await run_blocking(
                "creator-replay-checkpoint", get_message_units, message_id
            )
            context.clear()
            for unit in latest:
                event = unit_event(unit, context)
                index = unit["unit_index"]
                if index > last_index and (until is None or index < until):
                    if index != last_index + 1:
                        raise RuntimeError("Creator replay checkpoint has a gap")
                    last_index = index
                    yield (
                        "data: "
                        + json.dumps(event, ensure_ascii=False)
                        + "\n\n"
                    )

        async def fresh(event):
            nonlocal last_index
            for line in event.splitlines():
                if line.startswith("data: "):
                    chunk = json.loads(line[6:])
                    index = chunk.get("unit_index", -1)
                    if index > last_index + 1:
                        async for saved in persisted(index):
                            yield saved
                        if index != last_index + 1:
                            raise RuntimeError("Creator replay buffer is incomplete")
                    if index > last_index:
                        last_index = index
                        yield "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"

        async def interrupted():
            async for saved in persisted():
                yield saved
            current = await runtime_state_service.get_run_state_async(
                user_id, conversation_id
            )
            if current.get("generation") != generation:
                return
            error = {
                "unit_index": last_index + 1,
                "unit_type": "error",
                "unit_content": "Creator execution was interrupted. Retry to continue.",
            }
            try:
                await run_blocking(
                    "creator-mark-interrupted",
                    checkpoint_creator_message,
                    message_id,
                    conversation_id,
                    user_id,
                    [error],
                    message.get("message_content", ""),
                    "failed",
                )
            except ValueError:
                # A terminal checkpoint or a newer turn won the conversation lock.
                return
            await runtime_state_service._run_managed(
                "creator-interrupted-state",
                runtime_state_service.mark_run_finished,
                user_id,
                conversation_id,
                "failed",
                generation,
            )
            yield "data: " + json.dumps(unit_event(error), ensure_ascii=False) + "\n\n"

        if state.get("status") in {"completed", "failed", "stopped"}:
            async for saved in persisted():
                yield saved
            return
        alive = (
            runtime_state_service.enabled
            and await runtime_state_service.creator_lease_async(
                user_id, conversation_id, generation
            )
        )
        if not alive:
            async for chunk in interrupted():
                yield chunk
            return
        last_id = "0-0"
        while True:
            current = await runtime_state_service.get_run_state_async(
                user_id, conversation_id
            )
            if current.get("generation") != generation:
                return
            events = await runtime_state_service.wait_for_stream_events_async(
                user_id, conversation_id, last_id
            )
            for event_id, event in events:
                last_id = event_id
                async for chunk in fresh(event):
                    yield chunk
            if current.get("status") != "running":
                async for saved in persisted():
                    yield saved
                return
            if not await runtime_state_service.creator_lease_async(
                user_id, conversation_id, generation
            ):
                async for chunk in interrupted():
                    yield chunk
                return

    return replay()


async def shutdown_creator_streams(timeout):
    """Cancel owned producers before the runtime thread manager shuts down."""
    pending = list(_producers)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.wait(pending, timeout=max(0, timeout))
    return sum(not task.done() for task in pending)
