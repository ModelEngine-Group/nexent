"""NL2AGENT workflow transitions and recommendation proof handling."""

import hashlib
import json
import logging
import re
import unicodedata
import uuid
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from agents import nl2agent_session_store as _session_store

from agents.nl2agent_workflow import (
    CardDelivery,
    McpWorkflow,
    OnlineInstallation,
    RecommendationBatch,
    RequirementsReview,
    Nl2AgentWorkflowState,
    evaluate_workflow,
    state_to_dict,
)
from utils.nl2agent_catalog_snapshot import (
    mcp_recommendation_id,
)

logger = logging.getLogger(__name__)

_INSTALLATION_LOCK_TTL_SECONDS = 5 * 60
_REQUIREMENTS_FIELDS = (
    "goal",
    "audience_or_scenario",
    "primary_input",
    "expected_output",
    "key_constraints",
)
_REQUIREMENTS_STATUSES = {"collecting", "awaiting_confirmation", "confirmed"}
_CARD_DELIVERY_TYPES = {
    "requirements_summary",
    "model_selection",
    "local_resources",
    "web_mcp",
    "web_skill",
    "agent_identity",
    "final_review",
}


def _ordered_unique(values, transform=lambda value: value):
    result = []
    seen = set()
    for value in values:
        normalized = transform(value)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
_CARD_DELIVERY_STATUSES = {"rendered", "failed"}
_CARD_DELIVERY_FAILURE_REASONS = {
    "truncated_fence",
    "invalid_json",
    "invalid_schema",
    "missing_card",
}
_CONFIRMATION_PHRASES = {
    "确认",
    "确认需求",
    "需求正确",
    "没有问题",
    "没问题",
    "可以继续",
    "按此执行",
    "是",
    "对",
    "confirm",
    "confirm requirements",
    "confirmed",
    "looks good",
    "correct",
    "proceed",
    "yes",
}
_SHORT_CONFIRMATION_PHRASES = {"是", "对", "yes"}
_MODIFICATION_MARKERS = {
    "不确认",
    "不正确",
    "需要修改",
    "修改",
    "改成",
    "补充",
    "不是",
    "change",
    "modify",
    "incorrect",
    "not correct",
    "instead",
}
_NO_MODIFICATION_PHRASES = {
    "no change",
    "no changes",
    "nothing to change",
    "do not change",
    "don t change",
    "no modification",
    "no modifications",
    "无需修改",
    "不需要修改",
    "不用修改",
    "不必修改",
    "不要修改",
    "没有修改",
    "无修改",
}


Nl2AgentSessionCatalogError = _session_store.Nl2AgentSessionCatalogError
Nl2AgentStateConflictError = _session_store.Nl2AgentStateConflictError


_validate_identifiers = _session_store.validate_identifiers
initialize_nl2agent_session_state = _session_store.initialize_session_state
get_nl2agent_session_state = _session_store.get_session_state
_mutate_session_state = _session_store.mutate_session_state
get_nl2agent_session_catalogs = _session_store.get_session_catalogs


def summarize_workflow_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate a workflow snapshot without another database read."""
    parsed = _session_store.parse_session_state(
        json.dumps(state, ensure_ascii=False), "summary", int(state.get("conversation_id") or 1)
    )
    return evaluate_workflow(parsed).model_dump(mode="json")


def get_workflow_summary(
    tenant_id: Optional[str], draft_agent_id: Optional[int]
) -> Dict[str, Any]:
    state = get_nl2agent_session_state(tenant_id, draft_agent_id)
    return summarize_workflow_state(state)


def _ensure_workflow_action_allowed(summary: Dict[str, Any], action: str) -> None:
    """Validate one action against an already loaded workflow snapshot."""
    idempotent_registration_stages = {
        "render_requirements_summary": "requirements_confirmation",
        "search_local_resources": "local_resource_review",
        "search_online_resources": "online_resource_review",
    }
    if action not in summary["allowed_actions"] and summary["current_stage"] != (
        idempotent_registration_stages.get(action)
    ):
        raise Nl2AgentSessionCatalogError(
            f"Action '{action}' is not allowed during stage '{summary['current_stage']}'."
        )


def assert_workflow_action_allowed(
    tenant_id: Optional[str], draft_agent_id: Optional[int], action: str
) -> Dict[str, Any]:
    """Reject state mutations that do not belong to the current workflow stage."""
    summary = get_workflow_summary(tenant_id, draft_agent_id)
    _ensure_workflow_action_allowed(summary, action)
    return summary


def _finish_revision(
    state: Nl2AgentWorkflowState,
    *,
    invalidate_final_review: bool = True,
) -> None:
    """Leave edit routing and require a fresh final card after an action."""
    if not state.revision_mode:
        return
    state.revision_mode = False
    if invalidate_final_review:
        state.card_delivery.pop("final_review", None)


def enter_revision_mode(
    tenant_id: Optional[str], draft_agent_id: Optional[int]
) -> Dict[str, Any]:
    """Open edit routing for one active session at final review."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        summary = evaluate_workflow(state)
        if summary.current_stage == "revision_routing":
            return state_to_dict(state)
        if summary.current_stage != "final_review":
            raise Nl2AgentSessionCatalogError(
                "NL2AGENT editing can only start from final review."
            )
        state.revision_mode = True
        return state_to_dict(state)

    return _mutate_session_state(tenant, draft_id, mutate)


