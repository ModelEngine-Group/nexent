# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""One explicit historical recovery transaction after a capacity rejection."""

import inspect
import logging
import time
from dataclasses import dataclass, replace

from nexent.core.concurrency.cancellation import RunTerminated

from .budget import message_role
from .models import ContextItemType
from .usage import ContextInputCapacityExceeded


logger = logging.getLogger("agent_context.runtime")
HISTORY_TYPES = {ContextItemType.HISTORY_SUMMARY, ContextItemType.CONVERSATION_TURN}


@dataclass
class ContextRecoveryBudget:
    used: bool = False
    summary_calls: int = 0
    max_summary_calls: int = 3
    deadline: float | None = None

    def check(self, cancelled):
        if cancelled():
            raise RunTerminated()
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise ContextInputCapacityExceeded("Context capacity recovery deadline exceeded")


class RecoverySummaryModel:
    allow_summary_input_truncation = False

    def __init__(self, model, budget, cancelled):
        object.__setattr__(self, "_model", model)
        object.__setattr__(self, "_budget", budget)
        object.__setattr__(self, "_cancelled", cancelled)

    def __getattr__(self, name):
        return getattr(self._model, name)

    def __setattr__(self, name, value):
        setattr(self._model, name, value)

    @property
    def context_call_parameters(self):
        return getattr(self._model, "context_call_parameters", inspect.signature(self._model.__call__).parameters)

    def __call__(self, messages, **kwargs):
        self._budget.check(self._cancelled)
        if self._budget.summary_calls >= self._budget.max_summary_calls:
            raise ContextInputCapacityExceeded("Context capacity recovery summary budget exhausted")
        self._budget.summary_calls += 1
        recover_call = getattr(self._model, "capacity_recovery_call", None)
        result = (
            recover_call(messages, deadline=self._budget.deadline, **kwargs)
            if callable(recover_call)
            else self._model(messages, **kwargs)
        )
        self._budget.check(self._cancelled)
        return result


class RecoveryDeadlineService:
    """Request-local forwarding preserves transport retries under one deadline."""

    def __init__(self, service, deadline):
        self._service = service
        self._deadline = deadline

    def __getattr__(self, name):
        method = getattr(self._service, name)
        if name not in {"invoke", "ainvoke", "stream", "astream"}:
            return method

        def bounded(*args, **kwargs):
            existing = kwargs.get("deadline")
            if self._deadline is not None:
                kwargs["deadline"] = min(existing, self._deadline) if existing is not None else self._deadline
            return method(*args, **kwargs)

        return bounded


def recover_history(
    *, manager, run_context, assemble, model, budget, cancelled, revision, limit, error, origin, finalize=None
):
    """Stage history only, validate the full native frame, then commit old facts."""
    budget.check(cancelled)
    if not limit or budget.used or manager.processing_mode != "adaptive_compact":
        raise error
    if not any(item.type in HISTORY_TYPES for item in run_context.items) and manager._history_candidate is None:
        raise error
    old_candidate = manager._history_candidate
    old_event = manager._pending_history_summary_event
    old_overrides = dict(manager._representation_overrides)
    old_staged = manager._pending_capacity_candidate
    old_attempts = manager._run_compaction_attempts
    source_revision = revision()
    committed = False
    try:
        # The protected frame includes everything except committed historical items.
        manager._history_candidate = None
        protected = assemble(
            replace(run_context, items=tuple(item for item in run_context.items if item.type not in HISTORY_TYPES)),
            False,
            model,
        )
        manager._history_candidate = old_candidate
        if manager.estimate_request_tokens(protected.messages, protected.tools) >= limit:
            raise error
        budget.check(cancelled)
        budget.used = True
        manager._pending_capacity_candidate = None
        manager._run_compaction_attempts = 0
        before = assemble(run_context, False, model)
        before_tokens = manager.estimate_request_tokens(before.messages, before.tools)
        bounded_model = RecoverySummaryModel(model, budget, cancelled)
        final = assemble(run_context, True, bounded_model)
        candidate = manager._pending_capacity_candidate
        budget.check(cancelled)
        if revision() != source_revision or candidate is None:
            raise error
        final_tokens = manager.estimate_request_tokens(final.messages, final.tools)
        if final_tokens >= limit or final_tokens >= before_tokens:
            raise error
        if candidate.covered_through_message_id <= 0:
            raise error
        if finalize is not None:
            final = finalize(final)
            final_tokens = manager.estimate_request_tokens(final.messages, final.tools)
            if final_tokens >= limit:
                raise error
        budget.check(cancelled)
        if revision() != source_revision:
            raise error
        status = manager._persist_candidate(candidate)
        if status == "failed":
            raise error
        manager._history_candidate = candidate
        manager._pending_history_summary_event = {
            **candidate.as_item().content,
            "persist_status": status,
            "status": "accepted",
        }
        manager._pending_capacity_candidate = None
        committed = True
        manager._last_compressed_token_count = final_tokens
        system_messages = [m for m in final.messages if message_role(m) in {"system", "developer"}]
        dynamic_messages = [m for m in final.messages if message_role(m) not in {"system", "developer"}]
        logger.info(
            "event=context_capacity_recovery origin=%s before=%s after=%s limit=%s summary_calls=%s",
            origin,
            before_tokens,
            final_tokens,
            limit,
            budget.summary_calls,
        )
        return replace(
            final,
            evidence=replace(
                final.evidence,
                maintenance_phase=origin,
                usage_source="estimated_after_capacity_recovery",
                provider_input_tokens=None,
                calibrated_input_estimate=final_tokens,
                final_token_estimate=final_tokens,
                stable_message_count=len(system_messages),
                dynamic_message_count=len(dynamic_messages),
                messages_fingerprint=manager._fingerprint(final.messages),
                system_messages_fingerprint=manager._fingerprint(system_messages),
                history_messages_fingerprint=manager._fingerprint(dynamic_messages),
                message_roles=tuple(message_role(m) for m in final.messages),
                history_message_roles=tuple(message_role(m) for m in dynamic_messages),
                summary_persist_status=status,
                history_compression_triggered=True,
                new_summary_coverage=candidate.covered_through_message_id,
                exceeds_effective_input_limit=False,
            ),
        )
    finally:
        if not committed:
            manager._history_candidate = old_candidate
            manager._pending_history_summary_event = old_event
            manager._representation_overrides = old_overrides
            manager._pending_capacity_candidate = old_staged
            manager._run_compaction_attempts = old_attempts
