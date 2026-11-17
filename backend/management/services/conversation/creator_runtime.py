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

from contracts.errors.exceptions import (
    RuntimeCapacityExceededError,
    RuntimeQueueTimeoutError,
)
from infrastructure.concurrency import runtime_thread_manager
from infrastructure.streaming.channels import streaming_channel_manager
from management.db.conversation.repository import (
    checkpoint_creator_message,
    get_conversation_history,
    get_message_units,
)
from management.services.agent.lifecycle import (
    AgentRunAlreadyActiveError,
    agent_run_manager,
)
from management.services.agent.run_state import runtime_state_service
from nexent.core.agents.run_agent import DeferredAgentRun
from nexent.core.concurrency import ManagedTaskSpec, RunCancellationScope, run_blocking
from nexent.core.concurrency.errors import ThreadCapacityExceeded, ThreadQueueTimedOut

logger = logging.getLogger(__name__)
_producers: set[asyncio.Task] = set()
_request_claims: dict[str, float] = {}


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

    async def admit(self):
        if self.info is None:
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


async def claim_creator(conversation_id, user_id, generation):
    reservation = agent_run_manager.reserve_agent_run(conversation_id, user_id)
    try:
        if not await runtime_state_service.claim_creator_run_async(
            user_id, conversation_id, generation
        ):
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

        async def watch_cancel():
            try:
                while True:
                    alive = await runtime_state_service.creator_lease_async(
                        user_id, conversation_id, control.generation, True
                    )
                    if (
                        not alive
                        or control.stop_event.is_set()
                        or await runtime_state_service.is_cancelled_async(
                            user_id, conversation_id
                        )
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
                if any(
                    json.loads(line[6:]).get("type") == "error"
                    for line in event.splitlines()
                    if line.startswith("data: ")
                ):
                    status = "failed"
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

            def release(_future=None):
                agent_run_manager.unregister_agent_run(
                    conversation_id, user_id, status, agent_run_info=info
                )

            try:
                try:
                    await stream.aclose()
                except Exception:
                    status = "failed"
                    logger.exception(
                        "Creator stream cleanup failed conversation_id=%s",
                        conversation_id,
                    )
                channel.complete(status)
                await runtime_state_service.mark_stream_completed_async(
                    user_id, conversation_id, status, generation=control.generation
                )
            finally:
                try:
                    await streaming_channel_manager.remove_channel(
                        conversation_id, user_id, expected_channel=channel
                    )
                finally:
                    if (
                        control.execution is not None
                        and not control.execution.future.done()
                    ):
                        control.execution.future.add_done_callback(release)
                    else:
                        release()

    task = asyncio.create_task(produce())
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
    return channel.subscribe_with_history(0)


def unit_event(unit):
    kind = unit["unit_type"]
    content = unit.get("unit_content") or ""
    if kind in {
        "model_attempt_control",
        "agent_new_run",
        "skill_body",
        "file_content",
        "target_files",
        "done",
    }:
        try:
            event = json.loads(content)
            if isinstance(event, dict):
                return {**event, "unit_index": unit["unit_index"]}
        except (TypeError, json.JSONDecodeError):
            pass
    return {
        "type": kind,
        "content": content,
        "unit_index": unit["unit_index"],
        "tool_call_id": unit.get("tool_call_id"),
        "invocation_id": unit.get("invocation_id"),
    }


async def resume_creator(conversation_id, user_id):
    """Replay durable units then tail the current generation without starting it."""
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
    # Capture the local cursor before the history read so concurrent events are retained.
    cursor = channel.history_start_index if channel is not None else 0
    units = await run_blocking("creator-resume-units", get_message_units, message_id)

    async def replay():
        last_index = -1
        for unit in units:
            last_index = max(last_index, unit["unit_index"])
            yield "data: " + json.dumps(unit_event(unit), ensure_ascii=False) + "\n\n"
        if message.get("status") != "streaming":
            return

        async def persisted(until=None):
            nonlocal last_index
            latest = await run_blocking(
                "creator-replay-checkpoint", get_message_units, message_id
            )
            for unit in latest:
                index = unit["unit_index"]
                if index > last_index and (until is None or index < until):
                    if index != last_index + 1:
                        raise RuntimeError("Creator replay checkpoint has a gap")
                    last_index = index
                    yield (
                        "data: "
                        + json.dumps(unit_event(unit), ensure_ascii=False)
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

        if channel is not None:
            async for event in channel.subscribe_with_history(cursor):
                async for chunk in fresh(event):
                    yield chunk
            async for saved in persisted():
                yield saved
            return
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
