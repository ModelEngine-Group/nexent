"""Redis-backed NL2AGENT session catalog handoff."""

import hashlib
import json
import logging
import re
import unicodedata
import uuid
from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional, TypeVar

import redis
from pydantic import ValidationError

from consts.exceptions import (
    Nl2AgentStateConflictError as _Nl2AgentStateConflictError,
    Nl2AgentWorkflowConflictError,
)

from agents.nl2agent_workflow import (
    CardDelivery,
    McpWorkflow,
    OnlineRecommendationBatch,
    RecommendationBatch,
    RequirementsReview,
    TrustedSearchBatch,
    WORKFLOW_SCHEMA_VERSION,
    Nl2AgentWorkflowState,
    evaluate_workflow,
    state_to_dict,
)

logger = logging.getLogger(__name__)

_CATALOG_KEYS = (
    "tool_catalog",
    "skill_catalog",
    "registry_results",
    "community_results",
    "official_skills",
)
_CACHE_KEY_PREFIX = "nl2agent:session_catalog"
_STATE_KEY_PREFIX = "nl2agent:session_state"
_INSTALLATION_LOCK_KEY_PREFIX = "nl2agent:mcp_installation_lock"
_CACHE_TTL_SECONDS = 24 * 60 * 60
_INSTALLATION_LOCK_TTL_SECONDS = 5 * 60
_CAS_MAX_RETRIES = 5
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


class Nl2AgentSessionCatalogError(Nl2AgentWorkflowConflictError):
    """Raised when NL2AGENT session catalogs cannot be persisted or loaded."""


class Nl2AgentStateConflictError(_Nl2AgentStateConflictError):
    """Raised when concurrent writers exhaust the state CAS retry budget."""


_MutationResult = TypeVar("_MutationResult")


def get_redis_service():
    """Resolve the shared Redis service lazily to keep agent imports lightweight."""
    from services.redis_service import get_redis_service as redis_service_factory

    return redis_service_factory()


def _cache_key(tenant_id: str, draft_agent_id: int) -> str:
    return f"{_CACHE_KEY_PREFIX}:{tenant_id}:{int(draft_agent_id)}"


def _state_key(tenant_id: str, draft_agent_id: int) -> str:
    return f"{_STATE_KEY_PREFIX}:{tenant_id}:{int(draft_agent_id)}"


def _new_session_state(conversation_id: int) -> Nl2AgentWorkflowState:
    return Nl2AgentWorkflowState(conversation_id=int(conversation_id))


def initialize_nl2agent_session_state(
    tenant_id: Optional[str], draft_agent_id: Optional[int], conversation_id: int
) -> Dict[str, Any]:
    """Create a v2 workflow state exactly once for a new draft session."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    state = _new_session_state(conversation_id)
    key = _state_key(tenant, draft_id)
    try:
        created = get_redis_service().client.set(
            key,
            json.dumps(state_to_dict(state), ensure_ascii=False),
            ex=_CACHE_TTL_SECONDS,
            nx=True,
        )
    except Exception as exc:
        logger.error(
            "Failed to initialize NL2AGENT session state: tenant_id=%s draft_agent_id=%s",
            tenant,
            draft_id,
            exc_info=True,
        )
        raise Nl2AgentSessionCatalogError(
            f"Failed to initialize NL2AGENT session state for tenant={tenant}, draft_agent_id={draft_id}."
        ) from exc
    if not created:
        raise Nl2AgentSessionCatalogError("NL2AGENT session state already exists for this draft.")
    return state_to_dict(state)


def _parse_session_state(raw: Any, tenant_id: str, draft_agent_id: int) -> Nl2AgentWorkflowState:
    if raw is None:
        raise Nl2AgentSessionCatalogError(
            f"NL2AGENT session state is missing for tenant={tenant_id}, draft_agent_id={draft_agent_id}."
        )
    try:
        payload = json.loads(raw)
        if payload.get("schema_version") != WORKFLOW_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version={payload.get('schema_version')!r}")
        return Nl2AgentWorkflowState.model_validate(payload)
    except (
        json.JSONDecodeError,
        TypeError,
        AttributeError,
        ValueError,
        ValidationError,
    ) as exc:
        logger.error(
            "Malformed NL2AGENT session state: tenant_id=%s draft_agent_id=%s",
            tenant_id,
            draft_agent_id,
            exc_info=True,
        )
        raise Nl2AgentSessionCatalogError(
            f"Malformed NL2AGENT session state for tenant={tenant_id}, draft_agent_id={draft_agent_id}."
        ) from exc


def get_nl2agent_session_state(tenant_id: Optional[str], draft_agent_id: Optional[int]) -> Dict[str, Any]:
    """Return resource-review state for one tenant-scoped draft."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    try:
        raw = get_redis_service().client.get(_state_key(tenant, draft_id))
    except Exception as exc:
        logger.error(
            "Failed to load NL2AGENT session state: tenant_id=%s draft_agent_id=%s",
            tenant,
            draft_id,
            exc_info=True,
        )
        raise Nl2AgentSessionCatalogError(
            f"Failed to load NL2AGENT session state for tenant={tenant}, draft_agent_id={draft_id}."
        ) from exc
    return state_to_dict(_parse_session_state(raw, tenant, draft_id))


