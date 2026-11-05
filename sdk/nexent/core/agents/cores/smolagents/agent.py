# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import CancelledError
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from threading import RLock
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from smolagents import ActionStep, AgentText, TaskStep, Timing
from smolagents.tools import Tool

from nexent.consts.mcp_errors import (
    classify_mcp_failure, find_mcp_server_url, is_mcp_timeout_error, mcp_failure_message,
)
from nexent.core.agents.contracts.clarification import choose_clarification_tool_name
from nexent.core.agents.contracts.config import AgentConfig
from nexent.core.agents.contracts.run import AgentHistory
from nexent.core.agents.cores.smolagents.core_agent import CoreAgent, convert_code_format
from nexent.core.agents.cores.smolagents.output_protocol import ModelOutputProtocolExhaustedError
from nexent.core.agents.prompt.clarification import clarification_policy
from nexent.core.agents.resources.monitoring import (
    _build_tool_input,
    _is_retriever_tool,
    _tool_name,
    _wrap_tool_with_monitoring,
)
from nexent.core.agents.resources.provider import AgentResources
from nexent.core.agents.resources.tool_user_context import (
    apply_model_visible_tool_schemas_to_context_items,
)
from nexent.core.agents.resources.workspace import cleanup_run_workspace
from nexent.core.model_errors import ModelInvocationTerminalError
from nexent.core.models.openai_llm import OpenAIModel
from nexent.core.tools import *
from nexent.core.utils.constants import THINK_PREFIX_PATTERN, THINK_TAG_PATTERN
from nexent.core.utils.observer import ProcessType
from nexent.monitor import AgentRunMetadata, get_agent_monitoring_context, get_monitoring_manager


if TYPE_CHECKING:
    from nexent.core.agents.context import ContextItemInput
    from nexent.core.agents.resources.subagents import SubAgentToolWrapper as SubAgentToolWrapper


# Safe base imports for Python interpreter - excludes file modification and system access modules
SAFE_PYTHON_INTERPRETER_IMPORTS = [
    "math", "cmath", "statistics", "decimal", "fractions", "random",
    "collections", "itertools", "functools", "heapq", "bisect", "array", "copy",
    "re", "string", "textwrap", "unicodedata",
    "datetime", "time", "calendar",
    "base64", "hashlib", "hmac",
    "json", "csv",
    "uuid", "pprint", "operator", "typing",
]


def get_local_python_authorized_imports() -> List[str]:
    """Return the imports permitted by Nexent's default local code executor."""
    from smolagents.local_python_executor import BASE_BUILTIN_MODULES

    return sorted(set(BASE_BUILTIN_MODULES) | set(SAFE_PYTHON_INTERPRETER_IMPORTS))


logger = logging.getLogger(__name__)


def _ensure_non_empty_final_answer(answer: str, lang: str) -> str:
    """Return a user-visible fallback when final-answer cleanup removes all content."""
    if answer.strip():
        return answer
    logger.warning("Final answer was empty after removing reasoning content")
    if lang == "zh":
        return "智能体未能生成有效的最终回复，请重试或换一种方式描述需求。"
    return "The agent could not generate a valid final response. Please try again or rephrase your request."


def _has_host_tools(tools: List[Any]) -> bool:
    """Return whether the agent has tools marked for host-process execution."""
    return any(getattr(tool, "_nexent_execute_on_host", False) for tool in tools)


