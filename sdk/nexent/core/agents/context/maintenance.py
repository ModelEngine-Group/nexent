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
    current: tuple[tuple[str, str], ...] = field(default=(), repr=False)


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
    manager._agent_triggered = True
    if not boundary.items:
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
    manager._agent_summary_current = boundary.current
    logger.info("event=context_run_local_summary input=%s output=%s total=%s threshold=%s target=%s persist=disabled",
                counts[0], counts[1], total, manager._compaction_trigger_threshold_tokens(),
                manager._compaction_target_tokens())
    return {"phase": "run_local", "input_tokens": counts[0], "output_tokens": counts[1],
            "total_tokens": total, "attempts": attempts, "request_id": snapshot.request_id,
            "attempt": snapshot.attempt, "target_tokens": manager._compaction_target_tokens()}


def finish_agent_context(*, manager, run_context, current_items, final_output, model, cancelled):
    """Propose a whole completed turn; Management supplies its authoritative DB boundary."""
    from nexent.core.agents.context.models import ContextItemType

    if cancelled() or not manager._agent_triggered or manager._agent_checkpoint_finished:
        return None
    manager._agent_checkpoint_finished = True
    epoch = manager._agent_epoch
    history = [item for item in run_context.items if item.type in {
        ContextItemType.HISTORY_SUMMARY, ContextItemType.CONVERSATION_TURN}]
    base = manager._agent_history
    if any(type(item.content.get("assistant_message_id")) is not int
           or item.content["assistant_message_id"] <= 0 for item in history
           if item.type == ContextItemType.CONVERSATION_TURN):
        return None
    # A failed run-local summary cannot silently discard any old history.
    if history and (base is None or any(
            (item.id, manager._fingerprint(item.content)) not in manager._agent_covered for item in history)):
        return None
    covered = set(manager._agent_summary_current) if base is not None else set()
    tail = [{"type": item.type.value, "content": item.content} for item in current_items
            if item.type not in {ContextItemType.SYSTEM, ContextItemType.HISTORY_SUMMARY,
                                 ContextItemType.CONVERSATION_TURN}
            and (item.id, manager._fingerprint(item.content)) not in covered]
    material = {"completed_turn_tail": tail, "final_output": final_output}
    if base is not None:
        material["accepted_summary"] = base.content["summary"]
    generated = manager._llm.generate_summary(json.dumps(material, ensure_ascii=False), model,
        call_type="history_summary", retry_context_error=False)
    text = generated.summary_text
    if (cancelled() or epoch != manager._agent_epoch or base is not manager._agent_history
            or not isinstance(text, str) or not text.strip()):
        return None
    checkpoint = next((item for item in history if item.type == ContextItemType.HISTORY_SUMMARY), None)
    tail_id = max((item.content.get("assistant_message_id", 0) for item in history
                   if item.type == ContextItemType.CONVERSATION_TURN), default=0)
    if checkpoint is not None:
        tail_id = max(tail_id, checkpoint.content.get("covered_through_message_id", 0))
    # Unsaved SDK history is not a Management persistence boundary.
    if history and tail_id <= 0:
        return None
    event = {"status": "accepted", "persist_status": "not_configured",
             "coverage_scope": "current_completed_turn", "summary": {"markdown": text.strip()},
             "history_tail_message_id": tail_id or None,
             "previous_summary_unit_id": checkpoint.content.get("unit_id") if checkpoint else None,
             "trigger": "completed_turn"}
    logger.info("event=context_completed_turn_checkpoint tail_items=%s", len(tail))
    return event
