# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Export authorized AgentOS snapshots from the Management compiler."""

import json
from functools import cache

from pydantic_core import PydanticSerializationError

from contracts.agent import AgentRequest
from contracts.agentos import (
    AgentResource, AgentRunReference, AnalysisToolBinding, EvaluationAgentOptions, EvaluationAnalysisTool, EvaluationAgentRun, EvaluationFileTool, EvaluationSkillTool,
    ExternalA2AExecutionBinding, FileToolDescription, KnowledgeSearchBinding, MCPExecutionBinding, ModelBindings, ParallelExecutorBinding,
    PreparedAgentRun, PreparedConversationHistory, PreparedConversationScope, PreparedEvaluationRun, PreparedHistoryCheckpoint, RunAttachment, RunHistoryMessage, RunInput, RunModelBinding, RunModelOverrides,
    SkillDerivedMCPBinding, SkillExecutionBinding, ToolBinding, ToolCallerContext,
)
from contracts.constants import environment
from contracts.errors.exceptions import ForbiddenError
from infrastructure.a2a_execution import external_agent_execution_revision
from infrastructure.agent_attachments import _build_internal_s3_url, validate_attachment_references
from infrastructure.agent_model_config import create_model_config_from_record, model_record_revision
from infrastructure.agent_model_overrides import get_provider_body_patch, merge_provider_body, provider_body_revision
from infrastructure.agent_tool_config import (
    PLAN_TOOL_NAMES, build_parallel_executor_tool_config, build_plan_tool_configs,
)
from infrastructure.langchain_plugins import (
    discover_langchain_plugin_refs, read_bound_langchain_tools, read_skill_derived_langchain_tools,
)
from infrastructure.local_tool_execution import LOCAL_SDK_TOOL_CLASSES
from infrastructure.mcp_execution import build_mcp_tool, mcp_binding_identity, mcp_execution_revision, select_mcp_server
from infrastructure.rdb.local_tool_records import read_bound_local_tools, read_skill_derived_local_tools
from infrastructure.rdb.mcp_execution_records import (
    read_bound_mcp_tools, read_mcp_execution_servers, read_skill_derived_mcp_tools,
)
from infrastructure.rdb.model_records import get_model_records
from infrastructure.rdb.skill_execution_records import read_bound_skills
from infrastructure.skill_execution import capture_skill_files, skill_execution_revision, validate_skill_context
from management.db.conversation.repository import get_conversation, get_historical_context
from management.services.agent.context import prepend_current_time
from management.services.configuration.user.memory import get_memory_switch
from management.services.agent.preparation.langchain_tool import export_langchain_tool
from management.services.agent.preparation.local_tool import export_local_tool
from nexent.core.agents.prompt.composer import EXECUTOR_CONTEXT_IDS
from nexent.core.concurrency import run_blocking
from nexent.multi_modal.utils import parse_s3_url


def _export_attachments(files):
    refs = []
    for file in (files or []):
        if not isinstance(file, dict) or not file.get("name") or not (url := _build_internal_s3_url(file)):
            continue
        bucket, key = parse_s3_url(url)
        refs.append(RunAttachment(
            name=file["name"], url=f"s3://{bucket}/{key}", presign=bool(file.get("presigned_url")),
        ))
    return refs


def build_evaluation_input(query, minio_files, history, user_id, tenant_id) -> RunInput:
    request = RunInput(
        query=query, attachment_refs=_export_attachments(minio_files),
        history=[
            RunHistoryMessage(role=item.role, content=item.content, attachment_refs=_export_attachments(item.minio_files))
            for item in (history or [])
        ],
    )
    urls = {file.url for file in request.attachment_refs}
    urls.update(file.url for message in request.history for file in message.attachment_refs)
    validate_attachment_references(list(urls), user_id, tenant_id)
    return request


async def prepare_evaluation_snapshot(request: EvaluationAgentRun, user_id: str, tenant_id: str):
    from management.services.agent.preparation.run import create_agent_run_info

    history = AgentRequest(
        agent_id=request.agent_id, query=request.query, history=request.history, is_debug=True,
    ).history
    return await create_agent_run_info(
        agent_id=request.agent_id, minio_files=None, query=request.query, history=history,
        tenant_id=tenant_id, user_id=user_id, allow_memory_search=False, is_debug=True,
        override_version_no=request.version_no, conversation_id=request.conversation_id,
        enable_automation_tool=False, export_evaluation=True,
    )