class NexentAgent(AgentResources):
    """smolagents execution assembled from shared authorized resources."""

    def create_model(self, model_cite_name: str):
        """create a model instance"""
        # Filter out None values and find matching model config
        model_config = next(
            (model_config for model_config in self.model_config_list
             if model_config is not None and model_config.cite_name == model_cite_name),
            None
        )
        if model_config is None:
            raise ValueError(f"Model {model_cite_name} not found")
        if model_config.resolved_profile is not None:
            return self._create_resolved_model(model_config)
        model_kwargs = dict(
            observer=self.observer,
            model_id=model_config.model_name,
            api_key=model_config.api_key,
            api_base=model_config.url,
            temperature=model_config.temperature,
            top_p=model_config.top_p,
            ssl_verify=model_config.ssl_verify if model_config.ssl_verify is not None else True,
            model_factory=model_config.model_factory,
            display_name=model_config.cite_name,
            extra_body=model_config.extra_body,
            max_output_tokens=model_config.max_output_tokens,
            timeout_seconds=model_config.timeout_seconds,
            prompt_cache=model_config.prompt_cache,
            reasoning_capability=model_config.reasoning_capability,
            diagnostic_chunks_enabled=model_config.diagnostic_chunks_enabled,
        )
        if model_config.explicit_sampling:
            model_kwargs["explicit_sampling"] = model_config.explicit_sampling
        if model_config.reasoning_budget_tokens is not None:
            model_kwargs["reasoning_budget_tokens"] = model_config.reasoning_budget_tokens
        if (
            model_config.enable_thinking
            and model_config.reasoning_effort is not None
            and model_config.reasoning_effort != "auto"
        ):
            model_kwargs["reasoning_effort"] = model_config.reasoning_effort
        if self.cancellation_scope is not None:
            model_kwargs["cancellation_scope"] = self.cancellation_scope
        if model_config.concurrency_limit is not None:
            model_kwargs["concurrency_limit"] = model_config.concurrency_limit
            model_kwargs["concurrency_key"] = (
                str(self.tenant_id or "default"),
                str(model_config.model_factory or "unknown"),
                str(model_config.model_name),
            )
        model = OpenAIModel(**model_kwargs)
        model.stop_event = self.stop_event
        return model


    def _create_resolved_model(self, model_config):
        """Use the supplied outlet snapshot and the run's existing cancellation owner."""
        from nexent.core.concurrency.cancellation import RunCancellationScope
        from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel

        profile = model_config.resolved_profile
        if (
            profile.identity.tenant_id != self.tenant_id
            or profile.identity.request_model_id != model_config.model_name
            or profile.connection.base_url != model_config.url
        ):
            raise ValueError("Model configuration does not match its outlet snapshot")
        scope = self.cancellation_scope if self.cancellation_scope is not None else RunCancellationScope(self.stop_event)
        return LegacyChatModel.from_profile(
            profile, model_config.api_key, http_headers=model_config.http_headers,
            observer=self.observer, cancellation_scope=scope,
        )


    def create_single_agent(
        self,
        agent_config: AgentConfig,
        _managed_context: bool = False,
        *,
        context_items_override: Sequence["ContextItemInput"] | None = None,
        _sandbox_tree_context: Optional[Dict[str, Any]] = None,
    ) -> CoreAgent:
        """
        Build a CoreAgent from ``agent_config``.

        Args:
            agent_config: AgentConfig describing this agent.
            _managed_context: Internal compatibility flag for managed agents.
            _sandbox_tree_context: Internal construction context used to share
                one session Docker container across the agent tree while each
                agent retains an isolated kernel.
        """
        if not isinstance(agent_config, AgentConfig):
            raise TypeError("agent_config must be a AgentConfig object")
        if _sandbox_tree_context is None:
            _sandbox_tree_context = {}
        _sandbox_tree_context.setdefault("initialization_lock", RLock())

        try:
            self._check_sandbox_cancelled()
            model = self.create_model(agent_config.model_name)
            model.context_budget_snapshot = getattr(
                agent_config,
                "context_budget_snapshot",
                None,
            )
            model.capacity_snapshot = getattr(
                agent_config,
                "capacity_snapshot",
                None,
            )
            prompt_templates = agent_config.prompt_templates

            prompt_tool_policy = getattr(agent_config, "prompt_tool_policy_snapshot", None)
            effective_prompt_tools = None
            tool_configs = agent_config.tools
            if prompt_tool_policy is not None:
                from nexent.core.tools.prompt_registry import PromptToolPolicySnapshot, filter_effective_prompt_tools

                snapshot = PromptToolPolicySnapshot.from_mapping(prompt_tool_policy)
                registry = {config.name: config for config in agent_config.tools if config.name}
                if len(registry) != len(agent_config.tools):
                    raise ValueError("Agent prompt tool registry has duplicate or unnamed entries")
                effective_prompt_tools = filter_effective_prompt_tools(
                    registry, enabled=set(snapshot.enabled), allowed=set(snapshot.allowed),
                    system_default_hidden=set(snapshot.system_default_hidden),
                    policy_version=snapshot.policy_version,
                    tool_schema_version=snapshot.tool_schema_version,
                )
                tool_configs = list(effective_prompt_tools.execution_tools.values())

            try:
                tool_list = [
                    _wrap_tool_with_monitoring(
                        self.create_tool(tool_config),
                        agent_config.name,
                    )
                    for tool_config in tool_configs
                ]
            except Exception as e:
                raise ValueError(f"Error in creating tool: {e}")

            try:
                # Definitions are lazy; each invocation owns its runtime and kernel.
                worker_agents_list = [
                    self._create_subagent_definition(sub_agent_config, _sandbox_tree_context)
                    for sub_agent_config in agent_config.worker_agents
                ]
            except Exception as e:
                raise ValueError(f"Error in creating worker agent: {e}")

            # Create wrapper agents for external A2A agents in the worker-agent call set.
            # so model can call them like: external_agent_name(task="...")
            from nexent.core.agent_names import resolve_external_agent_configs, validate_callable_names

            validate_callable_names(
                ["final_answer"] + [tool.name for tool in tool_list] + [agent.name for agent in worker_agents_list]
            )
            external_a2a_agents = resolve_external_agent_configs(
                agent_config.external_a2a_agents,
                [tool.name for tool in tool_list] + [agent.name for agent in worker_agents_list],
            )
            if agent_config.external_a2a_agents:
                try:
                    from nexent.core.agents.resources.a2a import ExternalA2AAgentWrapper
                    for ext_agent_config in external_a2a_agents:
                        a2a_agent_info = ext_agent_config.to_a2a_agent_info()
                        wrapper = ExternalA2AAgentWrapper(
                            agent_info=a2a_agent_info,
                            stop_event=self.stop_event,
                            observer=self.observer,
                            cancellation_scope=self.cancellation_scope,
                            user_context=self.user_context,
                        )
                        worker_agents_list.append(
                            self._wrap_subagent(
                                wrapper,
                                ext_agent_config,
                                agent_id=str(ext_agent_config.agent_id),
                            )
                        )
                except Exception as e:
                    raise ValueError(f"Error in creating external A2A agent wrapper: {e}")

            # ContextManager is the only production context assembly path.
            # ContextPolicy controls whether adaptive compaction is active.
            from nexent.core.agents.context import ContextManager, ContextManagerConfig
            from nexent.core.agents.cores.smolagents.context import ManagedContextRuntime

            ctx_config = (
                getattr(agent_config, "context_manager_config", None)
                or ContextManagerConfig()
            )
            context_manager = ContextManager(
                config=ctx_config,
                max_steps=agent_config.max_steps,
            )
            from nexent.core.agents.prompt.policies import with_common_behavior

            context_items = apply_model_visible_tool_schemas_to_context_items(
                list(context_items_override)
                if context_items_override is not None
                else list(getattr(agent_config, "context_items", None) or []),
                tool_list,
            )
            resolved_external = {agent.agent_id: agent for agent in external_a2a_agents}
            for index, item in enumerate(context_items):
                item_type = getattr(item, "type", None)
                if getattr(item_type, "value", item_type) != "external_agent":
                    continue
                config = resolved_external.get(str(item.content.get("agent_id", "")))
                if config is not None:
                    context_items[index] = item.model_copy(update={"content": {
                        **item.content,
                        "name": config.invocation_name,
                        "invocation_name": config.invocation_name,
                        "display_name": config.name,
                    }})
            from nexent.core.agents.context import ContextItemInput, ContextItemType

            enable_clarification = (
                not _managed_context
                and getattr(self.observer, "enable_nl2a_wrapper", False) is not True
                and getattr(agent_config, "output_protocol", "code_action") == "code_action"
            )
            if enable_clarification and any(item.type == ContextItemType.SYSTEM for item in context_items):
                tool_name = choose_clarification_tool_name({tool.name for tool in [*tool_list, *worker_agents_list]})
                context_items.append(ContextItemInput(
                    id="system:clarification_protocol",
                    type=ContextItemType.SYSTEM,
                    content={
                        "text": clarification_policy(
                            tool_name,
                            language=getattr(self.observer, "lang", "en"),
                        )
                    },
                    source=("runtime:clarification_protocol",),
                    priority=100,
                    metadata={"authority": "platform", "layout_order": 23},
                ))
            if effective_prompt_tools is not None:
                visible_names = set(effective_prompt_tools.tools)
                context_items = [
                    item for item in context_items
                    if getattr(getattr(item, "type", None), "value", getattr(item, "type", None)) != "tool"
                    or item.id.removeprefix("tool:") in visible_names
                ]
                self.observer.add_message(
                    agent_config.name,
                    ProcessType.OTHER,
                    json.dumps({"event": "prompt_tool_registry", **dict(effective_prompt_tools.audit)}),
                )
            context_runtime = ManagedContextRuntime(
                context_manager,
                items=(with_common_behavior(context_items, self.observer.lang)
                       if any(item.type == ContextItemType.SYSTEM for item in context_items) else context_items),
            )

            # Build one code executor for this agent. Worker-agent orchestration
            # is a host-marked tool, so every agent needs its own kernel to avoid
            # nested execution deadlocks; session containers can still be shared.
            python_executor = None
            if self.sandbox_config is not None:
                from nexent.core.agents.sandbox.config import SandboxLevel

                deferred = self.tool_fastpath_enabled and self.sandbox_config.level == SandboxLevel.DOCKER
                self._sandbox_scope = self.sandbox_config.scope.value

                def release_executor(executor):
                    with _sandbox_tree_context["initialization_lock"]:
                        self._release_deferred_executor(executor)
                        group = _sandbox_tree_context.get("session_container_group")
                        if group is not None and getattr(group, "_closed", False):
                            _sandbox_tree_context.pop("session_container_group", None)

                def create_executor():
                    python_executor = None
                    script_runner = None
                    with _sandbox_tree_context["initialization_lock"]:
                        try:
                            from nexent.core.agents.context.execution_history import ExecutionHistory
                            from nexent.core.agents.sandbox.execution import build_python_executor
                            self._check_sandbox_cancelled()
                            if deferred and self.workspace_path:
                                self._pull_file_workspace_from_sandbox()
                            has_worker = bool(
                                agent_config.worker_agents
                                or getattr(agent_config, "external_a2a_agents", [])
                            )
                            python_executor = build_python_executor(
                                config=self.sandbox_config,
                                logger_=logger,
                                worker_agents_exist=has_worker,
                                host_tools_exist=_has_host_tools([
                                    *tool_list,
                                    *worker_agents_list,
                                ]) or isinstance(getattr(self.observer, "execution_history", None), ExecutionHistory),
                                session_container_group=_sandbox_tree_context.get(
                                    "session_container_group"
                                ),
                                cancellation_scope=self.cancellation_scope,
                            )
                            self._sandbox_executors.append(python_executor)
                            self._check_sandbox_cancelled()
                            session_container_group = None
                            if (
                                self.sandbox_config.level == SandboxLevel.DOCKER
                                and self.sandbox_config.scope.value == "session"
                            ):
                                session_container_group = getattr(
                                    python_executor,
                                    "_nexent_session_container_group",
                                    None,
                                )
                            if session_container_group is not None:
                                existing_group = _sandbox_tree_context.setdefault(
                                    "session_container_group",
                                    session_container_group,
                                )
                                if existing_group is not session_container_group:
                                    raise RuntimeError(
                                        "Agent tree received multiple session sandbox containers"
                                    )
                            if self.sandbox_config.level != SandboxLevel.LOCAL:
                                from nexent.core.agents.sandbox.execution import SandboxSkillScriptRunner

                                configured_timeout = getattr(self.sandbox_config, "timeout_seconds", None)
                                skill_timeout = (
                                    max(1, int(configured_timeout))
                                    if isinstance(configured_timeout, (int, float))
                                    and not isinstance(configured_timeout, bool)
                                    else 300
                                )
                                script_runner = SandboxSkillScriptRunner(
                                    python_executor,
                                    timeout_seconds=skill_timeout,
                                    workspace_path=self.workspace_path,
                                    network_enabled=not self.sandbox_config.network_disabled,
                                    workspace_mapping=getattr(self, "workspace_mapping", None),
                                )
                                for tool in tool_list:
                                    bind_backend = getattr(tool, "bind_execution_backend", None)
                                    if callable(bind_backend) and _tool_name(tool) == "run_skill_script":
                                        bind_backend(
                                            script_runner,
                                            on_complete=lambda _result: self._pull_file_workspace_from_sandbox(),
                                        )
                                self._sandbox_skill_runners.append(script_runner)
                            self._check_sandbox_cancelled()
                            # Warm up remote executors when they are acquired.
                            if self.sandbox_config.level != SandboxLevel.LOCAL:
                                try:
                                    warm_start = time.time()
                                    current_metadata = get_agent_monitoring_context() or AgentRunMetadata()
                                    warmup_metadata = replace(
                                        current_metadata,
                                        agent_id=(
                                            getattr(agent_config, "_sub_agent_id", None)
                                            if _managed_context else current_metadata.agent_id
                                        ),
                                        agent_name=agent_config.name,
                                        agent_display_name=agent_config.display_name,
                                        model_name=agent_config.model_name,
                                    )
                                    with get_monitoring_manager().trace_agent_step(
                                        "agent.sandbox.warmup",
                                        warmup_metadata,
                                        step_type="sandbox_warmup",
                                        **{
                                            "sandbox.level": self.sandbox_config.level.value,
                                            "sandbox.scope": self.sandbox_config.scope.value,
                                            "sandbox.backend": getattr(python_executor, "_nexent_backend", "unknown"),
                                        },
                                    ):
                                        self._check_sandbox_cancelled()
                                        python_executor("[0, None]")
                                        self._check_sandbox_cancelled()
                                    warm_dur = time.time() - warm_start
                                    backend = getattr(python_executor, "_nexent_backend", "unknown")
                                    if backend == "local":
                                        if self.sandbox_config.failure_policy == "error":
                                            raise RuntimeError("Docker was requested but the executor is local")
                                        self.workspace_mapping = None
                                        for tool in tool_list:
                                            if getattr(tool, "workspace_mapping", None) is not None:
                                                tool.workspace_mapping = None
                                        self.observer.add_message(
                                            "", ProcessType.WARNING,
                                            "Docker sandbox unavailable; execution has fallen back to LocalPythonExecutor.",
                                        )
                                        logger.warning(
                                            "Sandbox level '%s' unavailable; using LocalPythonExecutor instead "
                                            "(scope=%s, warm-up %.2fs)",
                                            self.sandbox_config.level.value,
                                            self.sandbox_config.scope.value,
                                            warm_dur,
                                        )
                                    else:
                                        logger.info(
                                            "Sandbox warmed up in %.2fs (backend=%s, level=%s, scope=%s)",
                                            warm_dur,
                                            backend,
                                            self.sandbox_config.level.value,
                                            self.sandbox_config.scope.value,
                                        )
                                except CancelledError:
                                    raise
                                except Exception as warm_err:
                                    self._check_sandbox_cancelled()
                                    if self.sandbox_config.failure_policy == "error":
                                        raise RuntimeError("Sandbox FAILED phase=warmup") from warm_err
                                    logger.warning(
                                        "Sandbox warm-up failed (%s): %s",
                                        self.sandbox_config.level.value,
                                        warm_err,
                                    )
                            # Store scope on NexentAgent so _cleanup_sandbox() can read it.
                            self._sandbox_scope = self.sandbox_config.scope.value

                            if deferred:
                                self._check_sandbox_cancelled()
                                container = getattr(python_executor, "container", None)
                                if container is not None:
                                    self._push_file_workspace_to_sandbox(containers=[container])
                                self._initialize_sandbox_workspaces(executors=[python_executor])
                            return python_executor
                        except BaseException:
                            if deferred and python_executor is not None:
                                try:
                                    if script_runner is not None:
                                        skill_owner = self._sandbox_skill_cleanup_owner
                                        if skill_owner is self:
                                            script_runner.cleanup()
                                        else:
                                            # A failed child must not remove skills used by sibling invocations.
                                            with skill_owner._subagent_invocations_lock:
                                                skill_owner._sandbox_skill_runners.append(script_runner)
                                        self._sandbox_skill_runners[:] = [
                                            runner for runner in self._sandbox_skill_runners
                                            if runner is not script_runner
                                        ]
                                finally:
                                    release_executor(python_executor)
                            raise

                if deferred:
                    from nexent.core.agents.cores.smolagents.tool_fastpath import (
                        OFFICIAL_FASTPATH_TOOL_CLASSES,
                        DeferredToolExecutor,
                        official_fastpath_tools,
                    )

                    allowed_classes = (
                        OFFICIAL_FASTPATH_TOOL_CLASSES
                        if self.tool_fastpath_allowed_tools is None
                        else self.tool_fastpath_allowed_tools
                    )
                    python_executor = DeferredToolExecutor(
                        create_executor=create_executor,
                        release_executor=release_executor,
                        allowed_tools=official_fastpath_tools(tool_configs, tool_list, allowed_classes),
                        stop_event=self.stop_event,
                    )
                    self._tool_fastpath_executors.append(python_executor)
                else:
                    python_executor = create_executor()

            # Create the agent
            self._check_sandbox_cancelled()
            agent = CoreAgent(
                observer=self.observer,
                tools=tool_list,
                model=model,
                name=agent_config.invocation_name or agent_config.name,
                display_name=agent_config.display_name,
                description=agent_config.description,
                max_steps=agent_config.max_steps,
                prompt_templates=prompt_templates,
                provide_run_summary=agent_config.provide_run_summary,
                managed_agents=worker_agents_list,
                additional_authorized_imports=SAFE_PYTHON_INTERPRETER_IMPORTS,
                instructions=agent_config.instructions,
                context_runtime=context_runtime,
                enable_planning=agent_config.enable_planning,
                redis_client=self.redis_client,
                conversation_id=self.conversation_id,
                user_id=self.user_id,
                executor=python_executor,
                verification_config=getattr(agent_config, "verification_config", None),
                output_protocol=getattr(agent_config, "output_protocol", "code_action"),
                enable_protocol_repair_retry=agent_config.enable_protocol_repair_retry,
                enable_clarification=enable_clarification,
                workspace_path=self.workspace_path,
            )
            agent.stop_event = self.stop_event
            agent._delegation_collaborators = [
                *agent_config.worker_agents, *external_a2a_agents,
            ]

            # Wire plan tool deps if the plan tools are present in agent_config.tools.
            # CoreAgent already knows enable_planning (set above); use that to gate wiring.
            if agent.enable_planning:
                if (create_plan := agent.tools.get("create_plan")) is not None:
                    create_plan.observer = agent.observer
                    create_plan.plan_repo = agent.plan_repo
                    create_plan._on_plan_created = agent._on_plan_created
                    create_plan._get_conversation_id = agent._get_conversation_id
                    create_plan._get_user_id = agent._get_user_id
                if (update_step := agent.tools.get("update_plan_step")) is not None:
                    update_step.observer = agent.observer
                    update_step.plan_repo = agent.plan_repo
                    update_step._on_step_updated = agent._on_step_updated
                    update_step._get_conversation_id = agent._get_conversation_id
                    update_step._get_user_id = agent._get_user_id

            return agent
        except CancelledError:
            self._cleanup_sandbox()
            raise
        except Exception as e:
            if getattr(self.sandbox_config, "failure_policy", None) == "error":
                try:
                    self._cleanup_sandbox()
                except Exception:
                    logger.exception("Failed to release sandbox resources after agent construction failed")
            raise ValueError(f"Error in creating agent, agent name: {agent_config.name}, Error: {e}")


    def add_history_to_agent(self, history: List[AgentHistory]):
        """
        Add conversation history to agent's memory

        Args:
            history: List of conversation messages with role and content
        """
        if history is None:
            return

        if not isinstance(self.agent, CoreAgent):
            raise TypeError(f"agent must be a CoreAgent object, not {type(self.agent)}")

        if not all(isinstance(msg, AgentHistory) for msg in history):
            raise TypeError("history must be a list of AgentHistory objects")

        self.agent.memory.reset()
        # Add conversation history to memory sequentially
        for msg in history:
            if msg.role == 'user':
                # Create task step for user message
                self.agent.memory.steps.append(TaskStep(task=msg.content))
            elif msg.role == 'assistant':
                self.agent.memory.steps.append(ActionStep(step_number=len(self.agent.memory.steps) + 1,
                                                          timing=Timing(start_time=time.time()),
                                                          action_output=msg.content, model_output=msg.content))

        self.agent._history_step_count = len(self.agent.memory.steps)


    @staticmethod
    def _set_runtime_metadata_for_agent_tree(root_agent: CoreAgent, metadata: Dict[str, Any]):
        """Set isolated runtime metadata on internal and external sub-agents."""

        snapshots = []
        pending = [root_agent]
        visited = set()
        while pending:
            current = pending.pop()
            if not isinstance(current, CoreAgent) or id(current) in visited:
                continue
            visited.add(id(current))
            snapshots.append(("core", current, "metadata" in current.state, current.state.get("metadata")))
            current.state["metadata"] = deepcopy(metadata)
            children = getattr(current, "managed_agents", {}) or {}
            if isinstance(children, dict):
                child_values = children.values()
            elif isinstance(children, (list, tuple)):
                child_values = children
            else:
                child_values = ()
            for child in child_values:
                inner_agent = (
                    child
                    if isinstance(child, CoreAgent)
                    else getattr(child, "_inner", child)
                )
                if isinstance(inner_agent, CoreAgent):
                    pending.append(inner_agent)
                    continue

                set_runtime_metadata = getattr(inner_agent, "set_runtime_metadata", None)
                get_runtime_metadata = getattr(inner_agent, "get_runtime_metadata", None)
                if callable(set_runtime_metadata) and callable(get_runtime_metadata):
                    snapshots.append(("external", inner_agent, True, get_runtime_metadata()))
                    set_runtime_metadata(deepcopy(metadata))
        return snapshots


    @staticmethod
    def _restore_runtime_metadata_for_agent_tree(snapshots) -> None:
        """Restore agent state after one run, including failure and cancellation."""

        for agent_type, agent, existed, previous_value in snapshots:
            if agent_type == "external":
                agent.set_runtime_metadata(previous_value)
            elif existed:
                agent.state["metadata"] = previous_value
            else:
                agent.state.pop("metadata", None)


    def agent_run_with_observer(
        self,
        query: str,
        reset: bool = True,
        additional_args: Optional[Dict[str, Any]] = None,
    ):
        if not isinstance(self.agent, CoreAgent):
            raise TypeError(f"agent must be a CoreAgent object, not {type(self.agent)}")

        monitoring_manager = get_monitoring_manager()
        current_metadata = get_agent_monitoring_context() or AgentRunMetadata()
        metadata = replace(
            current_metadata,
            agent_name=current_metadata.agent_name or getattr(self.agent, "name", None) or self.agent.agent_name,
            agent_display_name=current_metadata.agent_display_name or getattr(self.agent, "display_name", None),
            query=current_metadata.query if current_metadata.query is not None else query,
        )
        observer = self.agent.observer
        total_output_tokens = 0
        final_answer_for_trace = None
        with monitoring_manager.start_agent_run(metadata):
            with monitoring_manager.trace_agent_step(
                "agent.run.loop",
                metadata,
                step_type="agent_loop",
            ):
                runtime_state_snapshots = []
                try:
                    query = self._prepare_file_workspace(query)
                    runtime_state_snapshots = self._set_runtime_metadata_for_agent_tree(
                        self.agent,
                        (additional_args or {}).get("metadata", {}),
                    )
                    step_log = None
                    run_kwargs = {"stream": True, "reset": reset}
                    if additional_args is not None:
                        run_kwargs["additional_args"] = additional_args
                    for step_log in self.agent.run(query, **run_kwargs):
                        # Add content to observer
                        if not isinstance(step_log, ActionStep):
                            continue

                        # Real tool-call chunks are emitted by CoreAgent
                        # (_emit_real_tool_chunks_from_code) right after the
                        # PARSE chunk, so we deliberately skip re-emitting them
                        # here to avoid duplicating the synthetic
                        # ``python_interpreter`` ToolCall that smolagents
                        # stamps on every action step.

                        # Emit token stats after each action step
                        step_duration = getattr(step_log.timing, "duration", None)
                        step_input = None
                        step_output = None
                        if hasattr(step_log, "token_usage") and step_log.token_usage is not None:
                            step_input = getattr(step_log.token_usage, "input_tokens", None)
                            step_output = getattr(step_log.token_usage, "output_tokens", None)
                        if step_output:
                            total_output_tokens += step_output

                        estimated_context = None
                        last_metric = None
                        if hasattr(self.agent, "step_metrics") and self.agent.step_metrics:
                            last_metric = self.agent.step_metrics[-1]
                            estimated_context = last_metric.get(
                                "memory_state", {}
                            ).get("estimated_input_tokens")

                        token_threshold = None
                        context_window_tokens = None
                        effective_input_limit_tokens = None
                        context_processing_mode = None
                        context_runtime = getattr(self.agent, "context_runtime", None)
                        if context_runtime is not None:
                            token_threshold = context_runtime.token_threshold
                            context_window_tokens = context_runtime.context_window_tokens
                            effective_input_limit_tokens = context_runtime.effective_input_limit_tokens
                            context_processing_mode = context_runtime.processing_mode

                        token_data = {
                            "step_number": step_log.step_number,
                            "duration": round(float(step_duration), 2) if step_duration is not None else 0.0,
                            "step_input_tokens": step_input,
                            "step_output_tokens": step_output,
                            "total_output_tokens": total_output_tokens,
                            "estimated_context_tokens": estimated_context,
                            "token_threshold": token_threshold,
                            "context_window_tokens": context_window_tokens,
                            "effective_input_limit_tokens": effective_input_limit_tokens,
                            "context_processing_mode": context_processing_mode,
                            "output_finish_reason": getattr(
                                getattr(self.agent, "model", None),
                                "last_finish_reason",
                                None,
                            ),
                        }
                        if last_metric:
                            compression = last_metric.get("compression", {}) or {}
                            token_data.update({
                                "compression_calls": compression.get("calls", 0),
                                "compression_input_tokens": compression.get("input_tokens", 0),
                                "compression_output_tokens": compression.get("output_tokens", 0),
                                "compression_cache_hits": compression.get("cache_hits", 0),
                                "compression_cache_types": compression.get("cache_types", []),
                                "compression_ratio": last_metric.get("compression_ratio", 0.0),
                                "uncompressed_est_tokens": last_metric.get("uncompressed_mem_est_input", 0),
                            })
                        active_model = getattr(self.agent, "model", None)
                        cache_usage = getattr(active_model, "last_prompt_cache_usage", None)
                        cache_advice = getattr(active_model, "last_provider_cache_advice", None)
                        if cache_usage is not None:
                            metrics_source = getattr(cache_usage, "metrics_source", "capability_unknown")
                            metrics_available = metrics_source not in {"none", "capability_unknown"}
                            capability_supported = bool(getattr(cache_advice, "supported", False))
                            token_data.update({
                                "provider_cache_status": (
                                    "available" if metrics_available else
                                    "unavailable" if capability_supported else
                                    "unsupported"
                                ),
                                "provider_cache_metrics_source": metrics_source,
                                "provider_cache_hit": bool(getattr(cache_usage, "provider_cache_hit", False)),
                                "provider_cached_input_tokens": int(
                                    getattr(cache_usage, "cached_input_tokens", 0) or 0
                                ),
                                "provider_uncached_input_tokens": int(
                                    getattr(cache_usage, "uncached_input_tokens", 0) or 0
                                ),
                            })
                        observer.add_message("", ProcessType.TOKEN_COUNT, json.dumps(token_data))

                        if (
                            hasattr(step_log, "error")
                            and step_log.error is not None
                            and not getattr(step_log, "_suppress_user_error", False)
                        ):
                            # Action-step failures are observations in the ReAct loop:
                            # the model receives them and can repair/retry on the next
                            # step. Surface them as warnings so the UI does not imply
                            # that the whole run has already failed.
                            observer.add_message("", ProcessType.WARNING, str(step_log.error))

                    if step_log is None:
                        raise ValueError("Agent run produced no output")

                    final_answer = step_log.output  # Last log is the run's final_answer

                    if isinstance(final_answer, AgentText):
                        final_answer_str = convert_code_format(final_answer.to_string())
                    else:
                        # prepare for multi-modal final_answer
                        final_answer_str = convert_code_format(str(final_answer))
                    final_answer_str = re.sub(
                        THINK_TAG_PATTERN, "", final_answer_str, flags=re.DOTALL | re.IGNORECASE)
                    # Remove thinking prefix content (until two newlines)
                    final_answer_str = re.sub(
                        THINK_PREFIX_PATTERN, "", final_answer_str, flags=re.DOTALL)
                    final_answer_str = _ensure_non_empty_final_answer(
                        final_answer_str,
                        getattr(observer, "lang", "en"),
                    )
                    final_answer_for_trace = final_answer_str
                    monitoring_manager.set_openinference_output(final_answer_str)
                    observer.complete_final_answer(self.agent.agent_name, final_answer_str)

                    # Check if we need to stop from external stop_event
                    if self.agent.stop_event.is_set():
                        observer.add_message(self.agent.agent_name, ProcessType.WARNING,
                                             "Agent execution interrupted by external stop signal")
                except ModelOutputProtocolExhaustedError as e:
                    observer.add_message(
                        agent_name=self.agent.agent_name,
                        process_type=ProcessType.ERROR,
                        content=str(e),
                        error_code="model_output_protocol_exhausted",
                        retryable=False,
                    )
                    raise
                except ModelInvocationTerminalError as e:
                    observer.add_message(
                        agent_name=self.agent.agent_name,
                        process_type=ProcessType.ERROR,
                        content=e.safe_message(getattr(observer, "lang", "en")),
                        error_code=e.error_code.value,
                        retryable=False,
                    )
                    raise
                except Exception as e:
                    if is_mcp_timeout_error(e):
                        raise
                    category, leaf = classify_mcp_failure(e)
                    if category:
                        # Keep the ReAct loop alive: the model receives the
                        # friendly text and can switch tools or tell the user.
                        content = mcp_failure_message(
                            category,
                            getattr(observer, "lang", "en"),
                            server=find_mcp_server_url(e),
                            leaf=leaf,
                        )
                        logger.error(
                            "event=agent_step_mcp_failure agent=%s category=%s",
                            self.agent.agent_name,
                            category,
                            exc_info=True,
                        )
                        observer.add_message(
                            agent_name=self.agent.agent_name,
                            process_type=ProcessType.ERROR,
                            content=content,
                            error_code=f"mcp_{category}",
                            retryable=True,
                        )
                        raise ValueError(f"Error in interaction: {content}")
                    observer.add_message(agent_name=self.agent.agent_name, process_type=ProcessType.ERROR,
                                         content=f"Error in interaction: {str(e)}")
                    raise ValueError(f"Error in interaction: {str(e)}")

                finally:
                    self._close_subagent_invocations()
                    self._restore_runtime_metadata_for_agent_tree(runtime_state_snapshots)
                    self._log_step_metrics()
                    self.close()

            if final_answer_for_trace is not None:
                if hasattr(self.agent, "step_metrics"):
                    monitoring_manager.set_agent_context_metrics(self.agent.step_metrics)
                monitoring_manager.set_openinference_output(final_answer_for_trace)
            return final_answer_for_trace


    def set_agent(self, agent: CoreAgent):
        if not isinstance(agent, CoreAgent):
            raise TypeError(f"agent must be a CoreAgent object, not {type(agent)}")
        self.agent = agent


    def _log_step_metrics(self):
        """Output step_metrics to log or local file for quantitative analysis of context management."""
        if not hasattr(self.agent, "step_metrics") or not self.agent.step_metrics:
            return

        metrics = self.agent.step_metrics

        # Pre-collect all values
        real_i_vals = [m['main_llm']['input_tokens'] for m in metrics]
        real_o_vals = [m['main_llm']['output_tokens'] for m in metrics]
        comp_i_vals = [m['compression']['input_tokens'] for m in metrics]
        comp_o_vals = [m['compression']['output_tokens'] for m in metrics]
        est_i_vals  = [m['memory_state']['estimated_input_tokens'] for m in metrics]
        est_o_vals  = [m['memory_state']['estimated_output_tokens'] for m in metrics]
        raw_i_vals  = [m['uncompressed_mem_est_input'] for m in metrics]
        save_vals   = [f"{m['compression_ratio']}%" for m in metrics]
        hit_vals    = [str(m['cache_hit']) for m in metrics]

        # Total summary
        total_ri   = sum(real_i_vals)
        total_ro   = sum(real_o_vals)
        total_ci   = sum(comp_i_vals)
        total_co   = sum(comp_o_vals)
        total_ei   = sum(est_i_vals)
        total_eo   = sum(est_o_vals)
        total_raw  = sum(raw_i_vals)
        hit_count  = sum(1 for m in metrics if m['cache_hit'])

        if total_raw > 0:
            total_save_str = f"{round((1 - total_ei / total_raw) * 100, 1)}%"
        else:
            total_save_str = "N/A"
        hit_total_str = f"{hit_count}/{len(metrics)}"

        # Column widths based on max value width
        def _val_width(vals, extra_val=None):
            w = 0
            for v in vals:
                w = max(w, len(str(v)))
            if extra_val is not None:
                w = max(w, len(str(extra_val)))
            return w

        w_ri   = _val_width(real_i_vals, total_ri)
        w_ro   = _val_width(real_o_vals, total_ro)
        w_ci   = _val_width(comp_i_vals, total_ci)
        w_co   = _val_width(comp_o_vals, total_co)
        w_ei   = _val_width(est_i_vals, total_ei)
        w_eo   = _val_width(est_o_vals, total_eo)
        w_raw  = _val_width(raw_i_vals, total_raw)
        w_save = _val_width(save_vals, total_save_str)
        w_hit  = _val_width(hit_vals, hit_total_str)

        # Prefix formatting
        max_step_digits = max(len(str(m['step_number'])) for m in metrics)
        step_prefix_fmt = f"Step {{:>{max_step_digits}}}:  "
        total_prefix = "Total:  " + " " * max_step_digits

        lines = []
        for i, m in enumerate(metrics):
            lines.append(
                step_prefix_fmt.format(m['step_number']) +
                f"real_i={real_i_vals[i]:>{w_ri}}  real_o={real_o_vals[i]:>{w_ro}} | "
                f"comp_i={comp_i_vals[i]:>{w_ci}}  comp_o={comp_o_vals[i]:>{w_co}} | "
                f"est_i={est_i_vals[i]:>{w_ei}}  est_o={est_o_vals[i]:>{w_eo}} | "
                f"est_raw_i={raw_i_vals[i]:>{w_raw}}  save={save_vals[i]:>{w_save}} | "
                f"hit={hit_vals[i]:>{w_hit}}"
            )

        lines.append(
            total_prefix +
            f"real_i={total_ri:>{w_ri}}  real_o={total_ro:>{w_ro}} | "
            f"comp_i={total_ci:>{w_ci}}  comp_o={total_co:>{w_co}} | "
            f"est_i={total_ei:>{w_ei}}  est_o={total_eo:>{w_eo}} | "
            f"est_raw_i={total_raw:>{w_raw}}  save={total_save_str:>{w_save}} | "
            f"hit={hit_total_str:>{w_hit}}"
        )
        context_runtime = getattr(self.agent, "context_runtime", None)
        if context_runtime is not None:
            lines.append(f"Context Manager Global: {context_runtime.global_compression_stats()}")

        lines.append(
            "-----"
        )
        logger.debug("\n".join(lines))

        # Optional: write to local file
        with open("nexent_context_metrics.log", "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def _resolve_tool_class(self, name):
        return globals().get(name)

    @contextmanager
    def _legacy_subagent_invocation(self, config, definition, tree_context, scope, mark_drained):
        """Preserve direct SDK child construction when no host run was supplied."""
        from nexent.core.agents.contracts.config import copy_invocation_config
        from nexent.core.concurrency.cancellation import RunTerminated
        runtime = type(self)(
            observer=self.observer, model_config_list=self.model_config_list, stop_event=scope.stop_event,
            mcp_tool_collection=self.mcp_tool_collection, redis_client=self.redis_client,
            sandbox_config=self.sandbox_config, minio_client=self.minio_client,
            conversation_id=self.conversation_id, user_id=self.user_id, tenant_id=self.tenant_id,
            workspace_path=self.workspace_path, workspace_run_id=self.workspace_run_id,
            cancellation_scope=scope, user_context=self.user_context,
            tool_fastpath_enabled=self.tool_fastpath_enabled,
            tool_fastpath_allowed_tools=self.tool_fastpath_allowed_tools,
        )
        runtime._sandbox_skill_cleanup_owner = self._sandbox_skill_cleanup_owner
        try:
            agent = runtime.create_single_agent(copy_invocation_config(config), _managed_context=True,
                                                _sandbox_tree_context=tree_context)
            runtime.set_agent(agent)
            runtime._set_runtime_metadata_for_agent_tree(agent, definition.get_runtime_metadata())
            runtime._initialize_sandbox_workspaces()
            if scope.cancelled:
                raise RunTerminated("Subagent invocation cancelled during allocation")
            yield agent
        finally:
            runtime._close_subagent_invocations()
            try:
                if runtime.workspace_path:
                    runtime._pull_file_workspace_from_sandbox()
            finally:
                runtime._cleanup_sandbox()
            mark_drained()

    @property
    def core_run_info(self):
        return self._core_run_info

    @core_run_info.setter
    def core_run_info(self, info):
        self._core_run_info = info
        if info is not None:
            from nexent.core.agents.orchestration.children import child_invocation_factory
            self._child_invocation_factory = child_invocation_factory(info)


__all__ = [
    "NexentAgent", "CoreAgent", "Tool", "ActionStep", "TaskStep", "_wrap_tool_with_monitoring",
    "_tool_name", "_is_retriever_tool", "_build_tool_input", "cleanup_run_workspace",
    "SAFE_PYTHON_INTERPRETER_IMPORTS", "get_local_python_authorized_imports",
]