def _mutate_session_state(
    tenant_id: str,
    draft_agent_id: int,
    mutator: Callable[[Nl2AgentWorkflowState], _MutationResult],
) -> _MutationResult:
    """Atomically mutate one workflow state with bounded optimistic retries."""
    key = _state_key(tenant_id, draft_agent_id)
    client = get_redis_service().client
    for _attempt in range(_CAS_MAX_RETRIES):
        pipe = client.pipeline()
        try:
            pipe.watch(key)
            state = _parse_session_state(pipe.get(key), tenant_id, draft_agent_id)
            original_state = state_to_dict(state)
            result = mutator(state)
            if state_to_dict(state) == original_state:
                pipe.unwatch()
                return deepcopy(result)
            state.revision += 1
            pipe.multi()
            pipe.setex(
                key,
                _CACHE_TTL_SECONDS,
                json.dumps(state_to_dict(state), ensure_ascii=False),
            )
            pipe.execute()
            return deepcopy(result)
        except redis.WatchError:
            continue
        finally:
            pipe.reset()
    raise Nl2AgentStateConflictError(
        f"NL2AGENT session state changed concurrently for tenant={tenant_id}, draft_agent_id={draft_agent_id}."
    )


def summarize_workflow_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate a workflow snapshot without loading Redis again."""
    return evaluate_workflow(Nl2AgentWorkflowState.model_validate(state)).model_dump(
        mode="json"
    )


def get_workflow_summary(tenant_id: Optional[str], draft_agent_id: Optional[int]) -> Dict[str, Any]:
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    state = _parse_session_state(get_redis_service().client.get(_state_key(tenant, draft_id)), tenant, draft_id)
    return summarize_workflow_state(state.model_dump(mode="json"))


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
        field_name: _normalize_requirement_text(summary.get(field_name)) for field_name in _REQUIREMENTS_FIELDS
    }
    missing_fields = [field_name for field_name, field_value in normalized_summary.items() if not field_value]
    if missing_fields:
        raise Nl2AgentSessionCatalogError("Requirements summary fields cannot be empty: " + ", ".join(missing_fields))
    fingerprint = _requirements_fingerprint(normalized_summary)

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        review = state.requirements_review
        existing_fingerprint = review.fingerprint
        is_current = False
        if not existing_fingerprint or (review.status == "collecting" and existing_fingerprint != fingerprint):
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
    if any(phrase in normalized for phrase in _CONFIRMATION_PHRASES - _SHORT_CONFIRMATION_PHRASES):
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
        elif review.status != "confirmed":
            raise Nl2AgentSessionCatalogError("The requirements summary is not awaiting confirmation.")
        return review.model_dump(mode="json")

    return _mutate_session_state(tenant, draft_id, mutate)


def assert_requirements_confirmed(
    tenant_id: str, draft_agent_id: int
) -> Dict[str, Any]:
    """Reject protected workflow actions until requirements are confirmed."""
    state = get_nl2agent_session_state(tenant_id, draft_agent_id)
    if state["requirements_review"].get("status") != "confirmed":
        raise Nl2AgentSessionCatalogError("Confirm the requirements summary before continuing configuration.")
    return state


def set_model_selection_confirmed(
    tenant_id: Optional[str], draft_agent_id: Optional[int], confirmed: bool = True
) -> Dict[str, Any]:
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        state.model_selection_confirmed = bool(confirmed)
        return {"model_selection_confirmed": state.model_selection_confirmed}

    return _mutate_session_state(tenant, draft_id, mutate)


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
            int(existing.retry_count) + 1 if status == "failed" and existing is not None else int(status == "failed")
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
        return delivery.model_dump(mode="json")

    return _mutate_session_state(tenant, draft_id, mutate)


def confirm_agent_identity(tenant_id: Optional[str], draft_agent_id: Optional[int]) -> Dict[str, Any]:
    """Record that the user explicitly saved the draft display name."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        state.identity_confirmed = True
        return state_to_dict(state)

    return _mutate_session_state(tenant, draft_id, mutate)


