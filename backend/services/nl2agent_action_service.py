"""Unified, idempotent business-action dispatcher for NL2AGENT sessions."""

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict

from consts.exceptions import (
    ForbiddenError,
    Nl2AgentOperationError,
    Nl2AgentValidationError,
    Nl2AgentWorkflowConflictError,
)
from consts.model import Nl2AgentActionContext, Nl2AgentActionRequest
from utils.nl2agent_observability import record_action, record_cas_conflict


@dataclass(frozen=True)
class Nl2AgentActionDependencies:
    """Authorized persistence and domain operations used by the dispatcher."""

    get_session: Callable[..., Dict[str, Any] | None]
    get_action_message: Callable[..., Dict[str, Any] | None]
    claim_action_message: Callable[..., tuple[Dict[str, Any], bool]]
    update_action_message: Callable[..., bool]
    summarize_workflow_state: Callable[[Dict[str, Any]], Dict[str, Any]]
    get_session_catalogs: Callable[[str, int], Dict[str, Any]]
    confirm_requirements: Callable[..., Dict[str, Any]]
    save_model_selection: Callable[..., Awaitable[Dict[str, Any]]]
    apply_local_resources: Callable[..., Awaitable[Dict[str, Any]]]
    skip_local_resources: Callable[..., Awaitable[Dict[str, Any]]]
    install_mcp: Callable[..., Awaitable[Dict[str, Any]]]
    bind_mcp_tools: Callable[..., Awaitable[Dict[str, Any]]]
    skip_mcp_tools: Callable[..., Awaitable[Dict[str, Any]]]
    install_web_skill: Callable[..., Awaitable[Dict[str, Any]]]
    complete_online_configuration: Callable[..., Awaitable[Dict[str, Any]]]
    save_identity: Callable[..., Awaitable[Dict[str, Any]]]
    finalize: Callable[..., Awaitable[Dict[str, Any]]]


_WORKFLOW_ACTIONS = {
    "save_model_selection": "select_models",
    "apply_local_resources": "apply_local_resources",
    "skip_local_resources": "skip_local_resources",
    "install_mcp": "configure_online_resources",
    "bind_mcp_tools": "configure_online_resources",
    "skip_mcp_tools": "configure_online_resources",
    "install_web_skill": "configure_online_resources",
    "complete_online_configuration": "complete_online_configuration",
    "save_identity": "save_identity",
    "finalize": "publish_agent",
}


def _fingerprint_action(request: Nl2AgentActionRequest) -> str:
    payload = request.model_dump(mode="json", exclude={"action_id"})
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _action_response(
    request: Nl2AgentActionRequest,
    *,
    status: str,
    workflow_revision: int,
    result: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "action_id": request.action_id,
        "action": request.action,
        "status": status,
        "workflow_revision": int(workflow_revision),
        "result": result or {},
    }


def _existing_action_response(
    request: Nl2AgentActionRequest,
    existing: Dict[str, Any],
    fingerprint: str,
) -> Dict[str, Any] | None:
    metadata = existing.get("message_metadata") or {}
    if metadata.get("action_fingerprint") != fingerprint:
        raise Nl2AgentWorkflowConflictError(
            "The action_id is already bound to a different NL2AGENT action."
        )
    status = metadata.get("action_status")
    if status == "applied":
        return _action_response(
            request,
            status="replayed",
            workflow_revision=int(metadata.get("workflow_revision") or 0),
            result=dict(metadata.get("action_result") or {}),
        )
    if status == "pending":
        return _action_response(
            request,
            status="pending",
            workflow_revision=int(
                metadata.get("workflow_revision")
                or metadata.get("expected_revision")
                or 0
            ),
        )
    return None


