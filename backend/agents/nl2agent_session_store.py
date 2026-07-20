"""Durable database and Redis projections for NL2AGENT sessions."""

import json
import logging
from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional, TypeVar

from pydantic import ValidationError
from redis import RedisError

from agents.nl2agent_workflow import (
    WORKFLOW_SCHEMA_VERSION,
    Nl2AgentWorkflowState,
    state_to_dict,
)
from consts.exceptions import (
    Nl2AgentStateConflictError as _Nl2AgentStateConflictError,
    Nl2AgentWorkflowConflictError,
)
from utils.nl2agent_catalog_snapshot import catalog_snapshot_id

logger = logging.getLogger(__name__)

CATALOG_KEYS = (
    "tool_catalog",
    "skill_catalog",
    "registry_results",
    "community_results",
    "official_skills",
)
CACHE_KEY_PREFIX = "nl2agent:session_catalog"
CATALOG_SNAPSHOT_KEY_PREFIX = "nl2agent:catalog_snapshot"
STATE_KEY_PREFIX = "nl2agent:session_state"
CACHE_TTL_SECONDS = 24 * 60 * 60
CAS_MAX_RETRIES = 5


class Nl2AgentSessionCatalogError(Nl2AgentWorkflowConflictError):
    """Raised when NL2AGENT session snapshots cannot be persisted or loaded."""


class Nl2AgentStateConflictError(_Nl2AgentStateConflictError):
    """Raised when concurrent writers exhaust the state CAS retry budget."""


MutationResult = TypeVar("MutationResult")


def get_redis_service():
    """Resolve the shared Redis service lazily to keep imports lightweight."""
    from services.redis_service import get_redis_service as redis_service_factory

    return redis_service_factory()


def cache_key(tenant_id: str, draft_agent_id: int) -> str:
    return f"{CACHE_KEY_PREFIX}:{tenant_id}:{int(draft_agent_id)}"


def state_key(tenant_id: str, draft_agent_id: int) -> str:
    return f"{STATE_KEY_PREFIX}:{tenant_id}:{int(draft_agent_id)}"


def catalog_snapshot_key(tenant_id: str, snapshot_id: str) -> str:
    return f"{CATALOG_SNAPSHOT_KEY_PREFIX}:{tenant_id}:{snapshot_id}"


def load_durable_session(
    tenant_id: str, draft_agent_id: int
) -> Optional[Dict[str, Any]]:
    """Load one authoritative database snapshot."""
    from database.nl2agent_session_db import get_nl2agent_session_snapshot

    return get_nl2agent_session_snapshot(tenant_id, draft_agent_id)


def persist_workflow_state(
    tenant_id: str,
    draft_agent_id: int,
    expected_revision: int,
    workflow_state: Dict[str, Any],
) -> bool:
    """Advance the authoritative database workflow revision."""
    from database.nl2agent_session_db import update_nl2agent_workflow_state

    return update_nl2agent_workflow_state(
        tenant_id=tenant_id,
        draft_agent_id=draft_agent_id,
        expected_revision=expected_revision,
        workflow_schema_version=WORKFLOW_SCHEMA_VERSION,
        workflow_state=workflow_state,
    )


def cache_durable_snapshot(snapshot: Dict[str, Any]) -> None:
    """Refresh disposable Redis projections from one database snapshot."""
    tenant_id = str(snapshot["tenant_id"])
    draft_agent_id = int(snapshot["draft_agent_id"])
    snapshot_id = str(snapshot["catalog_snapshot_id"])
    pipe = get_redis_service().client.pipeline()
    pipe.set(
        state_key(tenant_id, draft_agent_id),
        json.dumps(snapshot["workflow_state"], ensure_ascii=False),
        ex=CACHE_TTL_SECONDS,
    )
    pipe.set(
        catalog_snapshot_key(tenant_id, snapshot_id),
        json.dumps(snapshot["catalog_snapshot"], ensure_ascii=False),
        ex=CACHE_TTL_SECONDS,
    )
    pipe.set(
        cache_key(tenant_id, draft_agent_id),
        json.dumps({"snapshot_id": snapshot_id}),
        ex=CACHE_TTL_SECONDS,
    )
    pipe.execute()


def recover_durable_session(
    tenant_id: str, draft_agent_id: int
) -> Optional[Dict[str, Any]]:
    snapshot = load_durable_session(tenant_id, draft_agent_id)
    if snapshot is not None:
        cache_durable_snapshot(snapshot)
    return snapshot


def refresh_cache_best_effort(snapshot: Optional[Dict[str, Any]]) -> None:
    """Refresh Redis without turning a committed database write into a failure."""
    if snapshot is None:
        return
    try:
        cache_durable_snapshot(snapshot)
    except Exception:
        logger.warning(
            "Failed to refresh disposable NL2AGENT Redis cache: tenant_id=%s draft_agent_id=%s",
            snapshot.get("tenant_id"),
            snapshot.get("draft_agent_id"),
            exc_info=True,
        )


