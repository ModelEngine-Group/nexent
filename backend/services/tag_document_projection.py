"""Provider contracts and orchestration for knowledge document tag projections."""

import base64
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from database import document_tag_projection_db
from database.tag_management_db import TagManagementDB
from services.tag_resource_adapters import (
    AIDP_DOCUMENT_PROVIDER,
    KNOWLEDGE_CONTENT_LIBRARY_CODE,
    LOCAL_DOCUMENT_PROVIDER,
    _encode_document_resource_id,
)

logger = logging.getLogger(__name__)

PROJECTION_PROVIDERS = (LOCAL_DOCUMENT_PROVIDER, AIDP_DOCUMENT_PROVIDER)
PROJECTION_INDEX_NAME = "nexent_tag_projection"

STATUS_PENDING = "pending"
STATUS_SYNCED = "synced"
STATUS_FAILED = "failed"
STATUS_UNSUPPORTED = "unsupported"
KNOWLEDGE_DOCUMENT_TYPE = "knowledge_document"


class DocumentTagProjectionError(Exception):
    pass


class DocumentTagProjectionRejected(DocumentTagProjectionError):
    pass


class DocumentTagProjectionUnsupported(DocumentTagProjectionError):
    pass


class DocumentProjectionProvider(Protocol):
    provider_name: str

    def capability(self) -> str:
        ...

    def project(self, payload: dict[str, Any]) -> None:
        ...

    def clear(self, resource_id: str) -> None:
        ...


class LocalElasticsearchDocumentProjectionProvider:
    provider_name = LOCAL_DOCUMENT_PROVIDER

    def __init__(self, vdb_core: Any = None) -> None:
        self._vdb_core = vdb_core

    def capability(self) -> str:
        return "full"

    def _core(self) -> Any:
        if self._vdb_core is not None:
            return self._vdb_core
        from management.services.knowledge_base.service import get_vector_db_core

        return get_vector_db_core()

    def project(self, payload: dict[str, Any]) -> None:
        core = self._core()
        core.create_index(PROJECTION_INDEX_NAME)
        core.create_chunk(
            PROJECTION_INDEX_NAME,
            {
                "id": payload["resource_id"],
                "path_or_url": payload["resource_id"],
                "title": payload.get("document_name") or payload["provider_document_id"],
                "filename": payload["provider_document_id"],
                "content": "",
                "metadata": {
                    "tenant_id": payload["tenant_id"],
                    "provider": payload["provider"],
                    "knowledge_base_id": payload["knowledge_base_id"],
                    "provider_document_id": payload["provider_document_id"],
                    "tags": payload["tags"],
                    "version": payload["version"],
                },
            },
        )

    def clear(self, resource_id: str) -> None:
        self._core().delete_documents(PROJECTION_INDEX_NAME, resource_id)


class AidpDocumentProjectionProvider:
    provider_name = AIDP_DOCUMENT_PROVIDER

    def capability(self) -> str:
        return "unsupported"

    def project(self, payload: dict[str, Any]) -> None:
        raise DocumentTagProjectionUnsupported(
            "AIDP does not expose a document metadata write endpoint; "
            "projection is unsupported until the provider API adds one"
        )

    def clear(self, resource_id: str) -> None:
        return None


def get_projection_provider(
    provider: str,
    *,
    vdb_core: Any = None,
) -> DocumentProjectionProvider:
    normalized = (provider or "").strip().lower()
    if normalized == LOCAL_DOCUMENT_PROVIDER:
        return LocalElasticsearchDocumentProjectionProvider(vdb_core=vdb_core)
    if normalized == AIDP_DOCUMENT_PROVIDER:
        return AidpDocumentProjectionProvider()
    raise ValueError(f"Unsupported document projection provider: {provider}")


def decode_document_resource_id(resource_id: str) -> tuple[str, str, str]:
    """Reverse the canonical encoded document resource id into its identity tuple."""

    try:
        payload = base64.urlsafe_b64decode(resource_id.encode("ascii"))
        provider, knowledge_base_id, provider_document_id = json.loads(payload)
    except Exception as error:  # noqa: BLE001 - decode boundary for external ids
        raise ValueError(f"Invalid document resource id: {resource_id}") from error
    return str(provider), str(knowledge_base_id), str(provider_document_id)


