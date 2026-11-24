# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Compile the current Nexent configuration from Management-owned resources."""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from contracts.constants.constants import LANGUAGE
from contracts.constants.environment import (
    NEXENT_SANDBOX_DEFAULT_LEVEL,
)
from contracts.constants.constants import MODEL_CONFIG_MAPPING
from infrastructure.system_configuration.runtime import get_config_snapshot
from contracts.errors.exceptions import RunModelControlsError, WorkbenchError
from contracts.tool import ToolParamsRequest
from infrastructure.agent_tool_config import (
    build_automation_proposal_tool, build_parallel_executor_tool_config, build_store_memory_tool,
)
from management.db.agent.repository import (
    query_sub_agent_relations,
    resolve_sub_agent_version_no,
    search_agent_info_by_agent_id,
)
from management.db.model.repository import get_model_by_model_id
from management.services.agent.context import build_context_inputs
from management.services.agent.core_policy import apply_agent_core_policy
from management.services.agent.preparation.resources import (
    _build_effective_knowledge_base_summary,
    _get_external_a2a_agents,
)
from management.services.agent.preparation.tools import (
    _get_skill_script_tools,
    _inject_plan_tools,
    _normalize_tool_params_request,
    create_tool_config_list,
)
from management.services.agent.prompt import (
    load_agent_prompt_bundle,
    should_enable_automation_tool_policy,
    should_enable_memory_tool_policy,
)
from management.services.agent.resource_resolver import _get_skills_for_template
from management.services.configuration.tenant.settings import tenant_config_manager
from management.services.configuration.user.memory import build_memory_context
from infrastructure.memory_io import memory_deadline, optional_memory_io
from management.services.memory.providers.service import (
    get_memory_external_provider_service,
)
from management.services.model.resolver import is_model_available
from management.services.model.run_budget import (
    _resolve_context_budget,
    _resolve_input_budget,
)
from management.services.model.run_controls import select_configured_model_id
from nexent.core.agents.contracts.config import (
    AgentConfig,
    AgentVerificationConfig,
    ToolConfig,
)
from nexent.core.agents.context import (
    ContextManagerConfig,
    PolicyLayers,
    resolve_policy,
)
from nexent.core.agents.cores.smolagents.agent import get_local_python_authorized_imports
from nexent.core.agents.prompt import AgentPromptComposer
from nexent.core.concurrency import ManagedTaskSpec, get_default_thread_manager
from nexent.memory import models as memory_models
from nexent.monitor.phase_capture import trace_phase

logger = logging.getLogger("create_agent_info")
logger.setLevel(logging.INFO)


