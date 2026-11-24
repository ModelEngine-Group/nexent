# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Serialize Runtime maintenance independently of the HTTP and scheduler lifecycle."""

import argparse
import json
import logging
import re
import socket
import ssl
from collections.abc import Callable
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener
from uuid import UUID, uuid4

from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.agent_execution import recover_expired_executions
from infrastructure.rdb.model_records import fail_detecting_models_on_startup
from management.db.execution import repository
from management.recovery import recover_runtime_tasks
from infrastructure.workspace_cleanup import cleanup_orphaned_agent_workspaces


logger = logging.getLogger(__name__)
KUBERNETES_SERVICE = "https://kubernetes.default.svc"
SERVICE_ACCOUNT_DIRECTORY = Path("/var/run/secrets/kubernetes.io/serviceaccount")


def _validate_epoch(epoch: str) -> None:
    try:
        canonical = str(UUID(epoch))
    except ValueError:
        canonical = None
    if canonical != epoch:
        raise ValueError("Runtime maintenance batch must be a canonical UUID")


def require_completed_runtime_maintenance(epoch: str) -> datetime:
    """Return the completed batch's common cutoff, or prevent Runtime startup."""
    _validate_epoch(epoch)
    with get_db_session() as session:
        completed_at = repository.maintenance_completed_at(session, epoch)
    if completed_at is None:
        raise RuntimeError("Runtime does not have a completed maintenance batch")
    return completed_at.replace(tzinfo=timezone.utc)


def run_runtime_maintenance(
    epoch: str,
    owner_instance_id: str,
    check_paused: Callable[[str], None],
) -> bool:
    """Run one effective maintenance pass after verifying the paused release."""
    _validate_epoch(epoch)
    if not owner_instance_id or len(owner_instance_id) > 100:
        raise ValueError("Runtime maintenance requires a valid owner instance ID")
    check_paused(epoch)
    with get_db_session() as session:
        repository.lock_maintenance(session)
        check_paused(epoch)
        if repository.maintenance_completed_at(session, epoch) is not None:
            return False
        recover_runtime_tasks(db_session=session)
        recover_expired_executions(offline_session=session)
        fail_detecting_models_on_startup(db_session=session)
        cleanup_orphaned_agent_workspaces(strict=True)
        check_paused(epoch)
        repository.interrupt_active_executions(session)
        repository.record_maintenance_completion(session, epoch, owner_instance_id)
    return True


def require_paused_kubernetes_runtime(
    read_resource: Callable[[str], dict], namespace: str, release: str, epoch: str,
) -> None:
    """Require a paused Deployment in this release and no old Runtime pods."""
    if not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?", namespace):
        raise ValueError("Invalid Kubernetes namespace for Runtime maintenance")
    deployment = read_resource(f"/apis/apps/v1/namespaces/{namespace}/deployments/nexent-runtime")
    metadata = deployment.get("metadata", {})
    annotations = metadata.get("annotations", {})
    if annotations.get("meta.helm.sh/release-name") != release:
        raise RuntimeError("Runtime Deployment does not belong to this Helm release")
    if annotations.get("nexent.io/maintenance-epoch") != epoch:
        raise RuntimeError("Runtime Deployment does not have the requested maintenance batch")
    if deployment.get("spec", {}).get("replicas") != 0:
        raise RuntimeError("Runtime Deployment must have zero replicas during maintenance")
    generation = metadata.get("generation", 0)
    status = deployment.get("status", {})
    if not generation or status.get("observedGeneration") != generation or status.get("replicas", 0) != 0:
        raise RuntimeError("Runtime Deployment has not reconciled to zero replicas")
    selector = urlencode({"labelSelector": "app=nexent-runtime"})
    pods = read_resource(f"/api/v1/namespaces/{namespace}/pods?{selector}")
    if pods.get("items") != [] or pods.get("metadata", {}).get("continue"):
        raise RuntimeError("Runtime maintenance requires all old Runtime Pods to exit")


def _in_cluster_api_reader() -> Callable[[str], dict]:
    context = ssl.create_default_context(cafile=str(SERVICE_ACCOUNT_DIRECTORY / "ca.crt"))
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context))

    def read_resource(path: str) -> dict:
        token = (SERVICE_ACCOUNT_DIRECTORY / "token").read_text(encoding="utf-8").strip()
        request = Request(f"{KUBERNETES_SERVICE}{path}", headers={"Authorization": f"Bearer {token}"})
        with opener.open(request, timeout=10) as response:
            return json.load(response)

    return read_resource


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--epoch", required=True)
    options = parser.parse_args()

    try:
        owner_instance_id = f"{socket.gethostname()[:63]}:{uuid4().hex}"
        check_paused = partial(require_paused_kubernetes_runtime, _in_cluster_api_reader(), options.namespace, options.release)
        performed = run_runtime_maintenance(options.epoch, owner_instance_id, check_paused)
    except Exception as exc:
        logger.error("Runtime maintenance failed; keep the release paused (%s)", type(exc).__name__)
        return 1

    print("Runtime maintenance completed" if performed else "Runtime maintenance was already completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
