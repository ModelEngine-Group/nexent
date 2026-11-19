# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read scoped Casdoor policies and evaluate their current actions in batches."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import NamedTuple

import httpx

from consts import const as settings
from permissions.casdoor_policy import FEATURE_ACTION_RESOURCES, managed_action_resources, policy_scope

logger = logging.getLogger(__name__)
_TIMEOUT_SECONDS = 5
_LEGACY_RESOURCE = "nexent"


class Policy(NamedTuple):
    id: str
    resource_actions: tuple[tuple[str, str], ...]


async def _data(client: httpx.AsyncClient, method: str, endpoint: str, **kwargs) -> list | None:
    try:
        async with asyncio.timeout(_TIMEOUT_SECONDS):
            response = await client.request(method, f"api/{endpoint}", **kwargs)
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, TimeoutError, ValueError) as exc:
        logger.warning("Casdoor feature policy request %s failed (%s)", endpoint, type(exc).__name__)
        return None
    if isinstance(result, dict) and result.get("status") == "ok" and isinstance(result.get("data"), list):
        return result["data"]
    logger.warning("Casdoor feature policy request %s returned no valid decisions", endpoint)
    return None


async def read_policies(client: httpx.AsyncClient, organization: str) -> list[Policy] | None:
    if not policy_scope():
        return None
    data = await _data(client, "GET", "get-permissions", params={"owner": organization})
    if data is None or not all(isinstance(record, dict) for record in data):
        return None
    model = f"{organization}/{settings.CASDOOR_PERMISSION_MODEL}"
    managed_resources = managed_action_resources()
    policies = []
    for record in data:
        if (record.get("owner") != organization or record.get("model") != model
                or record.get("resourceType") != "Custom" or record.get("isEnabled") is not True
                or record.get("state") != "Approved" or record.get("effect") != "Allow"):
            continue
        expires = record.get("expireTime")
        if expires:
            try:
                if datetime.fromisoformat(expires.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                    continue
            except (AttributeError, TypeError, ValueError):
                continue
        name, resources, actions = record.get("name"), record.get("resources"), record.get("actions")
        if not isinstance(name, str) or not name or "/" in name or not isinstance(resources, list):
            continue
        if not isinstance(actions, list):
            continue
        recognized = sorted({action for action in actions if isinstance(action, str) and action in managed_resources})
        resource_actions = []
        for action in recognized:
            resource = managed_resources[action]
            if resource in resources:
                resource_actions.append((resource, action))
            elif action in FEATURE_ACTION_RESOURCES and _LEGACY_RESOURCE in resources:
                resource_actions.append((_LEGACY_RESOURCE, action))
        if resource_actions:
            policies.append(Policy(f"{organization}/{name}", tuple(resource_actions)))
    return policies


async def evaluate_permissions(
    client: httpx.AsyncClient, organization: str, policies: list[Policy], usernames: list[str],
) -> list[set[str]] | None:
    grants: list[set[str]] = [set() for _ in usernames]
    for policy in policies:
        requests = [[f"{organization}/{username}", resource, action]
                    for username in usernames for resource, action in policy.resource_actions]
        result = await _data(client, "POST", "batch-enforce", params={"permissionId": policy.id}, json=requests)
        if result == []:
            continue
        if result is not None and len(result) == 1 and isinstance(result[0], list):
            result = result[0]
        if result is None or len(result) != len(requests) or not all(type(value) is bool for value in result):
            return None
        for index, allowed in enumerate(result):
            if allowed:
                account, action_index = divmod(index, len(policy.resource_actions))
                grants[account].add(policy.resource_actions[action_index][1])
    return grants
