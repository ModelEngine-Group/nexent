# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Resolve request configuration without loading the legacy execution facade."""

from contracts.agent import AgentRequest


def apply_workbench_runtime_plan(
    agent_request: AgentRequest, canonical_workbench, resolved_plan, tenant_id: str
) -> None:
    """Attach a validated Workbench plan to one in-memory run request."""
    from management.services.knowledge_base.scope import snapshot_runtime_knowledge_tree
    from management.services.agent.workbench import (
        attach_runtime_knowledge_tree,
        runtime_skill_snapshot,
    )

    knowledge_tree = snapshot_runtime_knowledge_tree(
        int(resolved_plan.root.identity.agent_id),
        tenant_id,
        int(resolved_plan.root.identity.version_no),
    )
    if canonical_workbench.knowledge_scope is not None:
        from management.services.knowledge_base.mount import mount_knowledge_records

        knowledge_tree = knowledge_tree[:1]
        knowledge_tree[0]["tools"] = mount_knowledge_records(
            knowledge_tree[0]["tools"], canonical_workbench.knowledge_scope, tenant_id
        )
        agent_request.__dict__["_runtime_knowledge_tools"] = knowledge_tree[0]["tools"]
    resolved_plan = attach_runtime_knowledge_tree(resolved_plan, knowledge_tree)
    root_identity = resolved_plan.root.identity
    agent_request.workbench = canonical_workbench
    agent_request.agent_id = root_identity.agent_id
    agent_request.version_no = root_identity.version_no
    if resolved_plan.overlay.model_id is not None:
        agent_request.model_id = resolved_plan.overlay.model_id
    if resolved_plan.overlay.requested_output_tokens is not None:
        agent_request.requested_output_tokens = (
            resolved_plan.overlay.requested_output_tokens
        )
    agent_request.knowledge_scope = canonical_workbench.knowledge_scope
    agent_request.__dict__["_runtime_skill_snapshot"] = runtime_skill_snapshot(
        resolved_plan
    )
    agent_request.__dict__["_runtime_mount_plan"] = resolved_plan
    agent_request.__dict__["_runtime_root_identity"] = {
        "agent_id": root_identity.agent_id,
        "version_no": root_identity.version_no,
        "runtime_ref": root_identity.runtime_ref,
        "invocation_name": root_identity.invocation_name,
        "display_name": root_identity.display_name,
        "origin": root_identity.origin,
    }
    agent_request.__dict__["_runtime_generation_config"] = (
        canonical_workbench.generation_config.model_dump(mode="json")
    )


def build_run_preparation_arguments(
    agent_request: AgentRequest, user_id: str, tenant_id: str, language: str, allow_memory_search: bool,
) -> dict:
    """Keep request configuration identical across local and exported preparation."""
    create_run_kwargs = {
        "agent_id": agent_request.agent_id,
        "minio_files": agent_request.minio_files,
        "query": agent_request.query,
        "history": agent_request.history,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "language": language,
        "allow_memory_search": allow_memory_search,
        "is_debug": agent_request.is_debug,
        "override_version_no": agent_request.version_no,
        "override_model_id": agent_request.model_id,
        "reasoning_effort": agent_request.reasoning_effort,
        "reasoning_budget_tokens": agent_request.reasoning_budget_tokens,
        "requested_output_tokens": agent_request.requested_output_tokens,
        "tool_params": agent_request.tool_params,
        "conversation_id": agent_request.conversation_id,
        "context_policy": agent_request.context_policy,
        "enable_planning": agent_request.enable_plan,
    }
    runtime_knowledge_context = getattr(
        agent_request, "_runtime_knowledge_context", None
    )
    if isinstance(runtime_knowledge_context, dict):
        create_run_kwargs["runtime_knowledge_context"] = runtime_knowledge_context
    runtime_skill_snapshot = getattr(agent_request, "_runtime_skill_snapshot", None)
    runtime_knowledge_tools = getattr(agent_request, "_runtime_knowledge_tools", None)
    if runtime_knowledge_tools is not None:
        create_run_kwargs["runtime_knowledge_tools"] = runtime_knowledge_tools
    if runtime_skill_snapshot is not None:
        create_run_kwargs["runtime_skill_snapshot"] = runtime_skill_snapshot
    runtime_generation_config = getattr(
        agent_request, "_runtime_generation_config", None
    )
    if (
        runtime_generation_config is None
        and agent_request.generation_config is not None
    ):
        runtime_generation_config = agent_request.generation_config.model_dump(
            mode="json", exclude_unset=True
        )
    if runtime_generation_config is not None:
        create_run_kwargs["runtime_generation_config"] = runtime_generation_config
    runtime_mount_plan = getattr(agent_request, "_runtime_mount_plan", None)
    if runtime_mount_plan is not None:
        create_run_kwargs["runtime_sub_agent_mounts"] = [
            {
                "agent_id": child.agent_id,
                "version_no": child.version_no,
                "runtime_ref": child.runtime_ref,
                "invocation_name": child.invocation_name,
                "display_name": child.display_name,
            }
            for child in runtime_mount_plan.child_mounts
        ]
    if not agent_request.enable_automation_tool:
        create_run_kwargs["enable_automation_tool"] = False
    return create_run_kwargs

