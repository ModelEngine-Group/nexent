"""Compile Nexent resources into a native Jiuwen agent and run its Runner."""

import asyncio
import inspect
import json
import logging
import uuid
from contextlib import aclosing
from types import SimpleNamespace

from ...concurrency import ManagedTaskSpec, RunCancellationScope
from ...concurrency.cancellation import RunTerminated
from ...tools.prompt_registry import PromptToolPolicySnapshot, filter_effective_prompt_tools
from ...utils.observer import ProcessType
from ..context.models import ContextItem, ContextItemType
from ..context.rendering import ContextItemRenderer
from ..nexent_agent import NexentAgent, _wrap_tool_with_monitoring
from .base import AgentCoreAdapter, UnsupportedAgentCoreConfig
from .events import JiuwenEventAdapter


logger = logging.getLogger(__name__)


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
        self.owner_id = f"nexent_{uuid.uuid4().hex}"
        self.session_id = f"{self.owner_id}_session"
        self.tool_configs = []
        self.visible_tool_names = set()
        self.business_tools = {}
        self.prefix_messages = []
        self._closed = False
        self._tool_executions = []

    @classmethod
    def capabilities(cls):
        return frozenset({"tools", "mcp", "skills", "streaming", "history", "cancellation"})

    def validate(self):
        config = self.run_info.agent_config
        unsupported = []
        if config.worker_agents:
            unsupported.append("worker_agents")
        if config.external_a2a_agents:
            unsupported.append("external_a2a_agents")
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
        if config.context_manager_config is not None:
            from ..context.policy import resolve_policy

            policy = resolve_policy(config.context_manager_config.policy_layers)
            if policy.processing_mode.value != "passthrough":
                unsupported.append("adaptive context compaction (disable enable_context_manager for Jiuwen)")
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
        self.tool_configs = list(config.tools)
        registry = {tool.name or tool.class_name: tool for tool in self.tool_configs}
        if len(registry) != len(self.tool_configs):
            raise ValueError("Duplicate tool names in agent configuration")
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
        if any(tool.source == "mcp" for tool in self.tool_configs) and not self.run_info.mcp_host:
            raise ValueError("Authorized MCP tools require resolved MCP hosts")

    def _observe_tool(self, name, arguments):
        call_id = uuid.uuid4().hex
        self.run_info.observer.add_message(
            self.run_info.agent_config.name, ProcessType.TOOL, "",
            tool_name=name, tool_arguments=arguments, tool_call_id=call_id,
        )
        return self.run_info.observer.tool_call_context(call_id)

    def prepare(self):
        from openjiuwen.core.foundation.tool import LocalFunction, ToolCard
        from openjiuwen.core.single_agent import AgentCard
        from openjiuwen.harness.factory import create_deep_agent

        from ..run_agent import _get_default_agent_thread_manager

        info = self.run_info
        self.manager = info.thread_manager or _get_default_agent_thread_manager()
        self.scope = info.cancellation_scope or RunCancellationScope(info.stop_event)
        if self.scope.cancelled:
            raise RunTerminated()
        self.resources = NexentAgent(
            observer=info.observer, model_config_list=info.model_config_list, stop_event=info.stop_event,
            redis_client=info.redis_client, sandbox_config=info.sandbox_config, minio_client=info.minio_client,
            conversation_id=info.conversation_id, user_id=info.user_id, tenant_id=info.tenant_id,
            workspace_path=info.workspace_path, workspace_run_id=info.workspace_run_id, minio_files=info.minio_files,
            cancellation_scope=self.scope, user_context=info.user_context,
        )
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
        # Reuse file/sandbox infrastructure, never construct a smolagents Agent.
        self.resources.agent = SimpleNamespace(tools=self.business_tools, python_executor=None)
        self._bind_skill_sandbox()
        self.query = self.resources._prepare_file_workspace(info.query)
        prompt = self._compile_context()
        rails = self._skill_rails()
        model = self._create_model()
        self.native_agent = create_deep_agent(
            model, card=AgentCard(id=self.owner_id, name=info.agent_config.name,
                                 description=info.agent_config.description),
            tool_owner_id=self.owner_id, system_prompt=prompt, tools=native_tools, rails=rails,
            max_iterations=info.agent_config.max_steps, workspace=info.workspace_path,
            enable_task_loop=False, enable_sys_operation=False, enable_read_image_multimodal=False,
            enable_model_anomaly_detection_rail=False, language="cn" if info.observer.lang == "zh" else "en",
            parallel_tool_calls=True,
        )
        if any(config.class_name == "ParallelExecutorTool" and
               (config.name or "parallel_executor") in self.visible_tool_names for config in self.tool_configs):
            self._bind_parallel_tool()

    def _business_handler(self, name, forward):
        async def execute(**arguments):
            if self.scope.cancelled:
                raise asyncio.CancelledError()
            with self._observe_tool(name, arguments):
                if inspect.iscoroutinefunction(forward):
                    result = await forward(**arguments)
                else:
                    execution = self.manager.submit(
                        "model-tool-io", ManagedTaskSpec(task_name=f"jiuwen-tool-{name}", owner=__name__),
                        forward, **arguments,
                    )
                    self._tool_executions.append(execution)
                    try:
                        result = await asyncio.wrap_future(execution.future)
                    except asyncio.CancelledError:
                        self.manager.cancel(execution.execution_id, reason="Jiuwen run cancelled", wait_timeout=0,
                                            mark_stuck_on_timeout=False)
                        raise
                self.run_info.observer.add_message(self.run_info.agent_config.name, ProcessType.EXECUTION_LOGS,
                                                   str(result))
                return result

        return execute

    def _compile_context(self):
        from ..run_agent import _get_authorized_context_items, _get_authorized_history

        config = self.run_info.agent_config
        instructions = [config.instructions or ""]
        context = []
        for item in _get_authorized_context_items(self.run_info) or ():
            if item.type == ContextItemType.SYSTEM:
                # Platform code-action instructions cannot be reused by a native tool-calling core.
                if item.id in {"system:duty", "system:constraint", "system:few_shots",
                               "system:knowledge_scope_policy", "system:memory_tool_policy",
                               "system:automation_tool_policy", "system:sandbox_workspace_guidance"} or (
                    not item.id.startswith("system:") and item.metadata.get("authority", "agent") == "agent"
                ):
                    instructions.append(item.content.get("text", ""))
            elif item.type not in {ContextItemType.TOOL, ContextItemType.SKILL,
                                    ContextItemType.WORKER_AGENT, ContextItemType.EXTERNAL_AGENT,
                                    ContextItemType.CURRENT_TASK}:
                context.append(ContextItem.from_input(item))
        self.prefix_messages = ContextItemRenderer().render(context)
        self.prefix_messages.extend(
            {"role": history.role, "content": history.content}
            for history in _get_authorized_history(self.run_info) or ()
        )
        return "\n\n".join(text for text in instructions if text) or config.description

    def _create_model(self):
        from openjiuwen.core.foundation.llm import Model
        from openjiuwen.core.foundation.llm.schema.config import ModelClientConfig, ModelRequestConfig

        from ...models.model_concurrency import model_concurrency_limiter
        from ...utils.token_estimation import estimate_tokens_text

        config = self.model_config
        prefix = self.prefix_messages
        info = self.run_info
        budget = getattr(info.agent_config.context_manager_config, "effective_input_limit_tokens", 0)
        model_step = 0

        def start_model_call():
            nonlocal model_step
            model_step += 1
            info.observer.add_message(info.agent_config.name, ProcessType.STEP_COUNT, str(model_step))

        def acquire(messages, tools):
            if budget:
                rendered = json.dumps([message.model_dump() if hasattr(message, "model_dump") else message
                                       for message in messages], ensure_ascii=False, default=str)
                schemas = json.dumps(tools or [], ensure_ascii=False, default=str)
                if estimate_tokens_text(rendered + schemas) > budget:
                    raise UnsupportedAgentCoreConfig("Jiuwen input exceeds the resolved Nexent context budget")
            if config.concurrency_limit is not None:
                return model_concurrency_limiter.acquire(
                    (str(info.tenant_id or "default"), str(config.model_factory or "unknown"), config.model_name),
                    config.concurrency_limit, config.timeout_seconds or 300, info.stop_event,
                )
            return None

        class RunModel(Model):
            async def invoke(model_self, messages, **kwargs):
                start_model_call()
                messages = [*prefix, *messages]
                permit = acquire(messages, kwargs.get("tools"))
                try:
                    return await super().invoke(messages, **kwargs)
                finally:
                    if permit:
                        permit.release()

            async def stream(model_self, messages, **kwargs):
                start_model_call()
                messages = [*prefix, *messages]
                permit = acquire(messages, kwargs.get("tools"))
                try:
                    async for chunk in super().stream(messages, **kwargs):
                        yield chunk
                finally:
                    if permit:
                        permit.release()

        timeout = config.timeout_seconds or 300.0
        return RunModel(
            ModelClientConfig(
                client_provider="OpenAI", api_key=config.api_key, api_base=config.url,
                auth_mode="api_key" if config.api_key else "none",
                timeout=timeout, stream_first_chunk_timeout=timeout, stream_idle_timeout=min(timeout, 60),
                max_retries=0, use_shared_llm_http_client=False, verify_ssl=config.ssl_verify is not False,
                extensions={"request_extra_body": config.extra_body or {}},
            ),
            ModelRequestConfig(
                model=config.model_name, temperature=config.temperature, top_p=config.top_p,
                max_tokens=self.run_info.agent_config.requested_output_tokens or config.max_output_tokens,
                context_window=config.context_window_tokens,
                reasoning={"mode": "enabled" if config.enable_thinking else "disabled",
                           "effort": config.reasoning_effort, "budget_tokens": config.reasoning_budget_tokens},
            ),
        )

    def _skill_rails(self):
        from .skills import NexentSkillRail

        directories, names = set(), set()
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
        return [NexentSkillRail(sorted(directories), sorted(names))] if directories and names else []

    def _bind_skill_sandbox(self):
        from ..sandbox import SandboxLevel, SandboxSkillScriptRunner, build_python_executor

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
                tool.bind_execution_backend(runner, on_complete=lambda _result: self.resources._pull_file_workspace_from_sandbox())

    def _bind_parallel_tool(self):
        from openjiuwen.core.foundation.tool import LocalFunction, ToolCard
        from openjiuwen.core.runner import Runner

        async def parallel(tasks):
            async def invoke(task):
                name = task["tool_name"]
                if name == "parallel_executor":
                    raise ValueError("Recursive parallel executor is not allowed")
                card = self.native_agent.ability_manager.get(name)
                if card is None:
                    raise PermissionError("Parallel task references an unavailable tool")
                tool = Runner.resource_mgr.get_tool(card.id)
                return await tool.invoke(task.get("arguments", {}))

            with self._observe_tool("parallel_executor", {"tasks": tasks}):
                return await asyncio.gather(*(invoke(task) for task in tasks))

        card = ToolCard(name="parallel_executor", description="Execute independent authorized native tools concurrently.",
                        input_params={"type": "object", "properties": {"tasks": {"type": "array", "maxItems": 16,
                            "items": {"type": "object", "properties": {"tool_name": {"type": "string"},
                                "arguments": {"type": "object"}}, "required": ["tool_name"]}}}, "required": ["tasks"]})
        self.native_agent.ability_manager.add_ability(card, LocalFunction(card, parallel))

    def run(self):
        try:
            asyncio.run(self._run_async())
        except asyncio.CancelledError:
            raise RunTerminated() from None

    async def _run_async(self):
        from openjiuwen.core.runner import Runner

        from .mcp import JiuwenMCPCollection

        info = self.run_info
        current = asyncio.current_task()
        loop = asyncio.get_running_loop()
        token = self.scope.register_closer(lambda: loop.call_soon_threadsafe(current.cancel))

        async def watch_stop():
            while not info.stop_event.is_set():
                await asyncio.sleep(0.05)
            current.cancel()

        watcher = asyncio.create_task(watch_stop())
        events = JiuwenEventAdapter(info.observer, info.agent_config.name)
        try:
            mcp_tools = [tool for tool in self.tool_configs if tool.source == "mcp" and
                         (tool.name or tool.class_name) in self.visible_tool_names]
            if mcp_tools:
                self.mcp = JiuwenMCPCollection(
                    authorized_tools=mcp_tools, observe=self._observe_tool, manager=self.manager,
                    emit_result=lambda result: info.observer.add_message(
                        info.agent_config.name, ProcessType.EXECUTION_LOGS, str(result)),
                    user_context=info.user_context,
                    server_parameters=info.mcp_host, cancellation_scope=self.scope,
                    tool_timeout_seconds=info.mcp_tool_timeout_seconds, close_timeout_seconds=info.mcp_close_timeout_seconds,
                    connect_timeout_seconds=info.mcp_request_timeout_seconds or 10.0,
                )
                collection = self.mcp.__enter__()
                for tool in collection.tools:
                    self.native_agent.ability_manager.add_ability(tool.card, tool)
            info.observer.add_message(info.agent_config.name, ProcessType.AGENT_NEW_RUN, self.query)
            for event in info.agent_config.pre_run_tool_events:
                info.observer.add_message(info.agent_config.name, ProcessType.OTHER, json.dumps(event, ensure_ascii=False))
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
            events.finish()
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
        self._closed = True
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
                try:
                    self.resources._finalize_file_workspace()
                finally:
                    self.resources._cleanup_file_workspace()
                    self.resources._cleanup_sandbox()
