"""Authoritative PostgreSQL session storage for NL2AGENT."""

import json
import logging
from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional, TypeVar

from pydantic import ValidationError

from agents.nl2agent_workflow import (
    WORKFLOW_SCHEMA_VERSION,
    Nl2AgentWorkflowState,
    state_to_dict,
)
from consts.exceptions import (
    Nl2AgentStateConflictError as _Nl2AgentStateConflictError,
    Nl2AgentWorkflowConflictError,
)

logger = logging.getLogger(__name__)

CATALOG_KEYS = (
    "tool_catalog",
    "skill_catalog",
    "registry_results",
    "community_results",
    "official_skills",
)
CAS_MAX_RETRIES = 5


class Nl2AgentSessionCatalogError(Nl2AgentWorkflowConflictError):
    """Raised when NL2AGENT session snapshots cannot be persisted or loaded."""


class Nl2AgentStateConflictError(_Nl2AgentStateConflictError):
    """Raised when concurrent writers exhaust the state CAS retry budget."""


MutationResult = TypeVar("MutationResult")


def load_durable_session(
    tenant_id: str, draft_agent_id: int, *, db_session=None
) -> Optional[Dict[str, Any]]:
    """Load one authoritative database snapshot."""
    from database.nl2agent_session_db import get_nl2agent_session_snapshot

    if db_session is None:
        return get_nl2agent_session_snapshot(tenant_id, draft_agent_id)
    return get_nl2agent_session_snapshot(tenant_id, draft_agent_id, db_session=db_session)


def persist_workflow_state(
    tenant_id: str,
    draft_agent_id: int,
    expected_revision: int,
    workflow_state: Dict[str, Any],
    *,
    db_session=None,
) -> bool:
    """Advance the authoritative database workflow revision."""
    from database.nl2agent_session_db import update_nl2agent_workflow_state

    return update_nl2agent_workflow_state(
        tenant_id=tenant_id,
        draft_agent_id=draft_agent_id,
        expected_revision=expected_revision,
        workflow_schema_version=WORKFLOW_SCHEMA_VERSION,
        workflow_state=workflow_state,
        db_session=db_session,
    )


def validate_identifiers(
    tenant_id: Optional[str], draft_agent_id: Optional[int]
) -> tuple[str, int]:
    if not tenant_id or not draft_agent_id:
        raise Nl2AgentSessionCatalogError(
            "NL2AGENT session catalog requires tenant_id and draft_agent_id."
        )
    return tenant_id, int(draft_agent_id)


def initialize_session_state(
    tenant_id: Optional[str], draft_agent_id: Optional[int], conversation_id: int
) -> Dict[str, Any]:
    """Build the initial workflow state; the database transaction persists it."""
    validate_identifiers(tenant_id, draft_agent_id)
    state = Nl2AgentWorkflowState(conversation_id=int(conversation_id))
    return state_to_dict(state)


def parse_session_state(
    raw: Any, tenant_id: str, draft_agent_id: int
) -> Nl2AgentWorkflowState:
    if raw is None:
        raise Nl2AgentSessionCatalogError(
            f"NL2AGENT session state is missing for tenant={tenant_id}, draft_agent_id={draft_agent_id}."
        )
    try:
        payload = json.loads(raw)
        if payload.get("schema_version") != WORKFLOW_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version={payload.get('schema_version')!r}"
            )
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


def get_session_state(
    tenant_id: Optional[str], draft_agent_id: Optional[int]
) -> Dict[str, Any]:
    """Load the authoritative database workflow."""
    tenant, draft_id = validate_identifiers(tenant_id, draft_agent_id)
    try:
        snapshot = load_durable_session(tenant, draft_id)
        raw = (
            json.dumps(snapshot["workflow_state"], ensure_ascii=False)
            if snapshot is not None
            else None
        )
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
    return state_to_dict(parse_session_state(raw, tenant, draft_id))


