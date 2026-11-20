# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Adapt native messages to the existing ContextManager without synthetic Agent memory."""

import asyncio
import json
import logging
import time
from copy import copy
from types import SimpleNamespace

from nexent.core.agents.context import ContextItem, ContextManager, ContextManagerConfig
from nexent.core.agents.context.maintenance import complete_context
from nexent.core.agents.context.models import CurrentActionContextItem
from nexent.core.agents.context.recovery import ContextRecoveryBudget, recover_history
from nexent.core.agents.context.usage import (
    ContextInputCapacityExceeded,
    ContextUsageBaseline,
    record_capacity_rejection,
)
from nexent.core.agents.contracts.context import ContextItemInput
from nexent.core.agents.contracts.output import ContextCapacityObservation
from nexent.core.agents.cores.jiuwen.messages import _mapping, resource_view
from nexent.core.concurrency import ManagedTaskSpec
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.model_service.compatibility.invocation_options import LegacyInvocationOptions
from nexent.core.utils.observer import ProcessType


logger = logging.getLogger(__name__)


class NativeActionItem(CurrentActionContextItem):
    """Keep live native call/result pairs intact while completed DB turns compact."""

    SUPPORTS_COMPACT = False


class SummaryModel:
    """Synchronous CM model seam using the same saved outlet and ModelService."""

    def __init__(self, model):
        self.model = model
        self.model_id = model.profile.identity.request_model_id

    def capacity_recovery_call(self, messages, *, deadline, **kwargs):
        return self(messages, _recovery_deadline=deadline, **kwargs)

    def __call__(self, messages, *, stop_sequences=None, max_tokens=None, _recovery_deadline=None):
        if self.model.scope.cancelled:
            raise RunTerminated()
        if stop_sequences:
            raise ValueError("Summary stop overrides are not supported")
        parameters = {"max_tokens": max_tokens} if max_tokens is not None else {}
        if any(rule["key"] == "enable_thinking" for rule in self.model.profile.parameter_rules):
            parameters["enable_thinking"] = False
        profile = LegacyInvocationOptions(parameters=parameters).resolve(self.model.profile)
        normalized = [message if isinstance(message, dict) else {
            "role": getattr(message.role, "value", message.role), "content": message.content,
        } for message in messages]
        view = resource_view(normalized, [])
        request = self.model.converter.convert(view, profile, stream=False, run_id=self.model.run_id).request
        deadline = self.model.deadline
        if _recovery_deadline is not None:
            deadline = min(deadline, _recovery_deadline) if deadline is not None else _recovery_deadline
        message = self.model.service.invoke(request, profile, scope=self.model.scope, deadline=deadline)
        if self.model.scope.cancelled:
            raise RunTerminated()
        if message.finish_reason != "stop" or message.tool_calls or message.refusal is not None:
            raise ValueError("Invalid context summary completion")
        if any(part.get("type") != "text" for part in message.content_parts):
            raise ValueError("Non-text context summary")
        return SimpleNamespace(
            content="".join(part["text"] for part in message.content_parts),
            token_usage=message.usage,
        )


