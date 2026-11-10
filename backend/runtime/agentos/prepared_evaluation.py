# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Materialize AgentOS snapshots and execute synthetic evaluations inside Runtime."""

import asyncio
import logging
import shutil
from contextlib import ExitStack
from functools import partial
from hmac import compare_digest
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from contracts.agentos import (
    AgentRunReference, EvaluationAgentResult, EvaluationAnalysisTool, EvaluationFileTool, FileToolDescription,
    ParallelExecutorBinding, PreparedAgentRun, PreparedEphemeralRun, PreparedEvaluationRun, WorkbenchSkillLookup,
)
from contracts.constants.environment import (
    AGENT_WORKSPACE_ROOT, MCP_REQUEST_TIMEOUT_SECONDS, NEXENT_TOOL_FASTPATH_ALLOWED_TOOLS,
    NEXENT_TOOL_FASTPATH_ENABLED, RUNTIME_MCP_CLOSE_TIMEOUT_SECONDS, RUNTIME_MCP_TOOL_TIMEOUT_SECONDS,
)
from contracts.errors.exceptions import RunModelControlsError, ValidationError as AgentValidationError
from infrastructure.a2a_execution import (
    build_external_agent_config, external_agent_execution_revision, extract_url_from_card,
)
from infrastructure.agent_attachments import validate_attachment_references
from infrastructure.agent_model_config import (
    create_model_config_from_record, create_tenant_default_model_config, model_record_revision, normalize_model_revision,
)
from infrastructure.agent_model_overrides import (
    apply_turn_model_generation, get_provider_body_patch, merge_provider_body, overlay_root_model, provider_body_revision,
)
from infrastructure.agent_tool_config import (
    PLAN_TOOL_NAMES, build_parallel_executor_tool_config, build_plan_tool_configs,
)
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.object_storage.read_access import require_s3_read_access
from infrastructure.rdb.a2a_execution_records import read_external_agent_bindings
from infrastructure.rdb.agent_model_overrides import read_agent_model_overrides
from infrastructure.rdb.model_records import get_model_by_model_id
from infrastructure.rdb.workbench_skill_records import read_workbench_derived_tools
from infrastructure.redis.client import get_redis_client
from infrastructure.workspace_paths import create_run_workspace
from nexent.core.agents.agent_model import AgentConfig, AgentRunInfo, ToolConfig
from nexent.core.agents.context import ContextManagerConfig
from nexent.core.agents.context_input import build_authorized_context_input
from nexent.core.agents.nexent_agent import get_local_python_authorized_imports
from nexent.core.agents.prompt import AgentPromptBundle, AgentPromptComposer
from nexent.core.agents.prompt.composer import EXECUTOR_CONTEXT_IDS
from nexent.core.agents.sandbox import SandboxLevel
from nexent.core.concurrency import run_blocking
from runtime.adapters.nexent.factory import materialize_run
from runtime.adapters.nexent.runner import agent_run
from runtime.adapters.nexent.sandbox import resolve_deployed_sandbox
from runtime.agentos.evaluation import collect_observer_output
from runtime.agentos.prepared_analysis import materialize_analysis_tools
from runtime.agentos.prepared_attachments import materialize_evaluation_input
from runtime.agentos.prepared_automation import materialize_automation_tool
from runtime.agentos.prepared_knowledge import materialize_knowledge_search
from runtime.agentos.prepared_langchain import materialize_langchain_tools
from runtime.agentos.prepared_local_tool import materialize_local_tools
from runtime.agentos.prepared_mcp import PreparedMCP
from runtime.agentos.prepared_memory import materialize_memory
from runtime.agentos.prepared_skills import materialize_skill_tools, skill_stage_path
from runtime.executions import AgentRunAlreadyActiveError, agent_run_manager
from runtime.thread_management import runtime_thread_manager, unregister_after_worker_exit


logger = logging.getLogger(__name__)


