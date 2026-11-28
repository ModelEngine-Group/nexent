# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Compile Nexent resources into a native Jiuwen agent and run its Runner."""

import asyncio
import inspect
import json
import logging
import time
import uuid
from contextlib import aclosing, contextmanager
from contextvars import ContextVar
from copy import deepcopy
from types import SimpleNamespace

from nexent.core.agents.context.models import ContextItem, ContextItemType
from nexent.core.agents.context.rendering import ContextItemRenderer
from nexent.core.agents.contracts.adapter import AgentCoreAdapter, UnsupportedAgentCoreConfig
from nexent.core.agents.contracts.clarification import render_question_text
from nexent.core.agents.contracts.identity import root_clarification_allowed
from nexent.core.agents.cores.jiuwen.clarification import ClarificationRequested, JiuwenClarification
from nexent.core.agents.cores.jiuwen.delegation import DelegationPolicy
from nexent.core.agents.cores.jiuwen.errors import failure_error, public_error
from nexent.core.agents.cores.jiuwen.events import JiuwenEventAdapter
from nexent.core.agents.cores.jiuwen.parallel import (
    child_parallel_mode,
    concurrent_children,
    is_parallel_child,
    is_read_only_tool,
)
from nexent.core.agents.cores.jiuwen.tool_tracing import record_tool_result, tool_execution_trace
from nexent.core.agents.resources.monitoring import _is_retriever_tool, _wrap_tool_with_monitoring
from nexent.core.agents.resources.provider import AgentResources
from nexent.core.concurrency import ManagedTaskSpec, RunCancellationScope
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.tools.prompt_registry import PromptToolPolicySnapshot, filter_effective_prompt_tools
from nexent.core.utils.observer import ProcessType
from nexent.monitor import get_monitoring_manager


logger = logging.getLogger(__name__)
_PARALLEL_PYTHON_CHILD_LIMIT = 4


def _prepend_context_messages(messages, prefix):
    """Replay authorized context without mixing dictionaries and native messages."""
    from openjiuwen.core.foundation.llm.schema.message import AssistantMessage, BaseMessage, ToolMessage, UserMessage

    def native(message):
        if not isinstance(message, dict):
            return message
        message_type = {"assistant": AssistantMessage, "tool": ToolMessage}.get(message["role"], BaseMessage)
        return message_type.model_validate(dict(message))

    current = [UserMessage(content=messages)] if isinstance(messages, str) else [native(item) for item in messages]
    # Keep the harness system prompt first, then previous turns, then this run.
    boundary = 0
    while boundary < len(current) and current[boundary].role in {"system", "developer"}:
        boundary += 1
    return [*current[:boundary], *(native(item) for item in prefix), *current[boundary:]]


def _tool_schema(inputs):
    """Convert existing tool parameter declarations into JSON Schema."""
    if isinstance(inputs, str):
        inputs = json.loads(inputs)
    inputs = inputs or {}
    if inputs.get("type") == "object" and "properties" in inputs:
        return inputs
    properties, required = {}, []
    for name, specification in inputs.items():
        value = dict(specification)
        nullable = value.pop("nullable", False)
        value.pop("description_zh", None)
        if value.get("type") == "any":
            value.pop("type")
        if value.get("type") == "array":
            value.setdefault("items", {})
        if not nullable and "default" not in value:
            required.append(name)
        properties[name] = value
    return {"type": "object", "properties": properties, "required": required}


