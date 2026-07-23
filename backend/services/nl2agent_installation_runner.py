"""Durable, lease-backed execution for NL2AGENT installation operations."""

import asyncio
import hashlib
import json
import logging
import threading
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, TypeVar

from consts.exceptions import AgentRunException, Nl2AgentOperationError
from database.nl2agent_installation_db import (
    InstallationLeaseActiveError,
    InstallationRequestConflictError,
    claim_installation_operation,
    release_installation_lease,
    renew_installation_operation,
    transition_installation_operation,
)
from database.nl2agent_session_db import Nl2AgentSessionIdentity
from utils.nl2agent_observability import record_installation

logger = logging.getLogger(__name__)
BlockingResult = TypeVar("BlockingResult")

_DEFAULT_LEASE_SECONDS = 5 * 60
_DEFAULT_HEARTBEAT_SECONDS = 60
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "header",
    "password",
    "private_key",
    "secret",
    "token",
)


def fingerprint_installation_request(payload: Dict[str, Any]) -> str:
    """Hash a canonical request without persisting submitted configuration values."""
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def derive_installation_operation_id(
    identity: Nl2AgentSessionIdentity,
    resource_type: str,
    installation_key: str,
) -> str:
    """Derive the server-owned operation identifier from its complete scope."""
    scope = ":".join(
        (
            identity.tenant_id,
            identity.user_id,
            str(identity.runner_agent_id),
            str(identity.draft_agent_id),
            str(identity.conversation_id),
            resource_type,
            installation_key,
        )
    )
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()