def _validate_stage(
    request: Nl2AgentActionRequest,
    workflow_state: Dict[str, Any],
    summary: Dict[str, Any],
) -> None:
    if request.action == "confirm_requirements":
        if not (
            {"render_requirements_summary", "confirm_requirements"}
            & set(summary.get("allowed_actions") or [])
        ):
            raise Nl2AgentWorkflowConflictError(
                "Requirements cannot be confirmed during the current workflow stage."
            )
        return
    required = _WORKFLOW_ACTIONS[request.action]
    if required not in set(summary.get("allowed_actions") or []):
        raise Nl2AgentWorkflowConflictError(
            f"Action '{request.action}' is not allowed during stage "
            f"'{summary.get('current_stage')}'."
        )
    _validate_recommendation_proof(request, workflow_state)


def _validate_recommendation_proof(
    request: Nl2AgentActionRequest,
    workflow_state: Dict[str, Any],
) -> None:
    payload = request.payload
    recommendations = workflow_state.get("recommendations") or {}
    if request.action in {"apply_local_resources", "skip_local_resources"}:
        batch = recommendations.get(payload.recommendation_batch_id) or {}
        if batch.get("resource_type") != "local":
            raise Nl2AgentWorkflowConflictError(
                "The local recommendation batch is not part of this session."
            )
    elif request.action == "install_mcp":
        batch = recommendations.get(payload.recommendation_batch_id) or {}
        if batch.get("resource_type") != "mcp" or payload.recommendation_id not in set(
            batch.get("item_keys") or []
        ):
            raise Nl2AgentWorkflowConflictError(
                "The MCP recommendation is not part of this session batch."
            )
    elif request.action == "install_web_skill":
        batch = recommendations.get(payload.recommendation_batch_id) or {}
        if batch.get("resource_type") != "skill" or payload.item_key not in set(
            batch.get("item_keys") or []
        ):
            raise Nl2AgentWorkflowConflictError(
                "The Skill recommendation is not part of this session batch."
            )
    elif request.action in {"bind_mcp_tools", "skip_mcp_tools"}:
        workflow = (workflow_state.get("mcp_workflows") or {}).get(
            payload.recommendation_id
        ) or {}
        if not isinstance(workflow.get("mcp_id"), int):
            raise Nl2AgentWorkflowConflictError(
                "The installed MCP workflow is not part of this session."
            )


def _skill_key(item: Dict[str, Any]) -> str | None:
    skill_id = item.get("skill_id")
    if isinstance(skill_id, int) and not isinstance(skill_id, bool) and skill_id > 0:
        return f"skill:{skill_id}"
    name = str(item.get("skill_name") or item.get("name") or "").strip()
    if not name:
        return None
    normalized = unicodedata.normalize("NFKC", name).casefold()
    return f"skill-name:{normalized}"


def _resolve_skill(
    dependencies: Nl2AgentActionDependencies,
    *,
    tenant_id: str,
    draft_agent_id: int,
    item_key: str,
) -> Dict[str, Any]:
    catalogs = dependencies.get_session_catalogs(tenant_id, draft_agent_id)
    for item in catalogs.get("official_skills", []):
        if _skill_key(item) == item_key:
            return item
    raise Nl2AgentValidationError(
        "The requested Skill is not available in this NL2AGENT session."
    )


def _mcp_id(workflow_state: Dict[str, Any], recommendation_id: str) -> int:
    workflow = (workflow_state.get("mcp_workflows") or {}).get(recommendation_id) or {}
    mcp_id = workflow.get("mcp_id")
    if not isinstance(mcp_id, int) or isinstance(mcp_id, bool) or mcp_id <= 0:
        raise Nl2AgentWorkflowConflictError("The installed MCP could not be resolved.")
    return mcp_id


