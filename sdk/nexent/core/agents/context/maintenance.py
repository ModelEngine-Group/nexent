# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Core-neutral accepted-response maintenance with transactional candidates."""
import json
import logging
from dataclasses import dataclass, field


logger = logging.getLogger("agent_context.runtime")


@dataclass(frozen=True)
class AgentHistoryBoundary:
    """Selected old CM history, independent of the actual model input material."""

    epoch: str
    items: tuple[tuple[str, str], ...]
    executions: tuple[str, ...] = field(default=(), repr=False)


def complete_agent_context(*, manager, response, model, cancelled):
    """Summarize one accepted physical completion, only into a run-local view."""
    from nexent.core.model_service.contracts import AgentCompletionInput

    snapshot = getattr(response, "_agent_input", None)
    if cancelled():
        return None
    reason = None
    if not isinstance(snapshot, AgentCompletionInput):
        reason = "no_physical_input"
    else:
        boundary = snapshot.binding
        if not isinstance(boundary, AgentHistoryBoundary) or boundary.epoch != manager._agent_epoch:
            reason = "foreign_run"
        elif not boundary.items:
            reason = "no_replaceable_history"
        elif boundary.items != manager._selected_agent_history:
            reason = "history_boundary_changed"
    if reason:
        logger.info("event=context_run_local_skipped reason=%s", reason)
        return None
    key = (snapshot.request_id, snapshot.attempt)
    if key in manager._agent_completions:
        return None
    manager._agent_completions.add(key)
    usage = response.usage
    counts = (usage.input_tokens, usage.output_tokens)
    if usage.origin != "provider" or any(type(value) is not int or value < 0 for value in counts):
        logger.info("event=context_run_local_skipped reason=unknown_provider_usage")
        return None
    total = sum(counts)
    if manager.processing_mode != "adaptive_compact" or total < manager._compaction_trigger_threshold_tokens():
        return None
    output = {"role": "assistant", "content": response.content_parts, "finish_reason": response.finish_reason,
              "tool_calls": [{"id": call.provider_call_id, "type": "function", "function": {
                  "name": call.name, "arguments": call.raw_arguments}} for call in response.tool_calls]}
    if response.refusal is not None:
        output["refusal"] = response.refusal
    material = json.dumps({"input": json.loads(snapshot.semantic_json), "output": output}, ensure_ascii=False)
    generated = manager._llm.generate_summary(material, model, call_type="history_summary", retry_context_error=False)
    text = generated.summary_text
    if (cancelled() or not isinstance(text, str) or not text.strip()
            or boundary.epoch != manager._agent_epoch or boundary.items != manager._selected_agent_history):
        return None
    last_valid, attempts = text.strip(), 1
    if not manager.adopt_agent_summary(boundary, last_valid, snapshot.request_id):
        return None
    logger.info("event=context_run_local_summary input=%s output=%s total=%s threshold=%s target=%s persist=disabled",
                counts[0], counts[1], total, manager._compaction_trigger_threshold_tokens(),
                manager._compaction_target_tokens())
    return {"phase": "run_local", "input_tokens": counts[0], "output_tokens": counts[1],
            "total_tokens": total, "attempts": attempts, "request_id": snapshot.request_id,
            "attempt": snapshot.attempt, "target_tokens": manager._compaction_target_tokens()}