def _prepare_conversation_history(history, user_id, tenant_id) -> PreparedConversationHistory:
    summary = history.get("history_summary")
    checkpoint = None
    if summary is not None:
        checkpoint = PreparedHistoryCheckpoint.model_validate({
            name: summary[name] for name in PreparedHistoryCheckpoint.model_fields if name in summary
        })

    turns = []
    for turn in history["conversation_turns"]:
        attachments = turn.get("attachments")
        if isinstance(attachments, str):
            try:
                attachments = json.loads(attachments)
            except ValueError:
                attachments = None
        refs = _export_attachments(attachments if isinstance(attachments, list) else None)
        turns.append({key: value for key, value in turn.items() if key != "attachments"} | {"attachment_refs": refs})
    snapshot = PreparedConversationHistory(history_summary=checkpoint, conversation_turns=turns)
    urls = {ref.url for turn in snapshot.conversation_turns for ref in turn.attachment_refs}
    validate_attachment_references(list(urls), user_id, tenant_id)
    return snapshot


async def prepare_conversation_snapshot(
    request: AgentRequest, reference: AgentRunReference, user_id: str, tenant_id: str, *,
    language: str = "zh", timezone: str | None = None, current_user_message_id: int | None = None,
    before_message_index: int | None = None,
) -> PreparedAgentRun | None:
    """Compile an existing authorized conversation without constructing Runtime SDK objects."""
    from management.services.agent.preparation.run import create_agent_run_info
    from management.services.model.run_controls import preflight_agent_turn_controls, validate_agent_model_selection
    from management.db.agent.repository import search_agent_info_by_agent_id

    if request.conversation_id != reference.conversation_id:
        raise ForbiddenError("Conversation does not match the admitted run")
    conversation = await run_blocking(
        "snapshot-conversation-scope", get_conversation, reference.conversation_id,
        user_id=user_id, tenant_id=tenant_id, lane="control-io", owner="management",
    )
    if conversation is None:
        raise ForbiddenError("Conversation is not accessible to the current identity")
    if any((
        request.agent_id is None, request.is_debug, request.entrypoint,
        request.enable_automation_tool, request.generation_config, request.metadata is not None,
        request.clarification_response is not None, request.knowledge_scope is not None,
        conversation.get("workbench_config") is not None, conversation.get("knowledge_scope") is not None,
    )):
        return None
    if await run_blocking(
        "snapshot-memory-policy", get_memory_switch, user_id, lane="control-io", owner="management",
    ):
        return None

    validate_agent_model_selection(request, tenant_id, search_agent_info_by_agent_id)
    preflight_agent_turn_controls(request, tenant_id, search_agent_info_by_agent_id)
    historical_context = None
    if current_user_message_id is not None or before_message_index is not None:
        boundary = {"before_message_index": before_message_index} if before_message_index is not None else {}
        history = await run_blocking(
            "snapshot-conversation-history", get_historical_context,
            reference.conversation_id, current_user_message_id, user_id, tenant_id,
            lane="control-io", owner="management", **boundary,
        )
        if history is None:
            raise ForbiddenError("Conversation history boundary is not accessible")
        historical_context = _prepare_conversation_history(history, user_id, tenant_id)
    scope = PreparedConversationScope(
        **reference.model_dump(),
        historical_context=historical_context,
        runtime_metadata=conversation.get("runtime_metadata") or {},
        runtime_metadata_version=conversation.get("runtime_metadata_version") or 0,
    )
    return await create_agent_run_info(
        agent_id=request.agent_id, minio_files=request.minio_files,
        query=prepend_current_time(request.query, timezone, language=language), history=request.history,
        tenant_id=tenant_id, user_id=user_id, language=language, allow_memory_search=False,
        override_version_no=request.version_no, override_model_id=request.model_id,
        reasoning_effort=request.reasoning_effort, reasoning_budget_tokens=request.reasoning_budget_tokens,
        requested_output_tokens=request.requested_output_tokens, tool_params=request.tool_params,
        conversation_id=reference.conversation_id, context_policy=request.context_policy,
        enable_automation_tool=False, enable_planning=bool(request.enable_plan), prepared_conversation=scope,
    )


def _file_tool_binding(tool):
    builtin = next((item for item in EvaluationFileTool if item.value == tool.name), None)
    if builtin is None or tool.class_name != builtin.class_name or tool.source != "builtin":
        return None
    if (set(tool.params or {}) - {"workspace_path"}) or (set(tool.metadata or {}) - {
        "workspace_path", "minio_client", "user_id", "tenant_id", "run_id", "validate_url_access",
    }):
        return None
    return _builtin_binding(tool)


