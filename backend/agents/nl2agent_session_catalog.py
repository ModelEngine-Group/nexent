"""Redis-backed NL2AGENT session catalog handoff."""

import hashlib
import json
import logging
import re
import unicodedata
from copy import deepcopy
from typing import Any, Dict, List, Optional

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
_CACHE_TTL_SECONDS = 24 * 60 * 60
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


class Nl2AgentSessionCatalogError(RuntimeError):
    """Raised when NL2AGENT session catalogs cannot be persisted or loaded."""


def get_redis_service():
    """Resolve the shared Redis service lazily to keep agent imports lightweight."""
    from services.redis_service import get_redis_service as redis_service_factory

    return redis_service_factory()


def _cache_key(tenant_id: str, draft_agent_id: int) -> str:
    return f"{_CACHE_KEY_PREFIX}:{tenant_id}:{int(draft_agent_id)}"


def _state_key(tenant_id: str, draft_agent_id: int) -> str:
    return f"{_STATE_KEY_PREFIX}:{tenant_id}:{int(draft_agent_id)}"


def _empty_session_state() -> Dict[str, Any]:
    return {
        "requirements_review": {
            "status": "collecting",
            "summary": None,
            "fingerprint": "",
        },
        "recommendation_batches": {},
        "identity_confirmed": False,
        "mcp_workflows": {},
        "online_recommendation_batches": {},
        "online_configuration_confirmed": False,
        "card_delivery": {},
    }