def assert_identity_confirmed(tenant_id: str, draft_agent_id: int) -> None:
    """Reject finalization until the user explicitly saves the identity card."""
    state = get_nl2agent_session_state(tenant_id, draft_agent_id)
    if not state.get("identity_confirmed"):
        raise Nl2AgentSessionCatalogError("Save the agent display name before finalizing.")


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
        workflow = state.mcp_workflows.setdefault(recommendation_id, McpWorkflow(recommendation_id=recommendation_id))
        updated = {
            **workflow.model_dump(mode="python"),
            **{key: deepcopy(value) for key, value in values.items() if key in allowed},
        }
        state.mcp_workflows[recommendation_id] = McpWorkflow.model_validate(updated)
        return state.mcp_workflows[recommendation_id].model_dump(mode="json")

    return _mutate_session_state(tenant, draft_id, mutate)


def find_mcp_workflow_by_id(tenant_id: str, draft_agent_id: int, mcp_id: int) -> tuple[str, Dict[str, Any]]:
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
            raise Nl2AgentSessionCatalogError(
                "Installed MCP workflow was not found."
            )
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
            raise Nl2AgentSessionCatalogError(
                "MCP tool binding is already resolved."
            )
        if match.status != "connected":
            raise Nl2AgentSessionCatalogError(
                "MCP tool binding is already resolved."
            )
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
            raise Nl2AgentSessionCatalogError(
                "Installed MCP workflow was not found."
            )
        if workflow.status == status and workflow.binding_operation_id == operation_id:
            return workflow.model_dump(mode="json")
        if workflow.status != "binding" or workflow.binding_operation_id != operation_id:
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
            raise Nl2AgentSessionCatalogError(
                "Installed MCP workflow was not found."
            )
        if workflow.status == "binding" and workflow.binding_operation_id == operation_id:
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
    normalized_keys = sorted({str(key).strip() for key in item_keys if str(key).strip()})

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        trusted = state.trusted_search_batches.get(recommendation_batch_id)
        if (
            trusted is None
            or trusted.resource_type != resource_type
            or trusted.item_keys != normalized_keys
        ):
            raise Nl2AgentSessionCatalogError(
                "Online recommendation batch does not match a trusted search result."
            )
        batches = state.online_recommendation_batches
        existing = batches.get(recommendation_batch_id)
        if existing is None:
            batches[recommendation_batch_id] = OnlineRecommendationBatch(
                resource_type=resource_type,
                item_keys=normalized_keys,
                status="recommendations_ready",
            )
            state.online_configuration_confirmed = False
        elif existing.resource_type != resource_type or existing.item_keys != normalized_keys:
            raise Nl2AgentSessionCatalogError("Online recommendation batch contents do not match the registered card.")
        return batches[recommendation_batch_id].model_dump(mode="json")

    return _mutate_session_state(tenant, draft_id, mutate)