def _normalize_requirement_text(value: Any) -> str:
    """Normalize one persisted requirement field without changing its meaning."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
    return re.sub(r"\s+", " ", normalized)


def _requirements_fingerprint(summary: Dict[str, str]) -> str:
    payload = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def register_requirements_summary(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    """Register one rendered requirements summary for explicit card confirmation."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    normalized_summary = {
        field_name: _normalize_requirement_text(summary.get(field_name))
        for field_name in _REQUIREMENTS_FIELDS
    }
    missing_fields = [
        field_name
        for field_name, field_value in normalized_summary.items()
        if not field_value
    ]
    if missing_fields:
        raise Nl2AgentSessionCatalogError(
            "Requirements summary fields cannot be empty: " + ", ".join(missing_fields)
        )
    fingerprint = _requirements_fingerprint(normalized_summary)

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        review = state.requirements_review
        existing_fingerprint = review.fingerprint
        is_current = False
        if state.revision_mode:
            review = RequirementsReview(
                status="awaiting_confirmation",
                summary=normalized_summary,
                fingerprint=fingerprint,
            )
            state.requirements_review = review
            is_current = True
        elif not existing_fingerprint or (
            review.status == "collecting" and existing_fingerprint != fingerprint
        ):
            review = RequirementsReview(
                status="awaiting_confirmation",
                summary=normalized_summary,
                fingerprint=fingerprint,
            )
            state.requirements_review = review
            is_current = True
        elif existing_fingerprint == fingerprint and review.status != "collecting":
            is_current = True
        return {**review.model_dump(mode="json"), "is_current": is_current}

    return _mutate_session_state(tenant, draft_id, mutate)


