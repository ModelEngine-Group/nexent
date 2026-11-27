# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Check the deployed Core before preparing a CodeAgent protocol fixture."""

from shared.asset_registry import AssetDependencyError
from shared.http import assert_status, client


class AgentCoreUnavailableError(AssetDependencyError):
    """The deployment cannot run the CodeAgent protocol under test."""


async def require_code_agent(identity, case_id: str) -> None:
    async with client("config", token=identity.access_token) as api:
        response = await api.get("/tenant_config/deployment_version")
    assert_status(response, 200)
    if response.json().get("agent_core") != "smolagents":
        raise AgentCoreUnavailableError(
            "deployment", "agent_core", consumer_case_id=case_id,
            detail="This CodeAgent protocol fixture requires NEXENT_AGENT_CORE=smolagents.",
        )
