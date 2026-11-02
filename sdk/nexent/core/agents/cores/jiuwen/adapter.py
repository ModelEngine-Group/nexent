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
from types import SimpleNamespace

from nexent.core.agents.context.models import ContextItem, ContextItemType
from nexent.core.agents.context.rendering import ContextItemRenderer
from nexent.core.agents.contracts.adapter import AgentCoreAdapter, UnsupportedAgentCoreConfig
from nexent.core.agents.cores.jiuwen.delegation import DelegationPolicy
from nexent.core.agents.cores.jiuwen.events import JiuwenEventAdapter
from nexent.core.agents.resources.monitoring import _wrap_tool_with_monitoring
from nexent.core.agents.resources.provider import AgentResources
from nexent.core.concurrency import ManagedTaskSpec, RunCancellationScope
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.tools.prompt_registry import PromptToolPolicySnapshot, filter_effective_prompt_tools
from nexent.core.utils.observer import ProcessType


logger = logging.getLogger(__name__)


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
        self._active_resource = ContextVar("jiuwen_resource", default=None)
        self._run_completed = False
        self.tool_configs = []
        self.visible_tool_names = set()
        self.business_tools = {}
        self.prefix_messages = []
        self._closed = False
        self._tool_executions = []
        self.text_protocol = False
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

    @classmethod
    def capabilities(cls):
        return frozenset({"tools", "mcp", "skills", "streaming", "history", "cancellation", "workers", "a2a"})

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
        if config.enable_protocol_repair_retry or config.output_protocol != "code_action":
            unsupported.append("smolagents output protocol")
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
        self.text_protocol = profile.capabilities.tools.status != "supported"
        self.tool_configs = list(config.tools)
        registry = {tool.name or tool.class_name: tool for tool in self.tool_configs}
        if len(registry) != len(self.tool_configs):
            raise ValueError("Duplicate tool names in agent configuration")
        from nexent.core.agents.cores.jiuwen.protocol import EXECUTION_TOOL, NATIVE_EXECUTION_TOOL

        reserved = {EXECUTION_TOOL, NATIVE_EXECUTION_TOOL}
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

    @contextmanager
    def _observe_tool(self, name, arguments):
        call_id = uuid.uuid4().hex
        provider_id = self.events.tool_call(name, arguments, call_id)
        token = self._active_resource.set((call_id, provider_id))
        try:
            with self.run_info.observer.tool_call_context(call_id):
                try:
                    yield
                except BaseException as error:
                    self.events.tool_result(call_id, provider_id, type(error).__name__, is_error=True)
                    raise
        finally:
            self._active_resource.reset(token)

    def _resource_result(self, result):
        active = self._active_resource.get()
        if active is not None:
            value = result.model_dump() if hasattr(result, "model_dump") else result
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    pass
            is_error = isinstance(value, dict) and (value.get("success") is False or value.get("isError") is True
                                                    or value.get("status") in ("error", "failed"))
            rendered = result if isinstance(result, str) else json.dumps(value, ensure_ascii=False, default=str)
            self.events.tool_result(*active, rendered, is_error)
        # Keep legacy side channels for artifacts and existing consumers.
        self.run_info.observer.add_message(self.run_info.agent_config.name, ProcessType.EXECUTION_LOGS, str(result))

    def prepare(self):
        from openjiuwen.core.foundation.tool import LocalFunction, ToolCard
        from openjiuwen.core.single_agent import AgentCard
        from openjiuwen.harness.factory import create_deep_agent

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
            child_invocation_factory=child_invocation_factory(info),
        )
        self.resources.core_run_info = info
        native_tools = []
        for config in self.tool_configs:
            if config.source == "mcp" or config.class_name == "ParallelExecutorTool":
                continue
            tool = _wrap_tool_with_monitoring(self.resources.create_tool(config), info.agent_config.name)
            name = config.name or tool.name
            self.business_tools[name] = tool
            if name in self.visible_tool_names:
                native_tools.append(LocalFunction(
                    ToolCard(name=name, description=config.description or tool.description,
                             input_params=_tool_schema(tool.inputs)), self._business_handler(name, tool.forward),
                ))
        for child in info.agent_config.worker_agents:
            tool = self.resources._create_subagent_definition(child, {})
            self.business_tools[tool.name] = tool
            native_tools.append(LocalFunction(
                ToolCard(name=tool.name, description=tool.description, input_params=_tool_schema(tool.inputs)),
                self._business_handler(tool.name, tool, lane="control-io"),
            ))
        for external in self.external_agents:
            from nexent.core.agents.resources.a2a import ExternalA2AAgentWrapper
            from nexent.core.agents.resources.subagents import SubAgentDefinition

            definition = SubAgentDefinition(external.invocation_name, external.description or external.name)

            def invoke_remote(task, _config=external):
                # A proxy owns a single call; parallel siblings never share client/task state.
                if self.scope.cancelled:
                    raise RunTerminated()
                remote = ExternalA2AAgentWrapper(
                    _config.to_a2a_agent_info(), stop_event=self.scope.stop_event,
                    observer=info.observer, cancellation_scope=self.scope, user_context=info.user_context,
                )
                remote.set_runtime_metadata(info.runtime_metadata)
                return remote(task=task)

            definition.forward = invoke_remote
            tool = self.resources._wrap_subagent(definition, external, agent_id=str(external.agent_id))
            self.business_tools[tool.name] = tool
            native_tools.append(LocalFunction(
                ToolCard(name=tool.name, description=tool.description, input_params=_tool_schema(tool.inputs)),
                self._business_handler(tool.name, tool.forward, lane="control-io"),
            ))
        # Reuse file/sandbox infrastructure, never construct a smolagents Agent.
        self.resources.agent = SimpleNamespace(tools=self.business_tools, python_executor=None)
        self._bind_skill_sandbox()
        self.query = self.resources._prepare_file_workspace(info.query)
        prompt = self._compile_context()
        rails = self._skill_rails()
        model = self._create_model()
        from nexent.core.agents.cores.jiuwen.context import JiuwenContextBridge

        self.context_bridge = JiuwenContextBridge(info, self.scope, self.manager, model, self.context_items)
        model.prepare_messages = self._prepare_model_messages
        model.prefix = []
        self.native_agent = create_deep_agent(
            model, card=AgentCard(id=self.owner_id, name=info.agent_config.name,
                                 description=info.agent_config.description),
            tool_owner_id=self.owner_id, system_prompt=prompt, tools=native_tools, rails=rails,
            max_iterations=info.agent_config.max_steps, workspace=info.workspace_path,
            enable_task_loop=False, enable_sys_operation=False, enable_read_image_multimodal=False,
            enable_model_anomaly_detection_rail=False, language="cn" if info.observer.lang == "zh" else "en",
            enable_tool_resilience_rail=False, enable_skill_discovery=False,
            parallel_tool_calls=False,
        )
        if any(config.class_name == "ParallelExecutorTool" and
               (config.name or "parallel_executor") in self.visible_tool_names for config in self.tool_configs):
            self._bind_parallel_tool()
        self._bind_text_executor()

    def _business_handler(self, name, forward, *, lane="model-tool-io"):
        async def execute(**arguments):
            if self.scope.cancelled:
                raise asyncio.CancelledError()
            with self._observe_tool(name, arguments):
                if inspect.iscoroutinefunction(forward):
                    result = await forward(**arguments)
                else:
                    execution = self.manager.submit(
                        lane, ManagedTaskSpec(task_name=f"jiuwen-tool-{name}", owner=__name__),
                        forward, **arguments,
                    )
                    self._tool_executions.append(execution)
                    try:
                        if lane == "control-io":
                            timeout = self.run_info.collaboration_timeout_seconds
                            if self.run_info.model_deadline is not None:
                                timeout = min(timeout, max(0.0, self.run_info.model_deadline - time.monotonic()))
                            result = await asyncio.wait_for(asyncio.wrap_future(execution.future), timeout)
                        else:
                            result = await asyncio.wrap_future(execution.future)
                    except TimeoutError:
                        if lane != "control-io":
                            raise
                        logger.warning(
                            "event=agent_collaboration_timeout agent_name=%s timeout_seconds=%.3f "
                            "phase=queue_or_execution error_type=TimeoutError",
                            name, timeout,
                        )
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

        return execute

    def _compile_context(self):
        from nexent.core.agents.orchestration.execution import _get_authorized_context_items, _get_authorized_history

        config = self.run_info.agent_config
        context = []
        for item in _get_authorized_context_items(self.run_info) or ():
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
        from nexent.core.agents.prompt.policies import business_system_instructions

        from nexent.core.agents.cores.jiuwen.protocol import NATIVE_PROTOCOL_INSTRUCTION

        shared = business_system_instructions(
            config.instructions or config.description, _get_authorized_context_items(self.run_info) or (),
            getattr(getattr(self.run_info, "observer", None), "lang", "en"),
        )
        protocol = "" if self.text_protocol else NATIVE_PROTOCOL_INSTRUCTION
        return "\n\n".join(text for text in (*shared, self.delegation.instruction, protocol) if text)

    def _create_model(self):
        from nexent.core.agents.cores.jiuwen.model import JiuwenServiceModel
        from nexent.core.model_service.registry import AuthenticationRegistry
        from nexent.core.model_service.service import ModelService
        from nexent.core.utils.token_estimation import estimate_tokens_text

        info, config = self.run_info, self.model_config
        profile = config.resolved_profile
        output_cap = profile.parameter_values.get("max_output_tokens", profile.parameter_values.get("max_tokens"))
        budget = info.context_budget_snapshot or info.agent_config.context_budget_snapshot
        if (budget is None and info.agent_config.requested_output_tokens is not None
                and info.agent_config.requested_output_tokens != output_cap):
            raise UnsupportedAgentCoreConfig(
                "Resolve the Agent output override into the outlet snapshot before running")
        if budget is not None and budget.requested_output_tokens != output_cap:
            raise UnsupportedAgentCoreConfig("Resolve the output budget into the outlet snapshot before running")
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
                info.observer.add_message(info.agent_config.name, ProcessType.TOKEN_COUNT,
                                          event.message.usage.model_dump_json())

        def validate_input(view):
            budget = getattr(info.agent_config.context_manager_config, "effective_input_limit_tokens", 0)
            if budget and estimate_tokens_text(view.model_dump_json()) > budget:
                raise UnsupportedAgentCoreConfig("Jiuwen input exceeds the resolved Nexent context budget")

        return JiuwenServiceModel(service, profile, self.scope, prefix=self.prefix_messages,
                                  run_id=self.owner_id, deadline=info.model_deadline,
                                  on_step=on_step, on_event=on_event, validate_input=validate_input,
                                  on_error=self.events.record_error, on_recovery=self.events.recovery,
                                  delegation=self.delegation)

    def _bind_text_executor(self):
        from openjiuwen.core.foundation.tool import LocalFunction, ToolCard

        from nexent.core.agents.cores.jiuwen.protocol import EXECUTION_TOOL, NATIVE_EXECUTION_TOOL
        from nexent.core.agents.sandbox.config import SandboxConfig
        from nexent.core.agents.sandbox.execution import _execute_with_tool_context, build_python_executor

        executor = self.resources.agent.python_executor
        if executor is None:
            executor = build_python_executor(self.run_info.sandbox_config or SandboxConfig(), logger,
                                             host_tools_exist=True, cancellation_scope=self.scope)
            self.resources._sandbox_executors.append(executor)
            self.resources.agent.python_executor = executor

        def execute(code):
            # The sandbox lane waits on the run loop, never on another sandbox execution.
            # Native and text calls share the exact ability, including MCP deadlines/identity.
            executor.send_tools(self.resource_bridge.bindings())
            output = _execute_with_tool_context(executor, code)
            return json.dumps({"output": str(output.output), "logs": output.logs,
                               "is_final_answer": output.is_final_answer}, ensure_ascii=False)

        name = EXECUTION_TOOL if self.text_protocol else NATIVE_EXECUTION_TOOL
        card = ToolCard(name=name, description=(
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

        directories, names, authorized_by_root = set(), set(), {}
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
        return [NexentSkillRail(sorted(directories), sorted(names), authorized_by_root=authorized_by_root)] \
            if directories and names else []

    def _bind_skill_sandbox(self):
        from nexent.core.agents.sandbox.config import SandboxLevel
        from nexent.core.agents.sandbox.execution import SandboxSkillScriptRunner, build_python_executor

        config = self.run_info.sandbox_config
        if config is None or config.level == SandboxLevel.LOCAL:
            return
        executor = build_python_executor(config, logger, host_tools_exist=True, cancellation_scope=self.scope)
        self.resources._sandbox_executors.append(executor)
        self.resources.agent.python_executor = executor
        runner = SandboxSkillScriptRunner(
            executor, timeout_seconds=int(config.timeout_seconds), workspace_path=self.run_info.workspace_path,
            network_enabled=not config.network_disabled, workspace_mapping=self.resources.workspace_mapping,
        )
        self.resources._sandbox_skill_runners.append(runner)
        for tool in self.business_tools.values():
            if getattr(tool, "name", None) == "run_skill_script":
                tool.bind_execution_backend(
                    runner, on_complete=lambda _result: self.resources._pull_file_workspace_from_sandbox())

    def _bind_parallel_tool(self):
        from openjiuwen.core.foundation.tool import LocalFunction, ToolCard

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

        card = ToolCard(name="parallel_executor", description="Execute independent authorized resources concurrently.",
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
        if self.mcp is not None and self.mcp.terminal_error is not None:
            raise self.mcp.terminal_error
        prepared = await self.context_bridge.prepare_messages(messages, tools)
        if self.mcp is not None and self.mcp.terminal_error is not None:
            raise self.mcp.terminal_error
        return prepared

    def run(self):
        try:
            answer = asyncio.run(self._run_async())
            if self.events.final_answer is None:
                self.events.last_error = self.events.error("JIUWEN_TERMINAL_MISSING")
                raise RuntimeError("Jiuwen stream ended without a terminal answer")
            self._run_completed = True
            return answer
        except asyncio.CancelledError:
            raise RunTerminated() from None

    async def _run_async(self):
        from openjiuwen.core.runner import Runner

        from nexent.core.agents.cores.jiuwen.mcp import JiuwenMCPCollection

        info = self.run_info
        current = asyncio.current_task()
        loop = asyncio.get_running_loop()
        from nexent.core.agents.cores.jiuwen.resources import JiuwenResourceBridge

        self.resource_bridge = JiuwenResourceBridge(self.native_agent, loop, self.scope, self.visible_tool_names)
        token = self.scope.register_closer(lambda: loop.call_soon_threadsafe(current.cancel))

        async def watch_stop():
            while not info.stop_event.is_set():
                await asyncio.sleep(0.05)
            current.cancel()

        watcher = asyncio.create_task(watch_stop())
        events = self.events
        try:
            mcp_tools = [tool for tool in self.tool_configs if tool.source == "mcp" and
                         (tool.name or tool.class_name) in self.visible_tool_names]
            if mcp_tools:
                self.mcp = JiuwenMCPCollection(
                    authorized_tools=mcp_tools, observe=self._observe_tool, manager=self.manager,
                    emit_result=self._resource_result,
                    user_context=info.user_context,
                    server_parameters=info.mcp_host, cancellation_scope=self.scope,
                    tool_timeout_seconds=info.mcp_tool_timeout_seconds,
                    close_timeout_seconds=info.mcp_close_timeout_seconds,
                    connect_timeout_seconds=info.mcp_request_timeout_seconds or 10.0,
                )
                collection = self.mcp.__enter__()
                for tool in collection.tools:
                    self.native_agent.ability_manager.add_ability(tool.card, tool)
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
            await asyncio.gather(watcher, return_exceptions=True)
            self.scope.unregister_closer(token)
            try:
                await Runner.release(self.session_id)
            finally:
                if self.native_agent is not None:
                    for card in self.native_agent.ability_manager.list():
                        Runner.resource_mgr.remove_tool(card.id)

    def close(self):
        if self._closed:
            return
        try:
            self._close_resources()
        except BaseException:
            self._run_completed = False
            raise
        finally:
            status = "stopped" if self.run_info.stop_event.is_set() else (
                "completed" if self._run_completed else "failed")
            self.run_info.run_result = self.events.finish(status)

    def _close_resources(self):
        if self._closed:
            return
        self._closed = True
        if self.context_bridge is not None:
            self.context_bridge.close()
        if self.native_agent is not None:
            from openjiuwen.core.runner import Runner

            for card in self.native_agent.ability_manager.list():
                if Runner.resource_mgr.get_tool(card.id) is not None:
                    Runner.resource_mgr.remove_tool(card.id)
        for execution in self._tool_executions:
            if not execution.future.done():
                self.manager.cancel(execution.execution_id, reason="Jiuwen tool cleanup",
                                    wait_timeout=self.run_info.mcp_close_timeout_seconds, mark_stuck_on_timeout=True)
        try:
            if self.mcp:
                self.mcp.close()
        finally:
            if self.resources:
                self.resources.close()
