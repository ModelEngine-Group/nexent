"""Durable lease and checkpoint repository for NL2AGENT installations."""

from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import func, text

from database.client import as_dict, get_db_session
from database.db_models import Nl2AgentInstallationOperation
from database.nl2agent_session_db import Nl2AgentSessionIdentity


class InstallationLeaseConflictError(RuntimeError):
    """Raised when another worker owns a live operation lease."""


class InstallationLeaseActiveError(InstallationLeaseConflictError):
    """Raised when another worker still owns a non-expired lease."""


class InstallationRequestConflictError(InstallationLeaseConflictError):
    """Raised when one installation key is reused for a different request."""


def _identity_filters(identity: Nl2AgentSessionIdentity):
    return (
        Nl2AgentInstallationOperation.tenant_id == identity.tenant_id,
        Nl2AgentInstallationOperation.user_id == identity.user_id,
        Nl2AgentInstallationOperation.runner_agent_id == identity.runner_agent_id,
        Nl2AgentInstallationOperation.draft_agent_id == identity.draft_agent_id,
        Nl2AgentInstallationOperation.conversation_id == identity.conversation_id,
        Nl2AgentInstallationOperation.delete_flag != "Y",
    )


def list_installation_operations(
    *,
    identity: Nl2AgentSessionIdentity,
    resource_type: Optional[str] = None,
    statuses: Optional[Iterable[str]] = None,
) -> list[Dict[str, Any]]:
    """List scoped operations for workflow projection without exposing credentials."""
    with get_db_session() as session:
        query = session.query(Nl2AgentInstallationOperation).filter(
            *_identity_filters(identity)
        )
        if resource_type is not None:
            query = query.filter(
                Nl2AgentInstallationOperation.resource_type == resource_type
            )
        normalized_statuses = tuple(statuses or ())
        if normalized_statuses:
            query = query.filter(
                Nl2AgentInstallationOperation.status.in_(normalized_statuses)
            )
        return [as_dict(record) for record in query.all()]


def claim_installation_operation(
    *,
    identity: Nl2AgentSessionIdentity,
    operation_id: str,
    installation_key: str,
    request_fingerprint: str,
    resource_type: str,
    lease_owner: str,
    lease_expires_at: datetime,
) -> Dict[str, Any]:
    """Create, replay, or take over one operation using a short transaction."""
    with get_db_session() as session:
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {
                "lock_key": f"{identity.tenant_id}:{identity.draft_agent_id}:{installation_key}"
            },
        )
        record = (
            session.query(Nl2AgentInstallationOperation)
            .filter(
                *_identity_filters(identity),
                Nl2AgentInstallationOperation.installation_key == installation_key,
            )
            .with_for_update()
            .first()
        )
        now = datetime.utcnow()
        if record is not None:
            if record.request_fingerprint != request_fingerprint:
                raise InstallationRequestConflictError(
                    "Installation key was already used for a different request."
                )
            if record.status == "completed":
                return as_dict(record)
            lease_takeover = (
                record.status == "running"
                and record.lease_owner != lease_owner
                and (record.lease_expires_at is None or record.lease_expires_at <= now)
            )
            if (
                record.status == "running"
                and record.lease_expires_at is not None
                and record.lease_expires_at > now
                and record.lease_owner != lease_owner
            ):
                raise InstallationLeaseActiveError(
                    "Installation is already in progress."
                )
            record.status = "running"
            record.lease_owner = lease_owner
            record.lease_expires_at = lease_expires_at
            record.attempt = int(record.attempt or 0) + 1
            record.error = None
            record.updated_by = identity.user_id
            session.flush()
            result = as_dict(record)
            result["_lease_takeover"] = lease_takeover
            return result

        record = Nl2AgentInstallationOperation(
            operation_id=operation_id,
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            runner_agent_id=identity.runner_agent_id,
            draft_agent_id=identity.draft_agent_id,
            conversation_id=identity.conversation_id,
            installation_key=installation_key,
            request_fingerprint=request_fingerprint,
            resource_type=resource_type,
            status="running",
            checkpoint={},
            attempt=1,
            lease_owner=lease_owner,
            lease_expires_at=lease_expires_at,
            created_by=identity.user_id,
            updated_by=identity.user_id,
        )
        session.add(record)
        session.flush()
        return as_dict(record)


def renew_installation_operation(
    *, operation_id: str, lease_owner: str, lease_expires_at: datetime
) -> bool:
    """Extend a live lease only for its current owner."""
    with get_db_session() as session:
        updated = (
            session.query(Nl2AgentInstallationOperation)
            .filter(
                Nl2AgentInstallationOperation.operation_id == operation_id,
                Nl2AgentInstallationOperation.status == "running",
                Nl2AgentInstallationOperation.lease_owner == lease_owner,
                Nl2AgentInstallationOperation.delete_flag != "Y",
            )
            .update(
                {"lease_expires_at": lease_expires_at, "update_time": func.now()},
                synchronize_session=False,
            )
        )
        return updated == 1


def transition_installation_operation(
    *,
    operation_id: str,
    lease_owner: str,
    status: str,
    checkpoint: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[Dict[str, Any]] = None,
) -> bool:
    """Persist a secret-free checkpoint or terminal outcome for the lease owner."""
    if status not in {"pending", "running", "completed", "failed"}:
        raise ValueError("Invalid installation operation status")
    values: Dict[str, Any] = {"status": status, "update_time": func.now()}
    if checkpoint is not None:
        values["checkpoint"] = checkpoint
    if result is not None:
        values["result"] = result
    if error is not None:
        values["error"] = error
    elif status == "completed":
        values["error"] = None
    if status != "running":
        values.update({"lease_owner": None, "lease_expires_at": None})
    with get_db_session() as session:
        updated = (
            session.query(Nl2AgentInstallationOperation)
            .filter(
                Nl2AgentInstallationOperation.operation_id == operation_id,
                Nl2AgentInstallationOperation.status == "running",
                Nl2AgentInstallationOperation.lease_owner == lease_owner,
                Nl2AgentInstallationOperation.delete_flag != "Y",
            )
            .update(values, synchronize_session=False)
        )
        return updated == 1


def release_installation_lease(*, operation_id: str, lease_owner: str) -> bool:
    """Release only the lease; the operation row remains retryable."""
    with get_db_session() as session:
        updated = (
            session.query(Nl2AgentInstallationOperation)
            .filter(
                Nl2AgentInstallationOperation.operation_id == operation_id,
                Nl2AgentInstallationOperation.lease_owner == lease_owner,
                Nl2AgentInstallationOperation.status == "running",
                Nl2AgentInstallationOperation.delete_flag != "Y",
            )
            .update(
                {
                    "status": "pending",
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "update_time": func.now(),
                },
                synchronize_session=False,
            )
        )
        return updated == 1