def get_nl2agent_session_state(
    tenant_id: Optional[str], draft_agent_id: Optional[int]
) -> Dict[str, Any]:
    """Return resource-review state for one tenant-scoped draft."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    try:
        raw = get_redis_service().client.get(_state_key(tenant, draft_id))
        if raw is None:
            return _empty_session_state()
        state = json.loads(raw)
        requirements_review = state.get("requirements_review")
        if not isinstance(requirements_review, dict):
            raise ValueError("requirements_review must be an object")
        if requirements_review.get("status") not in _REQUIREMENTS_STATUSES:
            raise ValueError("requirements_review status is invalid")
        summary = requirements_review.get("summary")
        if summary is not None and (
            not isinstance(summary, dict)
            or any(
                not isinstance(summary.get(field_name), str)
                or not summary[field_name].strip()
                for field_name in _REQUIREMENTS_FIELDS
            )
        ):
            raise ValueError("requirements_review summary is invalid")
        if not isinstance(requirements_review.get("fingerprint", ""), str):
            raise ValueError("requirements_review fingerprint is invalid")
        state["requirements_review"] = requirements_review
        batches = state.get("recommendation_batches")
        if not isinstance(batches, dict):
            raise ValueError("recommendation_batches must be an object")
        identity_confirmed = state.get("identity_confirmed", False)
        if not isinstance(identity_confirmed, bool):
            raise ValueError("identity_confirmed must be a boolean")
        state["identity_confirmed"] = identity_confirmed
        workflows = state.get("mcp_workflows", {})
        if not isinstance(workflows, dict):
            raise ValueError("mcp_workflows must be an object")
        state["mcp_workflows"] = workflows
        online_batches = state.get("online_recommendation_batches", {})
        if not isinstance(online_batches, dict):
            raise ValueError("online_recommendation_batches must be an object")
        for batch_id, batch in online_batches.items():
            if not isinstance(batch_id, str) or not isinstance(batch, dict):
                raise ValueError("online recommendation batches must be typed objects")
            if batch.get("resource_type") not in {"mcp", "skill"}:
                raise ValueError("online recommendation resource_type is invalid")
            if not isinstance(batch.get("item_keys"), list) or not all(
                isinstance(item_key, str) for item_key in batch["item_keys"]
            ):
                raise ValueError("online recommendation item_keys must be strings")
            if batch.get("status") not in {"recommendations_ready", "completed"}:
                raise ValueError("online recommendation status is invalid")
        state["online_recommendation_batches"] = online_batches
        online_confirmed = state.get("online_configuration_confirmed", False)
        if not isinstance(online_confirmed, bool):
            raise ValueError("online_configuration_confirmed must be a boolean")
        state["online_configuration_confirmed"] = online_confirmed
        card_delivery = state.get("card_delivery", {})
        if not isinstance(card_delivery, dict):
            raise ValueError("card_delivery must be an object")
        for card_type, delivery in card_delivery.items():
            if card_type not in _CARD_DELIVERY_TYPES or not isinstance(delivery, dict):
                raise ValueError("card_delivery contains an invalid card type")
            if delivery.get("status") not in _CARD_DELIVERY_STATUSES:
                raise ValueError("card_delivery status is invalid")
            if not isinstance(delivery.get("message_key"), str):
                raise ValueError("card_delivery message_key is invalid")
            if not isinstance(delivery.get("retry_count", 0), int):
                raise ValueError("card_delivery retry_count is invalid")
        state["card_delivery"] = card_delivery
        return deepcopy(state)
    except Exception as exc:
        logger.error(
            "Malformed NL2AGENT session state: tenant_id=%s draft_agent_id=%s",
            tenant,
            draft_id,
            exc_info=True,
        )
        raise Nl2AgentSessionCatalogError(
            f"Malformed NL2AGENT session state for tenant={tenant}, draft_agent_id={draft_id}."
        ) from exc


def _set_nl2agent_session_state(
    tenant_id: str, draft_agent_id: int, state: Dict[str, Any]
) -> None:
    get_redis_service().client.setex(
        _state_key(tenant_id, draft_agent_id),
        _CACHE_TTL_SECONDS,
        json.dumps(state, ensure_ascii=False),
    )


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
    state = get_nl2agent_session_state(tenant, draft_id)
    review = state["requirements_review"]
    existing_fingerprint = review.get("fingerprint") or ""
    status = review.get("status")
    is_current = False
    if not existing_fingerprint or (
        status == "collecting" and existing_fingerprint != fingerprint
    ):
        review = {
            "status": "awaiting_confirmation",
            "summary": normalized_summary,
            "fingerprint": fingerprint,
        }
        is_current = True
    elif existing_fingerprint == fingerprint and status != "collecting":
        is_current = True
    state["requirements_review"] = review
    _set_nl2agent_session_state(tenant, draft_id, state)
    return {**deepcopy(review), "is_current": is_current}


def classify_requirements_message_intent(text: str) -> str:
    """Classify a pending-review message without confirming from chat text."""
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    normalized = re.sub(r"[^\w\u3400-\u4dbf\u4e00-\u9fff]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return "ambiguous"
    if any(marker in normalized for marker in _MODIFICATION_MARKERS):
        return "modify"
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
    if intent == "modify":
        review["status"] = "collecting"
        state["requirements_review"] = review
        _set_nl2agent_session_state(tenant, draft_id, state)
    return {"intent": intent, **deepcopy(review)}


def confirm_requirements_summary(
    tenant_id: Optional[str], draft_agent_id: Optional[int], fingerprint: str
) -> Dict[str, Any]:
    """Confirm the current requirements revision by its stable fingerprint."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    state = get_nl2agent_session_state(tenant, draft_id)
    review = state["requirements_review"]
    if not fingerprint or review.get("fingerprint") != fingerprint:
        raise Nl2AgentSessionCatalogError(
            "The requirements summary is stale. Reload the current summary before confirming."
        )
    if review.get("status") == "awaiting_confirmation":
        review["status"] = "confirmed"
        state["requirements_review"] = review
        _set_nl2agent_session_state(tenant, draft_id, state)
    elif review.get("status") != "confirmed":
        raise Nl2AgentSessionCatalogError(
            "The requirements summary is not awaiting confirmation."
        )
    return deepcopy(review)


def assert_requirements_confirmed(tenant_id: str, draft_agent_id: int) -> None:
    """Reject protected workflow actions until requirements are confirmed."""
    state = get_nl2agent_session_state(tenant_id, draft_agent_id)
    if state["requirements_review"].get("status") != "confirmed":
        raise Nl2AgentSessionCatalogError(
            "Confirm the requirements summary before continuing configuration."
        )


def _rollback_failed_card(
    state: Dict[str, Any], card_type: str, card_key: Optional[str]
) -> None:
    """Clear only unconfirmed delivery state owned by the failed card."""
    if card_type == "requirements_summary":
        review = state["requirements_review"]
        if review.get("status") == "awaiting_confirmation":
            state["requirements_review"] = {
                "status": "collecting",
                "summary": None,
                "fingerprint": "",
            }
        return

    if card_type == "local_resources":
        batches = state["recommendation_batches"]
        removable = [
            batch_id
            for batch_id, batch in batches.items()
            if batch.get("status") == "recommendations_ready"
        ]
        for batch_id in removable:
            batches.pop(batch_id, None)
        return

    if card_type in {"web_mcp", "web_skill"}:
        resource_type = "mcp" if card_type == "web_mcp" else "skill"
        batches = state["online_recommendation_batches"]
        removable = [
            batch_id
            for batch_id, batch in batches.items()
            if batch.get("resource_type") == resource_type
            and batch.get("status") == "recommendations_ready"
        ]
        for batch_id in removable:
            batches.pop(batch_id, None)
        if removable:
            state["online_configuration_confirmed"] = False


