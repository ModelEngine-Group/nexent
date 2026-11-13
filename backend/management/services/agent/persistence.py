# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Assistant message projection persistence, independent of the execution engine."""

from management.services.agent.stream import (
    finalize_buffered_unit_fragments as _finalize_buffered_unit_fragments,
)
from management.services.agent.stream import (
    remove_answer_only_steps,
)
from nexent.core.concurrency import ManagedTaskSpec


def canonicalize_assistant_units(units):
    """Finalize the canonical answer and shared persistence representation."""
    remove_answer_only_steps(units)
    total_bytes = _finalize_buffered_unit_fragments(units)
    answer = next(
        (unit["content"] for unit in reversed(units) if unit["type"] == "final_answer" and not unit.get("invocation_id")),
        "",
    )
    return answer, total_bytes


async def finalize_assistant_projection(
    *,
    thread_manager,
    message_id,
    conversation_id,
    terminal_status,
    buffered_units,
    buffered_search_records,
    buffered_image_urls,
    frontend_skill_files,
    buffered_automation_proposals,
    user_id,
    tenant_id,
    final_answer_content,
    run_outcome,
    persist_batch,
    mark_failed,
    logger,
    projection_run_id: str | None = None,
):
    """Apply the established batch transaction and failure fallback through injected I/O."""
    persistence_failed = False
    if message_id is not None:
        try:
            final_answer_content, persistence_bytes = canonicalize_assistant_units(buffered_units)
            logger.info(
                "Finalizing assistant persistence conversation=%s units=%s bytes=%s",
                conversation_id,
                len(buffered_units),
                persistence_bytes,
            )
            projection_options = {"projection_run_id": projection_run_id} if projection_run_id is not None else {}
            await thread_manager.run(
                "control-io",
                ManagedTaskSpec(
                    task_name="persist-assistant-run-batch",
                    owner="management.services.agent.run",
                ),
                persist_batch,
                message_id=message_id,
                conversation_id=conversation_id,
                message_content=final_answer_content,
                terminal_status=terminal_status,
                message_units=buffered_units,
                search_records=buffered_search_records,
                image_urls=buffered_image_urls,
                skill_files=frontend_skill_files,
                automation_proposals=buffered_automation_proposals,
                user_id=user_id,
                tenant_id=tenant_id,
                **projection_options,
            )
        except Exception:
            persistence_failed = True
            terminal_status = "failed"
            run_outcome.attempt_outcome = "failed"
            logger.exception(
                "Failed to persist assistant stream batch conversation=%s message=%s",
                conversation_id,
                message_id,
            )
            try:
                await thread_manager.run(
                    "control-io",
                    ManagedTaskSpec(
                        task_name="mark-assistant-message-failed",
                        owner="management.services.agent.run",
                    ),
                    mark_failed,
                    message_id,
                    "failed",
                    user_id,
                )
            except Exception:
                logger.exception(
                    "Failed to mark assistant message as failed after batch rollback"
                )

    return terminal_status, persistence_failed, final_answer_content