def _build_tags(assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "definition_id": item["definition_id"],
            "definition_key": item["definition_key"],
            "definition_name": item["definition_name"],
            "value_id": item["value_id"],
            "display_value": item["display_value"],
        }
        for item in assignments
    ]


def _backoff_delay(retry_count: int) -> timedelta:
    seconds = min(30 * (2 ** max(retry_count - 1, 0)), 900)
    return timedelta(seconds=seconds)


def _status_dict(state: dict[str, Any] | None) -> dict[str, Any]:
    if state is None:
        return {
            "status": "not_projected",
            "version": 0,
            "tag_count": 0,
            "last_error": None,
            "retry_count": 0,
            "last_attempt_at": None,
            "next_attempt_at": None,
            "update_time": None,
        }
    return {
        "status": state["status"],
        "version": state["version"],
        "tag_count": len(state.get("payload") or []),
        "last_error": state.get("last_error"),
        "retry_count": state.get("retry_count") or 0,
        "last_attempt_at": state.get("last_attempt_at"),
        "next_attempt_at": state.get("next_attempt_at"),
        "update_time": state.get("update_time"),
    }


def project_document_assignments(
    tenant_id: str,
    provider: str,
    knowledge_base_id: str,
    provider_document_id: str,
    actor_id: str,
    *,
    vdb_core: Any = None,
    enabled: bool = True,
) -> dict[str, Any]:
    if not enabled:
        return _status_dict(None)
    normalized = (provider or "").strip().lower()
    if normalized not in PROJECTION_PROVIDERS:
        raise ValueError(f"Unsupported document projection provider: {provider}")

    resource_id = _encode_document_resource_id(
        normalized, knowledge_base_id, provider_document_id
    )
    assignments = TagManagementDB.list_resource_assignments(
        tenant_id,
        KNOWLEDGE_DOCUMENT_TYPE,
        resource_id,
        KNOWLEDGE_CONTENT_LIBRARY_CODE,
    )
    tags = _build_tags(assignments)
    current = document_tag_projection_db.get_projection_state(
        tenant_id, normalized, knowledge_base_id, provider_document_id
    )
    if (
        current is not None
        and current.get("payload") == tags
        and current.get("status") == STATUS_SYNCED
    ):
        return _status_dict(current)

    if current is not None and current.get("payload") == tags:
        version = current.get("version") or 0
    else:
        version = ((current.get("version") or 0) + 1) if current is not None else 1
    now = datetime.now(timezone.utc)
    payload = {
        "tenant_id": tenant_id,
        "provider": normalized,
        "knowledge_base_id": knowledge_base_id,
        "provider_document_id": provider_document_id,
        "resource_id": resource_id,
        "version": version,
        "tags": tags,
    }
    provider_impl = get_projection_provider(normalized, vdb_core=vdb_core)
    if provider_impl.capability() != "full":
        state = document_tag_projection_db.upsert_projection_state(
            tenant_id=tenant_id,
            provider=normalized,
            knowledge_base_id=knowledge_base_id,
            provider_document_id=provider_document_id,
            resource_id=resource_id,
            status=STATUS_UNSUPPORTED,
            version=version,
            payload=tags,
            last_attempt_at=now,
            last_error=(
                "provider does not expose a metadata write endpoint; "
                "retrieval filtering will not claim this document matches"
            ),
            next_attempt_at=None,
            retry_count=0,
            actor_id=actor_id,
        )
        return _status_dict(state)

    try:
        provider_impl.project(payload)
    except DocumentTagProjectionUnsupported as error:
        state = document_tag_projection_db.upsert_projection_state(
            tenant_id=tenant_id,
            provider=normalized,
            knowledge_base_id=knowledge_base_id,
            provider_document_id=provider_document_id,
            resource_id=resource_id,
            status=STATUS_UNSUPPORTED,
            version=version,
            payload=tags,
            last_attempt_at=now,
            last_error=str(error),
            next_attempt_at=None,
            retry_count=0,
            actor_id=actor_id,
        )
        return _status_dict(state)
    except Exception as error:  # noqa: BLE001 - provider boundary; preserve canonical assignments
        retry_count = (current.get("retry_count") or 0) + 1
        state = document_tag_projection_db.upsert_projection_state(
            tenant_id=tenant_id,
            provider=normalized,
            knowledge_base_id=knowledge_base_id,
            provider_document_id=provider_document_id,
            resource_id=resource_id,
            status=STATUS_FAILED,
            version=version,
            payload=tags,
            retry_count=retry_count,
            last_attempt_at=now,
            last_error=str(error),
            next_attempt_at=now + _backoff_delay(retry_count),
            actor_id=actor_id,
        )
        logger.warning(
            "Document tag projection failed for %s/%s/%s: %s",
            tenant_id,
            knowledge_base_id,
            provider_document_id,
            error,
        )
        return _status_dict(state)

    state = document_tag_projection_db.upsert_projection_state(
        tenant_id=tenant_id,
        provider=normalized,
        knowledge_base_id=knowledge_base_id,
        provider_document_id=provider_document_id,
        resource_id=resource_id,
        status=STATUS_SYNCED,
        version=version,
        payload=tags,
        last_attempt_at=now,
        last_error=None,
        next_attempt_at=None,
        retry_count=0,
        actor_id=actor_id,
    )
    return _status_dict(state)