class JiuwenContextBridge:
    """Own one run-local CM; persisted facts and checkpoints remain application-owned."""

    def __init__(self, info, scope, manager, model, items, *, message_format="openai_chat_completions"):
        self.info, self.scope, self.manager = info, scope, manager
        config = copy(info.agent_config.context_manager_config or ContextManagerConfig())
        sink = config.history_summary_sink
        if sink is not None:
            def guarded_sink(candidate):
                if scope.cancelled:
                    raise RunTerminated()
                return sink(candidate)
            config.history_summary_sink = guarded_sink
        status_sink = config.history_summary_status_sink

        def emit_status(payload):
            if status_sink is not None:
                status_sink(payload)
            info.observer.add_message(info.agent_config.name, ProcessType.HISTORY_SUMMARY,
                                      json.dumps(payload, ensure_ascii=False))

        config.history_summary_status_sink = emit_status
        self.context_manager = ContextManager(config, max_steps=info.agent_config.max_steps,
                                              message_format=message_format,
                                              request_token_estimator=self._estimate_wire)
        self.summary_model = SummaryModel(model)
        self.context_timeout = 6 * model.profile.connection.timeout_seconds + info.mcp_close_timeout_seconds
        self.executions = []
        self.last_evidence = None
        self.usage_baseline = ContextUsageBaseline()
        self._capacity_budget = None
        self._pending_calls = []
        self._completed_tool_ids = set()
        self._maintenance_execution = None
        self._current_items = []
        self._tools = []
        base = list(items)
        # Direct SDK callers have no database snapshot; preserve their completed turns.
        if info.context_input is None:
            pending = None
            for index, entry in enumerate(info.history or ()):
                if entry.role == "user":
                    pending = (index, entry.content)
                elif entry.role == "assistant" and pending is not None:
                    base.append(ContextItem.from_input(ContextItemInput(
                        id=f"sdk-history:{index}", type="conversation_turn", content={
                            "user_message": pending[1], "assistant_final_answer": entry.content,
                            "user_message_id": -(pending[0] + 1), "assistant_message_id": -(index + 1),
                        }, metadata={"layout_order": index},
                    )))
                    pending = None
        self.run_context = self.context_manager.prepare_items_context("", items=base)

    def capacity_metadata(self):
        """Use the same CM fields exposed by Nexent's ManagedContextRuntime, even in passthrough mode."""
        manager = self.context_manager
        return ContextCapacityObservation(
            context_window_tokens=manager.config.context_window_tokens or None,
            token_threshold=manager.config.token_threshold or None,
            effective_input_limit_tokens=manager.effective_input_limit_tokens or None,
            context_processing_mode=manager.processing_mode,
        )

    def begin_request(self):
        """One recovery allowance across corrections of one native main request."""
        deadline = time.monotonic() + min(self.context_timeout, 3 * self.summary_model.model.profile.connection.timeout_seconds)
        if self.info.model_deadline is not None:
            deadline = min(deadline, self.info.model_deadline)
        self._capacity_budget = ContextRecoveryBudget(deadline=deadline)

    def _assemble(self, messages, tools):
        if self.scope.cancelled:
            raise RunTerminated()
        values = [{"role": "user", "content": messages}] if isinstance(messages, str) else [
            _mapping(message) for message in messages
        ]
        current, task_seen = [], False
        for index, value in enumerate(values):
            if value["role"] in {"system", "developer"}:
                content = value.get("content") or ""
                if isinstance(content, list):
                    content = "\n".join(part if isinstance(part, str) else part.get("text", "") for part in content)
                if content:
                    current.append(ContextItem.from_input(ContextItemInput(
                        id=f"jiuwen-system:{index}", type="system",
                        content={"text": content, "role": value["role"]},
                        source=("jiuwen_native_instruction",), metadata={"layout_order": index},
                    )))
            elif value["role"] == "user" and not task_seen:
                task_seen = True
                current.append(ContextItem.from_input(ContextItemInput(
                    id="jiuwen-current-task", type="current_task", content={"text": self.info.query},
                    source=("current_user_request",),
                )))
            else:
                payload = {key: value[key] for key in ("role", "content", "tool_calls", "tool_call_id")
                           if key in value}
                current.append(NativeActionItem(id=f"jiuwen-action:{index}", type="current_action",
                    content={"messages": [payload]}, metadata={"layout_order": index}))
        if not task_seen:
            raise ValueError("Jiuwen current task is missing")
        definitions = [tool.model_dump() for tool in resource_view(messages, tools).tool_definitions]
        def assemble(run_context, recovering, selected_model):
            return self.context_manager.assemble_context_items(
                model=selected_model, current_items=current, tools=definitions, run_context=run_context,
                **({"force_compaction": True, "history_only_recovery": True} if recovering else {}))
        context = assemble(self.run_context, False, self.summary_model)
        if self.scope.cancelled:
            raise RunTerminated()
        self._current_items, self._tools = current, definitions
        local_estimate = self._estimate(context.messages, definitions)
        model_key = self._model_key()
        estimated = self.usage_baseline.estimate(local_estimate, model_key)
        limit = self.context_manager.effective_input_limit_tokens or self.context_manager.config.context_window_tokens
        if limit and estimated >= limit:
            record_capacity_rejection(local_tokens=local_estimate, estimated_tokens=estimated, limit=limit,
                                      baseline=self.usage_baseline, model_key=model_key)
            if self._capacity_budget is None:
                self.begin_request()
            def revision():
                return self.context_manager._fingerprint({
                    "model": self._model_key(), "query": self.info.query,
                    "native_messages": messages,
                    "current": [(item.id, item.content) for item in current],
                    "history": [(item.id, item.content, item.metadata) for item in self.run_context.items],
                    "capacity": self.context_manager.effective_input_limit_tokens,
                    "tools": definitions,
                })
            context = recover_history(
                manager=self.context_manager, run_context=self.run_context, assemble=assemble,
                model=self.summary_model, budget=self._capacity_budget, cancelled=lambda: self.scope.cancelled,
                revision=revision, limit=limit,
                error=ContextInputCapacityExceeded("Jiuwen input exceeds the combined context window"),
                origin="local_capacity_recovery")
            self.usage_baseline.invalidate()
            self.usage_baseline.source = "estimated_after_capacity_recovery"
        self.usage_baseline.capture(self._estimate(context.messages, definitions), self._model_key())
        self.last_evidence = context.evidence
        summary = self.context_manager.consume_history_summary_event()
        if summary:
            self.info.observer.add_message(self.info.agent_config.name, ProcessType.HISTORY_SUMMARY,
                                           json.dumps(summary, ensure_ascii=False))
        return context.messages

    def _model_key(self):
        profile = self.summary_model.model.profile
        return (profile.identity.tenant_id, profile.outlet_id, profile.config_revision,
                profile.identity.request_model_id)

    def _estimate(self, messages, tools):
        return self.context_manager.estimate_request_tokens(messages, tools)

    def _estimate_wire(self, messages, tools):
        from nexent.core.model_service.adapters.openai_chat import OpenAIChatAdapter

        model = self.summary_model.model
        definitions = [{"type": "function", "function": {
            "name": tool["name"], "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {})}} for tool in tools or []]
        request = model.preview_request(messages, definitions)
        body = OpenAIChatAdapter().prepare_http_request(request, model.profile).json_body
        return self.context_manager._message_tokens(body["messages"]) + self.context_manager._tools_tokens(body.get("tools"))

    def accepted_response(self, message, native_message):
        """Remember accepted usage; wait for every matching native tool result."""
        if self.scope.cancelled:
            return
        self._pending_usage = message.usage.input_tokens if message.usage.origin == "provider" else None
        self._pending_calls = list(native_message.tool_calls or ())
        self._completed_tool_ids.clear()
        content = "".join(part.get("text", "") for part in message.content_parts)
        payload = {"role": "assistant", "content": content}
        if self._pending_calls:
            payload["tool_calls"] = [{"id": call.id, "type": "function", "function": {
                "name": call.name, "arguments": call.arguments}} for call in self._pending_calls]
        self._current_items.append(NativeActionItem(id="jiuwen-accepted-response", type="current_action",
            content={"messages": [payload]}, metadata={"layout_order": 1000000}))
        if not self._pending_calls:
            self._schedule_maintenance()

    def completed_tool(self, name, result, local_id, *, provider_call_id=None):
        """Nested business calls cannot close an unrelated native tool transaction."""
        if self.scope.cancelled or local_id in self._completed_tool_ids:
            return
        matches = [call for call in self._pending_calls if call.name == name
                   and (provider_call_id is None or call.id == provider_call_id)]
        if len(matches) != 1:
            return
        call = matches[0]
        self._completed_tool_ids.add(local_id)
        self._pending_calls.remove(call)
        self._current_items.append(NativeActionItem(id="jiuwen-accepted-tool:" + local_id,
            type="current_action", content={"messages": [{"role": "tool", "tool_call_id": call.id,
                "content": str(result)}]}, metadata={"layout_order": 1000001 + len(self._completed_tool_ids)}))
        if not self._pending_calls:
            self._schedule_maintenance()

    def _schedule_maintenance(self):
        """Start maintenance at the completed response/tool boundary, never in prepare."""
        if self.scope.cancelled:
            return
        current, tools = list(self._current_items), list(self._tools)
        def work():
            def assemble(maintenance):
                return self.context_manager.assemble_context_items(
                    model=self.summary_model, current_items=current, tools=tools, run_context=self.run_context,
                    maintenance=maintenance, force_compaction=maintenance)
            evidence = complete_context(manager=self.context_manager, baseline=self.usage_baseline,
                model_key=self._model_key(), input_tokens=self._pending_usage, assemble=assemble,
                cancelled=lambda: self.scope.cancelled, estimate=self._estimate)
            if evidence is not None:
                self.last_evidence = evidence
        self._maintenance_execution = self.manager.submit(
            "model-tool-io", ManagedTaskSpec(task_name="jiuwen-context-maintenance", owner=__name__,
                run_id=self.summary_model.model.run_id,
                deadline_monotonic=time.monotonic() + self.context_timeout), work)
        self.executions.append(self._maintenance_execution)

    async def prepare_messages(self, messages, tools):
        if self.scope.cancelled:
            raise RunTerminated()
        deadline = time.monotonic() + self.context_timeout
        if self.info.model_deadline is not None:
            deadline = min(deadline, self.info.model_deadline)
        timeout = max(0.0, deadline - time.monotonic())
        if self._maintenance_execution is not None:
            try:
                await asyncio.wait_for(asyncio.wrap_future(self._maintenance_execution.future), timeout)
            finally:
                self._maintenance_execution = None
            timeout = max(0.0, deadline - time.monotonic())
        execution = self.manager.submit(
            "model-tool-io", ManagedTaskSpec(task_name="jiuwen-context", owner=__name__,
                run_id=self.summary_model.model.run_id, deadline_monotonic=deadline),
            self._assemble, messages, tools,
        )
        self.executions.append(execution)
        try:
            return await asyncio.wait_for(asyncio.wrap_future(execution.future), timeout)
        except TimeoutError:
            logger.warning("event=jiuwen_context_timeout timeout_seconds=%.3f phase=queue_or_execution "
                           "error_type=TimeoutError", timeout)
            self.scope.cancel()
            self.manager.cancel(execution.execution_id, reason="Jiuwen context deadline exceeded", wait_timeout=0,
                                mark_stuck_on_timeout=False)
            raise
        except asyncio.CancelledError:
            self.manager.cancel(execution.execution_id, reason="Jiuwen context cancelled", wait_timeout=0,
                                mark_stuck_on_timeout=False)
            raise

    def close(self):
        if self._maintenance_execution is not None and not self.scope.cancelled:
            try:
                self._maintenance_execution.future.result(timeout=self.context_timeout)
            except Exception:
                logger.warning("event=jiuwen_context_maintenance_close_failed", exc_info=True)
        for execution in self.executions:
            if not execution.future.done():
                self.manager.cancel(execution.execution_id, reason="Jiuwen context cleanup",
                    wait_timeout=self.info.mcp_close_timeout_seconds, mark_stuck_on_timeout=True)
