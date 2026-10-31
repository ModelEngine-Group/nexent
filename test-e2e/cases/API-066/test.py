# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""V5 API-066 independently collected scenario."""

import io
import json
import zipfile

import pytest
from d3.scenarios import scenario_agent_configuration_scenarios as scenario
from shared.asset_registry import resolve_asset
from shared.cases import case_params
from shared.factories.agent import _draft_agent
from shared.http import assert_status, client

@pytest.mark.parametrize("case", case_params("D3", ["API-066"]))
@pytest.mark.asyncio
async def test_api_066(case, tenant_a_admin, tenant_a_user, tenant_b_user):
    await scenario.execute_agent_configuration_scenario(case, tenant_a_admin, tenant_a_user, tenant_b_user)
    skill_id = int(resolve_asset(
        "skills", "configurable_id", consumer_case_id="API-066", dependency_case_id="API-066",
    ))
    async with _draft_agent(tenant_a_admin, name_prefix="export-removal") as (agent_id, payload):
        async with client("config", token=tenant_a_admin.access_token) as api:
            bound = await api.post("/agent/update", json={
                **payload, "enabled_skill_ids": [skill_id],
                "skill_instances": [{"skill_id": skill_id, "enabled": True, "config_values": {}}],
            })
            assert_status(bound, 200)
            exported = await api.post("/agent/export", json={"agent_id": agent_id})
            assert_status(exported, 200)
            assert exported.headers["content-type"].startswith("application/zip")
            with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
                config = json.loads(archive.read("agent.json"))
                names = config["agent_info"][str(agent_id)]["skill_names"]
                assert len(names) == 1
                assert set(archive.namelist()) == {"agent.json", f"skills/{names[0]}.zip"}

            removed = await api.post("/agent/update", json={
                **payload, "enabled_skill_ids": [], "skill_instances": [],
            })
            assert_status(removed, 200)
            exported = await api.post("/agent/export", json={"agent_id": agent_id})
            assert_status(exported, 200)
            assert exported.headers["content-type"].startswith("application/json")
            config = exported.json().get("data") or exported.json()
            assert config["agent_info"][str(agent_id)]["skill_names"] == []
