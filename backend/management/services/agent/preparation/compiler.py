# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Compile the current Nexent configuration from Management-owned resources."""

import json
import logging
from typing import Any, Dict, List, Optional

from contracts.constants.environment import (
    NEXENT_SANDBOX_DEFAULT_LEVEL,
    RUNTIME_PARALLEL_EXECUTOR_TIMEOUT_SECONDS,
)
from contracts.constants.constants import LANGUAGE
from contracts.errors.exceptions import WorkbenchError
from contracts.tool import ToolParamsRequest
from management.db.agent.repository import (
    query_sub_agent_relations,
    resolve_sub_agent_version_no,
    search_agent_info_by_agent_id,
)
from management.db.model.repository import get_model_by_model_id
from management.services.agent.context import build_context_inputs
from management.services.agent.preparation.resources import (
    _build_effective_knowledge_base_summary,
    _get_external_a2a_agents,
)
from management.services.agent.preparation.tools import (
    _build_parallel_executor_tool_config,
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
from management.services.memory.providers.service import (
    get_memory_external_provider_service,
)
from management.services.model.resolver import is_model_available
from management.services.model.run_budget import (
    _TOKEN_THRESHOLD_LEGACY_FALLBACK,
    _resolve_context_budget,
    _resolve_input_budget,
)
from nexent.core.agents.agent_model import (
    AgentConfig,
    AgentVerificationConfig,
    ToolConfig,
)
from nexent.core.agents.context import (
    ContextManagerConfig,
    PolicyLayers,
    resolve_policy,
)
from nexent.core.agents.nexent_agent import get_local_python_authorized_imports
from nexent.core.agents.prompt import AgentPromptComposer
from pydantic import ValidationError
from nexent.core.concurrency import run_blocking
from nexent.memory import models as memory_models

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
    runtime_model_records: Optional[Dict[int, Dict[str, Any]]] = None,
):
    normalized_tool_params = _normalize_tool_params_request(tool_params)
    agent_info = search_agent_info_by_agent_id(
        agent_id=agent_id, tenant_id=tenant_id, version_no=version_no
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
            version_no=sub_agent_version_no,
            override_model_id=None,
            tool_params=child_tool_params,
            conversation_id=conversation_id,
            include_automation_tool=False,
            runtime_knowledge_context=child_knowledge_context,
            runtime_file_context=runtime_file_context,
            # Workbench overlays replace Skills on the effective root only.
            runtime_skill_snapshot=None,
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
    )
    memory_tool_names = {"store_memory", "search_memory"}
    tool_list = [tool for tool in tool_list if tool.name not in memory_tool_names]

    # Append parallel_executor as an always-available system-managed tool.
    # Memory handling is wired separately below: only store_memory is exposed
    # to the model, while search_memory runs once during preparation.
    tool_list.append(
        _build_parallel_executor_tool_config(RUNTIME_PARALLEL_EXECUTOR_TIMEOUT_SECONDS)
    )

    if (
        include_automation_tool
        and conversation_id is not None
        and automation_user_message
    ):
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

    is_manager = len(worker_agents) > 0 or len(external_a2a_agents) > 0

    # Memory list population: in the new Memory system this is performed by
    # the backend's ``memory_context_service`` via the
    # ``MemoryService.search_memory`` facade. The legacy
    # ``search_memory_in_levels`` multi-level fan-out has been removed; the
    # streaming layer and tool wiring below remain in place.
    memory_list: list = []
    long_term_memory_items: list[dict[str, Any]] = []
    pre_run_tool_events: list[dict[str, Any]] = []
    memory_context = build_memory_context(
        user_id, tenant_id, agent_id, skip_query=not allow_memory_search
    )

    # The memory capability switch controls tenant, user, and agent memory.
    if memory_context.user_config.memory_switch:
        try:
            from management.services.memory.records import (
                _resolve_tenant_embedding_model_info,
            )

            embedding_configured = (
                _resolve_tenant_embedding_model_info(
                    str(memory_context.tenant_id or "")
                )
                is not None
            )
            memory_metadata = {
                "memory_user_config": memory_context.user_config,
                "tenant_id": memory_context.tenant_id,
                "user_id": memory_context.user_id,
                "agent_id": memory_context.agent_id,
                "conversation_id": (
                    str(conversation_id) if conversation_id is not None else ""
                ),
                "embedding_configured": embedding_configured,
            }

            # Wire the SDK ``MemoryService`` facade to the
            # backend services via the adapter. The facade handles policy
            # enforcement, embedding lookup, and idempotency on its own
            # and dispatches persistence/retrieval to
            # ``management.services.memory.records`` /
            # ``management.services.memory.retrieval``.
            memory_service = None
            try:
                from management.services.memory.provider import (
                    build_memory_service_for_agent,
                )

                memory_service = build_memory_service_for_agent(
                    tenant_id=memory_context.tenant_id,
                    user_id=memory_context.user_id,
                    agent_id=str(memory_context.agent_id or ""),
                )
                if memory_service is None:
                    raise RuntimeError("MemoryService builder returned no service")
                memory_metadata["memory_service"] = memory_service
            except Exception as exc:
                logger.warning(
                    "event=memory_service_init_failed tenant_id=%s user_id=%s "
                    "agent_id=%s error_type=%s",
                    tenant_id,
                    user_id,
                    agent_id,
                    type(exc).__name__,
                )

            memory_context_service = None
            try:
                from management.services.memory.context import (
                    get_memory_context_service,
                )

                memory_context_service = get_memory_context_service()
                if memory_context_service is None:
                    raise RuntimeError(
                        "MemoryContextService provider returned no service"
                    )
                memory_metadata["memory_context_service"] = memory_context_service
            except Exception as exc:
                logger.warning(
                    "event=memory_context_service_init_failed tenant_id=%s "
                    "user_id=%s agent_id=%s error_type=%s",
                    tenant_id,
                    user_id,
                    agent_id,
                    type(exc).__name__,
                )

            if memory_context_service is not None:
                try:
                    external_results = None
                    try:
                        provider_service = _get_external_provider_service_for_search()
                        if provider_service is not None:
                            top_k = memory_context.user_config.external_provider_top_k
                            logger.info(
                                "event=external_provider_search_started tenant_id=%s "
                                "agent_id=%s top_k=%d",
                                tenant_id,
                                agent_id,
                                top_k,
                            )

                            search_request = memory_models.MemorySearchRequest(
                                query=last_user_query or "",
                                tenant_id=str(memory_context.tenant_id or ""),
                                user_id=str(memory_context.user_id or ""),
                                agent_id=str(memory_context.agent_id or "") or None,
                                conversation_id=(
                                    str(conversation_id)
                                    if conversation_id is not None
                                    else None
                                ),
                                top_k=top_k,
                            )

                            ext_search_results = (
                                await provider_service.search_all_enabled(
                                    tenant_id=str(memory_context.tenant_id or ""),
                                    request=search_request,
                                    limit=top_k,
                                )
                            )

                            if ext_search_results:
                                external_results = [
                                    memory_models.ExternalMemoryItem(
                                        id=str(r.memory_id or r.external_id or ""),
                                        content=r.content,
                                        score=r.score,
                                        provider=r.source or "external",
                                        metadata=r.metadata or {},
                                        created_at=None,
                                    )
                                    for r in ext_search_results
                                ]
                            logger.info(
                                "event=external_provider_search_completed tenant_id=%s "
                                "agent_id=%s results_count=%d",
                                tenant_id,
                                agent_id,
                                len(external_results or []),
                            )
                    except Exception as exc:
                        logger.warning(
                            "event=external_provider_search_failed tenant_id=%s user_id=%s "
                            "agent_id=%s error_type=%s",
                            tenant_id,
                            user_id,
                            agent_id,
                            type(exc).__name__,
                        )

                    long_term_search_context = (
                        await memory_context_service.build_context(
                            tenant_id=str(memory_context.tenant_id or ""),
                            user_id=str(memory_context.user_id or ""),
                            agent_id=str(memory_context.agent_id or "") or None,
                            conversation_id=(
                                str(conversation_id)
                                if conversation_id is not None
                                else None
                            ),
                            query=None,
                            layers=["tenant", "user"],
                            external_results=external_results,
                        )
                    )
                    long_term_memory_items = _build_long_term_memory_items(
                        long_term_search_context
                    )
                except Exception as exc:
                    logger.warning(
                        "event=long_term_memory_load_failed tenant_id=%s user_id=%s "
                        "agent_id=%s error_type=%s",
                        tenant_id,
                        user_id,
                        agent_id,
                        type(exc).__name__,
                    )

            if memory_service is not None:
                store_tool_config = ToolConfig(
                    class_name="StoreMemoryTool",
                    name="store_memory",
                    description=(
                        "Store one model-selected and summarized short-term memory extracted only "
                        "from the conversation between the user and the current agent. Eligible "
                        "information is limited to process-level observations made during intermediate "
                        "action steps: user preferences, task goals, action plans and latest progress, "
                        "or reflections on user feedback and errors. Do not store whole conversations, "
                        "transient calculations, unverified guesses, duplicates, secrets, or information "
                        "the user asks to forget. Call this tool only during intermediate action steps, "
                        "not when generating the final answer."
                    ),
                    inputs=json.dumps(
                        {
                            "content": {
                                "type": "string",
                                "description": (
                                    "One concise, reusable short-term memory entry already judged, "
                                    "summarized, and deduplicated by the model"
                                ),
                                "description_zh": (
                                    "由模型判断、总结并去重后的一条简洁、可复用的短期记忆"
                                ),
                            }
                        },
                        ensure_ascii=False,
                    ),
                    output_type="string",
                    params={},
                    source="local",
                    usage=None,
                    metadata=memory_metadata,
                )
                tool_list.append(store_tool_config)

            if memory_context_service is not None:
                fixed_search_tool = _create_fixed_search_memory_tool()
                fixed_search_tool.memory_context_service = memory_context_service
                fixed_search_tool.tenant_id = str(memory_context.tenant_id or "")
                fixed_search_tool.user_id = str(memory_context.user_id or "")
                fixed_search_tool.agent_id = str(memory_context.agent_id or "")
                fixed_search_tool.conversation_id = (
                    str(conversation_id) if conversation_id is not None else ""
                )
                fixed_search_tool.embedding_configured = embedding_configured
                fixed_search_tool.external_results = external_results
                fixed_search_result = await run_blocking(
                    "memory-presearch",
                    fixed_search_tool.forward,
                    last_user_query or "",
                    5,
                    lane="model-tool-io",
                    owner="runtime",
                )
            else:
                fixed_search_result = (
                    "Memory search unavailable: retrieval pipeline is not configured. "
                    "Continuing without memory results."
                )
                logger.warning(
                    "event=memory_presearch_skipped tenant_id=%s user_id=%s "
                    "agent_id=%s conversation_id=%s "
                    "reason=context_service_unavailable",
                    tenant_id,
                    user_id,
                    agent_id,
                    conversation_id,
                )
            pre_run_tool_events.extend(
                [
                    {
                        "type": "tool",
                        "content": "",
                        "tool_name": "search_memory",
                        "tool_arguments": {
                            "query": last_user_query or "",
                            "top_k": 5,
                        },
                    },
                    {
                        "type": "execution_logs",
                        "content": fixed_search_result,
                    },
                ]
            )
            if fixed_search_result.startswith("Found "):
                memory_list.append(
                    {
                        "memory": fixed_search_result,
                        "memory_level": "agent",
                    }
                )
        except Exception as e:
            logger.error(f"Failed to load memory tools: {e}", exc_info=True)

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
        if model_info is None and override_model_id is not None:
            raise ValidationError("MODEL_OUTLET_NOT_AVAILABLE")
        model_name = model_info["display_name"] if model_info is not None else "main_model"
        # Capacity and output reserve come exclusively from the saved outlet.
        input_budget, capacity_snapshot, resolved_capacity_snapshot = (
            _resolve_input_budget(
                model_info,
            )
        )
    else:
        model_name = "main_model"
        input_budget = _TOKEN_THRESHOLD_LEGACY_FALLBACK
        capacity_snapshot = None
        resolved_capacity_snapshot = None

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
    policy_layers = PolicyLayers.model_validate(
        {
            "platform": {
                "processing_mode": "adaptive_compact"
                if enable_context_manager
                else "passthrough"
            },
            "tenant": tenant_config_manager.get_context_policy(tenant_id),
            "agent": agent_info.get("context_policy"),
            "request": request_context_policy,
        }
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
    return agent_config


def _select_agent_model_id(
    agent_model_ids: List[int],
    override_model_id: int | None,
    tenant_id: str,
) -> int | None:
    """Select the request override or the first configured available model."""
    if override_model_id is not None:
        return override_model_id
    for model_id in agent_model_ids:
        if is_model_available(get_model_by_model_id(model_id, tenant_id=tenant_id)):
            return model_id
    return agent_model_ids[0] if agent_model_ids else None


def _resolve_prompt_runtime_flags(
    agent_info: Dict[str, Any],
) -> tuple[AgentVerificationConfig, bool]:
    """Resolve prompt gates from Backend-owned configuration facts."""
    verification_config = AgentVerificationConfig.model_validate(
        agent_info.get("verification_config") or {}
    )
    is_local_python_executor = NEXENT_SANDBOX_DEFAULT_LEVEL.strip().lower() == "local"
    return verification_config, is_local_python_executor


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