def _materialize_file_tools(bindings, actor, workspace_path, workspace_run_id):
    if not bindings:
        return []

    from infrastructure.object_storage.client import minio_client

    metadata = {
        "workspace_path": workspace_path,
        "minio_client": minio_client,
        "user_id": actor.user_id,
        "tenant_id": actor.tenant_id,
        "run_id": workspace_run_id,
        "validate_url_access": partial(require_s3_read_access, user_id=actor.user_id, tenant_id=actor.tenant_id),
    }
    tools = []
    seen = set()
    for binding in bindings:
        if binding.version != "1" or binding.credential_ref is not None or binding.tool_id in seen:
            raise ValueError("Unsupported file tool binding")
        builtin = EvaluationFileTool(binding.tool_id)
        description = FileToolDescription.model_validate(binding.parameters)
        tools.append(ToolConfig(
            class_name=builtin.class_name, name=builtin.value, source="builtin", usage="builtin",
            params={"workspace_path": workspace_path}, metadata=metadata,
            **description.model_dump(),
        ))
        seen.add(builtin.value)
    return tools


def _materialize_parallel_executor(bindings):
    if not bindings:
        return {}
    if len(bindings) != 1 or bindings[0].version != "1" or bindings[0].credential_ref is not None:
        raise ValueError("Unsupported parallel executor binding")
    config = ParallelExecutorBinding.model_validate(bindings[0].parameters)
    return {"parallel_executor": build_parallel_executor_tool_config(config.default_timeout_seconds)}


def _agent_options(resource, language, sandbox_enabled):
    if resource.evaluation_options is None:
        return {}
    options = resource.evaluation_options.model_dump()
    if options.pop("render_executor_context"):
        items = options.get("context_items") or []
        if any(item.get("id") in EXECUTOR_CONTEXT_IDS for item in items):
            raise ValueError("Executor context must be rendered by Runtime")
        role = "manager" if resource.subagents or resource.external_a2a else "managed"
        composer = AgentPromptComposer(AgentPromptBundle.from_resource(role=role, language=language))
        context = composer.executor_context_item(
            sandbox_workspace_enabled=sandbox_enabled,
            restricted_python_authorized_imports=None if sandbox_enabled else get_local_python_authorized_imports(),
        )
        if context is not None:
            options["context_items"] = [*items, context]
    context_config = options.pop("context_manager_config")
    if context_config is not None:
        if "history_summary_sink" in context_config or "history_summary_status_sink" in context_config:
            raise ValueError("Callbacks must be constructed by Runtime")
        options["context_manager_config"] = ContextManagerConfig(**context_config)
    if options.get("verification_config") is None:
        del options["verification_config"]
    return options