def _builtin_binding(tool):
    description = FileToolDescription(
        description=tool.description, description_zh=tool.description_zh,
        inputs=tool.inputs, output_type=tool.output_type,
    )
    return ToolBinding(tool_id=tool.name, version="1", parameters=description.model_dump(mode="json"))


def _export_analysis_binding(tool):
    builtin = EvaluationAnalysisTool(tool.name)
    if tool.class_name != builtin.class_name or tool.source != "local":
        raise ValueError("Unsupported analysis tool configuration")
    descriptor = AnalysisToolBinding.model_validate((tool.metadata or {}).get("prepared_analysis"))
    return ToolBinding(tool_id=tool.name, version="1", parameters=descriptor.model_dump(mode="json"))


def _export_parallel_executor_binding(tool):
    binding = ParallelExecutorBinding.model_validate(tool.params)
    if tool != build_parallel_executor_tool_config(binding.default_timeout_seconds):
        raise ValueError("Unsupported parallel executor configuration")
    return ToolBinding(tool_id="parallel_executor", version="1", parameters=binding.model_dump())


def _export_mcp_binding(tool, candidates, servers, agent, tenant_id, tool_servers):
    matching = [row for row in candidates if row["name"] == tool.name]
    if len(matching) != 1 or build_mcp_tool(matching[0]) != tool:
        raise ValueError("MCP tool differs from its persisted binding")
    row = matching[0]
    server_id, host = select_mcp_server(servers, tool.usage, tenant_id)
    origin_name = row["origin_name"] or tool.class_name
    target = (server_id, origin_name)
    if tool_servers.setdefault(tool.class_name, target) != target:
        raise ValueError("Ambiguous MCP callable")
    revision = mcp_execution_revision(
        tenant_id, agent.agent_id, agent.version_no, mcp_binding_identity(row), tool,
        origin_name, server_id, host,
    )
    common = {"tool_name": tool.name, "server_id": server_id, "revision": revision}
    if "skill_instance_ids" in row:
        reference = SkillDerivedMCPBinding(tool_id=row["tool_id"], **common)
        version = "2"
    else:
        reference = MCPExecutionBinding(instance_id=row["tool_instance_id"], **common)
        version = "1"
    return ToolBinding(tool_id="mcp", version=version, parameters=reference.model_dump(mode="json"))


def _export_skill_bindings(agent, tenant_id, context_items):
    tools = [tool for tool in agent.tools if tool.name in set(EvaluationSkillTool)]
    if not tools:
        validate_skill_context(context_items, [])
        return []
    if {tool.name for tool in tools} != set(EvaluationSkillTool) or len(tools) != len(EvaluationSkillTool):
        raise ValueError("Incomplete evaluation skill tools")

    rows = read_bound_skills(agent.agent_id, agent.version_no, tenant_id)
    configs = {row["name"]: row["config"] for row in rows}
    if not rows or len(configs) != len(rows):
        raise ValueError("Ambiguous evaluation skill bindings")
    validate_skill_context(context_items, rows)

    metadata = {"agent_id": agent.agent_id, "tenant_id": tenant_id, "version_no": agent.version_no}
    for tool in tools:
        builtin = EvaluationSkillTool(tool.name)
        expected = {"local_skills_dir": environment.CONTAINER_SKILLS_PATH}
        actual = dict(tool.params or {})
        if builtin is EvaluationSkillTool.SCRIPT:
            actual.pop("workspace_path", None)
            expected.update(isolated_skills_root=False, authorized_skill_names=sorted(configs))
        elif builtin is EvaluationSkillTool.GUIDE:
            expected["isolated_skills_root"] = False
        else:
            expected["config_overrides"] = configs
        if (tool.class_name != builtin.class_name or tool.source != "builtin" or tool.usage != "builtin"
                or tool.metadata != metadata or actual != expected):
            raise ValueError("Unsupported evaluation skill tool configuration")

    return [
        SkillExecutionBinding(
            instance_id=row["instance_id"],
            revision=skill_execution_revision(
                tenant_id, agent.agent_id, agent.version_no, row, capture_skill_files(tenant_id, row["name"]),
            ),
        )
        for row in rows
    ]