async def create_agent_config(
    agent_id,
    tenant_id,
    user_id,
    language: str = LANGUAGE["ZH"],
    last_user_query: str = None,
    allow_memory_search: bool = True,
    version_no: int = 0,
    override_model_id: int | None = None,
    request_requested_output_tokens: int | None = None,
    tool_params: Optional[ToolParamsRequest | Dict[str, Any]] = None,
    conversation_id: Optional[int] = None,
    request_context_policy: Optional[Dict[str, Any]] = None,
    enable_planning: bool = False,
    include_automation_tool: bool = False,
    automation_user_message: Optional[str] = None,
    automation_model_id: Optional[int] = None,
    automation_has_attachments: bool = False,
    runtime_knowledge_context: Optional[Dict[str, str]] = None,
    runtime_file_context: Optional[Dict[str, Any]] = None,
    runtime_skill_snapshot: Optional[List[Dict[str, Any]]] = None,
    runtime_knowledge_tools: Optional[List[Dict[str, Any]]] = None,
    runtime_sub_agent_mounts: Optional[List[Dict[str, Any]]] = None,
    *,
    portable_evaluation: bool = False,
    authorized_knowledge_tools: dict | None = None,
    runtime_model_records: Optional[Dict[int, Dict[str, Any]]] = None,
    prompt_candidate_id: int | None = None,
    excluded_root_tools: frozenset[str] = frozenset(),
    memory_query_deadline: float | None = None,
):
    portable_options = {"portable_evaluation": True} if portable_evaluation else {}
    if authorized_knowledge_tools is not None:
        portable_options["authorized_knowledge_tools"] = authorized_knowledge_tools
    normalized_tool_params = _normalize_tool_params_request(tool_params)
    agent_info = search_agent_info_by_agent_id(
        agent_id=agent_id, tenant_id=tenant_id, version_no=version_no
    )

    if memory_query_deadline is None:
        memory_query_deadline = memory_deadline()
    memory_context = None
    if allow_memory_search:
        memory_context = await optional_memory_io(
            "memory-policy", _load_authorized_memory_context, user_id, tenant_id, agent_id,
            deadline=memory_query_deadline,
        )

    # create sub agent
    child_tool_params = normalized_tool_params
    child_knowledge_context = runtime_knowledge_context
    if runtime_knowledge_tools is not None:
        child_tool_params = normalized_tool_params.model_copy(deep=True)
        root_override = child_tool_params.agents.get(agent_info.get("name"))
        if root_override is not None:
            from management.services.knowledge_base.mount import MANAGED_CLASSES

            managed_names = MANAGED_CLASSES | {
                tool.get("name")
                for tool in runtime_knowledge_tools
                if tool.get("class_name") in MANAGED_CLASSES
            }
            root_override.tools = {
                name: params
                for name, params in root_override.tools.items()
                if name not in managed_names
            }
        child_knowledge_context = None
    memory_phase_attributes = {
        "agent.id": str(agent_id), "agent.name": agent_info.get("name", ""),
    }
    display_name = agent_info.get("display_name")
    if isinstance(display_name, str) and display_name.strip():
        memory_phase_attributes["agent.display_name"] = display_name.strip()
    # Start this Agent's optional context before awaiting recursive compilation.
    memory_task = asyncio.create_task(_prepare_traced_runtime_memory(
        tenant_id=str(tenant_id), user_id=str(user_id), agent_id=str(agent_id),
        conversation_id=str(conversation_id) if conversation_id is not None else None,
        query=last_user_query or "", external_top_k=memory_context.user_config.external_provider_top_k,
        deadline=memory_query_deadline, phase_attributes=memory_phase_attributes,
    )) if memory_context is not None else None
    prepared_memory = ([], None)
    try:
        sub_agent_relations = query_sub_agent_relations(
            main_agent_id=agent_id, tenant_id=tenant_id, version_no=version_no
        )
        worker_agents = []
        for rel in sub_agent_relations:
            sub_agent_id = rel["selected_agent_id"]
            sub_agent_version_no = resolve_sub_agent_version_no(
                selected_agent_id=sub_agent_id,
                selected_agent_version_no=rel.get("selected_agent_version_no"),
                tenant_id=tenant_id,
            )
            sub_agent_config = await create_agent_config(
                agent_id=sub_agent_id,
                tenant_id=tenant_id,
                user_id=user_id,
                language=language,
                last_user_query=last_user_query,
                allow_memory_search=allow_memory_search,
                memory_query_deadline=memory_query_deadline,
                version_no=sub_agent_version_no,
                override_model_id=None,
                tool_params=child_tool_params,
                conversation_id=conversation_id,
                include_automation_tool=False,
                runtime_knowledge_context=child_knowledge_context,
                runtime_file_context=runtime_file_context,
                # Workbench overlays replace Skills on the effective root only.
                runtime_skill_snapshot=None,
                **portable_options,
                runtime_model_records=runtime_model_records,
            )
            # Persisted Agent relations are rendered into the manager prompt by
            # their configured business name. Keep the callable registered in the
            # Python executor under that same name; the generic runtime identity
            # assigned by the recursive builder is only appropriate for roots and
            # Workbench-selected dynamic children.
            sub_agent_config.invocation_name = sub_agent_config.name
            worker_agents.append(sub_agent_config)

        # Workbench-selected Agents are request-scoped children. They are built
        # from pinned published versions but never persisted as Agent relations.
        used_invocation_names = {
            str(agent.invocation_name or agent.name) for agent in worker_agents
        }
        for mount in runtime_sub_agent_mounts or []:
            sub_agent_id = int(mount["agent_id"])
            sub_agent_version_no = int(mount["version_no"])
            if sub_agent_id == int(agent_id) and sub_agent_version_no == int(version_no):
                raise WorkbenchError("WORKBENCH_AGENT_CYCLE")
            sub_agent_config = await create_agent_config(
                agent_id=sub_agent_id,
                tenant_id=tenant_id,
                user_id=user_id,
                language=language,
                last_user_query=last_user_query,
                allow_memory_search=allow_memory_search,
                memory_query_deadline=memory_query_deadline,
                version_no=sub_agent_version_no,
                override_model_id=None,
                tool_params=child_tool_params,
                conversation_id=conversation_id,
                include_automation_tool=False,
                runtime_knowledge_context=child_knowledge_context,
                runtime_file_context=runtime_file_context,
                runtime_skill_snapshot=None,
                runtime_model_records=runtime_model_records,
                runtime_knowledge_tools=None,
                runtime_sub_agent_mounts=None,
                **portable_options,
            )
            invocation_name = str(
                mount.get("invocation_name")
                or f"agent_{sub_agent_id}_v{sub_agent_version_no}"
            )
            if invocation_name in used_invocation_names:
                raise WorkbenchError("WORKBENCH_AGENT_NAME_CONFLICT")
            used_invocation_names.add(invocation_name)
            sub_agent_config.name = invocation_name
            sub_agent_config.invocation_name = invocation_name
            sub_agent_config.runtime_ref = str(
                mount.get("runtime_ref") or f"agent:{sub_agent_id}:v{sub_agent_version_no}"
            )
            sub_agent_config.display_name = str(
                mount.get("display_name")
                or sub_agent_config.display_name
                or invocation_name
            )
            sub_agent_config.origin = "PERSISTED"
            worker_agents.append(sub_agent_config)
        if memory_task is not None:
            prepared_memory = await memory_task
    finally:
        if memory_task is not None:
            if not memory_task.done():
                memory_task.cancel()
            await asyncio.gather(memory_task, return_exceptions=True)

    # create external A2A agents (synchronous function, no await needed)
    external_a2a_agents = _get_external_a2a_agents(agent_id, tenant_id, version_no)

    tool_list = await create_tool_config_list(
        agent_id,
        tenant_id,
        user_id,
        version_no=version_no,
        tool_params=normalized_tool_params,
        runtime_skill_snapshot=runtime_skill_snapshot,
        runtime_knowledge_tools=runtime_knowledge_tools,
        language=language,
        **portable_options,
    )
    memory_tool_names = {"store_memory", "search_memory"}
    tool_list = [
        tool for tool in tool_list
        if tool.name not in memory_tool_names
        and tool.class_name not in {"StoreMemoryTool", "SearchMemoryTool"}
    ]
    parallel_timeout = get_config_snapshot().get("RUNTIME_PARALLEL_EXECUTOR_TIMEOUT_SECONDS")

    # Append parallel_executor as an always-available system-managed tool.
    # Memory handling is wired separately below: only store_memory is exposed
    # to the model, while search_memory runs once during preparation.
    tool_list.append(
        build_parallel_executor_tool_config(parallel_timeout)
    )

    if (
        include_automation_tool
        and conversation_id is not None
        and automation_user_message
    ):
        if portable_evaluation:
            tool_list.append(build_automation_proposal_tool())
        else:
            from management.services.automation.proposal import (
                agent_loop_automation_tool_adapter,
            )

            tool_list.append(
                agent_loop_automation_tool_adapter.build_tool_config(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    conversation_id=int(conversation_id),
                    agent_id=int(agent_id),
                    user_message=automation_user_message,
                    agent_version_no=version_no,
                    model_id=automation_model_id,
                    tool_params=normalized_tool_params.model_dump(mode="json"),
                    has_attachments=automation_has_attachments,
                    language=language,
                )
            )

    # Build the system prompt from the single stored Agent instruction field
    prompt = agent_info.get("prompt", "")
    if prompt_candidate_id is not None:
        from management.services.evaluation.prompt_candidates import resolve_prompt_candidate

        candidate = resolve_prompt_candidate(tenant_id, user_id, agent_id, version_no, prompt_candidate_id)
        if prompt != candidate["source_text"]:
            raise ValueError("Compiled Agent no longer matches the candidate baseline")
        prompt = candidate["result_text"]
    if agent_info.get("agent_origin") == "SYSTEM":
        from management.services.agent.system import localized_system_prompt

        prompt = localized_system_prompt(agent_info, language)

    is_manager = len(worker_agents) > 0 or len(external_a2a_agents) > 0

    memory_list = []
    long_term_memory_items = []
    pre_run_tool_events = []
    if memory_context is not None:
        store_tool = _build_runtime_store_tool(
            memory_context, tenant_id=tenant_id, user_id=user_id, agent_id=str(agent_id),
            version_no=version_no, conversation_id=conversation_id,
            phase_attributes=memory_phase_attributes,
        )
        if store_tool is not None:
            tool_list.append(store_tool)
        long_term_memory_items, fixed_search_result = prepared_memory
        if fixed_search_result:
            pre_run_tool_events = [
                {"type": "tool", "content": "", "tool_name": "search_memory",
                 "tool_arguments": {"query": last_user_query or "", "top_k": 5}},
                {"type": "execution_logs", "content": fixed_search_result},
            ]
            if fixed_search_result.startswith("Found "):
                memory_list.append({"memory": fixed_search_result, "memory_level": "agent"})

    released_exclusions = frozenset(agent_info.get("released_tool_exclusions") or ())
    if excluded_root_tools:
        selectable_names = {tool.name for tool in tool_list} - released_exclusions
        if not portable_evaluation or not excluded_root_tools.issubset(selectable_names):
            raise ValueError("Tool candidate does not match the compiled evaluation scope")
    hidden_tools = released_exclusions | excluded_root_tools
    if hidden_tools:
        tool_list = [tool for tool in tool_list if tool.name not in hidden_tools]

    # The final tool params already contain the conversation selection and ACL
    # intersection. Summaries therefore restore semantic routing without
    # expanding beyond the effective per-run knowledge-base whitelist.
    knowledge_base_summaries, knowledge_base_no_indexes = (
        _build_effective_knowledge_base_summary(
            tool_list,
            include_empty_message=not bool(runtime_knowledge_context),
        )
    )

    # This compatibility flag controls compression only. ContextManager remains
    # the single context assembly path when compression is disabled.
    enable_context_manager = agent_info.get("enable_context_manager", False)

    # Get the skills included in ContextManager items.
    skills = _get_skills_for_template(
        agent_id,
        tenant_id,
        version_no,
        runtime_skill_snapshot=runtime_skill_snapshot,
    )

    is_manager = len(worker_agents) > 0 or len(external_a2a_agents) > 0
    builtin_tools = _get_skill_script_tools(
        agent_id,
        tenant_id,
        version_no,
        runtime_file_context=runtime_file_context,
        runtime_skill_snapshot=runtime_skill_snapshot,
    )
    available_tools = tool_list + builtin_tools

    _inject_plan_tools(available_tools, enable_planning)
    if hidden_tools:
        # Skill, file and planning tools can be added after the first catalog is built.
        available_tools = [tool for tool in available_tools if tool.name not in hidden_tools]
    prompt_tools = {tool.name: tool for tool in available_tools}
    prompt_tool_policy_snapshot = agent_info.get("prompt_tool_policy_snapshot")
    if prompt_tool_policy_snapshot is not None:
        from nexent.core.tools.prompt_registry import (
            PromptToolPolicySnapshot,
            filter_effective_prompt_tools,
        )

        policy = PromptToolPolicySnapshot.from_mapping(prompt_tool_policy_snapshot)
        prompt_tools = dict(
            filter_effective_prompt_tools(
                prompt_tools,
                enabled=set(policy.enabled),
                allowed=set(policy.allowed),
                system_default_hidden=set(policy.system_default_hidden),
                policy_version=policy.policy_version,
                tool_schema_version=policy.tool_schema_version,
            ).tools
        )
    enable_memory_tool_policy = should_enable_memory_tool_policy(prompt_tools)
    enable_automation_tool_policy = should_enable_automation_tool_policy(prompt_tools)

    prompt_bundle = load_agent_prompt_bundle(is_manager=is_manager, language=language)
    prompt_composer = AgentPromptComposer(prompt_bundle)
    # AgentInfo stores model_ids (a list); pick the first available model.
    agent_model_ids = agent_info.get("model_ids") or []
    model_id_to_use = _select_agent_model_id(
        agent_model_ids, override_model_id, tenant_id
    )
    model_info = None
    if model_id_to_use is not None:
        model_info = (runtime_model_records.get(model_id_to_use) if runtime_model_records is not None
                      else get_model_by_model_id(model_id_to_use, tenant_id=tenant_id))
        if model_info is None:
            raise RunModelControlsError("model_not_available")
        model_name = model_info["display_name"] if model_info is not None else "main_model"
        # Capacity and output reserve come exclusively from the saved outlet.
        input_budget, capacity_snapshot, resolved_capacity_snapshot = (
            _resolve_input_budget(
                model_info,
            )
        )
    else:
        model_name = "main_model"
        model_info = tenant_config_manager.get_model_config(MODEL_CONFIG_MAPPING["llm"], tenant_id=tenant_id)
        input_budget, capacity_snapshot, resolved_capacity_snapshot = _resolve_input_budget(model_info)

    requested_output_tokens = None
    context_budget_snapshot = _resolve_context_budget(
        capacity_snapshot=resolved_capacity_snapshot,
        tenant_id=tenant_id,
        agent_requested_output_tokens=requested_output_tokens,
        request_requested_output_tokens=None,
    )
    if context_budget_snapshot is not None:
        effective_input_limit_tokens = (
            context_budget_snapshot.effective_input_limit_tokens
        )
        compaction_trigger_threshold_tokens = (
            context_budget_snapshot.compaction_trigger_threshold_tokens
        )
        compaction_target_tokens = context_budget_snapshot.compaction_target_tokens
        context_token_threshold = compaction_trigger_threshold_tokens
    else:
        effective_input_limit_tokens = 0
        compaction_trigger_threshold_tokens = 0
        compaction_target_tokens = 0
        context_token_threshold = input_budget

    context_window_tokens = (
        resolved_capacity_snapshot.context_window_tokens
        if resolved_capacity_snapshot is not None
        and resolved_capacity_snapshot.context_window_tokens is not None
        else input_budget
    )

    verification_config, is_local_python_executor = _resolve_prompt_runtime_flags(
        agent_info
    )

    context_items = build_context_inputs(
        prompt=prompt,
        language=language,
        is_manager=is_manager,
        enable_planning=enable_planning,
        verification_enabled=verification_config.enabled,
        tools=prompt_tools,
        skills=skills,
        worker_agents={agent.name: agent for agent in worker_agents},
        external_a2a_agents={agent.agent_id: agent for agent in external_a2a_agents},
        memory_list=memory_list,
        memory_search_query=last_user_query,
        enable_memory_tool_policy=enable_memory_tool_policy,
        enable_automation_tool_policy=enable_automation_tool_policy,
        long_term_memory_items=long_term_memory_items,
        knowledge_base_summaries=knowledge_base_summaries,
        knowledge_base_no_indexes=knowledge_base_no_indexes,
        knowledge_scope=(runtime_knowledge_context or {}).get("scope"),
        restricted_python_authorized_imports=(
            get_local_python_authorized_imports() if is_local_python_executor else None
        ),
        sandbox_workspace_enabled=not is_local_python_executor,
        prompt_bundle=prompt_bundle,
    )

    logger.debug(
        f"Agent {agent_id} context assembly: "
        f"skills_count={len(skills)}, "
        f"items={[f'{item.id}(type={item.type.value},priority={item.priority})' for item in context_items]}"
    )
    policy_layers = build_agent_context_policy(
        enable_context_manager, tenant_config_manager.get_context_policy(tenant_id),
        agent_info.get("context_policy"), request_context_policy,
    )
    effective_context_policy = resolve_policy(policy_layers)
    effective_processing_mode = getattr(
        effective_context_policy.processing_mode,
        "value",
        effective_context_policy.processing_mode,
    )
    policy_layers_payload = (
        policy_layers.model_dump(mode="json")
        if hasattr(policy_layers, "model_dump")
        else policy_layers
    )
    logger.info(
        "Agent %s effective context policy: processing_mode=%s layers=%s",
        agent_id,
        effective_processing_mode,
        policy_layers_payload,
    )
    cm_config = ContextManagerConfig(
        token_threshold=context_token_threshold,
        context_window_tokens=context_window_tokens,
        effective_input_limit_tokens=effective_input_limit_tokens,
        compaction_trigger_threshold_tokens=compaction_trigger_threshold_tokens,
        compaction_target_tokens=compaction_target_tokens,
        policy_layers=policy_layers,
    )

    agent_config = AgentConfig(
        released_skill_guides=agent_info.get("released_skill_guides") or [],
        name="undefined" if agent_info["name"] is None else agent_info["name"],
        display_name=agent_info.get("display_name"),
        description="undefined"
        if agent_info["description"] is None
        else agent_info["description"],
        prompt_templates=prompt_composer.compatibility_templates(),
        tools=available_tools,
        max_steps=agent_info.get("max_steps", 15),
        requested_output_tokens=requested_output_tokens,
        model_name=model_name,
        provide_run_summary=agent_info.get("provide_run_summary", False),
        allow_chat_metadata=agent_info.get("allow_chat_metadata", False),
        worker_agents=worker_agents,
        enable_protocol_repair_retry=agent_info.get("enable_protocol_repair_retry")
        is True,
        external_a2a_agents=external_a2a_agents,
        context_manager_config=cm_config,
        context_items=context_items,
        prompt_tool_policy_snapshot=prompt_tool_policy_snapshot,
        pre_run_tool_events=pre_run_tool_events,
        automatic_memory_enabled=memory_context is not None,
        capacity_snapshot=capacity_snapshot,
        context_budget_snapshot=context_budget_snapshot,
        verification_config=verification_config,
        enable_planning=enable_planning,
    )
    agent_config.agent_id = agent_id
    agent_config.version_no = int(version_no)
    agent_config.invocation_name = f"agent_{agent_id}_v{int(version_no)}"
    agent_config.runtime_ref = f"agent:{agent_id}:v{int(version_no)}"
    agent_config.display_name = agent_info.get("display_name") or agent_config.name
    agent_config.origin = "PERSISTED"
    return apply_agent_core_policy(agent_config)