def recover_committed_cache_best_effort(tenant_id: str, draft_agent_id: int) -> None:
    """Reconcile cache after commit without changing the committed outcome."""
    try:
        snapshot = load_durable_session(tenant_id, draft_agent_id)
    except Exception:
        logger.warning(
            "Failed to reload committed NL2AGENT state for cache reconciliation: "
            "tenant_id=%s draft_agent_id=%s",
            tenant_id,
            draft_agent_id,
            exc_info=True,
        )
        return
    refresh_cache_best_effort(snapshot)


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
    """Load the authoritative database workflow and repair its cache projection."""
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
    state = state_to_dict(parse_session_state(raw, tenant, draft_id))
    refresh_cache_best_effort(snapshot)
    return state


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
) -> MutationResult:
    """Atomically mutate durable workflow state with bounded database CAS retries."""
    for _attempt in range(CAS_MAX_RETRIES):
        snapshot = load_durable_session(tenant_id, draft_agent_id)
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
        original_state = state_to_dict(state)
        result = mutator(state)
        try:
            validated_state = Nl2AgentWorkflowState.model_validate(state_to_dict(state))
        except ValidationError as exc:
            raise Nl2AgentSessionCatalogError(
                "NL2AGENT workflow state exceeds its schema or capacity limits."
            ) from exc
        if state_to_dict(validated_state) == original_state:
            return deepcopy(result)
        validated_state.revision += 1
        persisted_state = state_to_dict(validated_state)
        if not persist_workflow_state(
            tenant_id,
            draft_agent_id,
            expected_revision=int(original_state["revision"]),
            workflow_state=persisted_state,
        ):
            _recover_active_session_after_conflict(tenant_id, draft_agent_id)
            continue
        recover_committed_cache_best_effort(tenant_id, draft_agent_id)
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


def set_session_catalogs(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    catalogs: Dict[str, List[Dict[str, Any]]],
) -> None:
    """Cache an immutable catalog snapshot and its per-session reference."""
    tenant, draft_id = validate_identifiers(tenant_id, draft_agent_id)
    payload = validate_catalogs(catalogs)
    snapshot_id = catalog_snapshot_id(payload)
    try:
        pipe = get_redis_service().client.pipeline()
        pipe.set(
            catalog_snapshot_key(tenant, snapshot_id),
            json.dumps(payload, ensure_ascii=False),
            ex=CACHE_TTL_SECONDS,
        )
        pipe.set(
            cache_key(tenant, draft_id),
            json.dumps({"snapshot_id": snapshot_id}),
            ex=CACHE_TTL_SECONDS,
        )
        pipe.execute()
    except Exception:
        logger.warning(
            "NL2AGENT catalog cache is unavailable during initialization; "
            "the durable transaction remains authoritative: tenant_id=%s draft_agent_id=%s",
            tenant,
            draft_id,
            exc_info=True,
        )


def get_session_catalogs(
    tenant_id: Optional[str], draft_agent_id: Optional[int]
) -> Dict[str, List[Dict[str, Any]]]:
    """Load immutable catalogs from Redis or the durable database snapshot."""
    tenant, draft_id = validate_identifiers(tenant_id, draft_agent_id)
    try:
        client = get_redis_service().client
        raw_reference = client.get(cache_key(tenant, draft_id))
        catalogs = None
        if raw_reference is not None:
            try:
                reference = json.loads(raw_reference)
                if isinstance(reference, dict) and reference.get("snapshot_id"):
                    raw_snapshot = client.get(
                        catalog_snapshot_key(tenant, str(reference["snapshot_id"]))
                    )
                    if raw_snapshot is not None:
                        catalogs = validate_catalogs(json.loads(raw_snapshot))
                else:
                    catalogs = validate_catalogs(reference)
            except (
                json.JSONDecodeError,
                TypeError,
                Nl2AgentSessionCatalogError,
            ) as exc:
                logger.error(
                    "Malformed NL2AGENT catalogs: tenant_id=%s draft_agent_id=%s",
                    tenant,
                    draft_id,
                    exc_info=True,
                )
                raise Nl2AgentSessionCatalogError(
                    f"Malformed NL2AGENT catalogs for tenant={tenant}, draft_agent_id={draft_id}."
                ) from exc
        if catalogs is None:
            snapshot = recover_durable_session(tenant, draft_id)
            catalogs = (
                validate_catalogs(snapshot["catalog_snapshot"])
                if snapshot is not None
                else None
            )
    except Exception as exc:
        if not isinstance(exc, RedisError):
            raise
        logger.warning(
            "NL2AGENT catalog cache is unavailable; loading durable snapshot: "
            "tenant_id=%s draft_agent_id=%s",
            tenant,
            draft_id,
            exc_info=True,
        )
        snapshot = load_durable_session(tenant, draft_id)
        catalogs = (
            validate_catalogs(snapshot["catalog_snapshot"])
            if snapshot is not None
            else None
        )
    except Nl2AgentSessionCatalogError:
        raise
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