def complete_online_configuration(tenant_id: Optional[str], draft_agent_id: Optional[int]) -> List[str]:
    """Complete all rendered online recommendation batches for one draft."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)

    def mutate(state: Nl2AgentWorkflowState) -> List[str]:
        batches = state.online_recommendation_batches
        resource_types = {batch.resource_type for batch in batches.values()}
        if not {"mcp", "skill"}.issubset(resource_types):
            raise Nl2AgentSessionCatalogError(
                "Show online resource recommendations for both MCP and Skill before completing configuration."
            )
        if any(workflow.status in {"installing", "connected", "binding"} for workflow in state.mcp_workflows.values()):
            raise Nl2AgentSessionCatalogError(
                "Bind discovered MCP tools or explicitly skip tool binding before completing online configuration."
            )
        for batch in batches.values():
            batch.status = "completed"
        state.online_configuration_confirmed = True
        return sorted(batches)

    return _mutate_session_state(tenant, draft_id, mutate)


def assert_online_configuration_complete(tenant_id: str, draft_agent_id: int) -> None:
    """Reject finalization when rendered online batches remain unfinished."""
    state = get_nl2agent_session_state(tenant_id, draft_agent_id)
    batches = state["online_recommendation_batches"]
    resource_types = {batch.get("resource_type") for batch in batches.values()}
    if not {"mcp", "skill"}.issubset(resource_types):
        raise Nl2AgentSessionCatalogError(
            "Show online resource recommendations for both MCP and Skill before finalizing."
        )
    if not state.get("online_configuration_confirmed") or any(
        batch.get("status") != "completed" for batch in batches.values()
    ):
        raise Nl2AgentSessionCatalogError("Complete the online resource configuration before finalizing.")


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
    normalized_tool_ids = sorted(set(map(int, tool_ids)))
    normalized_skill_ids = sorted(set(map(int, skill_ids)))

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        trusted = state.trusted_search_batches.get(recommendation_batch_id)
        if (
            trusted is None
            or trusted.resource_type != "local"
            or trusted.tool_ids != normalized_tool_ids
            or trusted.skill_ids != normalized_skill_ids
        ):
            raise Nl2AgentSessionCatalogError(
                "Recommendation batch does not match a trusted search result."
            )
        batches = state.recommendation_batches
        existing = batches.get(recommendation_batch_id)
        if existing is None:
            batches[recommendation_batch_id] = RecommendationBatch(
                status="recommendations_ready",
                tool_ids=normalized_tool_ids,
                skill_ids=normalized_skill_ids,
            )
        elif existing.tool_ids != normalized_tool_ids or existing.skill_ids != normalized_skill_ids:
            raise Nl2AgentSessionCatalogError("Recommendation batch contents do not match the registered card.")
        return _recommendation_batch_response(batches[recommendation_batch_id])

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
    trusted = state["trusted_search_batches"].get(recommendation_batch_id)
    if (
        trusted is None
        or trusted.get("resource_type") != "local"
        or trusted.get("tool_ids") != sorted(set(map(int, tool_ids)))
        or trusted.get("skill_ids") != sorted(set(map(int, skill_ids)))
    ):
        raise Nl2AgentSessionCatalogError(
            "Recommendation batch does not match a trusted search result."
        )


def record_trusted_search_batch(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    *,
    recommendation_batch_id: str,
    resource_type: str,
    tool_ids: Optional[List[int]] = None,
    skill_ids: Optional[List[int]] = None,
    item_keys: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Idempotently persist the exact batch produced by an SDK search tool."""
    return _record_trusted_search_batch(
        tenant_id,
        draft_agent_id,
        recommendation_batch_id=recommendation_batch_id,
        resource_type=resource_type,
        tool_ids=tool_ids,
        skill_ids=skill_ids,
        item_keys=item_keys,
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
    batch = TrustedSearchBatch(
        resource_type=resource_type,
        tool_ids=sorted(set(map(int, tool_ids or []))),
        skill_ids=sorted(set(map(int, skill_ids or []))),
        item_keys=sorted({str(key).strip() for key in item_keys or [] if str(key).strip()}),
    )

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        if workflow_action:
            _ensure_workflow_action_allowed(
                evaluate_workflow(state).model_dump(mode="json"),
                workflow_action,
            )
        existing = state.trusted_search_batches.get(recommendation_batch_id)
        if existing is None:
            state.trusted_search_batches[recommendation_batch_id] = batch
        elif existing != batch:
            raise Nl2AgentSessionCatalogError(
                "Trusted search batch contents changed for the same identifier."
            )
        return state.trusted_search_batches[recommendation_batch_id].model_dump(
            mode="json"
        )

    return _mutate_session_state(tenant, draft_id, mutate)


def _recommendation_batch_response(batch: RecommendationBatch) -> Dict[str, Any]:
    """Hide internal reservation metadata from action responses."""
    return batch.model_dump(mode="json", exclude={"operation_id"})


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
        batch = state.recommendation_batches.get(recommendation_batch_id)
        if batch is None:
            raise Nl2AgentSessionCatalogError("Recommendation batch was not registered.")
        if batch.status == "skipped":
            return _recommendation_batch_response(batch)
        if batch.status != "recommendations_ready":
            raise Nl2AgentSessionCatalogError(
                "Recommendation batch is already being applied or resolved."
            )
        batch.status = "skipped"
        return _recommendation_batch_response(batch)

    return _mutate_session_state(tenant, draft_id, mutate)


def reserve_recommendation_batch_apply(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    recommendation_batch_id: str,
    operation_id: str,
    tool_ids: List[int],
    skill_ids: List[int],
) -> Dict[str, Any]:
    """Reserve one unresolved batch for an idempotent database apply."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    selected_tool_ids = sorted(set(map(int, tool_ids or [])))
    selected_skill_ids = sorted(set(map(int, skill_ids or [])))

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        batch = state.recommendation_batches.get(recommendation_batch_id)
        if batch is None:
            raise Nl2AgentSessionCatalogError("Recommendation batch was not registered.")
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
        if batch.status != "recommendations_ready":
            raise Nl2AgentSessionCatalogError(
                "Recommendation batch is already resolved."
            )
        batch.status = "applying"
        batch.operation_id = operation_id
        batch.applied_tool_ids = selected_tool_ids
        batch.applied_skill_ids = selected_skill_ids
        return _recommendation_batch_response(batch)

    return _mutate_session_state(tenant, draft_id, mutate)


def complete_recommendation_batch_apply(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    recommendation_batch_id: str,
    operation_id: str,
) -> Dict[str, Any]:
    """Complete only the operation that owns an apply reservation."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        batch = state.recommendation_batches.get(recommendation_batch_id)
        if batch is None:
            raise Nl2AgentSessionCatalogError("Recommendation batch was not registered.")
        if batch.status == "applied" and batch.operation_id == operation_id:
            return _recommendation_batch_response(batch)
        if batch.status != "applying" or batch.operation_id != operation_id:
            raise Nl2AgentSessionCatalogError(
                "Recommendation apply reservation is no longer owned by this operation."
            )
        batch.status = "applied"
        return _recommendation_batch_response(batch)

    return _mutate_session_state(tenant, draft_id, mutate)


def release_recommendation_batch_apply(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    recommendation_batch_id: str,
    operation_id: str,
) -> Dict[str, Any]:
    """Release an apply reservation after a database transaction failure."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)

    def mutate(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
        batch = state.recommendation_batches.get(recommendation_batch_id)
        if batch is None:
            raise Nl2AgentSessionCatalogError("Recommendation batch was not registered.")
        if batch.status == "applying" and batch.operation_id == operation_id:
            batch.status = "recommendations_ready"
            batch.operation_id = None
            batch.applied_tool_ids = []
            batch.applied_skill_ids = []
        return _recommendation_batch_response(batch)

    return _mutate_session_state(tenant, draft_id, mutate)


def assert_resource_review_complete(tenant_id: str, draft_agent_id: int) -> None:
    state = get_nl2agent_session_state(tenant_id, draft_agent_id)
    batches = state["recommendation_batches"]
    if not batches:
        raise Nl2AgentSessionCatalogError("Show the local resource recommendation card before finalizing.")
    if any(batch.get("status") in {"recommendations_ready", "applying"} for batch in batches.values()):
        raise Nl2AgentSessionCatalogError("Apply or skip every shown local resource recommendation before finalizing.")


def _validate_identifiers(tenant_id: Optional[str], draft_agent_id: Optional[int]) -> tuple[str, int]:
    if not tenant_id or not draft_agent_id:
        raise Nl2AgentSessionCatalogError("NL2AGENT session catalog requires tenant_id and draft_agent_id.")
    return tenant_id, int(draft_agent_id)


def _validate_catalogs(catalogs: Any) -> Dict[str, List[Dict[str, Any]]]:
    if not isinstance(catalogs, dict):
        raise Nl2AgentSessionCatalogError("NL2AGENT session catalog payload is malformed.")

    payload: Dict[str, List[Dict[str, Any]]] = {}
    for key in _CATALOG_KEYS:
        value = catalogs.get(key)
        if not isinstance(value, list):
            raise Nl2AgentSessionCatalogError(f"NL2AGENT session catalog field '{key}' is malformed.")
        payload[key] = deepcopy(value)
    return payload


def set_nl2agent_session_catalogs(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    catalogs: Dict[str, List[Dict[str, Any]]],
) -> None:
    """Persist catalogs for a draft agent so every runtime worker can read them."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    payload = _validate_catalogs(catalogs)
    key = _cache_key(tenant, draft_id)
    try:
        get_redis_service().client.setex(
            key,
            _CACHE_TTL_SECONDS,
            json.dumps(payload, ensure_ascii=False),
        )
    except Exception as exc:
        logger.error(
            "Failed to persist NL2AGENT catalogs: tenant_id=%s draft_agent_id=%s",
            tenant,
            draft_id,
            exc_info=True,
        )
        raise Nl2AgentSessionCatalogError(
            f"Failed to persist NL2AGENT catalogs for tenant={tenant}, draft_agent_id={draft_id}."
        ) from exc


def mutate_nl2agent_session_catalogs(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    mutator: Callable[[Dict[str, List[Dict[str, Any]]]], _MutationResult],
) -> _MutationResult:
    """Atomically update one draft catalog without losing concurrent changes."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    key = _cache_key(tenant, draft_id)
    client = get_redis_service().client
    for _attempt in range(_CAS_MAX_RETRIES):
        pipe = client.pipeline()
        try:
            pipe.watch(key)
            raw = pipe.get(key)
            if raw is None:
                raise Nl2AgentSessionCatalogError(
                    f"NL2AGENT catalogs are missing for tenant={tenant}, draft_agent_id={draft_id}."
                )
            catalogs = _validate_catalogs(json.loads(raw))
            original_catalogs = deepcopy(catalogs)
            result = mutator(catalogs)
            if catalogs == original_catalogs:
                pipe.unwatch()
                return deepcopy(result)
            pipe.multi()
            pipe.setex(
                key,
                _CACHE_TTL_SECONDS,
                json.dumps(_validate_catalogs(catalogs), ensure_ascii=False),
            )
            pipe.execute()
            return deepcopy(result)
        except redis.WatchError:
            continue
        finally:
            pipe.reset()
    raise Nl2AgentStateConflictError(
        f"NL2AGENT catalogs changed concurrently for tenant={tenant}, draft_agent_id={draft_id}."
    )


def get_nl2agent_session_catalogs(
    tenant_id: Optional[str], draft_agent_id: Optional[int]
) -> Dict[str, List[Dict[str, Any]]]:
    """Load catalogs for a draft agent or fail explicitly when unavailable."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    key = _cache_key(tenant, draft_id)
    try:
        raw_catalogs = get_redis_service().client.get(key)
    except Exception as exc:
        logger.error(
            "Failed to load NL2AGENT catalogs: tenant_id=%s draft_agent_id=%s",
            tenant,
            draft_id,
            exc_info=True,
        )
        raise Nl2AgentSessionCatalogError(
            f"Failed to load NL2AGENT catalogs for tenant={tenant}, draft_agent_id={draft_id}."
        ) from exc

    if raw_catalogs is None:
        logger.error(
            "NL2AGENT catalogs are missing: tenant_id=%s draft_agent_id=%s",
            tenant,
            draft_id,
        )
        raise Nl2AgentSessionCatalogError(
            f"NL2AGENT catalogs are missing for tenant={tenant}, draft_agent_id={draft_id}."
        )

    try:
        return _validate_catalogs(json.loads(raw_catalogs))
    except (json.JSONDecodeError, TypeError, Nl2AgentSessionCatalogError) as exc:
        logger.error(
            "Malformed NL2AGENT catalogs: tenant_id=%s draft_agent_id=%s",
            tenant,
            draft_id,
            exc_info=True,
        )
        raise Nl2AgentSessionCatalogError(
            f"Malformed NL2AGENT catalogs for tenant={tenant}, draft_agent_id={draft_id}."
        ) from exc


def clear_nl2agent_session_catalogs() -> None:
    """Clear persisted NL2AGENT catalogs. Intended for tests."""
    client = get_redis_service().client
    keys = list(client.scan_iter(match=f"{_CACHE_KEY_PREFIX}:*"))
    keys.extend(client.scan_iter(match=f"{_STATE_KEY_PREFIX}:*"))
    if keys:
        client.delete(*keys)


def delete_nl2agent_session_catalogs(
    tenant_id: Optional[str], draft_agent_id: Optional[int]
) -> None:
    """Delete one draft's workflow and catalog keys during initialization compensation."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    get_redis_service().client.delete(
        _cache_key(tenant, draft_id),
        _state_key(tenant, draft_id),
    )


def acquire_mcp_installation_lock(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    installation_key: str,
) -> Optional[str]:
    """Acquire a tenant/draft installation lock and return its ownership token."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    token = uuid.uuid4().hex
    key = f"{_INSTALLATION_LOCK_KEY_PREFIX}:{tenant}:{draft_id}:{installation_key}"
    acquired = get_redis_service().client.set(
        key,
        token,
        nx=True,
        ex=_INSTALLATION_LOCK_TTL_SECONDS,
    )
    return token if acquired else None


def release_mcp_installation_lock(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    installation_key: str,
    token: str,
) -> None:
    """Release an installation lock only when the caller still owns it."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    key = f"{_INSTALLATION_LOCK_KEY_PREFIX}:{tenant}:{draft_id}:{installation_key}"
    client = get_redis_service().client
    for _attempt in range(_CAS_MAX_RETRIES):
        pipe = client.pipeline()
        try:
            pipe.watch(key)
            if pipe.get(key) != token:
                pipe.unwatch()
                return
            pipe.multi()
            pipe.delete(key)
            pipe.execute()
            return
        except redis.WatchError:
            continue
        finally:
            pipe.reset()


def renew_mcp_installation_lock(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    installation_key: str,
    token: str,
) -> bool:
    """Extend an installation lock only while the caller still owns it."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    key = f"{_INSTALLATION_LOCK_KEY_PREFIX}:{tenant}:{draft_id}:{installation_key}"
    client = get_redis_service().client
    for _attempt in range(_CAS_MAX_RETRIES):
        pipe = client.pipeline()
        try:
            pipe.watch(key)
            if pipe.get(key) != token:
                pipe.unwatch()
                return False
            pipe.multi()
            pipe.expire(key, _INSTALLATION_LOCK_TTL_SECONDS)
            result = pipe.execute()
            return bool(result and result[0])
        except redis.WatchError:
            continue
        finally:
            pipe.reset()
    return False