def _select_agent_model_id(
    agent_model_ids: List[int],
    override_model_id: int | None,
    tenant_id: str,
) -> int | None:
    """Select the request override or the first configured available model."""
    if override_model_id is not None:
        return override_model_id
    return select_configured_model_id(agent_model_ids,
        lambda model_id: is_model_available(get_model_by_model_id(model_id, tenant_id=tenant_id)))


def _resolve_prompt_runtime_flags(
    agent_info: Dict[str, Any],
) -> tuple[AgentVerificationConfig, bool]:
    """Resolve prompt gates from Backend-owned configuration facts."""
    verification_config = AgentVerificationConfig.model_validate(
        agent_info.get("verification_config") or {}
    )
    is_local_python_executor = NEXENT_SANDBOX_DEFAULT_LEVEL.strip().lower() == "local"
    return verification_config, is_local_python_executor


def _load_authorized_memory_context(user_id, tenant_id, agent_id):
    context = build_memory_context(user_id, tenant_id, agent_id)
    settings = context.user_config
    if (
        not settings.memory_switch
        or str(agent_id) in settings.disable_agent_ids
        or str(agent_id) in settings.disable_user_agent_ids
    ):
        return None
    return context


def _build_runtime_store_tool(memory_context, *, tenant_id, user_id, agent_id, version_no, conversation_id,
                              phase_attributes=None):
    try:
        from management.services.memory.provider import build_memory_service_for_agent

        with trace_phase(
            "memory.initialize", input_value={"service": "memory"}, attributes=phase_attributes,
        ) as phase:
            memory_service = build_memory_service_for_agent(
                tenant_id=tenant_id, user_id=user_id, agent_id=agent_id,
            )
            if memory_service is None:
                raise RuntimeError("MemoryService builder returned no service")
            phase.set_output({"service": "memory", "ready": True})
    except Exception as exc:
        logger.warning("event=memory_service_init_failed error_type=%s", type(exc).__name__)
        return None
    memory_metadata = {
        "memory_user_config": memory_context.user_config,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "agent_id": agent_id,
        "conversation_id": str(conversation_id) if conversation_id is not None else "",
        # The bounded store hook resolves model readiness at invocation.
        "embedding_configured": True,
        "memory_service": memory_service,
    }
    return build_store_memory_tool(memory_metadata)