def _materialize_external_agents(resource, actor):
    bindings = resource.external_a2a
    if not bindings:
        return []
    ids = [binding.agent_id for binding in bindings]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate external A2A execution binding")
    rows = read_external_agent_bindings(resource.agent_id, actor.tenant_id, ids)
    agents = []
    for binding in bindings:
        row = rows.get(binding.agent_id)
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "AGENTOS_EXTERNAL_AGENT_NOT_FOUND"})
        try:
            url = row.get("agent_url") or extract_url_from_card(row.get("raw_card"))
            if not url:
                raise ValueError("Missing external A2A endpoint")
            config = build_external_agent_config(row, url).model_copy(update={"invocation_name": binding.invocation_name})
            revision = external_agent_execution_revision(config, actor.tenant_id, resource.agent_id)
        except (AttributeError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_EXTERNAL_AGENT_REVISION_MISMATCH"}) from exc
        if not compare_digest(revision, binding.revision):
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_EXTERNAL_AGENT_REVISION_MISMATCH"})
        agents.append(config)
    return agents


def _materialize_agent(
    resource, actor, workspace_path, workspace_run_id, model_aliases, used_aliases, mcp,
    *, language, sandbox_enabled, root_alias=None, publish_skill_artifacts=False, public_reference=None,
    root_only_alias=None, allow_scoped_aidp=False, native_knowledge=False, memory_conversation_id=None,
    workbench_version=None, allow_debug_planning=False,
):
    if any((
        resource.mcp_server_refs, resource.knowledge_base_refs,
        resource.memory_ref is not None, resource.sandbox_policy is not None,
    )):
        raise ValueError("Unsupported evaluation resource")
    if root_alias is not None and resource.model_alias not in (None, root_alias):
        raise ValueError("Evaluation root model binding mismatch")
    alias = resource.model_alias or root_alias
    if root_alias is None and root_only_alias is not None and alias == root_only_alias:
        raise ValueError("Workbench root model cannot be used by a child Agent")
    if alias not in model_aliases:
        raise ValueError("Missing evaluation model binding")
    used_aliases.add(alias)
    plan_bindings = [binding for binding in resource.tools if binding.tool_id in PLAN_TOOL_NAMES]
    if plan_bindings and (
        (public_reference is None and not allow_debug_planning) or len(plan_bindings) != len(PLAN_TOOL_NAMES)
        or {binding.tool_id for binding in plan_bindings} != PLAN_TOOL_NAMES
        or any(binding.version != "1" or binding.parameters or binding.credential_ref is not None
               for binding in plan_bindings)
    ):
        raise ValueError("Unsupported prepared planning bindings")

    local_tools, mounted_skills = materialize_skill_tools(
        resource, actor, workspace_path, publish_artifacts=publish_skill_artifacts,
        public_reference=public_reference, workbench_version=workbench_version,
    )
    try:
        mounted_tools = read_workbench_derived_tools(
            resource.agent_id, resource.version_no, actor.tenant_id, mounted_skills,
        ) if mounted_skills else []
    except AgentValidationError as exc:
        raise HTTPException(status_code=409, detail={"code": "AGENTOS_SKILL_TOOL_REVISION_MISMATCH"}) from exc
    local_tools.update(materialize_automation_tool(resource, actor, public_reference))
    memory_tools, pre_run_tool_events = materialize_memory(resource, actor, memory_conversation_id)
    local_tools.update(memory_tools)
    if plan_bindings:
        local_tools.update({tool.name: tool for tool in build_plan_tool_configs()})
    workbench_lookup = None
    if workbench_version is not None and public_reference is not None and mounted_tools:
        workbench_lookup = WorkbenchSkillLookup(
            conversation_id=public_reference.conversation_id, run_id=public_reference.run_id,
            agent_id=resource.agent_id, agent_version=resource.version_no, workbench_version=workbench_version,
        )
    local_tools.update(materialize_local_tools(
        resource, actor, language, allow_scoped_aidp=allow_scoped_aidp or native_knowledge,
        require_scoped_aidp_instance=native_knowledge,
        workbench_tools=mounted_tools, workbench_lookup=workbench_lookup,
    ))
    local_tools.update(_materialize_parallel_executor(
        [binding for binding in resource.tools if binding.tool_id == "parallel_executor"],
    ))
    local_tools.update(materialize_knowledge_search(
        [binding for binding in resource.tools if binding.tool_id == "knowledge_base_search"], actor,
    ))
    local_tools.update(materialize_analysis_tools(
        [binding for binding in resource.tools if binding.tool_id in set(EvaluationAnalysisTool)], actor,
    ))
    ordered_tools = {
        "mcp": iter(mcp.materialize(resource, workbench_tools=mounted_tools)),
        "langchain": iter(materialize_langchain_tools(resource, actor, workbench_tools=mounted_tools)),
    }
    files = iter(_materialize_file_tools(
        [binding for binding in resource.tools if binding.tool_id not in local_tools and binding.tool_id not in ordered_tools],
        actor, workspace_path, workspace_run_id,
    ))
    tools = [
        local_tools[binding.tool_id] if binding.tool_id in local_tools
        else next(ordered_tools.get(binding.tool_id, files))
        for binding in resource.tools
    ]
    options = _agent_options(resource, language, sandbox_enabled)
    legacy_root = root_alias is not None and resource.model_alias is None
    return AgentConfig(
        name=resource.name, description=resource.description, prompt_templates=resource.prompt_templates,
        agent_id=resource.agent_id, version_no=resource.version_no, tools=tools, model_name=alias,
        max_steps=resource.max_steps, origin=resource.origin, enable_planning=bool(plan_bindings),
        pre_run_tool_events=pre_run_tool_events,
        invocation_name=f"agent_{resource.agent_id}_v{resource.version_no}" if legacy_root else resource.invocation_name,
        runtime_ref=f"agent:{resource.agent_id}:v{resource.version_no}" if legacy_root else resource.runtime_ref,
        external_a2a_agents=_materialize_external_agents(resource, actor),
        worker_agents=[
            _materialize_agent(
                child, actor, workspace_path, workspace_run_id, model_aliases, used_aliases, mcp,
                language=language, sandbox_enabled=sandbox_enabled, publish_skill_artifacts=publish_skill_artifacts,
                root_only_alias=root_only_alias, native_knowledge=native_knowledge,
                memory_conversation_id=memory_conversation_id,
            )
            for child in resource.subagents
        ],
        **options,
    )


def _materialize_model(binding, actor, resource):
    record = get_model_by_model_id(binding.model_id, actor.tenant_id)
    if not record or record.get("tenant_id") != actor.tenant_id or record.get("delete_flag") != "N":
        raise HTTPException(status_code=404, detail={"code": "MODEL_NOT_FOUND"})
    if record.get("model_type") != "llm":
        raise HTTPException(status_code=422, detail={"code": "MODEL_OPERATION_UNSUPPORTED"})
    if model_record_revision(record) != normalize_model_revision(binding.revision):
        raise HTTPException(status_code=409, detail={"code": "MODEL_REVISION_MISMATCH"})

    profile = binding.tenant_default_profile
    if profile is not None:
        if binding.provider_body_revision is not None:
            raise HTTPException(status_code=422, detail={"code": "AGENTOS_RESOURCE_UNSUPPORTED"})
        model = create_tenant_default_model_config(record, binding.alias, include_logprobs=profile == "logprobs")
    else:
        model = create_model_config_from_record(record)
    updates = binding.overrides.model_dump(exclude_unset=True) if binding.overrides is not None else {}
    if binding.provider_body_revision is not None:
        scope = (actor.tenant_id, resource.agent_id, resource.version_no, binding.model_id)
        overrides = read_agent_model_overrides(resource.agent_id, resource.version_no, actor.tenant_id)
        patch = get_provider_body_patch(overrides, binding.model_id)
        body = merge_provider_body(model.extra_body, patch) if patch else model.extra_body
        if patch is None or not compare_digest(provider_body_revision(scope, body), binding.provider_body_revision):
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_MODEL_BODY_REVISION_MISMATCH"})
        updates["extra_body"] = body
    model = model.model_copy(update={"cite_name": binding.alias, **updates})
    try:
        if binding.turn_generation is not None:
            return apply_turn_model_generation(model, binding.turn_generation, binding.alias)
        if binding.root_generation is not None:
            return overlay_root_model(model, binding.root_generation.model_dump(), binding.alias)
    except RunModelControlsError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code}) from exc
    return model


