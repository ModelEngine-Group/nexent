# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Adapt native messages to the existing ContextManager without synthetic Agent memory."""

import asyncio
import json
import logging
import time
from copy import copy
from types import SimpleNamespace

from nexent.core.agents.context import ContextItem, ContextManager, ContextManagerConfig
from nexent.core.agents.context.maintenance import complete_agent_context as complete_context
from nexent.core.agents.context.models import CurrentActionContextItem
from nexent.core.agents.context.usage import ContextUsageBaseline
from nexent.core.agents.contracts.context import ContextItemInput
from nexent.core.agents.contracts.output import ContextCapacityObservation
from nexent.core.agents.cores.jiuwen.messages import _mapping, resource_view
from nexent.core.concurrency import ManagedTaskSpec
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.concurrency.errors import ThreadCapacityExceeded
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

    def __call__(self, messages, *, stop_sequences=None, max_tokens=None):
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
        message = self.model.service.invoke(request, profile, scope=self.model.scope, deadline=self.model.deadline)
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
        self._pending_calls = []
        self._completed_tool_ids = set()
        self._maintenance_execution = None
        self._pending_maintenance = None
        self._maintenance_deadline = None
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
        context = self.context_manager.assemble_context_items(
            model=self.summary_model, current_items=current, tools=definitions, run_context=self.run_context,
        )
        if self.scope.cancelled:
            raise RunTerminated()
        self._current_items, self._tools = current, definitions
        local_estimate = self._estimate(context.messages, definitions)
        model_key = self._model_key()
        self.usage_baseline.capture(local_estimate, model_key)
        self.summary_model.model._agent_context = self.context_manager.agent_history_boundary()
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
        self._accepted_context_response = message
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

    def completed_tool(self, name, result, local_id, *, provider_call_id=None, parent_call_id=None):
        """Nested business calls cannot close an unrelated native tool transaction."""
        if (self.scope.cancelled or local_id in self._completed_tool_ids or parent_call_id is not None
                or not isinstance(provider_call_id, str) or not provider_call_id):
            return
        matches = [call for call in self._pending_calls if call.name == name
                   and call.id == provider_call_id]
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
        response, usage = self._accepted_context_response, self._pending_usage
        def work():
            try:
                if self.scope.cancelled:
                    return
                self.usage_baseline.accept(usage)
                self.last_run_local_summary = complete_context(manager=self.context_manager, response=response,
                    model=self.summary_model, cancelled=lambda: self.scope.cancelled)
                if self.last_run_local_summary is not None:
                    self.usage_baseline.invalidate()
            finally:
                if hasattr(response, "_agent_input"):
                    response._agent_input = None
        self._maintenance_deadline = time.monotonic() + self.context_timeout
        if self.info.model_deadline is not None:
            self._maintenance_deadline = min(self._maintenance_deadline, self.info.model_deadline)
        self._pending_maintenance = work
        if not self._submit_maintenance():
            logger.warning("event=jiuwen_context_maintenance_deferred lane=model-tool-io reason=capacity")

    def _submit_maintenance(self):
        try:
            execution = self.manager.submit(
                "model-tool-io", ManagedTaskSpec(task_name="jiuwen-context-maintenance", owner=__name__,
                    run_id=self.summary_model.model.run_id, deadline_monotonic=self._maintenance_deadline),
                self._pending_maintenance,
            )
        except ThreadCapacityExceeded:
            return False
        self._pending_maintenance = None
        self._maintenance_execution = execution
        self.executions.append(self._maintenance_execution)
        return True

    async def prepare_messages(self, messages, tools):
        if self.scope.cancelled:
            raise RunTerminated()
        deadline = time.monotonic() + self.context_timeout
        if self.info.model_deadline is not None:
            deadline = min(deadline, self.info.model_deadline)
        if self._maintenance_deadline is not None:
            deadline = min(deadline, self._maintenance_deadline)
        backoff = 0.05
        while self._pending_maintenance is not None:
            if self.scope.cancelled:
                raise RunTerminated()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                from nexent.core.model_service.service import ModelServiceError

                from .errors import protocol_error

                logger.warning("event=jiuwen_context_maintenance_timeout phase=admission "
                               "timeout_seconds=%.3f error_type=ThreadCapacityExceeded", self.context_timeout)
                raise ModelServiceError(protocol_error("JIUWEN_CONTEXT_BUSY",
                    request_id=str(self.summary_model.model.run_id), lang=self.info.observer.lang))
            if not self._submit_maintenance():
                await asyncio.sleep(min(backoff, remaining))
                backoff = min(1.0, backoff * 2)
        timeout = max(0.0, deadline - time.monotonic())
        if self._maintenance_execution is not None:
            execution = self._maintenance_execution
            waiting = asyncio.wrap_future(execution.future)
            loop = asyncio.get_running_loop()
            token = self.scope.register_closer(lambda: loop.call_soon_threadsafe(waiting.cancel))
            try:
                await asyncio.wait_for(waiting, timeout)
            except (TimeoutError, asyncio.CancelledError, RunTerminated) as error:
                if isinstance(error, TimeoutError):
                    logger.warning("event=jiuwen_context_maintenance_timeout phase=queue_or_execution "
                                   "timeout_seconds=%.3f error_type=TimeoutError", timeout)
                self.scope.cancel()
                self.manager.cancel(execution.execution_id, reason="Jiuwen maintenance wait terminated", wait_timeout=0,
                                    mark_stuck_on_timeout=False)
                raise
            finally:
                self.scope.unregister_closer(token)
                self._maintenance_execution = None
                self._maintenance_deadline = None
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
        self._pending_maintenance = None
        if self._maintenance_execution is not None and not self.scope.cancelled:
            try:
                self._maintenance_execution.future.result(timeout=self.context_timeout)
            except Exception:
                logger.warning("event=jiuwen_context_maintenance_close_failed", exc_info=True)
        for execution in self.executions:
            if not execution.future.done():
                self.manager.cancel(execution.execution_id, reason="Jiuwen context cleanup",
                    wait_timeout=self.info.mcp_close_timeout_seconds, mark_stuck_on_timeout=True)

        response = getattr(self, "_accepted_context_response", None)
        if hasattr(response, "_agent_input"):
            response._agent_input = None