class JiuwenAdapter(AgentCoreAdapter):
    core_name = "jiuwen"

    def __init__(self, run_info):
        super().__init__(run_info)
        self.native_agent = None
        self.resources = None
        self.mcp = None
        self.context_bridge = None
        self.owner_id = f"nexent_{uuid.uuid4().hex}"
        self.session_id = f"{self.owner_id}_session"
        self.events = JiuwenEventAdapter(
            getattr(run_info, "observer", None),
            getattr(getattr(run_info, "agent_config", None), "name", "jiuwen"), self.owner_id,
            capacity_provider=lambda: self.context_bridge.capacity_metadata() if self.context_bridge else None)
        self.artifact_output = getattr(run_info.agent_config, "response_mode", "chat") == "artifact"
        self.events.artifact_output = self.artifact_output
        self._active_resource = ContextVar("jiuwen_resource", default=None)
        self._child_context = ContextVar("jiuwen_child_context", default=(None, None))
        self._run_completed = False
        self.tool_configs = []
        self.visible_tool_names = set()
        self.business_tools = {}
        self.prefix_messages = []
        self._closed = False
        self._tool_executions = []
        self.text_protocol = False
        self._nl2agent_native = False
        self._parallel_children = {}
        self._parallel_tools = set()
        self._native_call_names = {}
        self._parallel_child_calls = {}
        self._python_child_slots = asyncio.BoundedSemaphore(_PARALLEL_PYTHON_CHILD_LIMIT)
        config = getattr(run_info, "agent_config", None)
        from nexent.core.agent_names import resolve_external_agent_configs

        reserved_names = [
            *(tool.name or tool.class_name for tool in getattr(config, "tools", ()) or ()),
            *(child.invocation_name or child.name for child in getattr(config, "worker_agents", ()) or ()),
            "nexent_execute_python", "nexent_execute_block",
        ]
        self.external_agents = resolve_external_agent_configs(
            getattr(config, "external_a2a_agents", None) or [], reserved_names,
        )
        self.delegation = DelegationPolicy(getattr(run_info, "query", ""), [
            *(getattr(config, "worker_agents", None) or []),
            *self.external_agents,
        ])
        occupied = {*reserved_names, *(child.invocation_name for child in self.external_agents)}
        self.clarification = JiuwenClarification(
            occupied, workbench=getattr(config, "origin", None) == "SYSTEM" and config.name == "workbench_main",
        ) if (
            root_clarification_allowed(run_info) and getattr(config, "response_mode", "chat") == "chat"
            and getattr(getattr(run_info, "observer", None), "enable_nl2a_wrapper", False) is not True
        ) else None

    @classmethod
    def capabilities(cls):
        return frozenset({"tools", "mcp", "skills", "streaming", "history", "cancellation", "workers", "a2a",
                          "human_interaction"})

    def validate(self):
        config = self.run_info.agent_config
        if self.delegation.pending and not self.delegation.names:
            raise UnsupportedAgentCoreConfig("Explicit delegation requires an authorized collaborator")
        unsupported = []
        if config.enable_planning:
            unsupported.append("enable_planning")
        if config.verification_config.enabled or (
            config.verification_config.guardrail_config and config.verification_config.guardrail_config.enabled
        ):
            unsupported.append("verification_config")
        if config.enable_protocol_repair_retry or (
            config.output_protocol != "code_action" and not self.artifact_output
        ):
            unsupported.append("smolagents output protocol")
        if self.artifact_output and (config.tools or config.worker_agents or self.external_agents):
            unsupported.append("artifact output cannot execute tools or collaborators")
        if config.provide_run_summary:
            unsupported.append("provide_run_summary")
        if config.model_name and any(model.cite_name == config.model_name and model.prompt_cache
                                     for model in self.run_info.model_config_list):
            unsupported.append("provider prompt_cache policy")
        if unsupported:
            raise UnsupportedAgentCoreConfig("Jiuwen does not yet support: " + ", ".join(unsupported))
        self.model_config = next(
            (model for model in self.run_info.model_config_list if model.cite_name == config.model_name), None,
        )
        if self.model_config is None:
            raise ValueError(f"Model alias not found: {config.model_name}")
        profile = self.model_config.resolved_profile
        from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile

        if not isinstance(profile, ResolvedModelProfile):
            raise UnsupportedAgentCoreConfig("Jiuwen requires a trusted resolved model outlet snapshot")
        if profile.outlet_id is None:
            raise UnsupportedAgentCoreConfig("Jiuwen requires a saved model outlet identity")
        if str(self.run_info.tenant_id or "") != profile.identity.tenant_id:
            raise UnsupportedAgentCoreConfig("Jiuwen model outlet tenant mismatch")
        if (self.model_config.model_name != profile.identity.request_model_id
                or self.model_config.url.rstrip("/") != profile.connection.base_url.rstrip("/")):
            raise UnsupportedAgentCoreConfig("Jiuwen model outlet identity mismatch")
        self.text_protocol = not self.artifact_output and profile.capabilities.tools.status != "supported"
        self.tool_configs = list(config.tools)
        if self.native_parallel:
            self.tool_configs = [
                tool for tool in self.tool_configs if tool.class_name != "ParallelExecutorTool"
            ]
        if self.run_info.parallel_child_mode == "read_only":
            if not is_parallel_child(config, self.run_info.model_config_list):
                raise UnsupportedAgentCoreConfig("Jiuwen parallel child requires a native read-only leaf")
            self.tool_configs = [tool for tool in self.tool_configs if is_read_only_tool(tool)]
        if self.run_info.parallel_child_mode == "sandbox" and child_parallel_mode(config, self.run_info) != "sandbox":
            raise UnsupportedAgentCoreConfig("Jiuwen parallel Python requires a native Docker child with a workspace")
        registry = {tool.name or tool.class_name: tool for tool in self.tool_configs}
        if len(registry) != len(self.tool_configs):
            raise ValueError("Duplicate tool names in agent configuration")
        from nexent.core.agents.cores.jiuwen.protocol import EXECUTION_TOOL, NATIVE_EXECUTION_TOOL

        reserved = {EXECUTION_TOOL, NATIVE_EXECUTION_TOOL, "read_execution_output"}
        if reserved.intersection(registry):
            raise UnsupportedAgentCoreConfig("Reserved Jiuwen execution tool name")
        self.visible_tool_names = set(registry)
        if config.prompt_tool_policy_snapshot is not None:
            policy = PromptToolPolicySnapshot.from_mapping(config.prompt_tool_policy_snapshot)
            effective = filter_effective_prompt_tools(
                registry, enabled=set(policy.enabled), allowed=set(policy.allowed),
                system_default_hidden=set(policy.system_default_hidden), policy_version=policy.policy_version,
                tool_schema_version=policy.tool_schema_version,
            )
            self.tool_configs = list(effective.execution_tools.values())
            self.visible_tool_names = set(effective.tools)
        collaborator_names = [child.invocation_name or child.name for child in config.worker_agents]
        collaborator_names.extend(child.invocation_name for child in self.external_agents)
        all_names = [*registry, *collaborator_names]
        if len(all_names) != len(set(all_names)) or reserved.intersection(collaborator_names):
            raise UnsupportedAgentCoreConfig("Duplicate or reserved collaboration tool name")
        self.visible_tool_names.update(collaborator_names)
        if any(tool.source == "mcp" for tool in self.tool_configs) and not self.run_info.mcp_host:
            raise ValueError("Authorized MCP tools require resolved MCP hosts")

    @property
    def native_parallel(self):
        return not self.text_protocol and self.run_info.agent_config.response_mode == "chat"

    @contextmanager
    def _observe_tool(self, name, arguments, *, provider_call_id=None):
        if getattr(self.run_info.observer, "boundary_reached", False) is True:
            raise asyncio.CancelledError()
        call_id = uuid.uuid4().hex
        parent = self._active_resource.get()
        provider_id = self.events.tool_call(name, arguments, call_id, parent_call_id=parent[0] if parent else None,
                                            provider_call_id=provider_call_id)
        source = self._resource_source(name)
        parent_call_id = parent[0] if parent else None
        token = self._active_resource.set((call_id, provider_id, name, source, parent_call_id))
        try:
            with self.run_info.observer.tool_call_context(call_id), tool_execution_trace(
                get_monitoring_manager, name, self.run_info.agent_config.name, {
                "nexent.runtime.turn_id": self.events.turn_id,
                "nexent.model.request_id": self.events.model_request_id,
                "nexent.runtime.step_number": self.events.step_number,
                "nexent.tool.local_call_id": call_id,
                "nexent.tool.provider_call_id": provider_id,
                "nexent.tool.parent_call_id": parent[0] if parent else None,
                "nexent.tool.source": source,
            }, tool_input=arguments, tool=self.business_tools.get(name), observer=self.run_info.observer):
                try:
                    yield
                except BaseException as error:
                    diagnostic = self._resource_failure(error, source, name)
                    self.events.tool_result(
                        call_id, provider_id,
                        (public_error(diagnostic, self.run_info.observer.lang).safe_message
                         if diagnostic else "Cancelled"),
                        is_error=diagnostic is not None, error=diagnostic, parent_call_id=parent_call_id,
                    )
                    if self.context_bridge is not None:
                        self.context_bridge.completed_tool(
                            name, "Resource failed", call_id, provider_call_id=provider_id,
                            parent_call_id=parent_call_id)
                    raise
        finally:
            self._active_resource.reset(token)

    def _resource_source(self, name):
        if any((tool.name or tool.class_name) == name and tool.source == "mcp" for tool in self.tool_configs):
            return "mcp"
        if any((child.invocation_name or child.name) == name for child in self.run_info.agent_config.worker_agents):
            return "subagent"
        if any(child.invocation_name == name for child in self.external_agents):
            return "a2a"
        if name in {"nexent_execute_python", "nexent_execute_block"}:
            return "sandbox"
        return "tool"

    def _resource_failure(self, error, source, name):
        diagnostic = failure_error(
            error, source=source, name=name,
            request_id=self.events.turn_id, lang=getattr(self.run_info.observer, "lang", "en"),
        )
        if diagnostic is not None:
            try:
                error._nexent_resource_error = diagnostic
            except (AttributeError, TypeError):
                pass
            self.events.resource_error = diagnostic
            logger.warning("event=jiuwen_resource_failed source=%s resource=%s category=%s request_id=%s",
                           source, name, diagnostic.category, diagnostic.request_id)
        return diagnostic

    def record_failure(self, error, *, phase="execution", source="agent"):
        diagnostic = failure_error(
            error, request_id=self.events.turn_id,
            lang=getattr(self.run_info.observer, "lang", "en"), source=source, phase=phase,
        )
        if diagnostic is None:
            return
        previous = self.events.last_error
        if previous is not None and phase == "cleanup":
            return
        if diagnostic.category == "JIUWEN_EXECUTION_FAILED":
            if previous is not None and previous.category not in {
                "JIUWEN_EXECUTION_FAILED", "JIUWEN_TERMINAL_MISSING",
            }:
                diagnostic = previous
            elif diagnostic.diagnostic_code is None:
                diagnostic = self.events.resource_error or previous or diagnostic
        self.events.record_error(diagnostic)
        origin = error.__traceback__
        while origin is not None and origin.tb_next is not None:
            origin = origin.tb_next
        location = None
        if origin is not None:
            frame = origin.tb_frame
            location = f"{frame.f_globals.get('__name__')}.{frame.f_code.co_name}:{origin.tb_lineno}"
        logger.error(
            "event=jiuwen_run_failed phase=%s category=%s reason=%s request_id=%s turn_id=%s "
            "step=%s exception_type=%s exception_site=%s",
            phase, diagnostic.category, diagnostic.diagnostic_code or "unclassified", diagnostic.request_id,
            self.events.turn_id, self.events.step_number, type(error).__name__, location,
        )

    def _resource_result(self, result):
        value = result.model_dump() if hasattr(result, "model_dump") else result
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        active = self._active_resource.get()
        failure_value = value
        if active is not None and active[3] == "mcp" and isinstance(value, dict) and set(value) == {"result"}:
            if isinstance(value["result"], str):
                try:
                    failure_value = json.loads(value["result"])
                except ValueError:
                    pass
        is_error = isinstance(failure_value, dict) and (
            failure_value.get("success") is False or failure_value.get("isError") is True
            or failure_value.get("status") in ("error", "failed")
        )
        if active is not None:
            rendered = result if isinstance(result, str) else json.dumps(value, ensure_ascii=False, default=str)
            record_tool_result(is_error, result, fingerprint_value=value)
            diagnostic = (
                self._resource_failure(RuntimeError("Resource returned failure"), active[3], active[2])
                if is_error else None
            )
            self.events.tool_result(*active[:2], rendered, is_error, error=diagnostic, parent_call_id=active[4])
            if self.context_bridge is not None:
                self.context_bridge.completed_tool(
                    active[2], rendered, active[0], provider_call_id=active[1], parent_call_id=active[4])
        # Keep legacy side channels for artifacts and existing consumers.
        log_text = str(result)
        if getattr(self.run_info.agent_config, "response_mode", "chat") == "python_workflow":
            if is_error:
                return
            # MCPTool.invoke wraps the compact transport text in one result
            # field. Decode that carrier, never arbitrary nested business JSON.
            if isinstance(value, dict) and set(value) == {"result"} and isinstance(value["result"], str):
                log_text = value["result"]
            elif isinstance(value, dict) and isinstance(value.get("logs"), str):
                log_text = value["logs"]
            elif isinstance(value, dict) and isinstance(value.get("content"), list):
                log_text = "\n".join(
                    part["text"] for part in value["content"]
                    if isinstance(part, dict) and isinstance(part.get("text"), str)
                )
        self.run_info.observer.add_message(self.run_info.agent_config.name, ProcessType.EXECUTION_LOGS, log_text)

    def prepare(self):
        from openjiuwen.core.foundation.tool import LocalFunction
        from openjiuwen.core.single_agent import AgentCard
        from openjiuwen.harness.factory import create_deep_agent

        from nexent.core.agents.cores.jiuwen.collaboration import CollaborationAgent, create_collaboration_host
        from nexent.core.agents.orchestration.children import child_invocation_factory
        from nexent.core.agents.orchestration.execution import _get_default_agent_thread_manager

        info = self.run_info
        self.manager = info.thread_manager or _get_default_agent_thread_manager()
        self.scope = info.cancellation_scope or RunCancellationScope(info.stop_event)
        if self.scope.cancelled:
            raise RunTerminated()
        self.resources = AgentResources(
            observer=info.observer, model_config_list=info.model_config_list, stop_event=info.stop_event,
            redis_client=info.redis_client, sandbox_config=info.sandbox_config, minio_client=info.minio_client,
            conversation_id=info.conversation_id, user_id=info.user_id, tenant_id=info.tenant_id,
            workspace_path=info.workspace_path, workspace_run_id=info.workspace_run_id, minio_files=info.minio_files,
            cancellation_scope=self.scope, user_context=info.user_context,
            child_invocation_factory=child_invocation_factory(info, parallel_mode=lambda: self._child_context.get()[1]),
            runtime_lifecycle=info.__dict__.get("_runtime_run_lifecycle"),
        )
        self.resources.core_run_info = info
        native_tools, collaborators = [], []
        for config in self.tool_configs:
            if config.source == "mcp" or config.class_name == "ParallelExecutorTool":
                continue
            # The shared execution boundary owns one span for this actual call.
            tool = self.resources.create_tool(config)
            if _is_retriever_tool(tool):
                # Retain the distinct retrieval phase, not a second TOOL span.
                tool = _wrap_tool_with_monitoring(tool, info.agent_config.name, observer=info.observer)
            name = config.name or tool.name
            self.business_tools[name] = tool
            if name in self.visible_tool_names:
                native_tools.append(LocalFunction(
                    self._tool_card(name=name, description=config.description or tool.description,
                             input_params=_tool_schema(tool.inputs), parallel_safe=is_read_only_tool(config)),
                    self._business_handler(name, tool.forward),
                ))
        for child in info.agent_config.worker_agents:
            tool = self.resources._create_subagent_definition(child, {}, scope_factory=lambda: self._child_context.get()[0])
            self.business_tools[tool.name] = tool
            mode = child_parallel_mode(child, info) if self.native_parallel else None
            if mode is not None:
                self._parallel_children[tool.name] = mode
            collaborators.append((tool, mode is not None, self._business_handler(
                tool.name, tool, lane="control-io", collaborator=True, local_child=True,
            )))
        for external in self.external_agents:
            from nexent.core.agents.resources.subagents import SubAgentDefinition

            definition = SubAgentDefinition(external.invocation_name, external.description or external.name)
            tool = self.resources._wrap_subagent(definition, external, agent_id=str(external.agent_id))
            self.business_tools[tool.name] = tool
            collaborators.append((tool, False, self._business_handler(
                tool.name, self._remote_handler(tool, external), collaborator=True,
            )))
        # Reuse file/sandbox infrastructure, never construct a smolagents Agent.
        self.resources.agent = SimpleNamespace(tools=self.business_tools, python_executor=None)
        if self.clarification is not None:
            # A configured class may expose a different runtime tool name.
            self.clarification = JiuwenClarification(
                set(self.business_tools) | self.visible_tool_names, workbench=self.clarification.workbench,
            )
        self._parallel_tools = {tool.card.name for tool in native_tools if tool.card.parallel_safe}
        self._parallel_tools.update(self._parallel_children)
        if info.parallel_child_mode != "read_only":
            self._bind_skill_sandbox()
        self.query = self.resources._prepare_file_workspace(info.query)
        prompt = self._compile_context()
        from nexent.core.agents.context.action_history import register_historical_results
        from nexent.core.agents.context.execution_history import ExecutionHistory
        from nexent.core.tools.read_execution_output_tool import ReadExecutionOutputTool
        history = getattr(info.observer, "execution_history", None)
        self.execution_history = history if isinstance(history, ExecutionHistory) else ExecutionHistory()
        self.context_items = register_historical_results(self.context_items, self.execution_history, self.owner_id)
        if self.execution_history.has_conversation_reader or any(
                item.metadata.get("execution_source_refs") for item in self.context_items):
            reader = ReadExecutionOutputTool(self.execution_history, self.owner_id, lambda: None)
            self.business_tools[reader.name] = reader
            self.visible_tool_names.add(reader.name)
            native_tools.append(LocalFunction(
                self._tool_card(name=reader.name, description=reader.description, input_params=_tool_schema(reader.inputs)),
                self._business_handler(reader.name, reader.forward),
            ))
        rails = self._skill_rails()
        model = self._create_model()
        from nexent.core.agents.cores.jiuwen.context import JiuwenContextBridge

        self.context_bridge = JiuwenContextBridge(info, self.scope, self.manager, model, self.context_items,
                                                  message_format="openai_chat_completions")
        self.context_bridge.context_manager.config.execution_history = self.execution_history
        model.prepare_messages = self._prepare_model_messages
        model.prefix = []
        create_agent = create_collaboration_host if collaborators else create_deep_agent
        self.native_agent = create_agent(
            model, card=AgentCard(id=self.owner_id, name=info.agent_config.name,
                                 description=info.agent_config.description),
            tool_owner_id=self.owner_id, system_prompt=prompt, tools=native_tools, rails=rails,
            max_iterations=info.agent_config.max_steps, workspace=info.workspace_path,
            enable_task_loop=False, enable_sys_operation=False, enable_read_image_multimodal=False,
            enable_model_anomaly_detection_rail=False, language="cn" if info.observer.lang == "zh" else "en",
            enable_tool_resilience_rail=False, enable_skill_discovery=False,
            parallel_tool_calls=self.native_parallel,
        )
        for tool, parallel_safe, handler in collaborators:
            card = AgentCard(
                id=f"{self.owner_id}_agent_{tool.name}", name=tool.name, description=tool.description,
                input_params={**_tool_schema(tool.inputs), "additionalProperties": False},
            )
            self.events.local_tool_schemas[card.name] = deepcopy(card.input_params)
            self.native_agent.ability_manager.add_collaborator(
                CollaborationAgent(card, self.session_id, handler), parallel_safe=parallel_safe,
            )
        if self.clarification is not None:
            # Publish the schema for native callers. The model boundary handles
            # terminal forms before Runner can dispatch any tool in the response.
            def terminal_only(**_arguments):
                raise RuntimeError("Clarification escaped the model boundary")

            card = self._tool_card(name=self.clarification.name,
                            description="Ask for essential missing user information and end this turn awaiting input.",
                            input_params=self.clarification.schema)
            self.native_agent.ability_manager.add_ability(card, LocalFunction(card, terminal_only))
        if not (self.native_parallel or self._nl2agent_native) and any(config.class_name == "ParallelExecutorTool" and
               (config.name or "parallel_executor") in self.visible_tool_names for config in self.tool_configs):
            self._bind_parallel_tool()
        if not (self.artifact_output or self._nl2agent_native) and info.parallel_child_mode != "read_only":
            self._bind_text_executor()

    def _remote_handler(self, tool, external):
        from nexent.core.agents.cores.jiuwen.a2a import invoke_native_a2a
        from nexent.core.agents.output.answer import normalize_public_answer

        async def invoke(task):
            info = self.run_info
            events = JiuwenEventAdapter(info.observer, external.name)
            try:
                timeout = min(external.timeout, self._collaboration_deadline() - time.monotonic())
                if timeout <= 0:
                    raise TimeoutError("Collaboration deadline exceeded")
                answer = await invoke_native_a2a(
                    external.to_a2a_agent_info(), task, scope=self.scope, runtime_metadata=info.runtime_metadata,
                    user_context=info.user_context, timeout=timeout, close_timeout=info.mcp_close_timeout_seconds,
                )
                events.final_answer = normalize_public_answer(answer)
            except asyncio.CancelledError:
                events.finish("stopped")
                raise
            except Exception as error:
                diagnostic = failure_error(
                    error, source="a2a", name=tool.name, request_id=events.turn_id, lang=info.observer.lang,
                )
                events.finish("failed", error=diagnostic)
                # Upstream framework exceptions may contain remote response bodies or credentials.
                logger.warning("event=jiuwen_a2a_failed agent_id=%s error_type=%s",
                               external.agent_id, type(error).__name__)
                if diagnostic is not None and diagnostic.category == "a2a_timeout":
                    raise TimeoutError("A2A request timed out") from None
                raise RuntimeError("A2A request failed") from None
            events.finish()
            return events.final_answer

        async def observed(task):
            return await tool.invoke_async(invoke, task=task)

        return observed

    def _collaboration_deadline(self):
        info = self.run_info
        deadline = time.monotonic() + min(info.collaboration_timeout_seconds, info.tool_call_timeout_seconds)
        return min(deadline, info.model_deadline) if info.model_deadline is not None else deadline

    def _tool_card(self, *, parallel_safe=False, **values):
        """Set the outer invocation limit for native tools."""
        from openjiuwen.core.foundation.tool import ToolCard

        card = ToolCard(parallel_safe=parallel_safe, **values)
        self._set_tool_timeout(card)
        self.events.local_tool_schemas[card.name] = deepcopy(card.input_params)
        return card

    def _set_tool_timeout(self, card):
        """Keep provider metadata while overriding Jiuwen's global 300-second fallback."""
        properties = dict(card.properties or {})
        properties["resilience"] = {
            **properties.get("resilience", {}),
            "timeout_s": self.run_info.tool_call_timeout_seconds,
        }
        card.properties = properties

    def begin_request(self):
        """Reset the existing bounded execution reader for one model invocation."""
        if getattr(self, "execution_history", None) is not None:
            self.execution_history.reset_read_budget(self.owner_id)

    @contextmanager
    def _runtime_tool_lifetime(self):
        lifecycle = self.run_info.__dict__.get("_runtime_run_lifecycle")
        holder = lifecycle.begin("callback") if lifecycle is not None else None
        try:
            yield
        finally:
            if holder is not None:
                lifecycle.finish(holder)

    def _business_handler(self, name, forward, *, lane="model-tool-io", collaborator=False, local_child=False):
        async def invoke(arguments, *, provider_call_id=None):
            if self.scope.cancelled:
                raise asyncio.CancelledError()
            parallel_mode = None
            if provider_call_id is not None:
                if self._native_call_names.get(provider_call_id) != name:
                    raise PermissionError("Jiuwen collaborator call does not match an accepted model call")
                del self._native_call_names[provider_call_id]
                if local_child:
                    parallel_mode = self._parallel_child_calls.get(provider_call_id)
            with self._observe_tool(name, arguments, provider_call_id=provider_call_id), self._runtime_tool_lifetime():
                if inspect.iscoroutinefunction(forward):
                    result = await forward(**arguments)
                else:
                    child_scope = RunCancellationScope(parent_stop_event=self.scope.stop_event) if local_child else None
                    deadline = None
                    if lane == "control-io":
                        deadline = self._collaboration_deadline()
                    sandbox_slot = parallel_mode == "sandbox"
                    if sandbox_slot:
                        loop = asyncio.get_running_loop()
                        await asyncio.wait_for(self._python_child_slots.acquire(), max(0.0, deadline - time.monotonic()))
                    close_hook = child_scope.cancel if child_scope is not None else None
                    if lane == "sandbox" and self.run_info.parallel_child_mode == "sandbox":
                        close_hook = self.scope.cancel
                    lifecycle = self.run_info.__dict__.get("_runtime_run_lifecycle")
                    worker_holder = None
                    token = self._child_context.set((child_scope, parallel_mode))
                    try:
                        if lifecycle is not None:
                            worker_holder = lifecycle.begin("callback")
                        execution = self.manager.submit(
                            lane, ManagedTaskSpec(task_name=f"jiuwen-tool-{name}", owner=__name__, close_hook=close_hook,
                                                  deadline_monotonic=deadline),
                            forward, **arguments,
                        )
                    except BaseException:
                        if sandbox_slot:
                            self._python_child_slots.release()
                        if worker_holder is not None:
                            lifecycle.finish(worker_holder)
                        raise
                    finally:
                        self._child_context.reset(token)
                    if sandbox_slot:
                        # A timed-out caller still owns its slot until the worker has released the kernel.
                        def release_slot(_):
                            if not loop.is_closed():
                                loop.call_soon_threadsafe(self._python_child_slots.release)

                        execution.future.add_done_callback(release_slot)
                    if worker_holder is not None:
                        execution.future.add_done_callback(lambda _: lifecycle.finish(worker_holder))
                    self._tool_executions.append(execution)
                    try:
                        if deadline is not None:
                            result = await asyncio.wait_for(asyncio.wrap_future(execution.future),
                                                            max(0.0, deadline - time.monotonic()))
                        else:
                            result = await asyncio.wrap_future(execution.future)
                    except TimeoutError:
                        if lane != "control-io":
                            raise
                        logger.warning(
                            "event=agent_collaboration_timeout agent_name=%s timeout_seconds=%.3f "
                            "phase=queue_or_execution error_type=TimeoutError",
                            name, self.run_info.collaboration_timeout_seconds,
                        )
                        if parallel_mode is None:
                            self.scope.cancel()
                        self.manager.cancel(execution.execution_id, reason="Collaboration deadline exceeded",
                                            wait_timeout=0, mark_stuck_on_timeout=False)
                        raise
                    except asyncio.CancelledError:
                        self.manager.cancel(execution.execution_id, reason="Jiuwen run cancelled", wait_timeout=0,
                                            mark_stuck_on_timeout=False)
                        raise
                    if inspect.isawaitable(result):
                        result = await result
                self._resource_result(result)
                self.delegation.record_dispatch(name)
                return result

        if collaborator:
            return invoke

        async def execute(**arguments):
            return await invoke(arguments)

        return execute

    def _compile_context(self):
        from nexent.core.agents.cores.nl2agent_prompt import nl2agent_protocol
        from nexent.core.agents.orchestration.execution import _get_authorized_context_items, _get_authorized_history

        config = self.run_info.agent_config
        items = _get_authorized_context_items(self.run_info) or ()
        context = []
        for item in items:
            if item.type not in {ContextItemType.SYSTEM, ContextItemType.TOOL, ContextItemType.SKILL,
                                 ContextItemType.WORKER_AGENT, ContextItemType.EXTERNAL_AGENT,
                                 ContextItemType.CURRENT_TASK}:
                context.append(ContextItem.from_input(item))
        self.context_items = context
        self.prefix_messages = ContextItemRenderer().render(context)
        self.prefix_messages.extend(
            {"role": history.role, "content": history.content}
            for history in _get_authorized_history(self.run_info) or ()
        )
        from nexent.core.agents.cores.jiuwen.protocol import NATIVE_PROTOCOL_INSTRUCTION
        from nexent.core.agents.prompt.policies import business_system_instructions

        language = getattr(self.run_info.observer, "lang", "en")
        shared = business_system_instructions(
            config.instructions or config.description, items, language,
            is_subagent=not root_clarification_allowed(self.run_info),
        )
        creator = nl2agent_protocol(items, language, "jiuwen" if self.text_protocol else "native")
        self._nl2agent_native = creator is not None and not self.text_protocol
        protocol = "" if self.text_protocol or self.artifact_output or creator is not None else NATIVE_PROTOCOL_INSTRUCTION
        if self.native_parallel:
            protocol += (
                "\nFor independent reads or delegations that can run in parallel, emit their individual native tool calls "
                "in the same response. Keep dependent operations in separate steps."
            )
        if self.run_info.parallel_child_mode == "read_only":
            protocol = "This parallel delegation is read-only. Use only the listed read tools and return your findings."
        if self.artifact_output:
            shared = [config.instructions or "", *(
                item.content.get("text", "") for item in items
                if item.type == ContextItemType.SYSTEM
            )]
        if config.response_mode == "python_workflow" and not self.text_protocol and creator is None:
            protocol += (
                "\nThe shared creation workflow describes Python action PAYLOADS. Its code tags and print examples "
                "are not the response wire format. Execute each complete action by calling nexent_execute_python "
                "with that Python as the code argument; never emit executable tags in a native response. "
                "Keep the workflow's authorization, fields, card boundaries and completion rules. "
                "Return completion summaries as ordinary text. Target Agent prompts use Core-neutral tool-use "
                "examples, without requiring Python actions or final_answer tags."
            )
        clarification = self.clarification.instructions(
            getattr(getattr(self.run_info, "observer", None), "lang", "en"), text_protocol=self.text_protocol,
        ) if self.clarification is not None else ""
        creator_text = creator.content["text"] if creator is not None else ""
        return "\n\n".join(
            text for text in (*shared, self.delegation.instruction, protocol, creator_text, clarification) if text
        )

    def _create_model(self):
        from nexent.core.agents.cores.jiuwen.model import JiuwenServiceModel
        from nexent.core.model_service.registry import AuthenticationRegistry
        from nexent.core.model_service.service import ModelService

        info, config = self.run_info, self.model_config
        profile = config.resolved_profile
        # Retired output budgets never constrain model dispatch, for any Core.
        service = info.model_service
        if service is None:
            # Capture credentials before any later configuration mutation.
            credential = config.api_key
            tenant = profile.identity.tenant_id
            reference = profile.connection.credential_ref

            def lookup(selected_tenant, selected_reference):
                if selected_tenant != tenant or selected_reference != reference:
                    raise PermissionError("Model credential scope mismatch")
                return credential

            auth = AuthenticationRegistry()
            headers = dict(config.http_headers)
            service = ModelService(lambda snapshot: auth.sender_for(snapshot, lookup, http_headers=headers))
        step = 0

        def on_step(_request):
            nonlocal step
            step += 1
            self.events.begin_step(_request)

        def on_event(event):
            self.events.model_event(event)
            if event.type == "message_completed":
                self._native_call_names = {call.provider_call_id: call.name for call in event.message.tool_calls}
                self._parallel_child_calls = concurrent_children(
                    event.message.tool_calls, self._parallel_tools, self._parallel_children,
                )
                info.observer.add_message(info.agent_config.name, ProcessType.TOKEN_COUNT,
                                          event.message.usage.model_dump_json())
                if self.context_bridge is not None:
                    self.context_bridge.accepted_response(event.message,
                        self.context_bridge.summary_model.model.last_native_message)

        return JiuwenServiceModel(service, profile, self.scope, prefix=self.prefix_messages,
                                  run_id=self.owner_id, deadline=info.model_deadline,
                                  on_step=on_step, on_event=on_event,
                                  on_error=self.events.record_error, on_recovery=self.events.recovery,
                                  delegation=self.delegation, artifact_output=self.artifact_output,
                                  clarification=self.clarification,
                                  verification_pending=getattr(info.observer, "has_pending_nl2agent_verification", None),
                                  full_generation_pending=getattr(info.observer, "pending_full_generation_action", None))

    def _bind_text_executor(self):
        from openjiuwen.core.foundation.tool import LocalFunction

        from nexent.core.agents.cores.jiuwen.protocol import EXECUTION_TOOL, NATIVE_EXECUTION_TOOL
        from nexent.core.agents.sandbox.config import SandboxConfig
        from nexent.core.agents.sandbox.execution import _execute_with_tool_context

        executor = self.resources.agent.python_executor
        if executor is None:
            executor = self._allocate_python_executor(self.run_info.sandbox_config or SandboxConfig())

        def execute(code):
            # The sandbox lane waits on the run loop, never on another sandbox execution.
            # Native and text calls share the exact ability, including MCP deadlines/identity.
            executor.send_tools(self.resource_bridge.bindings())
            output = _execute_with_tool_context(executor, code)
            return json.dumps({"output": str(output.output), "logs": output.logs,
                               "is_final_answer": output.is_final_answer}, ensure_ascii=False)

        name = EXECUTION_TOOL if self.text_protocol else NATIVE_EXECUTION_TOOL
        card = self._tool_card(name=name, description=(
            "Execute complete Python in the configured Nexent sandbox and current outputs directory. "
            "Use this to create files following an authorized Skill. Only authorized Nexent tools are bound; "
            "sandbox import, filesystem, network and shell restrictions apply. Return actual output and logs."),
                        input_params={"type": "object", "properties": {"code": {"type": "string"}},
                                      "required": ["code"], "additionalProperties": False})
        self.native_agent.ability_manager.add_ability(
            card, LocalFunction(card, self._business_handler(name, execute, lane="sandbox")),
        )

    def _skill_rails(self):
        from nexent.core.agents.cores.jiuwen.skills import NexentSkillRail

        directories, names, authorized_by_root, skill_name_to_id = set(), set(), {}, {}
        for config in self.tool_configs:
            if config.class_name not in {"ReadSkillMdTool", "RunSkillScriptTool", "ReadSkillConfigTool"}:
                continue
            parameters = config.params or {}
            authorized = parameters.get("authorized_skill_names")
            if authorized is None:
                raise UnsupportedAgentCoreConfig("Jiuwen Skills require an explicit authorized skill snapshot")
            if parameters.get("local_skills_dir"):
                directories.add(parameters["local_skills_dir"])
                names.update(authorized)
                authorized_by_root.setdefault(parameters["local_skills_dir"], set()).update(authorized)
            for name, skill_id in (parameters.get("skill_name_to_id") or {}).items():
                if name in names and skill_id is not None:
                    skill_name_to_id[name] = skill_id
        return [NexentSkillRail(sorted(directories), sorted(names), authorized_by_root=authorized_by_root,
                                skill_name_to_id=skill_name_to_id)] \
            if directories and names else []

    def _bind_skill_sandbox(self):
        from nexent.core.agents.sandbox.config import SandboxLevel
        from nexent.core.agents.sandbox.execution import SandboxSkillScriptRunner

        config = self.run_info.sandbox_config
        if config is None or config.level == SandboxLevel.LOCAL:
            return
        executor = self._allocate_python_executor(config)
        if getattr(executor, "_nexent_backend", None) == "local":
            self.resources.workspace_mapping = None
            for tool in self.business_tools.values():
                if getattr(tool, "workspace_mapping", None) is not None:
                    tool.workspace_mapping = None
            return
        runner_type = SandboxSkillScriptRunner
        runner_options = {}
        if getattr(executor, "_nexent_backend", None) == "kubernetes":
            from nexent.core.agents.sandbox_kubernetes_runner import KubernetesSkillScriptRunner

            runner_type = KubernetesSkillScriptRunner
            runner_options["workspace_access"] = config.workspace_access
        runner = runner_type(
            executor, timeout_seconds=int(config.timeout_seconds), workspace_path=self.run_info.workspace_path,
            network_enabled=not config.network_disabled, workspace_mapping=self.resources.workspace_mapping,
            **runner_options,
        )
        self.resources._sandbox_skill_runners.append(runner)
        for tool in self.business_tools.values():
            if getattr(tool, "name", None) == "run_skill_script":
                tool.bind_execution_backend(
                    runner, on_complete=lambda _result: self.resources._pull_file_workspace_from_sandbox())

    def _allocate_python_executor(self, config):
        from nexent.core.agents.sandbox.execution import build_python_executor

        executor = build_python_executor(config, logger, host_tools_exist=True, cancellation_scope=self.scope)
        self.resources._sandbox_scope = config.scope.value
        self.resources._sandbox_executors.append(executor)
        self.resources.agent.python_executor = executor
        return executor

    def _bind_parallel_tool(self):
        from openjiuwen.core.foundation.tool import LocalFunction

        from nexent.core.tools.parallel_executor import ParallelExecutorTool

        # Reuse the existing scheduler/results/timeout contract. Bridge waiters
        # use control-io; actual resource effects still use model-tool-io.
        scheduler = ParallelExecutorTool(execution_lane="control-io")

        def parallel(tasks, timeout=None, max_workers=4):
            bindings = self.resource_bridge.bindings()
            prepared = []
            for task in tasks:
                name = task["tool_name"]
                if name == "parallel_executor" or name not in bindings:
                    raise PermissionError("Parallel task references an unavailable resource")
                item = (bindings[name], task.get("arguments") or {})
                if task.get("result_key") is not None:
                    item += (task["result_key"],)
                prepared.append(item)
            return scheduler.forward(prepared, timeout=timeout, max_workers=max_workers)

        card = self._tool_card(name="parallel_executor", description="Execute independent authorized resources concurrently.",
                        input_params={"type": "object", "properties": {"tasks": {"type": "array", "maxItems": 16,
                            "items": {"type": "object", "properties": {"tool_name": {"type": "string"},
                                "arguments": {"type": "object"}, "result_key": {"type": "string"}},
                                "required": ["tool_name"], "additionalProperties": False}},
                            "timeout": {"type": "integer", "minimum": 1, "default": 120},
                            "max_workers": {"type": "integer", "minimum": 1, "maximum": 16, "default": 4}},
                            "required": ["tasks"], "additionalProperties": False})
        self.native_agent.ability_manager.add_ability(
            card, LocalFunction(
                card, self._business_handler("parallel_executor", parallel, lane="background-service")),
        )

    async def _prepare_model_messages(self, messages, tools):
        """Stop native loop retries at the model boundary after a resource failure."""
        if getattr(self.run_info.observer, "boundary_reached", False) is True:
            raise asyncio.CancelledError()
        if self.mcp is not None and self.mcp.terminal_error is not None:
            raise self.mcp.terminal_error
        prepared = await self.context_bridge.prepare_messages(messages, tools)
        if self.mcp is not None and self.mcp.terminal_error is not None:
            raise self.mcp.terminal_error
        return prepared

    def _connect_mcp(self):
        """Establish blocking session owners on the admitted Agent worker."""
        from nexent.core.agents.cores.jiuwen.mcp import JiuwenMCPCollection

        info = self.run_info
        mcp_tools = [tool for tool in self.tool_configs if tool.source == "mcp" and
                     (tool.name or tool.class_name) in self.visible_tool_names]
        if mcp_tools:
            self.mcp = JiuwenMCPCollection(
                authorized_tools=mcp_tools, observe=self._observe_tool, manager=self.manager,
                emit_result=self._resource_result, user_context=info.user_context,
                server_parameters=info.mcp_host, cancellation_scope=self.scope,
                tool_timeout_seconds=info.mcp_tool_timeout_seconds,
                close_timeout_seconds=info.mcp_close_timeout_seconds,
                connect_timeout_seconds=info.mcp_request_timeout_seconds or 10.0,
            )
            for tool in self.mcp.__enter__().tools:
                tool.card.parallel_safe = False
                self._set_tool_timeout(tool.card)
                self.native_agent.ability_manager.add_ability(tool.card, tool)

    def run(self):
        from nexent.core.agents.cores.jiuwen.execution_loop import get_execution_loop

        try:
            try:
                self._connect_mcp()
            except Exception as error:
                self.record_failure(error, source="mcp")
                raise
            answer = get_execution_loop(self.manager).run(self._run_async, cancel=self.scope.cancel)
            if getattr(self.run_info.observer, "boundary_reached", False):
                self.events.waiting_for_input = True
                self._run_completed = True
                return ""
            if self.events.final_answer is None:
                self.events.last_error = self.events.error("JIUWEN_TERMINAL_MISSING")
                raise RuntimeError("Jiuwen stream ended without a terminal answer")
            self._run_completed = True
            return answer
        except ClarificationRequested as requested:
            if getattr(self, "scope", None) is not None and self.scope.cancelled:
                raise RunTerminated() from None
            if not root_clarification_allowed(self.run_info):
                answer = render_question_text(requested.form)
                self.events.final_answer = answer
                self._run_completed = True
                return answer
            self.events.output(ProcessType.HUMAN_INTERACTION,
                               json.dumps({"schema_version": 1, **requested.form.model_dump(mode="json", exclude_none=True)},
                                          ensure_ascii=False))
            self.events.waiting_for_input = True
            self._run_completed = True
            return render_question_text(requested.form)
        except asyncio.CancelledError:
            if getattr(self.run_info.observer, "boundary_reached", False):
                self.events.waiting_for_input = True
                self._run_completed = True
                return ""
            raise RunTerminated() from None

    async def _run_async(self):
        from openjiuwen.core.runner import Runner

        from nexent.core.agents.cores.jiuwen.collaboration import remove_run_abilities
        info = self.run_info
        current = asyncio.current_task()
        loop = asyncio.get_running_loop()
        from nexent.core.agents.cores.jiuwen.resources import JiuwenResourceBridge

        self.resource_bridge = JiuwenResourceBridge(
            self.native_agent, loop, self.scope, self.visible_tool_names, self.session_id,
        )

        def cancel_run():
            if not current.done() and not current.cancelling():
                current.cancel()

        token = self.scope.register_closer(lambda: loop.call_soon_threadsafe(cancel_run))

        async def watch_stop():
            while not info.stop_event.is_set():
                await asyncio.sleep(0.05)
            self.scope.cancel()

        watcher = asyncio.create_task(watch_stop())
        events = self.events
        try:
            info.observer.add_message(info.agent_config.name, ProcessType.AGENT_NEW_RUN, self.query)
            for event in info.agent_config.pre_run_tool_events:
                info.observer.add_message(
                    info.agent_config.name, ProcessType.OTHER, json.dumps(event, ensure_ascii=False))
            async with aclosing(Runner.run_agent_streaming(
                self.native_agent, {"query": self.query, "conversation_id": self.session_id}, session=self.session_id,
            )) as stream:
                async for chunk in stream:
                    if self.scope.cancelled:
                        raise asyncio.CancelledError()
                    if self.mcp and self.mcp.terminal_error:
                        raise self.mcp.terminal_error
                    events.emit(chunk)
            if self.scope.cancelled:
                raise asyncio.CancelledError()
            return events.final_answer
        finally:
            watcher.cancel()
            try:
                await asyncio.gather(watcher, return_exceptions=True)
            finally:
                # A queued cancellation must not bypass native session cleanup.
                self.scope.unregister_closer(token)
                try:
                    await Runner.release(self.session_id)
                finally:
                    if self.native_agent is not None:
                        remove_run_abilities(self.native_agent)

    def close(self):
        if self._closed:
            return
        try:
            self._close_resources()
        except BaseException as error:
            self.record_failure(error, phase="cleanup")
            self._run_completed = False
            raise
        finally:
            if self.events.waiting_for_input:
                status = "completed"
            elif self.run_info.stop_event.is_set():
                status = "stopped"
            else:
                status = "completed" if self._run_completed else "failed"
            if (status == "completed" and not self.events.waiting_for_input and self.context_bridge is not None
                    and root_clarification_allowed(self.run_info) and self.events.final_answer is not None):
                checkpoint = self.context_bridge.finish_run(str(self.events.final_answer))
                if self.run_info.stop_event.is_set():
                    status, checkpoint = "stopped", None
                if isinstance(checkpoint, dict):
                    self.events.output(ProcessType.HISTORY_SUMMARY, json.dumps(checkpoint, ensure_ascii=False))
            self.run_info.run_result = self.events.finish(status)

    def _close_resources(self):
        if self._closed:
            return
        self._closed = True
        if self.context_bridge is not None:
            self.context_bridge.close()
        if self.native_agent is not None:
            from nexent.core.agents.cores.jiuwen.collaboration import remove_run_abilities

            remove_run_abilities(self.native_agent)
        for execution in self._tool_executions:
            if not execution.future.done():
                outcome = self.manager.cancel(execution.execution_id, reason="Jiuwen tool cleanup",
                                              wait_timeout=self.run_info.mcp_close_timeout_seconds,
                                              mark_stuck_on_timeout=True)
                if self.run_info.parallel_child_mode == "sandbox" and outcome.stuck:
                    raise RuntimeError("Child sandbox still has an active operation; retaining its owned resources")
        try:
            if self.mcp:
                self.mcp.close()
        finally:
            if self.resources:
                if self.run_info.parallel_child_mode == "sandbox":
                    completed = self._run_completed and not self.scope.cancelled
                    self.resources.close(publish_outputs=completed)
                    if completed:
                        self.run_info.published_child_files = [
                            {key: file[key] for key in ("name", "url")}
                            for file in self.resources._workspace_uploads
                            if file.get("name") and file.get("url")
                        ]
                elif self.run_info.parallel_child_mode == "read_only":
                    self.resources.close(publish_outputs=False)
                else:
                    self.resources.close()