def _remove_skill_files(workspace_path: str | None) -> None:
    if workspace_path is None:
        return
    stage = skill_stage_path(workspace_path)
    if stage is None:
        return
    try:
        shutil.rmtree(stage)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Could not remove staged evaluation skill files", exc_info=True)


def _restore_conversation_history(history, actor):
    if history is None:
        return None
    refs = {ref.url for turn in history.conversation_turns for ref in turn.attachment_refs}
    try:
        validate_attachment_references(list(refs), actor.user_id, actor.tenant_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"code": "AGENTOS_ATTACHMENT_FORBIDDEN"}) from exc

    return {
        "history_summary": history.history_summary.model_dump(exclude_none=True) if history.history_summary else None,
        "conversation_turns": [
            turn.model_dump(exclude={"attachment_refs"}) | {
                "attachments": [{"name": ref.name, "url": ref.url} for ref in turn.attachment_refs],
            }
            for turn in history.conversation_turns
        ],
    }


def prepare_run_snapshot(
    payload: PreparedEvaluationRun | PreparedAgentRun | PreparedEphemeralRun, actor: ServicePrincipal,
) -> AgentRunInfo:
    if any((
        payload.models.summary, payload.models.verifier, payload.models.embedding, payload.models.rerank,
    )):
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_RESOURCE_UNSUPPORTED"})

    workbench_version = payload.workbench_config_version if isinstance(payload, PreparedAgentRun) else None
    native_knowledge = isinstance(payload, PreparedAgentRun) and payload.native_knowledge is True
    root_generation = payload.models.llm.root_generation
    turn_generation = payload.models.llm.turn_generation
    debug = isinstance(payload, PreparedEphemeralRun) and payload.debug is True
    native_run = isinstance(payload, PreparedAgentRun) or debug
    if (
        (root_generation is not None) != (workbench_version is not None)
        or (native_knowledge and workbench_version is not None)
        or (turn_generation is not None and (workbench_version is not None or not native_run))
        or any(binding.root_generation is not None or binding.turn_generation is not None
               for binding in payload.models.additional_llms)
    ):
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_RESOURCE_UNSUPPORTED"})

    historical_context = (
        _restore_conversation_history(payload.historical_context, actor) if isinstance(payload, PreparedAgentRun) else None
    )
    query, history, files = materialize_evaluation_input(payload.input, actor, payload.language)
    mcp = PreparedMCP(actor)
    bindings = [payload.models.llm, *payload.models.additional_llms]
    aliases = {binding.alias for binding in bindings}
    workspace_run_id = payload.run_id if isinstance(payload, (PreparedAgentRun, PreparedEphemeralRun)) else uuid4().hex
    workspace_path = create_run_workspace(actor.user_id, workspace_run_id, workspace_root=AGENT_WORKSPACE_ROOT)
    with ExitStack() as cleanup:
        cleanup.callback(_remove_skill_files, workspace_path)
        try:
            sandbox_config = resolve_deployed_sandbox(None)
            sandbox_enabled = sandbox_config is not None and sandbox_config.level is not SandboxLevel.LOCAL
            if len(aliases) != len(bindings):
                raise ValueError("Duplicate evaluation model binding")
            used_aliases = set()
            agent_config = _materialize_agent(
                payload.resource, actor, workspace_path, workspace_run_id, aliases, used_aliases, mcp,
                language=payload.language, sandbox_enabled=sandbox_enabled, root_alias=payload.models.llm.alias,
                publish_skill_artifacts=isinstance(payload, (PreparedAgentRun, PreparedEphemeralRun)),
                root_only_alias=payload.models.llm.alias if root_generation is not None or turn_generation is not None else None,
                allow_scoped_aidp=workbench_version is not None, native_knowledge=native_knowledge,
                public_reference=AgentRunReference(
                    run_id=payload.run_id, conversation_id=payload.conversation_id,
                ) if isinstance(payload, PreparedAgentRun) else None,
                memory_conversation_id=payload.conversation_id if isinstance(payload, PreparedAgentRun) else None,
                workbench_version=workbench_version, allow_debug_planning=debug,
            )
            if used_aliases != aliases:
                raise ValueError("Unused evaluation model binding")
        except (ValidationError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail={"code": "AGENTOS_RESOURCE_UNSUPPORTED"}) from exc

        models = [_materialize_model(binding, actor, payload.resource) for binding in bindings]
        user_context = None
        if mcp.hosts or payload.tool_caller is not None:
            user_context = payload.tool_caller.model_dump() if payload.tool_caller is not None else {}
            user_context.update(user_id=actor.user_id, tenant_id=actor.tenant_id)
        info = materialize_run(
            sandbox_config=sandbox_config,
            workspace_root=AGENT_WORKSPACE_ROOT,
            mcp_host=list(mcp.hosts.values()) or None,
            mcp_request_timeout_seconds=MCP_REQUEST_TIMEOUT_SECONDS,
            mcp_tool_timeout_seconds=RUNTIME_MCP_TOOL_TIMEOUT_SECONDS,
            mcp_close_timeout_seconds=RUNTIME_MCP_CLOSE_TIMEOUT_SECONDS,
            user_context=user_context,
            query=query,
            history=history,
            minio_files=files or None,
            agent_config=agent_config,
            workspace_path=workspace_path,
            workspace_run_id=workspace_run_id,
            capacity_snapshot=agent_config.capacity_snapshot,
            context_budget_snapshot=agent_config.context_budget_snapshot,
            tool_fastpath_enabled=NEXENT_TOOL_FASTPATH_ENABLED,
            tool_fastpath_allowed_tools=list(NEXENT_TOOL_FASTPATH_ALLOWED_TOOLS),
            model_config_list=models,
            language=payload.language,
            conversation_id=None if isinstance(payload, PreparedEphemeralRun) else payload.conversation_id,
            user_id=actor.user_id,
            tenant_id=actor.tenant_id,
            redis_client=get_redis_client() if agent_config.enable_planning and not debug else None,
        )
        if isinstance(payload, (PreparedAgentRun, PreparedEphemeralRun)):
            info.runtime_metadata = payload.runtime_metadata
        if isinstance(payload, PreparedAgentRun):
            info.runtime_metadata_version = payload.runtime_metadata_version
        info.context_input = build_authorized_context_input(info, historical_context)
        cleanup.pop_all()
    return info