async def _prepare_traced_runtime_memory(**kwargs):
    with trace_phase(
        "memory.presearch", input_value={"query": kwargs["query"], "top_k": 5},
        attributes=kwargs["phase_attributes"],
    ) as phase:
        result = await _prepare_runtime_memory(**kwargs)
        phase.set_output(result[1])
        return result


async def _prepare_runtime_memory(*, tenant_id, user_id, agent_id, conversation_id, query, external_top_k, deadline,
                                  phase_attributes=None):
    from management.services.memory.context import get_memory_context_service
    from management.services.memory.records import _resolve_tenant_embedding_model_info
    from management.services.memory.runtime_embedding import compute_runtime_embedding

    def initialize_context():
        with trace_phase(
            "memory.initialize", input_value={"service": "context"}, attributes=phase_attributes,
        ) as phase:
            service = get_memory_context_service()
            if service is None:
                raise RuntimeError("MemoryContextService provider returned no service")
            phase.set_output({"service": "context", "ready": True})
            return service

    service = await optional_memory_io("memory-context-service", initialize_context, deadline=deadline)
    if service is None:
        return [], "Memory search unavailable: retrieval pipeline is not configured. Continuing without memory results."
    scope = dict(tenant_id=tenant_id, user_id=user_id, agent_id=agent_id, conversation_id=conversation_id)
    request = memory_models.MemorySearchRequest(
        **scope, query=query, top_k=5, layers=[memory_models.MemoryLayer.AGENT],
    )

    def load_long_term():
        with trace_phase(
            "memory.load_context", input_value={"layers": ["tenant", "user"]}, attributes=phase_attributes,
        ) as phase:
            context = asyncio.run(service.build_context(**scope, layers=["tenant", "user"], external_results=[]))
            phase.set_output(_build_long_term_memory_items(context) if context else [])
            return context

    async def search_vectors():
        if not query:
            return []
        model = _resolve_tenant_embedding_model_info(tenant_id)
        if model is None:
            return None
        vector = await compute_runtime_embedding(query, model, tenant_id=tenant_id, user_id=user_id, deadline=deadline)
        if vector is None:
            return None
        return await service.retrieval_service.search(
            request.model_copy(update={"embedding": vector}), embedding_model_info=model, write_hits=False,
            deadline=deadline,
        )

    def search_external():
        provider = _get_external_provider_service_for_search()
        if provider is None or not query:
            return []
        ext_request = request.model_copy(update={"top_k": external_top_k})
        with trace_phase(
            "memory.external_search", input_value={"query": query, "top_k": external_top_k},
            attributes=phase_attributes,
        ) as phase:
            results = asyncio.run(provider.search_all_enabled(
                tenant_id=tenant_id, request=ext_request, limit=external_top_k, deadline=deadline - 0.05,
            ))
            phase.set_output(results)
        return [
            memory_models.ExternalMemoryItem(
                id=str(result.memory_id or result.external_id or ""), content=result.content,
                score=result.score, provider=result.source or "external", metadata=result.metadata or {},
                created_at=None,
            )
            for result in results
        ]

    long_term, local, external = await asyncio.gather(
        optional_memory_io("memory-long-term", load_long_term, deadline=deadline),
        optional_memory_io("memory-vector-search", lambda: asyncio.run(search_vectors()), deadline=deadline),
        optional_memory_io("memory-external-search", search_external, deadline=deadline),
    )
    long_term_items = _build_long_term_memory_items(long_term) if long_term else []

    if not local and not external:
        if local is None:
            return long_term_items, "Vector memory unavailable. Continuing with other available context."
        return long_term_items, "No relevant memories found."
    try:
        context = service.pipeline.run(
            internal_results=local or [], query=query, external_results=external or [],
        ).into_memory_search_context()
        # Keep source hits only for local results that survived context selection.
        selected_ids = {item.memory_id for item in context.agent_short_term if not item.is_external}
        selected_hits = [item for item in local or () if item.memory_id in selected_ids]
        if selected_hits:
            try:
                get_default_thread_manager().submit(
                    "memory-write", ManagedTaskSpec(task_name="memory-recall-hits", owner="memory"),
                    service.retrieval_service._record_hits, request=request, results=selected_hits,
                )
            except Exception as exc:
                logger.warning("event=memory_recall_hits_skipped error_type=%s", type(exc).__name__)
        return long_term_items, _create_fixed_search_memory_tool().format_search_context(context, external)
    except Exception as exc:
        logger.warning("event=memory_context_selection_failed error_type=%s", type(exc).__name__)
        return long_term_items, None


