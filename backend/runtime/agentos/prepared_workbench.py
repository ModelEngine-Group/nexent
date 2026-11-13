# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Resolve Workbench turn-owned mounts through the signed Management API."""

import httpx
from fastapi import HTTPException

from contracts.agentos import ManagementOperation, WorkbenchDebugSkillLookup, WorkbenchSkillLookup, WorkbenchSkillMounts
from contracts.constants import environment
from infrastructure.agentos_identity import AgentOSIdentityError, ServicePrincipal, sign_call

_TIMEOUT = httpx.Timeout(10, connect=3)


def fetch_workbench_skill_mounts(
    lookup: WorkbenchSkillLookup | WorkbenchDebugSkillLookup, actor: ServicePrincipal,
) -> dict[int, dict]:
    operation = (
        ManagementOperation.WORKBENCH_DEBUG_SKILL_MOUNTS if isinstance(lookup, WorkbenchDebugSkillLookup)
        else ManagementOperation.WORKBENCH_SKILL_MOUNTS
    )
    body = lookup.model_dump_json().encode()
    try:
        token = sign_call(operation, body, actor)
        with httpx.Client(timeout=_TIMEOUT, trust_env=False, follow_redirects=False) as client:
            response = client.post(
                f"{environment.MANAGEMENT_AGENTOS_URL}/api{operation.value}", content=body,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            if response.status_code == 404:
                raise HTTPException(status_code=404, detail={"code": "AGENTOS_SKILL_NOT_FOUND"})
            if response.status_code == 409:
                raise HTTPException(status_code=409, detail={"code": "AGENTOS_SKILL_REVISION_MISMATCH"})
            response.raise_for_status()
            result = WorkbenchSkillMounts.model_validate_json(response.content)
    except (AgentOSIdentityError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail={"code": "AGENTOS_WORKBENCH_SCOPE_UNAVAILABLE"}) from exc
    return {mount.skill_id: mount.config_values for mount in result.mounts}