async def _execute_action(
    dependencies: Nl2AgentActionDependencies,
    request: Nl2AgentActionRequest,
    *,
    draft_agent_id: int,
    tenant_id: str,
    user_id: str,
    locale: str,
    workflow_state: Dict[str, Any],
) -> Dict[str, Any]:
    payload = request.payload
    if request.action == "confirm_requirements":
        review = dependencies.confirm_requirements(
            tenant_id,
            draft_agent_id,
            payload.summary.model_dump(mode="json"),
        )
        return {"agent_id": draft_agent_id, **review}
    if request.action == "save_model_selection":
        return await dependencies.save_model_selection(
            agent_id=draft_agent_id,
            primary_model_id=payload.primary_model_id,
            fallback_model_ids=payload.fallback_model_ids,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    if request.action == "apply_local_resources":
        return await dependencies.apply_local_resources(
            agent_id=draft_agent_id,
            recommendation_batch_id=payload.recommendation_batch_id,
            tool_ids=payload.tool_ids,
            skill_ids=payload.skill_ids,
            tool_config_values=payload.tool_config_values,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    if request.action == "skip_local_resources":
        return await dependencies.skip_local_resources(
            draft_agent_id,
            payload.recommendation_batch_id,
            tenant_id,
            user_id,
        )
    if request.action == "install_mcp":
        return await dependencies.install_mcp(
            agent_id=draft_agent_id,
            recommendation_id=payload.recommendation_id,
            option_id=payload.option_id,
            config_values=payload.config_values,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    if request.action == "bind_mcp_tools":
        return await dependencies.bind_mcp_tools(
            agent_id=draft_agent_id,
            mcp_id=_mcp_id(workflow_state, payload.recommendation_id),
            tool_ids=payload.tool_ids,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    if request.action == "skip_mcp_tools":
        return await dependencies.skip_mcp_tools(
            draft_agent_id,
            _mcp_id(workflow_state, payload.recommendation_id),
            tenant_id,
            user_id,
        )
    if request.action == "install_web_skill":
        skill = _resolve_skill(
            dependencies,
            tenant_id=tenant_id,
            draft_agent_id=draft_agent_id,
            item_key=payload.item_key,
        )
        return await dependencies.install_web_skill(
            agent_id=draft_agent_id,
            skill_id=skill.get("skill_id"),
            skill_name=skill.get("skill_name") or skill.get("name"),
            tenant_id=tenant_id,
            user_id=user_id,
            locale=locale,
            config_values=payload.config_values,
        )
    if request.action == "complete_online_configuration":
        return await dependencies.complete_online_configuration(
            draft_agent_id,
            tenant_id,
            user_id,
        )
    if request.action == "save_identity":
        return await dependencies.save_identity(
            draft_agent_id,
            payload.display_name,
            tenant_id,
            user_id,
        )
    if request.action == "finalize":
        return await dependencies.finalize(
            agent_id=draft_agent_id,
            user_id=user_id,
            tenant_id=tenant_id,
            **payload.model_dump(mode="json"),
        )
    raise Nl2AgentValidationError("Unsupported NL2AGENT action.")


async def _dispatch_nl2agent_action(
    dependencies: Nl2AgentActionDependencies,
    *,
    draft_agent_id: int,
    request: Nl2AgentActionRequest,
    tenant_id: str,
    user_id: str,
    locale: str,
) -> Dict[str, Any]:
    """Authorize, deduplicate, execute, and persist one business action."""
    session = dependencies.get_session(tenant_id, draft_agent_id, user_id=user_id)
    if session is None:
        raise ForbiddenError("NL2AGENT draft is not accessible to this identity.")

    conversation_id = int(session["conversation_id"])
    fingerprint = _fingerprint_action(request)
    existing = dependencies.get_action_message(
        conversation_id,
        str(request.action_id),
        user_id=user_id,
    )
    if existing:
        response = _existing_action_response(request, existing, fingerprint)
        if response is not None:
            return response
    if session.get("status") != "active":
        raise Nl2AgentWorkflowConflictError("NL2AGENT session is no longer active.")

    current_revision = int(session.get("workflow_revision") or 0)
    if current_revision != request.expected_revision:
        record_cas_conflict("action")
        raise Nl2AgentWorkflowConflictError(
            "The NL2AGENT workflow revision changed before this action was applied."
        )
    workflow_state = dict(session.get("workflow_state") or {})
    summary = dependencies.summarize_workflow_state(workflow_state)
    _validate_stage(request, workflow_state, summary)

    claimed_message, claimed = dependencies.claim_action_message(
        conversation_id=conversation_id,
        action_id=str(request.action_id),
        action=request.action,
        fingerprint=fingerprint,
        expected_revision=request.expected_revision,
        display_text=request.display_text,
        user_id=user_id,
    )
    if not claimed:
        response = _existing_action_response(request, claimed_message, fingerprint)
        if response is not None:
            return response
        raise Nl2AgentWorkflowConflictError(
            "The NL2AGENT action could not be claimed for execution."
        )

    try:
        result = await _execute_action(
            dependencies,
            request,
            draft_agent_id=draft_agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            locale=locale,
            workflow_state=workflow_state,
        )
        public_result = dict(result or {})
        updated_session = dependencies.get_session(
            tenant_id,
            draft_agent_id,
            user_id=user_id,
        )
        workflow_revision = int(
            (updated_session or {}).get("workflow_revision", request.expected_revision)
        )
        if not dependencies.update_action_message(
            conversation_id=conversation_id,
            action_id=str(request.action_id),
            user_id=user_id,
            action_status="applied",
            workflow_revision=workflow_revision,
            result=public_result,
        ):
            raise Nl2AgentOperationError(
                "NL2AGENT action completed but its durable receipt could not be updated."
            )
        return _action_response(
            request,
            status="applied",
            workflow_revision=workflow_revision,
            result=public_result,
        )
    except Exception as exc:
        latest = dependencies.get_session(tenant_id, draft_agent_id, user_id=user_id)
        dependencies.update_action_message(
            conversation_id=conversation_id,
            action_id=str(request.action_id),
            user_id=user_id,
            action_status="failed",
            workflow_revision=int(
                (latest or {}).get("workflow_revision", request.expected_revision)
            ),
            error_code=type(exc).__name__,
        )
        raise


async def dispatch_nl2agent_action(
    dependencies: Nl2AgentActionDependencies,
    *,
    draft_agent_id: int,
    request: Nl2AgentActionRequest,
    tenant_id: str,
    user_id: str,
    locale: str,
) -> Dict[str, Any]:
    """Dispatch one action and record a bounded, secret-free outcome."""
    try:
        response = await _dispatch_nl2agent_action(
            dependencies,
            draft_agent_id=draft_agent_id,
            request=request,
            tenant_id=tenant_id,
            user_id=user_id,
            locale=locale,
        )
    except Nl2AgentWorkflowConflictError:
        record_action(request.action, "conflict")
        raise
    except Exception:
        record_action(request.action, "failure")
        raise
    outcome = {
        "applied": "success",
        "replayed": "replayed",
        "pending": "pending",
    }.get(str(response.get("status")), "failure")
    record_action(request.action, outcome)
    return response


def validate_nl2agent_action_context(
    *,
    get_session: Callable[..., Dict[str, Any] | None],
    get_action_message: Callable[..., Dict[str, Any] | None],
    context: Nl2AgentActionContext,
    draft_agent_id: int,
    conversation_id: int,
    tenant_id: str,
    user_id: str,
) -> str:
    """Validate the next-turn context against the durable action receipt."""
    session = get_session(tenant_id, draft_agent_id, user_id=user_id)
    if session is None or int(session.get("conversation_id") or 0) != conversation_id:
        raise ForbiddenError("NL2AGENT action context is not accessible.")
    message = get_action_message(
        conversation_id,
        str(context.action_id),
        user_id=user_id,
    )
    metadata = (message or {}).get("message_metadata") or {}
    if (
        not message
        or metadata.get("action") != context.action
        or metadata.get("action_status") != "applied"
        or int(metadata.get("workflow_revision") or -1) != context.workflow_revision
        or str(message.get("message_content") or "").strip()
        != context.display_text.strip()
    ):
        raise Nl2AgentWorkflowConflictError(
            "NL2AGENT action context does not match an applied session action."
        )
    return json.dumps(
        {
            "type": "nl2agent_action_context",
            "action": context.action,
            "workflow_revision": context.workflow_revision,
            "instruction": "Continue from the authoritative NL2AGENT workflow state.",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