def _recover_active_session_after_conflict(tenant_id: str, draft_agent_id: int) -> None:
    snapshot = load_durable_session(tenant_id, draft_agent_id)
    if snapshot is None:
        raise Nl2AgentSessionCatalogError("NL2AGENT durable session is missing.")
    if snapshot.get("status") != "active":
        raise Nl2AgentSessionCatalogError("NL2AGENT session is no longer active.")


def mutate_session_state(
    tenant_id: str,
    draft_agent_id: int,
    mutator: Callable[[Nl2AgentWorkflowState], MutationResult],
    *,
    db_session=None,
) -> MutationResult:
    """Atomically mutate durable workflow state with bounded database CAS retries."""
    for _attempt in range(CAS_MAX_RETRIES):
        snapshot = (
            load_durable_session(tenant_id, draft_agent_id)
            if db_session is None
            else load_durable_session(tenant_id, draft_agent_id, db_session=db_session)
        )
        if snapshot is None:
            raise Nl2AgentSessionCatalogError(
                f"NL2AGENT session state is missing for tenant={tenant_id}, "
                f"draft_agent_id={draft_agent_id}."
            )
        if snapshot.get("status") != "active":
            raise Nl2AgentSessionCatalogError("NL2AGENT session is no longer active.")
        state = parse_session_state(
            json.dumps(snapshot["workflow_state"], ensure_ascii=False),
            tenant_id,
            draft_agent_id,
        )
        original_state = state.model_dump(mode="json")
        result = mutator(state)
        try:
            validated_state = Nl2AgentWorkflowState.model_validate(state.model_dump(mode="json"))
        except ValidationError as exc:
            raise Nl2AgentSessionCatalogError(
                "NL2AGENT workflow state exceeds its schema or capacity limits."
            ) from exc
        if validated_state.model_dump(mode="json") == original_state:
            return deepcopy(result)
        validated_state.revision += 1
        persisted_state = state_to_dict(validated_state)
        persist_kwargs = {
            "expected_revision": int(original_state["revision"]),
            "workflow_state": persisted_state,
        }
        if db_session is not None:
            persist_kwargs["db_session"] = db_session
        if not persist_workflow_state(tenant_id, draft_agent_id, **persist_kwargs):
            _recover_active_session_after_conflict(tenant_id, draft_agent_id)
            continue
        return deepcopy(result)
    raise Nl2AgentStateConflictError(
        f"NL2AGENT session state changed concurrently for tenant={tenant_id}, draft_agent_id={draft_agent_id}."
    )


def validate_catalogs(catalogs: Any) -> Dict[str, List[Dict[str, Any]]]:
    if not isinstance(catalogs, dict):
        raise Nl2AgentSessionCatalogError(
            "NL2AGENT session catalog payload is malformed."
        )
    payload: Dict[str, List[Dict[str, Any]]] = {}
    for key in CATALOG_KEYS:
        value = catalogs.get(key)
        if not isinstance(value, list):
            raise Nl2AgentSessionCatalogError(
                f"NL2AGENT session catalog field '{key}' is malformed."
            )
        payload[key] = deepcopy(value)
    return payload


def get_session_catalogs(
    tenant_id: Optional[str], draft_agent_id: Optional[int]
) -> Dict[str, List[Dict[str, Any]]]:
    """Load immutable catalogs directly from the authoritative session row."""
    tenant, draft_id = validate_identifiers(tenant_id, draft_agent_id)
    snapshot = load_durable_session(tenant, draft_id)
    if snapshot is None:
        raise Nl2AgentSessionCatalogError(
            f"NL2AGENT catalogs are missing for tenant={tenant}, draft_agent_id={draft_id}."
        )
    catalogs = validate_catalogs(
        snapshot.get("session_catalogs") or snapshot.get("catalog_snapshot")
    )
    if catalogs is None:
        logger.error(
            "NL2AGENT catalogs are missing: tenant_id=%s draft_agent_id=%s",
            tenant,
            draft_id,
        )
        raise Nl2AgentSessionCatalogError(
            f"NL2AGENT catalogs are missing for tenant={tenant}, draft_agent_id={draft_id}."
        )
    return validate_catalogs(catalogs)
