# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Retain legacy-valid subagent configuration across prepared execution."""

import pytest

from contracts.agentos import PreparedEvaluationRun
from infrastructure.agent_model_config import create_model_config_from_record
from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent.preparation import evaluation_snapshot
from nexent.core.agents.agent_model import AgentConfig
from runtime.agentos import prepared_evaluation
from test.backend.app.test_agentos_prepared_evaluation import model_record


@pytest.mark.parametrize("depth", [1, 2])
@pytest.mark.parametrize("child_level", ["local", "docker"])
def test_nested_sandbox_configuration_exports_without_legacy_fallback(mocker, tmp_path, depth, child_level):
    from runtime.adapters.nexent import factory

    mocker.patch("contracts.constants.environment.NEXENT_SANDBOX_DEFAULT_LEVEL", "local")
    mocker.patch.object(factory, "get_redis_client", return_value=None)
    record = model_record(model_id=11)
    model = create_model_config_from_record(record)
    leaf = AgentConfig(agent_id=9, version_no=1, name="leaf", description="", tools=[], model_name=model.cite_name,
                       sandbox_policy={"level": child_level, "auto_sync_outputs": False})
    child = leaf if depth == 1 else AgentConfig(
        agent_id=8, version_no=1, name="middle", description="", tools=[], model_name=model.cite_name, worker_agents=[leaf],
    )
    root = AgentConfig(agent_id=7, version_no=1, name="root", description="", tools=[], model_name=model.cite_name,
                       worker_agents=[child], sandbox_policy={"level": "local", "auto_sync_outputs": False})
    actor = ServicePrincipal("user-a", "tenant-a")
    legacy = factory.materialize_legacy_run(
        agent_config=root, workspace_path=str(tmp_path / "legacy"), query="hello", model_config_list=[model],
        mcp_host=[], history=[], language="zh", user_id=actor.user_id, tenant_id=actor.tenant_id,
    )
    mocker.patch.object(evaluation_snapshot, "get_model_records", return_value=[record])
    snapshot = evaluation_snapshot.export_snapshot(root, [model], "hello", None,
                                                  tenant_id="tenant-a", conversation_id=0, language="zh")
    assert snapshot is not None
    payload = PreparedEvaluationRun.model_validate_json(snapshot.model_dump_json())
    mocker.patch.object(prepared_evaluation, "get_model_by_model_id", return_value=record)
    restored = prepared_evaluation.prepare_run_snapshot(payload, actor)
    try:
        assert restored.sandbox_config.level == legacy.sandbox_config.level
        assert restored.sandbox_config.auto_sync_outputs == legacy.sandbox_config.auto_sync_outputs
        current = restored.agent_config
        old = legacy.agent_config
        for _ in range(depth):
            current = current.worker_agents[0]
            old = old.worker_agents[0]
        assert current.sandbox_policy == old.sandbox_policy == leaf.sandbox_policy
        assert current.name == old.name and current.model_name == old.model_name
    finally:
        prepared_evaluation.discard_prepared_workspace(restored)