def classify_requirements_message_intent(text: str) -> str:
    """Classify a pending-review message without confirming from chat text."""
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    normalized = re.sub(r"[^\w\u3400-\u4dbf\u4e00-\u9fff]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return "ambiguous"
    modification_text = normalized
    contains_no_modification = False
    for phrase in _NO_MODIFICATION_PHRASES:
        if phrase in modification_text:
            contains_no_modification = True
            modification_text = modification_text.replace(phrase, " ")
    if any(marker in modification_text for marker in _MODIFICATION_MARKERS):
        return "modify"
    if contains_no_modification:
        return "confirmation_requires_button"
    if normalized in _CONFIRMATION_PHRASES:
        return "confirmation_requires_button"
    if any(
        phrase in normalized
        for phrase in _CONFIRMATION_PHRASES - _SHORT_CONFIRMATION_PHRASES
    ):
        tokens = normalized.split()
        if len(tokens) <= 6:
            return "confirmation_requires_button"
    return "ambiguous"


def apply_requirements_revision_text(
    tenant_id: Optional[str], draft_agent_id: Optional[int], text: str
) -> Dict[str, Any]:
    """Apply only explicit revision intent to a pending requirements review."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    state = get_nl2agent_session_state(tenant, draft_id)
    review = state["requirements_review"]
    intent = (
        classify_requirements_message_intent(text)
        if review.get("status") == "awaiting_confirmation"
        else "not_applicable"
    )
    if intent != "modify":
        return {"intent": intent, **deepcopy(review)}

    def mutate(workflow: Nl2AgentWorkflowState) -> Dict[str, Any]:
        if workflow.requirements_review.status == "awaiting_confirmation":
            workflow.requirements_review.status = "collecting"
            workflow.card_delivery.pop("requirements_summary", None)
        return {
            "intent": intent,
            **workflow.requirements_review.model_dump(mode="json"),
        }

    return _mutate_session_state(tenant, draft_id, mutate)


def confirm_requirements_summary(
    tenant_id: Optional[str], draft_agent_id: Optional[int], fingerprint: str
) -> Dict[str, Any]:
    """Confirm the current requirements revision by its stable fingerprint."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        review = state.requirements_review
        if not fingerprint or review.fingerprint != fingerprint:
            raise Nl2AgentSessionCatalogError(
                "The requirements summary is stale. Reload the current summary before confirming."
            )
        if review.status == "awaiting_confirmation":
            review.status = "confirmed"
            _finish_revision(state)
        elif review.status != "confirmed":
            raise Nl2AgentSessionCatalogError(
                "The requirements summary is not awaiting confirmation."
            )
        return review.model_dump(mode="json")

    return _mutate_session_state(tenant, draft_id, mutate)


def assert_requirements_confirmed(
    tenant_id: str, draft_agent_id: int
) -> Dict[str, Any]:
    """Reject protected workflow actions until requirements are confirmed."""
    state = get_nl2agent_session_state(tenant_id, draft_agent_id)
    if state["requirements_review"].get("status") != "confirmed":
        raise Nl2AgentSessionCatalogError(
            "Confirm the requirements summary before continuing configuration."
        )
    return state


def set_model_selection_confirmed(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    confirmed: bool = True,
    *,
    finish_revision: bool = True,
    db_session=None,
) -> Dict[str, Any]:
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        state.model_selection_confirmed = bool(confirmed)
        if confirmed and finish_revision:
            _finish_revision(state)
        return {"model_selection_confirmed": state.model_selection_confirmed}

    return _mutate_session_state(tenant, draft_id, mutate, db_session=db_session)


def record_card_delivery(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    message_id: int,
    card_type: str,
    status: str,
    card_key: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist one final-message receipt without mutating business workflow state."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    if card_type not in _CARD_DELIVERY_TYPES:
        raise Nl2AgentSessionCatalogError("Invalid NL2AGENT card type.")
    if status not in _CARD_DELIVERY_STATUSES:
        raise Nl2AgentSessionCatalogError("Invalid NL2AGENT card delivery status.")
    if not isinstance(message_id, int) or message_id <= 0:
        raise Nl2AgentSessionCatalogError("message_id must be a positive integer.")
    if status == "failed" and reason not in _CARD_DELIVERY_FAILURE_REASONS:
        raise Nl2AgentSessionCatalogError("Invalid NL2AGENT card failure reason.")

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        existing = state.card_delivery.get(card_type)
        if (
            existing is not None
            and existing.message_id == message_id
            and existing.status == status
            and existing.card_key == card_key
        ):
            return existing.model_dump(mode="json")
        retry_count = (
            int(existing.retry_count) + 1
            if status == "failed" and existing is not None
            else int(status == "failed")
        )
        delivery = CardDelivery(
            message_id=message_id,
            card_type=card_type,
            status=status,
            card_key=card_key,
            reason=reason if status == "failed" else None,
            retry_count=retry_count,
        )
        state.card_delivery[card_type] = delivery
        if card_type == "final_review" and status == "rendered":
            _finish_revision(state, invalidate_final_review=False)
        return delivery.model_dump(mode="json")

    return _mutate_session_state(tenant, draft_id, mutate)


def confirm_agent_identity(
    tenant_id: Optional[str], draft_agent_id: Optional[int]
) -> Dict[str, Any]:
    """Record that the user explicitly saved the draft display name."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        state.identity_confirmed = True
        _finish_revision(state)
        return state_to_dict(state)

    return _mutate_session_state(tenant, draft_id, mutate)


def assert_identity_confirmed(tenant_id: str, draft_agent_id: int) -> None:
    """Reject finalization until the user explicitly saves the identity card."""
    state = get_nl2agent_session_state(tenant_id, draft_agent_id)
    if not state.get("identity_confirmed"):
        raise Nl2AgentSessionCatalogError(
            "Save the agent display name before finalizing."
        )


def update_mcp_workflow(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    recommendation_id: str,
    **values: Any,
) -> Dict[str, Any]:
    """Persist redacted MCP installation/binding state for a draft."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    allowed = {
        "option_id",
        "installation_key",
        "status",
        "mcp_id",
        "discovered_tool_ids",
        "bound_tool_ids",
        "binding_operation_id",
        "error",
    }

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        workflow = state.mcp_workflows.setdefault(
            recommendation_id, McpWorkflow(recommendation_id=recommendation_id)
        )
        updated = {
            **workflow.model_dump(mode="python"),
            **{key: deepcopy(value) for key, value in values.items() if key in allowed},
        }
        state.mcp_workflows[recommendation_id] = McpWorkflow.model_validate(updated)
        return state.mcp_workflows[recommendation_id].model_dump(mode="json")

    return _mutate_session_state(tenant, draft_id, mutate)


def find_mcp_workflow_by_id(
    tenant_id: str, draft_agent_id: int, mcp_id: int
) -> tuple[str, Dict[str, Any]]:
    state = get_nl2agent_session_state(tenant_id, draft_agent_id)
    for recommendation_id, workflow in state["mcp_workflows"].items():
        if workflow.get("mcp_id") == int(mcp_id):
            return recommendation_id, deepcopy(workflow)
    raise Nl2AgentSessionCatalogError("Installed MCP workflow was not found.")


def reserve_mcp_binding_operation(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    mcp_id: int,
    operation_id: str,
    tool_ids: List[int],
) -> Dict[str, Any]:
    """Reserve one connected MCP for exactly one bind or skip operation."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    selected_tool_ids = sorted(set(map(int, tool_ids or [])))

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        match = next(
            (
                workflow
                for workflow in state.mcp_workflows.values()
                if workflow.mcp_id == int(mcp_id)
            ),
            None,
        )
        if match is None:
            raise Nl2AgentSessionCatalogError("Installed MCP workflow was not found.")
        if not set(selected_tool_ids).issubset(set(match.discovered_tool_ids)):
            raise Nl2AgentSessionCatalogError(
                "Selected MCP tools were not discovered by this installation."
            )
        if match.status == "binding":
            if (
                match.binding_operation_id == operation_id
                and match.bound_tool_ids == selected_tool_ids
            ):
                return match.model_dump(mode="json")
            raise Nl2AgentSessionCatalogError(
                "MCP tool binding is reserved by another operation."
            )
        if match.status in {"tools_bound", "binding_skipped"}:
            if (
                match.binding_operation_id == operation_id
                and match.bound_tool_ids == selected_tool_ids
            ):
                return match.model_dump(mode="json")
            raise Nl2AgentSessionCatalogError("MCP tool binding is already resolved.")
        if match.status != "connected":
            raise Nl2AgentSessionCatalogError("MCP tool binding is already resolved.")
        match.status = "binding"
        match.binding_operation_id = operation_id
        match.bound_tool_ids = selected_tool_ids
        return match.model_dump(mode="json")

    return _mutate_session_state(tenant, draft_id, mutate)


def complete_mcp_binding_operation(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    recommendation_id: str,
    operation_id: str,
    status: str,
) -> Dict[str, Any]:
    """Complete an MCP bind/skip only for the reservation owner."""
    if status not in {"tools_bound", "binding_skipped"}:
        raise Nl2AgentSessionCatalogError("Invalid MCP binding completion status.")
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        workflow = state.mcp_workflows.get(recommendation_id)
        if workflow is None:
            raise Nl2AgentSessionCatalogError("Installed MCP workflow was not found.")
        if workflow.status == status and workflow.binding_operation_id == operation_id:
            return workflow.model_dump(mode="json")
        if (
            workflow.status != "binding"
            or workflow.binding_operation_id != operation_id
        ):
            raise Nl2AgentSessionCatalogError(
                "MCP binding reservation is no longer owned by this operation."
            )
        workflow.status = status
        if status == "binding_skipped":
            workflow.bound_tool_ids = []
        return workflow.model_dump(mode="json")

    return _mutate_session_state(tenant, draft_id, mutate)


def release_mcp_binding_operation(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    recommendation_id: str,
    operation_id: str,
) -> Dict[str, Any]:
    """Release an MCP binding reservation after a database failure."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        workflow = state.mcp_workflows.get(recommendation_id)
        if workflow is None:
            raise Nl2AgentSessionCatalogError("Installed MCP workflow was not found.")
        if (
            workflow.status == "binding"
            and workflow.binding_operation_id == operation_id
        ):
            workflow.status = "connected"
            workflow.binding_operation_id = None
            workflow.bound_tool_ids = []
        return workflow.model_dump(mode="json")

    return _mutate_session_state(tenant, draft_id, mutate)


def assert_mcp_workflows_resolved(tenant_id: str, draft_agent_id: int) -> None:
    state = get_nl2agent_session_state(tenant_id, draft_agent_id)
    unresolved = [
        workflow
        for workflow in state["mcp_workflows"].values()
        if workflow.get("status") in {"connected", "binding"}
    ]
    if unresolved:
        raise Nl2AgentSessionCatalogError(
            "Bind discovered MCP tools or explicitly skip tool binding before finalizing."
        )


def register_online_recommendation_batch(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    recommendation_batch_id: str,
    resource_type: str,
    item_keys: List[str],
) -> Dict[str, Any]:
    """Idempotently record one rendered online recommendation batch."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    if resource_type not in {"mcp", "skill"}:
        raise Nl2AgentSessionCatalogError("Invalid online resource type.")
    if not recommendation_batch_id:
        raise Nl2AgentSessionCatalogError("recommendation_batch_id is required.")
    normalized_keys = _ordered_unique(
        (key for key in item_keys if str(key).strip()), lambda key: str(key).strip()
    )

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        trusted = state.recommendations.get(recommendation_batch_id)
        if (
            trusted is None
            or trusted.resource_type != resource_type
            or trusted.item_keys != normalized_keys
        ):
            raise Nl2AgentSessionCatalogError(
                "Online recommendation batch does not match a trusted search result."
            )
        if trusted.resource_type != resource_type or trusted.item_keys != normalized_keys:
            raise Nl2AgentSessionCatalogError(
                "Online recommendation batch contents do not match the registered card."
            )
        if trusted.status == "searched":
            trusted.status = "presented"
            state.online_configuration_confirmed = False
        return {
            "resource_type": trusted.resource_type,
            "item_keys": list(trusted.item_keys),
            "status": "completed" if trusted.status == "completed" else "recommendations_ready",
        }

    return _mutate_session_state(tenant, draft_id, mutate)


def complete_online_configuration(
    tenant_id: Optional[str], draft_agent_id: Optional[int]
) -> List[str]:
    """Complete all rendered online recommendation batches for one draft."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)

    def mutate(state: Nl2AgentWorkflowState) -> List[str]:
        batches = {
            key: batch
            for key, batch in state.recommendations.items()
            if batch.resource_type in {"mcp", "skill"}
        }
        resource_types = {batch.resource_type for batch in batches.values()}
        if not {"mcp", "skill"}.issubset(resource_types):
            raise Nl2AgentSessionCatalogError(
                "Show online resource recommendations for both MCP and Skill before completing configuration."
            )
        if any(
            workflow.status in {"installing", "connected", "binding"}
            for workflow in state.mcp_workflows.values()
        ):
            raise Nl2AgentSessionCatalogError(
                "Bind discovered MCP tools or explicitly skip tool binding before completing online configuration."
            )
        if any(
            installation.status == "installing"
            for installation in state.online_installations.values()
        ):
            raise Nl2AgentSessionCatalogError(
                "Wait for every online Skill installation to finish before completing online configuration."
            )
        for batch in batches.values():
            batch.status = "completed"
        state.online_configuration_confirmed = True
        _finish_revision(state)
        return sorted(batches)

    return _mutate_session_state(tenant, draft_id, mutate)


def reserve_online_installation(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    installation_key: str,
    operation_id: str,
) -> Dict[str, Any]:
    """Reserve one online installation inside the workflow CAS."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        _ensure_workflow_action_allowed(
            evaluate_workflow(state).model_dump(mode="json"),
            "configure_online_resources",
        )
        existing = state.online_installations.get(installation_key)
        if existing is not None:
            if existing.operation_id == operation_id:
                return existing.model_dump(mode="json")
            raise Nl2AgentSessionCatalogError(
                "Online resource installation is owned by another operation."
            )
        state.online_installations[installation_key] = OnlineInstallation(
            status="installing",
            operation_id=operation_id,
        )
        return state.online_installations[installation_key].model_dump(mode="json")

    return _mutate_session_state(tenant, draft_id, mutate)


def complete_online_installation(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    installation_key: str,
    operation_id: str,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """Complete only the operation that owns an online installation."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        installation = state.online_installations.get(installation_key)
        if installation is None or installation.operation_id != operation_id:
            raise Nl2AgentSessionCatalogError(
                "Online installation reservation is no longer owned by this operation."
            )
        if installation.status == "completed":
            return installation.model_dump(mode="json")
        installation.status = "completed"
        installation.result = deepcopy(result)
        return installation.model_dump(mode="json")

    return _mutate_session_state(tenant, draft_id, mutate)


def release_online_installation(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    installation_key: str,
    operation_id: str,
) -> None:
    """Release a failed online installation if the operation still owns it."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)

    def mutate(state: Nl2AgentWorkflowState) -> None:
        installation = state.online_installations.get(installation_key)
        if (
            installation is not None
            and installation.status == "installing"
            and installation.operation_id == operation_id
        ):
            del state.online_installations[installation_key]

    _mutate_session_state(tenant, draft_id, mutate)


def assert_online_configuration_complete(tenant_id: str, draft_agent_id: int) -> None:
    """Reject finalization when rendered online batches remain unfinished."""
    state = get_nl2agent_session_state(tenant_id, draft_agent_id)
    batches = {
        key: batch
        for key, batch in state["recommendations"].items()
        if batch.get("resource_type") in {"mcp", "skill"}
    }
    resource_types = {batch.get("resource_type") for batch in batches.values()}
    if not {"mcp", "skill"}.issubset(resource_types):
        raise Nl2AgentSessionCatalogError(
            "Show online resource recommendations for both MCP and Skill before finalizing."
        )
    if not state.get("online_configuration_confirmed") or any(
        batch.get("status") != "completed" for batch in batches.values()
    ):
        raise Nl2AgentSessionCatalogError(
            "Complete the online resource configuration before finalizing."
        )


def register_recommendation_batch(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    recommendation_batch_id: str,
    tool_ids: List[int],
    skill_ids: List[int],
) -> Dict[str, Any]:
    """Idempotently record that a recommendation card was rendered."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    if not recommendation_batch_id:
        raise Nl2AgentSessionCatalogError("recommendation_batch_id is required.")
    normalized_tool_ids = _ordered_unique(tool_ids, int)
    normalized_skill_ids = _ordered_unique(skill_ids, int)

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        trusted = state.recommendations.get(recommendation_batch_id)
        if (
            trusted is None
            or trusted.resource_type != "local"
            or trusted.tool_ids != normalized_tool_ids
            or trusted.skill_ids != normalized_skill_ids
        ):
            raise Nl2AgentSessionCatalogError(
                "Recommendation batch does not match a trusted search result."
            )
        if trusted.tool_ids != normalized_tool_ids or trusted.skill_ids != normalized_skill_ids:
            raise Nl2AgentSessionCatalogError(
                "Recommendation batch contents do not match the registered card."
            )
        if trusted.status == "searched":
            trusted.status = "presented"
        return _recommendation_batch_response(trusted)

    return _mutate_session_state(tenant, draft_id, mutate)


def assert_trusted_local_search_batch(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    recommendation_batch_id: str,
    tool_ids: List[int],
    skill_ids: List[int],
) -> None:
    """Validate a local card against the immutable server-recorded search result."""
    state = get_nl2agent_session_state(tenant_id, draft_agent_id)
    trusted = state["recommendations"].get(recommendation_batch_id)
    if (
        trusted is None
        or trusted.get("resource_type") != "local"
        or trusted.get("tool_ids") != _ordered_unique(tool_ids, int)
        or trusted.get("skill_ids") != _ordered_unique(skill_ids, int)
    ):
        raise Nl2AgentSessionCatalogError(
            "Recommendation batch does not match a trusted search result."
        )


def record_stage_validated_search_batch(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    *,
    recommendation_batch_id: str,
    resource_type: str,
    tool_ids: Optional[List[int]] = None,
    skill_ids: Optional[List[int]] = None,
    item_keys: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Persist an SDK search result only while its search action is allowed."""
    workflow_action = (
        "search_local_resources"
        if resource_type == "local"
        else "search_online_resources"
    )
    return _record_trusted_search_batch(
        tenant_id,
        draft_agent_id,
        recommendation_batch_id=recommendation_batch_id,
        resource_type=resource_type,
        tool_ids=tool_ids,
        skill_ids=skill_ids,
        item_keys=item_keys,
        workflow_action=workflow_action,
    )


def _record_trusted_search_batch(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    *,
    recommendation_batch_id: str,
    resource_type: str,
    tool_ids: Optional[List[int]] = None,
    skill_ids: Optional[List[int]] = None,
    item_keys: Optional[List[str]] = None,
    workflow_action: Optional[str] = None,
) -> Dict[str, Any]:
    """CAS one immutable search proof with an optional stage precondition."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    if not recommendation_batch_id:
        raise Nl2AgentSessionCatalogError("recommendation_batch_id is required.")
    batch = RecommendationBatch(
        resource_type=resource_type,
        status="searched",
        tool_ids=_ordered_unique(tool_ids or [], int),
        skill_ids=_ordered_unique(skill_ids or [], int),
        item_keys=_ordered_unique(
            (key for key in item_keys or [] if str(key).strip()),
            lambda key: str(key).strip(),
        ),
    )

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        if workflow_action:
            _ensure_workflow_action_allowed(
                evaluate_workflow(state).model_dump(mode="json"),
                workflow_action,
            )
        existing = state.recommendations.get(recommendation_batch_id)
        if existing is None:
            state.recommendations[recommendation_batch_id] = batch
        elif (
            existing.resource_type != batch.resource_type
            or existing.tool_ids != batch.tool_ids
            or existing.skill_ids != batch.skill_ids
            or existing.item_keys != batch.item_keys
        ):
            raise Nl2AgentSessionCatalogError(
                "Trusted search batch contents changed for the same identifier."
            )
        return state.recommendations[recommendation_batch_id].model_dump(
            mode="json"
        )

    return _mutate_session_state(tenant, draft_id, mutate)


def _recommendation_batch_response(batch: RecommendationBatch) -> Dict[str, Any]:
    """Project the aggregate into the stable local-card response contract."""
    payload = batch.model_dump(mode="json", exclude={"operation_id", "resource_type", "item_keys"})
    if payload.get("status") == "presented":
        payload["status"] = "recommendations_ready"
    return payload


def resolve_recommendation_batch(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    recommendation_batch_id: str,
    status: str,
    tool_ids: Optional[List[int]] = None,
    skill_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Atomically skip one unresolved recommendation batch."""
    if status != "skipped":
        raise Nl2AgentSessionCatalogError(
            "Applied batches must use the reservation completion workflow."
        )
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        batch = state.recommendations.get(recommendation_batch_id)
        if batch is None:
            raise Nl2AgentSessionCatalogError(
                "Recommendation batch was not registered."
            )
        if batch.status == "skipped":
            return _recommendation_batch_response(batch)
        if batch.status != "presented":
            raise Nl2AgentSessionCatalogError(
                "Recommendation batch is already being applied or resolved."
            )
        batch.status = "skipped"
        _finish_revision(state)
        return _recommendation_batch_response(batch)

    return _mutate_session_state(tenant, draft_id, mutate)


def reserve_recommendation_batch_apply(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    recommendation_batch_id: str,
    operation_id: str,
    tool_ids: List[int],
    skill_ids: List[int],
    db_session=None,
) -> Dict[str, Any]:
    """Reserve one unresolved batch for an idempotent database apply."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    selected_tool_ids = sorted(set(map(int, tool_ids or [])))
    selected_skill_ids = sorted(set(map(int, skill_ids or [])))

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        batch = state.recommendations.get(recommendation_batch_id)
        if batch is None:
            raise Nl2AgentSessionCatalogError(
                "Recommendation batch was not registered."
            )
        if not set(selected_tool_ids).issubset(set(batch.tool_ids)) or not set(
            selected_skill_ids
        ).issubset(set(batch.skill_ids)):
            raise Nl2AgentSessionCatalogError(
                "Applied resources are not part of the recommendation batch."
            )
        if batch.status == "applying":
            if (
                batch.operation_id == operation_id
                and batch.applied_tool_ids == selected_tool_ids
                and batch.applied_skill_ids == selected_skill_ids
            ):
                return _recommendation_batch_response(batch)
            raise Nl2AgentSessionCatalogError(
                "Recommendation batch is already reserved by another operation."
            )
        if batch.status == "applied":
            if (
                batch.operation_id == operation_id
                and batch.applied_tool_ids == selected_tool_ids
                and batch.applied_skill_ids == selected_skill_ids
            ):
                return _recommendation_batch_response(batch)
            raise Nl2AgentSessionCatalogError(
                "Recommendation batch is already resolved."
            )
        if batch.status != "presented":
            raise Nl2AgentSessionCatalogError(
                "Recommendation batch is already resolved."
            )
        batch.status = "applying"
        batch.operation_id = operation_id
        batch.applied_tool_ids = selected_tool_ids
        batch.applied_skill_ids = selected_skill_ids
        return _recommendation_batch_response(batch)

    return _mutate_session_state(tenant, draft_id, mutate, db_session=db_session)


def complete_recommendation_batch_apply(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    recommendation_batch_id: str,
    operation_id: str,
    db_session=None,
) -> Dict[str, Any]:
    """Complete only the operation that owns an apply reservation."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        batch = state.recommendations.get(recommendation_batch_id)
        if batch is None:
            raise Nl2AgentSessionCatalogError(
                "Recommendation batch was not registered."
            )
        if batch.status == "applied" and batch.operation_id == operation_id:
            return _recommendation_batch_response(batch)
        if batch.status != "applying" or batch.operation_id != operation_id:
            raise Nl2AgentSessionCatalogError(
                "Recommendation apply reservation is no longer owned by this operation."
            )
        batch.status = "applied"
        _finish_revision(state)
        return _recommendation_batch_response(batch)

    return _mutate_session_state(tenant, draft_id, mutate, db_session=db_session)


def release_recommendation_batch_apply(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    recommendation_batch_id: str,
    operation_id: str,
) -> Dict[str, Any]:
    """Release an apply reservation after a database transaction failure."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        batch = state.recommendations.get(recommendation_batch_id)
        if batch is None:
            raise Nl2AgentSessionCatalogError(
                "Recommendation batch was not registered."
            )
        if batch.status == "applying" and batch.operation_id == operation_id:
            batch.status = "presented"
            batch.operation_id = None
            batch.applied_tool_ids = []
            batch.applied_skill_ids = []
        return _recommendation_batch_response(batch)

    return _mutate_session_state(tenant, draft_id, mutate)


def assert_resource_review_complete(tenant_id: str, draft_agent_id: int) -> None:
    state = get_nl2agent_session_state(tenant_id, draft_agent_id)
    batches = {
        key: batch
        for key, batch in state["recommendations"].items()
        if batch.get("resource_type") == "local"
    }
    if not batches:
        raise Nl2AgentSessionCatalogError(
            "Show the local resource recommendation card before finalizing."
        )
    if any(
        batch.get("status") in {"searched", "presented", "applying"}
        for batch in batches.values()
    ):
        raise Nl2AgentSessionCatalogError(
            "Apply or skip every shown local resource recommendation before finalizing."
        )


def _installed_skill_references(
    installations: Dict[str, Any],
) -> tuple[set[int], set[str]]:
    installed_ids: set[int] = set()
    installed_names: set[str] = set()
    for installation in installations.values():
        if installation.get("status") != "completed":
            continue
        result = installation.get("result") or {}
        candidate_ids = (
            result.get("_source_skill_id"),
            result.get("skill_id"),
            *(result.get("installed_ids") or []),
        )
        for value in candidate_ids:
            try:
                if value is not None:
                    installed_ids.add(int(value))
            except (TypeError, ValueError):
                continue
        candidate_names = (
            result.get("_source_skill_name"),
            result.get("skill_name"),
            *(result.get("installed_names") or []),
        )
        installed_names.update(
            str(value).casefold().strip() for value in candidate_names if value
        )
    return installed_ids, installed_names


def _mark_installed_official_skills(
    official_skills: List[Dict[str, Any]],
    installed_ids: set[int],
    installed_names: set[str],
) -> None:
    for item in official_skills:
        item_name = (
            str(item.get("skill_name") or item.get("name") or "").casefold().strip()
        )
        try:
            item_id = (
                int(item["skill_id"]) if item.get("skill_id") is not None else None
            )
        except (TypeError, ValueError):
            item_id = None
        if item_id in installed_ids or item_name in installed_names:
            item["status"] = "installed"


def get_nl2agent_search_catalogs(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    workflow_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Project immutable catalogs through session installation state for search."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    catalogs = get_nl2agent_session_catalogs(tenant, draft_id)
    state = workflow_state or get_nl2agent_session_state(tenant, draft_id)
    installed_mcp_ids = {
        recommendation_id
        for recommendation_id, workflow in state.get("mcp_workflows", {}).items()
        if workflow.get("status")
        in {"installing", "connected", "binding", "tools_bound", "binding_skipped"}
    }
    for source, catalog_key in (
        ("registry", "registry_results"),
        ("community", "community_results"),
    ):
        catalogs[catalog_key] = [
            item
            for item in catalogs[catalog_key]
            if mcp_recommendation_id(source, item) not in installed_mcp_ids
        ]

    installed_skill_ids, installed_skill_names = _installed_skill_references(
        state.get("online_installations", {})
    )
    _mark_installed_official_skills(
        catalogs["official_skills"],
        installed_skill_ids,
        installed_skill_names,
    )
    return catalogs


def acquire_mcp_installation_lock(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    installation_key: str,
) -> Optional[str]:
    """Claim a durable installation lease and return its ownership token."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    from database.nl2agent_installation_db import (
        InstallationLeaseConflictError,
        claim_installation_operation,
    )
    from database.nl2agent_session_db import Nl2AgentSessionIdentity, get_nl2agent_session

    session = get_nl2agent_session(tenant, draft_id)
    if session is None:
        return None
    token = uuid.uuid4().hex
    operation_id = hashlib.sha256(
        f"{tenant}:{draft_id}:{installation_key}".encode("utf-8")
    ).hexdigest()
    identity = Nl2AgentSessionIdentity(
        tenant_id=tenant,
        user_id=str(session["user_id"]),
        runner_agent_id=int(session["runner_agent_id"]),
        draft_agent_id=draft_id,
        conversation_id=int(session["conversation_id"]),
    )
    try:
        claim_installation_operation(
            identity=identity,
            operation_id=operation_id,
            installation_key=installation_key,
            request_fingerprint=operation_id,
            resource_type=("skill" if installation_key.startswith("skill:") else "mcp"),
            lease_owner=token,
            lease_expires_at=datetime.utcnow() + timedelta(seconds=_INSTALLATION_LOCK_TTL_SECONDS),
        )
    except InstallationLeaseConflictError:
        return None
    return token


def _installation_identity(tenant_id: str, draft_agent_id: int):
    """Resolve the complete active Session identity for an installation operation."""
    from database.nl2agent_session_db import Nl2AgentSessionIdentity, get_nl2agent_session

    session = get_nl2agent_session(tenant_id, draft_agent_id)
    if session is None:
        return None
    return Nl2AgentSessionIdentity(
        tenant_id=tenant_id,
        user_id=str(session["user_id"]),
        runner_agent_id=int(session["runner_agent_id"]),
        draft_agent_id=draft_agent_id,
        conversation_id=int(session["conversation_id"]),
    )


def get_installation_operation(
    tenant_id: Optional[str], draft_agent_id: Optional[int], installation_key: str
) -> Optional[Dict[str, Any]]:
    """Load a durable installation outcome through the active Session identity."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    identity = _installation_identity(tenant, draft_id)
    if identity is None:
        return None
    from database.nl2agent_installation_db import get_installation_operation as load

    return load(identity=identity, installation_key=installation_key)


def transition_installation_operation(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    installation_key: str,
    token: str,
    status: str,
    *,
    checkpoint: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[Dict[str, Any]] = None,
) -> bool:
    """Persist a secret-free checkpoint or outcome for the current lease owner."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    from database.nl2agent_installation_db import transition_installation_operation as persist

    operation_id = hashlib.sha256(
        f"{tenant}:{draft_id}:{installation_key}".encode("utf-8")
    ).hexdigest()
    return persist(
        operation_id=operation_id,
        lease_owner=token,
        status=status,
        checkpoint=checkpoint,
        result=result,
        error=error,
    )


def release_mcp_installation_lock(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    installation_key: str,
    token: str,
) -> None:
    """Release a durable installation lease only for its owner."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    from database.nl2agent_installation_db import release_installation_lease

    operation_id = hashlib.sha256(
        f"{tenant}:{draft_id}:{installation_key}".encode("utf-8")
    ).hexdigest()
    release_installation_lease(operation_id=operation_id, lease_owner=token)


def renew_mcp_installation_lock(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    installation_key: str,
    token: str,
) -> bool:
    """Extend a durable installation lease only while the caller owns it."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    from database.nl2agent_installation_db import renew_installation_operation

    operation_id = hashlib.sha256(
        f"{tenant}:{draft_id}:{installation_key}".encode("utf-8")
    ).hexdigest()
    return renew_installation_operation(
        operation_id=operation_id,
        lease_owner=token,
        lease_expires_at=datetime.utcnow() + timedelta(seconds=_INSTALLATION_LOCK_TTL_SECONDS),
    )
