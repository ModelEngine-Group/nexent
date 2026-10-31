# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Explicit deployment command: python -m management.services.agent.system_release."""

import argparse
import json

from contracts.agent import SystemAgentRef
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.errors.exceptions import WorkbenchAgentError
from management.db.agent.system import (
    load_system_agent, lock_system_agent_release, write_system_agent_release,
    latest_workbench_release, next_workbench_version, select_workbench_snapshot,
)
from management.db.client import get_db_session
from management.services.agent.system import SystemAgentProvider


def _publish_workbench(session, provider, existing):
    revision = provider.release_manifest.system_revision
    fields = provider._editable_fields()
    if existing is None:
        raise WorkbenchAgentError("system_agent_not_ready", retryable=True)
    if existing.get("system_revision") == revision:
        published = latest_workbench_release(session, existing["agent_id"], revision)
        if published is None or any(published.get(key) != value for key, value in fields.items()):
            raise WorkbenchAgentError("system_agent_drift_detected")
        return SystemAgentRef(ASSET_OWNER_TENANT_ID, "workbench_main", existing["agent_id"], existing["current_version_no"])
    if existing.get("system_revision") and not provider._is_newer_release(existing["system_revision"]):
        raise WorkbenchAgentError("system_agent_revision_ahead")
    agent_id = existing["agent_id"]
    version = next_workbench_version(session, agent_id)
    write_system_agent_release(session, existing=existing, system_key="workbench_main", revision=revision, fields=fields, version_no=version)
    return SystemAgentRef(ASSET_OWNER_TENANT_ID, "workbench_main", agent_id, version)


def release_system_agents(*, app_version=None):
    """Publish only Workbench; initialization and legacy migration are separate steps."""
    provider = SystemAgentProvider(app_version=app_version)
    with get_db_session() as session:
        lock_system_agent_release(session, "workbench_main")
        existing = load_system_agent(session, "workbench_main")
        workbench = _publish_workbench(session, provider, existing)
    return {"workbench_main": workbench.agent_id, "workbench_version": workbench.version_no}


def select_workbench_version(version_no: int):
    """Select a retained Workbench snapshot and its persisted capability bindings."""
    with get_db_session() as session:
        lock_system_agent_release(session, "workbench_main")
        select_workbench_snapshot(session, version_no)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--select-workbench-version", type=int)
    args = parser.parse_args()
    if args.select_workbench_version is not None:
        select_workbench_version(args.select_workbench_version)
    else:
        print(json.dumps(release_system_agents()))


if __name__ == "__main__":
    main()
