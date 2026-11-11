# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Own the lifetime of a legacy SSE producer in Runtime."""

import asyncio
import logging

from contracts.agentos import AGENTOS_PREPARATION_STOP
from infrastructure.agent_stream_channels import streaming_channel_manager
from infrastructure.legacy_stream_replay import cleanup_channel_later
from infrastructure.rdb.agent_execution import RunIdentity, finish_execution
from nexent.core.concurrency import run_blocking
from nexent.monitor import agent_monitoring_context

logger = logging.getLogger(__name__)


async def consume_legacy_producer(
    stream_gen,
    channel,
    agent_metadata,
    conversation_id: int,
    user_id: str,
    *,
    execution_host,
    render_error,
) -> None:
    """Consume a non-debug agent stream independently from its SSE subscriber."""
    host = execution_host
    fallback_status = "failed"
    producer_error = False
    try:
        with agent_monitoring_context(agent_metadata):
            async for _ in stream_gen:
                pass
    except asyncio.CancelledError as exc:
        if exc.args == (AGENTOS_PREPARATION_STOP,):
            fallback_status = "stopped"
        try:
            await stream_gen.aclose()
        except (AttributeError, RuntimeError):
            logger.debug(
                "Agent stream generator was already closing conversation=%s",
                conversation_id,
            )
        raise
    except Exception as stream_exc:
        producer_error = True
        logger.error(
            "Agent stream response error: %r",
            stream_exc,
            exc_info=True,
        )
        if not channel.is_completed:
            try:
                await channel.publish(render_error(stream_exc))
            except Exception:
                logger.exception(
                    "Failed to publish producer error conversation=%s",
                    conversation_id,
                )
    finally:
        # _stream_agent_chunks normally owns persistence and terminal state.
        # This fallback covers failures before that generator is entered.
        if not channel.is_completed:
            if fallback_status == "failed" and not producer_error:
                logger.error(
                    "Agent stream producer exited without terminal state conversation=%s",
                    conversation_id,
                )
            try:
                run_info = host.registry.get_agent_run_info(
                    conversation_id, user_id
                )
                host.unregister(
                    conversation_id,
                    user_id,
                    status=fallback_status,
                    agent_run_info=run_info,
                )
            except Exception:
                logger.exception(
                    "Failed to unregister incomplete producer conversation=%s",
                    conversation_id,
                )
            try:
                await streaming_channel_manager.complete_channel(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    status=fallback_status,
                )
            except Exception:
                logger.exception(
                    "Failed to complete producer channel conversation=%s",
                    conversation_id,
                )
            cleanup_task = asyncio.create_task(
                cleanup_channel_later(
                    streaming_channel_manager,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    expected_channel=channel,
                )
            )
            host.cleanup_tasks.add(cleanup_task)
            cleanup_task.add_done_callback(host.cleanup_tasks.discard)
        identity = getattr(channel, "execution_identity", None)
        if isinstance(identity, RunIdentity):
            await run_blocking(
                "agentos-execution-finish", finish_execution, identity, channel.completion_status or fallback_status,
                lane="control-io", owner="runtime",
            )
        logger.info(
            "Agent stream cleanup conversation=%s status=%s active_runs=%s "
            "active_channels=%s active_producers=%s replay_bytes=%s",
            conversation_id,
            "failed" if not channel.is_completed else channel.completion_status,
            host.registry.get_active_run_count(),
            streaming_channel_manager.get_active_channel_count(),
            len(host.producer_tasks),
            streaming_channel_manager.get_retained_history_bytes(),
        )
