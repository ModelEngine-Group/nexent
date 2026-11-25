# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Recover abandoned work after an operator has stopped the application release."""

import argparse
import json
import logging
import re
import ssl
from collections.abc import Callable
from functools import partial
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

from sqlalchemy import text

from infrastructure.rdb.agent_execution import recover_expired_executions
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.model_records import fail_detecting_models_on_startup
from infrastructure.workspace_cleanup import cleanup_orphaned_agent_workspaces
from management.recovery import recover_runtime_tasks


logger = logging.getLogger(__name__)
KUBERNETES_SERVICE = "https://kubernetes.default.svc"
SERVICE_ACCOUNT_DIRECTORY = Path("/var/run/secrets/kubernetes.io/serviceaccount")
BUSINESS_WORKLOADS = (
    "nexent-runtime", "nexent-config", "nexent-northbound", "nexent-mcp", "nexent-data-process",
)


def run_runtime_maintenance(check_paused: Callable[[], None]) -> None:
    """Recover interrupted work under the same lock used by the deploy script."""
    check_paused()
    with get_db_session() as session:
        locked = session.scalar(text(
            "SELECT pg_try_advisory_xact_lock(hashtextextended('nexent:runtime:deployment', 0))"
        ))
        if not locked:
            raise RuntimeError("Another process holds the Runtime deployment lock")
        check_paused()
        recover_runtime_tasks(db_session=session)
        recover_expired_executions(offline_session=session)
        fail_detecting_models_on_startup(db_session=session)
        cleanup_orphaned_agent_workspaces(strict=True)
        check_paused()


def require_paused_kubernetes_runtime(
    read_resource: Callable[[str], dict], namespace: str, release: str,
) -> None:
    """Verify the target release has no live Runtime or background writers."""
    if not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?", namespace):
        raise ValueError("Invalid Kubernetes namespace for Runtime maintenance")
    selector = urlencode({"labelSelector": f"app in ({','.join(BUSINESS_WORKLOADS)})"})
    deployments = read_resource(f"/apis/apps/v1/namespaces/{namespace}/deployments?{selector}")
    items = deployments.get("items")
    if deployments.get("metadata", {}).get("continue") or not isinstance(items, list):
        raise RuntimeError("Could not verify all application Deployments")
    names = set()
    for deployment in items:
        _require_zero_replicas(deployment, release)
        names.add(deployment["metadata"]["name"])
    if "nexent-runtime" not in names:
        raise RuntimeError("Runtime Deployment does not belong to this Helm release")
    pods = read_resource(f"/api/v1/namespaces/{namespace}/pods?{selector}")
    if pods.get("items") != [] or pods.get("metadata", {}).get("continue"):
        raise RuntimeError("Runtime maintenance requires all selected business Pods to exit")


def _require_zero_replicas(deployment: dict, release: str) -> None:
    metadata = deployment.get("metadata", {})
    annotations = metadata.get("annotations", {})
    name = metadata.get("name", "Deployment")
    if annotations.get("meta.helm.sh/release-name") != release:
        raise RuntimeError(f"{name} does not belong to this Helm release")
    if deployment.get("spec", {}).get("replicas") != 0:
        raise RuntimeError(f"{name} must have zero replicas during maintenance")
    generation = metadata.get("generation", 0)
    status = deployment.get("status", {})
    if not generation or status.get("observedGeneration") != generation or status.get("replicas", 0) != 0:
        raise RuntimeError(f"{name} has not reconciled to zero replicas")


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
    options = parser.parse_args()

    try:
        check_paused = partial(
            require_paused_kubernetes_runtime, _in_cluster_api_reader(), options.namespace, options.release,
        )
        run_runtime_maintenance(check_paused)
    except Exception as exc:
        logger.error("Runtime maintenance failed; keep the release paused (%s)", type(exc).__name__)
        return 1

    print("Runtime maintenance completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