def prepare_evaluation_run(payload: PreparedEvaluationRun, actor: ServicePrincipal) -> AgentRunInfo:
    return prepare_run_snapshot(payload, actor)


def _remove_abandoned_skill_files(preparation: asyncio.Task) -> None:
    if not preparation.cancelled() and preparation.exception() is None:
        _remove_skill_files(preparation.result().workspace_path)


async def load_prepared_run(payload, actor, materialize) -> AgentRunInfo:
    preparation = asyncio.create_task(run_blocking(
        "agentos-materialize-run", materialize, payload, actor,
        lane="control-io", owner="runtime",
    ))
    try:
        return await asyncio.shield(preparation)
    except asyncio.CancelledError:
        preparation.add_done_callback(_remove_abandoned_skill_files)
        raise


def discard_prepared_workspace(info: AgentRunInfo) -> None:
    future = info.thread_future
    if future is not None and not future.done():
        future.add_done_callback(lambda _: _remove_skill_files(info.workspace_path))
    else:
        _remove_skill_files(info.workspace_path)


def release_prepared_run(info: AgentRunInfo, conversation_id: int, user_id: str, status: str) -> None:
    try:
        unregister_after_worker_exit(agent_run_manager, conversation_id, user_id, status, info)
    finally:
        discard_prepared_workspace(info)


async def execute_prepared_evaluation(payload: PreparedEvaluationRun, actor: ServicePrincipal) -> EvaluationAgentResult:
    info = await load_prepared_run(payload, actor, prepare_evaluation_run)
    try:
        agent_run_manager.register_agent_run(payload.conversation_id, info, actor.user_id)
    except Exception as exc:
        _remove_skill_files(info.workspace_path)
        if isinstance(exc, AgentRunAlreadyActiveError):
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_RUN_ALREADY_ACTIVE"}) from exc
        raise

    status = "failed"
    try:
        result = await collect_observer_output(info, agent_run, runtime_thread_manager)
        status = info.attempt_outcome or "completed"
        return result
    except asyncio.CancelledError:
        status = "stopped"
        raise
    finally:
        release_prepared_run(info, payload.conversation_id, actor.user_id, status)