def _export_resource(agent, aliases, tenant_id, language, read_servers, tool_servers, *, allow_planning=False):
    if agent.pre_run_tool_events or agent.sandbox_policy is not None:
        raise ValueError("Unsupported prepared resource")
    plan_tools = [tool for tool in agent.tools if tool.name in PLAN_TOOL_NAMES]
    if plan_tools or agent.enable_planning:
        if not (allow_planning and agent.enable_planning and len(plan_tools) == len(PLAN_TOOL_NAMES)):
            raise ValueError("Unsupported prepared planning scope")
        expected = {tool.name: tool.class_name for tool in build_plan_tool_configs()}
        if set(expected) != {tool.name for tool in plan_tools} or any(
            tool.class_name != expected[tool.name] or tool.source != "builtin" or tool.params or tool.metadata
            for tool in plan_tools
        ):
            raise ValueError("Unsupported prepared planning tools")

    profile = agent.model_dump(mode="json", include=set(EvaluationAgentOptions.model_fields))
    context_items = profile.get("context_items")
    if context_items is not None:
        portable_items = [item for item in context_items if item["id"] not in EXECUTOR_CONTEXT_IDS]
        if len(portable_items) != len(context_items):
            profile.update(context_items=portable_items, render_executor_context=True)
    skill_refs = _export_skill_bindings(agent, tenant_id, profile.get("context_items"))
    tools = []
    mcp_names = [tool.name for tool in agent.tools if tool.source == "mcp"]
    candidates = read_bound_mcp_tools(agent.agent_id, agent.version_no, tenant_id, mcp_names) if mcp_names else []
    unresolved = sorted(set(mcp_names) - {row["name"] for row in candidates})
    authorized = {ref.instance_id for ref in skill_refs}
    if unresolved and authorized:
        candidates.extend(
            row for row in read_skill_derived_mcp_tools(agent.agent_id, agent.version_no, tenant_id, unresolved)
            if set(row["skill_instance_ids"]) <= authorized
        )
    mcp_servers = read_servers(tenant_id) if mcp_names else []
    local_names = [tool.name for tool in agent.tools if tool.source == "local" and tool.name in LOCAL_SDK_TOOL_CLASSES]
    local_scope = (agent.agent_id, agent.version_no, tenant_id)
    local_candidates = read_bound_local_tools(*local_scope, local_names) if local_names else []
    unresolved_local = sorted(set(local_names) - {row["name"] for row in local_candidates})
    if unresolved_local and authorized:
        local_candidates.extend(
            row for row in read_skill_derived_local_tools(*local_scope, unresolved_local)
            if set(row["skill_instance_ids"]) <= authorized
        )
    langchain_names = [tool.name for tool in agent.tools if tool.source == "langchain"]
    langchain_candidates = read_bound_langchain_tools(*local_scope, langchain_names) if langchain_names else []
    unresolved_langchain = sorted(set(langchain_names) - {row["name"] for row in langchain_candidates})
    if unresolved_langchain and authorized:
        langchain_candidates.extend(
            row for row in read_skill_derived_langchain_tools(*local_scope, unresolved_langchain)
            if set(row["skill_instance_ids"]) <= authorized
        )
    plugins = discover_langchain_plugin_refs(set(langchain_names)) if langchain_names else {}
    for tool in agent.tools:
        if tool.source == "mcp":
            binding = _export_mcp_binding(tool, candidates, mcp_servers, agent, tenant_id, tool_servers)
        elif tool.source == "langchain":
            binding = export_langchain_tool(tool, langchain_candidates, plugins, *local_scope)
        elif tool.name == "knowledge_base_search" and tool.class_name == "KnowledgeBaseSearchTool" and tool.source == "local":
            descriptor = KnowledgeSearchBinding.model_validate((tool.metadata or {}).get("prepared_knowledge_search"))
            binding = ToolBinding(tool_id=tool.name, version="1", parameters=descriptor.model_dump(mode="json"))
        elif tool.name in set(EvaluationAnalysisTool):
            binding = _export_analysis_binding(tool)
        elif tool.source == "local" and tool.name in LOCAL_SDK_TOOL_CLASSES:
            binding = export_local_tool(tool, local_candidates, agent.agent_id, agent.version_no, tenant_id, language)
        elif tool.name == "parallel_executor":
            binding = _export_parallel_executor_binding(tool)
        elif tool.name in PLAN_TOOL_NAMES:
            binding = ToolBinding(tool_id=tool.name, version="1")
        elif tool.name in set(EvaluationSkillTool):
            binding = _builtin_binding(tool)
        else:
            binding = _file_tool_binding(tool)
        if binding is None:
            raise ValueError("Unsupported evaluation tool")
        tools.append(binding)

    context_config = profile.get("context_manager_config")
    if context_config is not None:
        for key in ("history_summary_sink", "history_summary_status_sink"):
            if context_config.pop(key, None) is not None:
                raise ValueError("Unsupported evaluation callback")
    if any(item["type"] in {"memory", "long_term_memory"} for item in profile.get("context_items") or []):
        raise ValueError("Unsupported evaluation context")

    aliases.setdefault(agent.model_name, None)
    return AgentResource(
        agent_id=agent.agent_id, version_no=agent.version_no, name=agent.name,
        description=agent.description, prompt_templates=agent.prompt_templates or {},
        max_steps=agent.max_steps, tools=tools, skill_refs=skill_refs, model_alias=agent.model_name,
        invocation_name=agent.invocation_name, runtime_ref=agent.runtime_ref, origin=agent.origin,
        evaluation_options=EvaluationAgentOptions(**profile),
        subagents=[_export_resource(child, aliases, tenant_id, language, read_servers, tool_servers) for child in agent.worker_agents],
        external_a2a=[
            ExternalA2AExecutionBinding(
                agent_id=int(external.agent_id), invocation_name=external.invocation_name,
                revision=external_agent_execution_revision(external, tenant_id, agent.agent_id),
            )
            for external in agent.external_a2a_agents
        ],
    )