def _create_fixed_search_memory_tool():
    """Create the internal search tool lazily to keep import boundaries stable."""
    from nexent.core.tools.search_memory_tool import SearchMemoryTool

    return SearchMemoryTool()


def _get_external_provider_service_for_search():
    """Resolve the external provider service used to search enabled providers."""
    return get_memory_external_provider_service()


def _build_long_term_memory_items(search_context: Any) -> list[dict[str, Any]]:
    """Return at most one structured active document for each long-term scope."""
    result = []
    for attribute, scope in (
        ("tenant_long_term", "tenant"),
        ("user_long_term", "user"),
    ):
        for item in (getattr(search_context, attribute, ()) or ())[:1]:
            content = (
                item.get("content", "")
                if isinstance(item, dict)
                else getattr(item, "content", "")
            )
            metadata = (
                item.get("metadata", {})
                if isinstance(item, dict)
                else getattr(item, "metadata", {})
            )
            source = (
                item.get("source")
                if isinstance(item, dict)
                else getattr(item, "source", None)
            )
            if str(content or "").strip():
                result.append(
                    {
                        "memory": str(content).strip(),
                        "memory_level": scope,
                        "scope": scope,
                        "version_id": (metadata or {}).get("version_id"),
                        "source": source or "manual",
                    }
                )
            break
    return result


def build_agent_context_policy(enable_context_manager, tenant_policy=None, agent_policy=None, request_policy=None):
    """Apply the saved CM switch at Agent precedence, retaining explicit request overrides."""
    mode = "adaptive_compact" if enable_context_manager else "passthrough"
    return PolicyLayers.model_validate({
        "platform": {"processing_mode": mode}, "tenant": tenant_policy,
        "agent": {**(agent_policy or {}), "processing_mode": mode}, "request": request_policy,
    })
