# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Core-neutral accepted-response maintenance with transactional candidates."""
from dataclasses import replace
import logging

logger = logging.getLogger("agent_context.runtime")


def complete_context(*, manager, baseline, model_key, input_tokens, assemble, cancelled, estimate):
    """Commit maintenance only after the caller has closed its response/tool step."""
    if cancelled():
        return None
    if not baseline.accept(input_tokens):
        return None
    try:
        before = assemble(False)
    except Exception:
        logger.warning("event=context_post_response_assembly_failed", exc_info=True)
        return None
    estimated = baseline.estimate(
        estimate(before.messages, before.tools), model_key,
    )
    threshold = manager._compaction_trigger_threshold_tokens()
    if estimated < threshold or manager.processing_mode != "adaptive_compact":
        return before.evidence
    # Bound attempts per accepted response rather than per entire Agent run.
    manager._run_compaction_attempts = 0
    config = manager.config
    old_limit, old_target = config.effective_input_limit_tokens, config.compaction_target_tokens
    old_candidate = manager._history_candidate
    old_overrides = dict(manager._representation_overrides)
    old_event = manager._pending_history_summary_event
    old_sink = config.history_summary_sink
    config.history_summary_sink = None
    correction = estimated - estimate(before.messages, before.tools)
    config.effective_input_limit_tokens = max(1, old_limit - correction)
    config.compaction_target_tokens = max(1, manager._compaction_target_tokens() - correction)
    try:
        final = assemble(True)
    except Exception:
        manager._history_candidate = old_candidate
        manager._representation_overrides = old_overrides
        manager._pending_history_summary_event = old_event
        logger.warning("event=context_post_response_maintenance_failed", exc_info=True)
        return before.evidence
    finally:
        config.effective_input_limit_tokens, config.compaction_target_tokens = old_limit, old_target
        config.history_summary_sink = old_sink
    if cancelled():
        manager._history_candidate = old_candidate
        manager._representation_overrides = old_overrides
        manager._pending_history_summary_event = old_event
        return before.evidence
    status = final.evidence.summary_persist_status
    if manager._history_candidate is not old_candidate:
        status = manager._persist_candidate(manager._history_candidate)
        if manager._pending_history_summary_event is not None:
            manager._pending_history_summary_event["persist_status"] = status
    final = replace(final, evidence=replace(final.evidence,
        maintenance_phase="post_response", usage_source=baseline.source,
        provider_input_tokens=baseline.actual_input_tokens,
        calibrated_input_estimate=baseline.estimate(estimate(final.messages, final.tools), model_key)))
    final = replace(final, evidence=replace(final.evidence,
        summary_persist_status=status,
        effective_input_limit_tokens=old_limit,
        compaction_target_tokens=old_target,
        exceeds_effective_input_limit=final.evidence.calibrated_input_estimate >= old_limit))
    logger.info("event=context_post_response_maintenance source=%s actual_input=%s estimated_before=%s "
                "estimated_after=%s trigger=%s target=%s", baseline.source,
                baseline.actual_input_tokens, estimated,
                final.evidence.calibrated_input_estimate, threshold, old_target)
    if final.evidence.final_token_estimate < before.evidence.final_token_estimate:
        baseline.invalidate()
    return final.evidence