def clear_document_projection(
    tenant_id: str,
    provider: str,
    knowledge_base_id: str,
    provider_document_id: str,
    *,
    vdb_core: Any = None,
) -> bool:
    normalized = (provider or "").strip().lower()
    resource_id = _encode_document_resource_id(
        normalized, knowledge_base_id, provider_document_id
    )
    try:
        get_projection_provider(normalized, vdb_core=vdb_core).clear(resource_id)
    except Exception as error:  # noqa: BLE001 - best-effort provider cleanup
        logger.warning(
            "Failed to clear provider projection for %s/%s: %s",
            knowledge_base_id,
            provider_document_id,
            error,
        )
    return document_tag_projection_db.delete_projection_state(
        tenant_id, normalized, knowledge_base_id, provider_document_id
    )


def clear_projection_states_for_knowledge_base(
    tenant_id: str,
    provider: str,
    knowledge_base_id: str,
) -> int:
    normalized = (provider or "").strip().lower()
    return document_tag_projection_db.delete_projection_states_for_knowledge_base(
        tenant_id, normalized, knowledge_base_id
    )


def get_document_projection_status(
    tenant_id: str,
    provider: str,
    knowledge_base_id: str,
    provider_document_id: str,
) -> dict[str, Any]:
    normalized = (provider or "").strip().lower()
    state = document_tag_projection_db.get_projection_state(
        tenant_id, normalized, knowledge_base_id, provider_document_id
    )
    return _status_dict(state)


def document_projection_status_dict(
    state: dict[str, Any] | None,
) -> dict[str, Any]:
    """Public status view for one raw projection state row."""

    return _status_dict(state)


def retry_pending_document_projections(
    tenant_id: str | None = None,
    limit: int = 50,
    *,
    vdb_core: Any = None,
) -> dict[str, Any]:
    outcomes: dict[str, Any] = {"attempted": 0, "synced": 0, "failed": 0, "unsupported": 0}
    for state in document_tag_projection_db.list_due_projection_states(
        tenant_id=tenant_id, limit=limit
    ):
        try:
            result = project_document_assignments(
                state["tenant_id"],
                state["provider"],
                state["knowledge_base_id"],
                state["provider_document_id"],
                "projection:retry",
                vdb_core=vdb_core,
            )
        except Exception as error:  # noqa: BLE001 - retry loop must never halt the batch
            logger.error("Projection retry failed unexpectedly: %s", error)
            result = {"status": STATUS_FAILED}
        outcomes["attempted"] = outcomes.get("attempted", 0) + 1
        status = result.get("status", STATUS_FAILED)
        outcomes[status] = outcomes.get(status, 0) + 1
    return outcomes


def filter_document_ids_by_predicates(
    tenant_id: str,
    provider: str,
    knowledge_base_id: str,
    predicates: list[dict[str, Any]],
) -> list[str]:
    normalized = (provider or "").strip().lower()
    merged: dict[int, set[int]] = {}
    for predicate in predicates:
        definition_id = int(predicate["definition_id"])
        merged.setdefault(definition_id, set()).update(
            int(value_id) for value_id in predicate.get("value_ids", [])
        )
    effective = [
        {"definition_id": definition_id, "value_ids": sorted(values)}
        for definition_id, values in merged.items()
        if values
    ]
    return document_tag_projection_db.filter_document_ids_by_predicates(
        tenant_id, normalized, knowledge_base_id, effective
    )
