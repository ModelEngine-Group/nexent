# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Adapt native messages to the existing ContextManager without synthetic Agent memory."""

import asyncio
import json
import logging
import time
from copy import copy
from types import SimpleNamespace

from nexent.core.agents.context import ContextItem, ContextManager, ContextManagerConfig
from nexent.core.agents.context.models import CurrentActionContextItem
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

    def __init__(self, info, scope, manager, model, items):
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
        self.context_manager = ContextManager(config, max_steps=info.agent_config.max_steps)
        self.summary_model = SummaryModel(model)
        self.context_timeout = 6 * model.profile.connection.timeout_seconds + info.mcp_close_timeout_seconds
        self.executions = []
        self.last_evidence = None
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
        self.last_evidence = context.evidence
        summary = self.context_manager.consume_history_summary_event()
        if summary:
            self.info.observer.add_message(self.info.agent_config.name, ProcessType.HISTORY_SUMMARY,
                                           json.dumps(summary, ensure_ascii=False))
        return context.messages

    async def prepare_messages(self, messages, tools):
        if self.scope.cancelled:
            raise RunTerminated()
        deadline = time.monotonic() + self.context_timeout
        if self.info.model_deadline is not None:
            deadline = min(deadline, self.info.model_deadline)
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
        for execution in self.executions:
            if not execution.future.done():
                self.manager.cancel(execution.execution_id, reason="Jiuwen context cleanup",
                    wait_timeout=self.info.mcp_close_timeout_seconds, mark_stuck_on_timeout=True)