def sanitize_installation_payload(value: Any) -> Any:
    """Recursively remove credential-bearing fields before durable persistence."""
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).casefold().replace("-", "_")
            if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
                continue
            sanitized[str(key)] = sanitize_installation_payload(item)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [sanitize_installation_payload(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


async def run_blocking_installation(
    operation: Callable[..., BlockingResult],
    *args: Any,
    **kwargs: Any,
) -> BlockingResult:
    """Run blocking provider I/O in an owned thread while heartbeat stays live."""
    loop = asyncio.get_running_loop()
    completed: asyncio.Future[BlockingResult] = loop.create_future()

    def set_result(result: BlockingResult) -> None:
        if not completed.done():
            completed.set_result(result)

    def set_exception(exc: BaseException) -> None:
        if not completed.done():
            completed.set_exception(exc)

    def invoke() -> None:
        try:
            result = operation(*args, **kwargs)
        except BaseException as exc:
            loop.call_soon_threadsafe(set_exception, exc)
        else:
            loop.call_soon_threadsafe(set_result, result)

    worker = threading.Thread(
        target=invoke,
        name="nl2agent-installation-provider",
        daemon=True,
    )
    worker.start()
    try:
        return await completed
    finally:
        worker.join()


@dataclass(frozen=True)
class InstallationRunnerRepository:
    """Short PostgreSQL operations used by the durable runner."""

    claim: Callable[..., Dict[str, Any]]
    renew: Callable[..., bool]
    transition: Callable[..., bool]
    release: Callable[..., bool]


@dataclass(frozen=True)
class InstallationRunRequest:
    """Secret-free identity and persistence policy for one execution."""

    installation_key: str
    request_fingerprint: str
    resource_type: str
    failure_code: str = "installation_failed"
    failure_message: str = "Installation failed; retry is allowed."


class InstallationRunContext:
    """Lease-scoped checkpoint writer passed to an installation adapter."""

    def __init__(
        self,
        *,
        operation_id: str,
        lease_owner: str,
        checkpoint: Dict[str, Any],
        repository: InstallationRunnerRepository,
    ) -> None:
        self.operation_id = operation_id
        self.lease_owner = lease_owner
        self._checkpoint = sanitize_installation_payload(checkpoint or {})
        self._repository = repository

    @property
    def checkpoint_data(self) -> Dict[str, Any]:
        return deepcopy(self._checkpoint)

    async def save_checkpoint(
        self,
        values: Dict[str, Any],
        *,
        replace: bool = False,
    ) -> Dict[str, Any]:
        """Persist a secret-free checkpoint only while this lease is owned."""
        sanitized = sanitize_installation_payload(values)
        checkpoint = sanitized if replace else {**self._checkpoint, **sanitized}
        try:
            persisted = self._repository.transition(
                operation_id=self.operation_id,
                lease_owner=self.lease_owner,
                status="running",
                checkpoint=checkpoint,
            )
        except Exception as exc:
            raise Nl2AgentOperationError(
                "Installation checkpoint could not be persisted. Retry installation."
            ) from exc
        if not persisted:
            raise AgentRunException(
                "Installation lease ownership was lost. Retry installation."
            )
        self._checkpoint = checkpoint
        return self.checkpoint_data


InstallationExecutor = Callable[
    [InstallationRunContext, Dict[str, Any]], Awaitable[Dict[str, Any]]
]


class DurableInstallationRunner:
    """Claim, heartbeat, checkpoint, retry, and replay one durable operation."""

    def __init__(
        self,
        *,
        identity: Nl2AgentSessionIdentity,
        repository: InstallationRunnerRepository,
        lease_seconds: int = _DEFAULT_LEASE_SECONDS,
        heartbeat_seconds: float = _DEFAULT_HEARTBEAT_SECONDS,
    ) -> None:
        self.identity = identity
        self.repository = repository
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds

    async def run(
        self,
        request: InstallationRunRequest,
        execute: InstallationExecutor,
    ) -> Dict[str, Any]:
        """Execute outside repository transactions and persist a redacted outcome."""
        operation_id = derive_installation_operation_id(
            self.identity,
            request.resource_type,
            request.installation_key,
        )
        lease_owner = uuid.uuid4().hex
        try:
            operation = self.repository.claim(
                identity=self.identity,
                operation_id=operation_id,
                installation_key=request.installation_key,
                request_fingerprint=request.request_fingerprint,
                resource_type=request.resource_type,
                lease_owner=lease_owner,
                lease_expires_at=datetime.utcnow()
                + timedelta(seconds=self.lease_seconds),
            )
        except InstallationRequestConflictError as exc:
            record_installation(request.resource_type, "request_conflict")
            raise AgentRunException(
                "This installation key belongs to a different request."
            ) from exc
        except InstallationLeaseActiveError as exc:
            record_installation(request.resource_type, "lease_conflict")
            raise AgentRunException(
                "This installation is already in progress. Retry after it completes."
            ) from exc
        except Exception as exc:
            raise Nl2AgentOperationError(
                "The durable installation operation could not be claimed."
            ) from exc

        if operation.get("status") == "completed":
            record_installation(request.resource_type, "replayed")
            return deepcopy(operation.get("result") or {})
        if int(operation.get("attempt") or 0) > 1:
            record_installation(request.resource_type, "retry")
        if operation.get("_lease_takeover") is True:
            record_installation(request.resource_type, "lease_takeover")

        context = InstallationRunContext(
            operation_id=operation_id,
            lease_owner=lease_owner,
            checkpoint=dict(operation.get("checkpoint") or {}),
            repository=self.repository,
        )
        heartbeat = asyncio.create_task(
            self._heartbeat(operation_id=operation_id, lease_owner=lease_owner)
        )

        async def execute_with_observability() -> Dict[str, Any]:
            try:
                return await execute(context, context.checkpoint_data)
            except asyncio.CancelledError:
                raise
            except Exception:
                record_installation(request.resource_type, "provider_failure")
                raise

        execution = asyncio.create_task(execute_with_observability())
        terminal = False
        try:
            done, _ = await asyncio.wait(
                {execution, heartbeat},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat in done:
                heartbeat_error = heartbeat.exception()
                execution.cancel()
                await asyncio.gather(execution, return_exceptions=True)
                if heartbeat_error is not None:
                    record_installation(request.resource_type, "heartbeat_failure")
                    raise heartbeat_error
                raise AgentRunException(
                    "Installation heartbeat stopped unexpectedly. Retry installation."
                )

            result = sanitize_installation_payload(await execution)
            try:
                completed = self.repository.transition(
                    operation_id=operation_id,
                    lease_owner=lease_owner,
                    status="completed",
                    checkpoint=context.checkpoint_data,
                    result=result,
                )
            except Exception as exc:
                raise Nl2AgentOperationError(
                    "Installation completed, but its durable result could not be persisted."
                ) from exc
            if not completed:
                raise Nl2AgentOperationError(
                    "Installation completed, but its durable lease was lost. Retry installation."
                )
            terminal = True
            record_installation(request.resource_type, "success")
            return result
        except asyncio.CancelledError:
            raise
        except Exception:
            try:
                terminal = self.repository.transition(
                    operation_id=operation_id,
                    lease_owner=lease_owner,
                    status="failed",
                    checkpoint=context.checkpoint_data,
                    error={
                        "code": request.failure_code,
                        "message": request.failure_message,
                    },
                )
            except Exception:
                logger.warning(
                    "Failed to persist a redacted NL2AGENT installation failure",
                    exc_info=True,
                )
            raise
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            if not terminal:
                try:
                    self.repository.release(
                        operation_id=operation_id,
                        lease_owner=lease_owner,
                    )
                except Exception:
                    logger.warning(
                        "Failed to release an interrupted NL2AGENT installation lease",
                        exc_info=True,
                    )

    async def _heartbeat(self, *, operation_id: str, lease_owner: str) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            try:
                renewed = self.repository.renew(
                    operation_id=operation_id,
                    lease_owner=lease_owner,
                    lease_expires_at=datetime.utcnow()
                    + timedelta(seconds=self.lease_seconds),
                )
            except Exception as exc:
                raise Nl2AgentOperationError(
                    "Installation lease could not be renewed. Retry installation."
                ) from exc
            if not renewed:
                raise AgentRunException(
                    "Installation lease ownership was lost. Retry installation."
                )


def build_default_installation_runner(
    identity: Nl2AgentSessionIdentity,
) -> DurableInstallationRunner:
    """Compose the production runner with the PostgreSQL operation repository."""
    return DurableInstallationRunner(
        identity=identity,
        repository=InstallationRunnerRepository(
            claim=claim_installation_operation,
            renew=renew_installation_operation,
            transition=transition_installation_operation,
            release=release_installation_lease,
        ),
    )