def _export_model(alias, models, tenant_id, resource, agent_model_overrides):
    candidates = get_model_records({"display_name": alias, "model_type": "llm"}, tenant_id)
    effective = [model for model in models if model.cite_name == alias]
    if len(candidates) != 1 or len(effective) != 1:
        raise ValueError("Evaluation requires an unambiguous model binding")
    record = candidates[0]
    selected = effective[0]
    base = create_model_config_from_record(record)
    changes = {
        name: getattr(selected, name) for name in RunModelOverrides.model_fields
        if getattr(selected, name) != getattr(base, name)
    }
    model_id = record["model_id"]
    body_revision = None
    if base.extra_body != selected.extra_body:
        patch = get_provider_body_patch(agent_model_overrides, model_id)
        if patch is None or merge_provider_body(base.extra_body, patch) != selected.extra_body:
            raise ValueError("Unsupported evaluation provider body")
        body_revision = provider_body_revision(
            (tenant_id, resource.agent_id, resource.version_no, model_id), selected.extra_body,
        )
    if base.model_copy(update={**changes, "extra_body": selected.extra_body}) != selected:
        raise ValueError("Unsupported evaluation model override")
    return RunModelBinding(
        model_id=model_id, alias=alias, revision=model_record_revision(record),
        overrides=RunModelOverrides(**changes) if changes else None, provider_body_revision=body_revision,
    )


def export_snapshot(
    agent, models, query, history, *, tenant_id, conversation_id, language, user_id=None, run_input=None,
    agent_model_overrides=None, prepared_conversation: PreparedConversationScope | None = None,
):
    from management.services.agent.tool_identity import resolve_tool_user_context

    try:
        aliases = {}
        resource = _export_resource(
            agent, aliases, tenant_id, language, cache(read_mcp_execution_servers), {},
            allow_planning=prepared_conversation is not None,
        )
        bindings = [
            _export_model(alias, models, tenant_id, resource, agent_model_overrides) for alias in aliases
        ]
        identity = resolve_tool_user_context(agent, user_id, tenant_id) if user_id is not None else None
        tool_caller = ToolCallerContext(**{
            key: identity[key] for key in ToolCallerContext.model_fields if key in identity
        }) if identity is not None else None
        fields = dict(
            mode="nexent", language=language, resource=resource, tool_caller=tool_caller,
            models=ModelBindings(llm=bindings[0], additional_llms=bindings[1:]),
            input=run_input or RunInput(
                query=query, history=[RunHistoryMessage(role=item.role, content=item.content) for item in (history or [])],
            ),
        )
        if prepared_conversation is not None:
            return PreparedAgentRun(**fields, **prepared_conversation.model_dump())
        return PreparedEvaluationRun(**fields, conversation_id=conversation_id)
    except (LookupError, OSError, TypeError, ValueError, PydanticSerializationError):
        return None