def record_card_delivery(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    message_key: str,
    card_type: str,
    status: str,
    card_key: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist one final-message card delivery receipt and safely recover failures."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    if card_type not in _CARD_DELIVERY_TYPES:
        raise Nl2AgentSessionCatalogError("Invalid NL2AGENT card type.")
    if status not in _CARD_DELIVERY_STATUSES:
        raise Nl2AgentSessionCatalogError("Invalid NL2AGENT card delivery status.")
    message_key = str(message_key or "").strip()
    if not message_key:
        raise Nl2AgentSessionCatalogError("message_key is required.")
    if status == "failed" and reason not in _CARD_DELIVERY_FAILURE_REASONS:
        raise Nl2AgentSessionCatalogError("Invalid NL2AGENT card failure reason.")

    state = get_nl2agent_session_state(tenant, draft_id)
    deliveries = state["card_delivery"]
    existing = deliveries.get(card_type, {})
    if (
        existing.get("message_key") == message_key
        and existing.get("status") == status
        and existing.get("card_key") == card_key
    ):
        return deepcopy(existing)

    retry_count = 0
    if status == "failed":
        retry_count = int(existing.get("retry_count", 0)) + 1
        _rollback_failed_card(state, card_type, card_key)
    delivery = {
        "message_key": message_key,
        "card_type": card_type,
        "status": status,
        "card_key": card_key,
        "reason": reason if status == "failed" else None,
        "retry_count": retry_count,
    }
    deliveries[card_type] = delivery
    _set_nl2agent_session_state(tenant, draft_id, state)
    return deepcopy(delivery)


def confirm_agent_identity(
    tenant_id: Optional[str], draft_agent_id: Optional[int]
) -> Dict[str, Any]:
    """Record that the user explicitly saved the draft display name."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    state = get_nl2agent_session_state(tenant, draft_id)
    state["identity_confirmed"] = True
    _set_nl2agent_session_state(tenant, draft_id, state)
    return deepcopy(state)


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
        "status",
        "mcp_id",
        "discovered_tool_ids",
        "bound_tool_ids",
        "error",
    }
    state = get_nl2agent_session_state(tenant, draft_id)
    workflow = state["mcp_workflows"].setdefault(
        recommendation_id, {"recommendation_id": recommendation_id}
    )
    workflow.update(
        {key: deepcopy(value) for key, value in values.items() if key in allowed}
    )
    _set_nl2agent_session_state(tenant, draft_id, state)
    return deepcopy(workflow)


def find_mcp_workflow_by_id(
    tenant_id: str, draft_agent_id: int, mcp_id: int
) -> tuple[str, Dict[str, Any]]:
    state = get_nl2agent_session_state(tenant_id, draft_agent_id)
    for recommendation_id, workflow in state["mcp_workflows"].items():
        if workflow.get("mcp_id") == int(mcp_id):
            return recommendation_id, deepcopy(workflow)
    raise Nl2AgentSessionCatalogError("Installed MCP workflow was not found.")


def assert_mcp_workflows_resolved(tenant_id: str, draft_agent_id: int) -> None:
    state = get_nl2agent_session_state(tenant_id, draft_agent_id)
    unresolved = [
        workflow
        for workflow in state["mcp_workflows"].values()
        if workflow.get("status") == "connected"
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
    normalized_keys = sorted(
        {str(key).strip() for key in item_keys if str(key).strip()}
    )
    state = get_nl2agent_session_state(tenant, draft_id)
    batches = state["online_recommendation_batches"]
    expected = {
        "resource_type": resource_type,
        "item_keys": normalized_keys,
        "status": "recommendations_ready",
    }
    existing = batches.get(recommendation_batch_id)
    if existing is None:
        batches[recommendation_batch_id] = expected
        state["online_configuration_confirmed"] = False
    elif (
        existing.get("resource_type") != resource_type
        or existing.get("item_keys") != normalized_keys
    ):
        raise Nl2AgentSessionCatalogError(
            "Online recommendation batch contents do not match the registered card."
        )
    _set_nl2agent_session_state(tenant, draft_id, state)
    return deepcopy(batches[recommendation_batch_id])


def complete_online_configuration(
    tenant_id: Optional[str], draft_agent_id: Optional[int]
) -> List[str]:
    """Complete all rendered online recommendation batches for one draft."""
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    state = get_nl2agent_session_state(tenant, draft_id)
    batches = state["online_recommendation_batches"]
    resource_types = {batch.get("resource_type") for batch in batches.values()}
    if not {"mcp", "skill"}.issubset(resource_types):
        raise Nl2AgentSessionCatalogError(
            "Show online resource recommendations for both MCP and Skill before completing configuration."
        )
    unresolved = [
        workflow
        for workflow in state["mcp_workflows"].values()
        if workflow.get("status") in {"installing", "connected"}
    ]
    if unresolved:
        raise Nl2AgentSessionCatalogError(
            "Bind discovered MCP tools or explicitly skip tool binding before completing online configuration."
        )
    for batch in batches.values():
        batch["status"] = "completed"
    state["online_configuration_confirmed"] = True
    _set_nl2agent_session_state(tenant, draft_id, state)
    return sorted(batches)


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
    state = get_nl2agent_session_state(tenant, draft_id)
    batches = state["recommendation_batches"]
    expected = {
        "status": "recommendations_ready",
        "tool_ids": sorted(set(map(int, tool_ids))),
        "skill_ids": sorted(set(map(int, skill_ids))),
    }
    existing = batches.get(recommendation_batch_id)
    if existing is None:
        batches[recommendation_batch_id] = expected
    elif (
        existing.get("tool_ids") != expected["tool_ids"]
        or existing.get("skill_ids") != expected["skill_ids"]
    ):
        raise Nl2AgentSessionCatalogError(
            "Recommendation batch contents do not match the registered card."
        )
    _set_nl2agent_session_state(tenant, draft_id, state)
    return deepcopy(batches[recommendation_batch_id])


def resolve_recommendation_batch(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    recommendation_batch_id: str,
    status: str,
    tool_ids: Optional[List[int]] = None,
    skill_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Mark one registered batch applied or skipped."""
    if status not in {"applied", "skipped"}:
        raise Nl2AgentSessionCatalogError("Invalid recommendation batch status.")
    tenant, draft_id = _validate_identifiers(tenant_id, draft_agent_id)
    state = get_nl2agent_session_state(tenant, draft_id)
    batch = state["recommendation_batches"].get(recommendation_batch_id)
    if batch is None:
        raise Nl2AgentSessionCatalogError("Recommendation batch was not registered.")
    if status == "applied":
        if not set(map(int, tool_ids or [])).issubset(set(batch["tool_ids"])):
            raise Nl2AgentSessionCatalogError(
                "Applied tools are not part of the recommendation batch."
            )
        if not set(map(int, skill_ids or [])).issubset(set(batch["skill_ids"])):
            raise Nl2AgentSessionCatalogError(
                "Applied skills are not part of the recommendation batch."
            )
        batch["applied_tool_ids"] = sorted(set(map(int, tool_ids or [])))
        batch["applied_skill_ids"] = sorted(set(map(int, skill_ids or [])))
    batch["status"] = status
    _set_nl2agent_session_state(tenant, draft_id, state)
    return deepcopy(batch)


def assert_resource_review_complete(tenant_id: str, draft_agent_id: int) -> None:
    state = get_nl2agent_session_state(tenant_id, draft_agent_id)
    batches = state["recommendation_batches"]
    if not batches:
        raise Nl2AgentSessionCatalogError(
            "Show the local resource recommendation card before finalizing."
        )
    if any(
        batch.get("status") == "recommendations_ready" for batch in batches.values()
    ):
        raise Nl2AgentSessionCatalogError(
            "Apply or skip every shown local resource recommendation before finalizing."
        )


def _validate_identifiers(
    tenant_id: Optional[str], draft_agent_id: Optional[int]
) -> tuple[str, int]:
    if not tenant_id or not draft_agent_id:
        raise Nl2AgentSessionCatalogError(
            "NL2AGENT session catalog requires tenant_id and draft_agent_id."
        )
    return tenant_id, int(draft_agent_id)


def _validate_catalogs(catalogs: Any) -> Dict[str, List[Dict[str, Any]]]:
    if not isinstance(catalogs, dict):
        raise Nl2AgentSessionCatalogError(
            "NL2AGENT session catalog payload is malformed."
        )

    payload: Dict[str, List[Dict[str, Any]]] = {}
    for key in _CATALOG_KEYS:
        value = catalogs.get(key)
        if not isinstance(value, list):
            raise Nl2AgentSessionCatalogError(
                f"NL2AGENT session catalog field '{key}' is malformed."
            )
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
