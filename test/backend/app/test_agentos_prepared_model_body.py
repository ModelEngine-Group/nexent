# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from contracts.constants import environment
from infrastructure.agent_model_config import create_model_config_from_record
from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent.preparation import evaluation_snapshot
from nexent.core.agents.agent_model import AgentConfig
from runtime.agentos import prepared_evaluation

from test.backend.app.test_agentos_prepared_evaluation import model_record


@pytest.mark.parametrize("change", [None, "body", "removed", "unpersisted"])
def test_evaluation_rebuilds_only_pinned_persisted_model_body(mocker, change):
    mocker.patch.object(environment, "JWT_SECRET", "fixture-agent-model-signing")
    row = model_record(model_id=11, extra_params={"inherited": 1, "remove_me": True})
    base = create_model_config_from_record(row)
    selected = base.model_copy(update={"temperature": 0.2, "extra_body": {"inherited": 1, "provider": "private-value"}})
    override = {"11": {"temperature": 0.2, "extra_params": {
        "__custom__": {"remove_me": None, "provider": "private-value"}, "enable_thinking": False,
    }}}
    agent = AgentConfig(agent_id=8, version_no=3, name="evaluate", description="Model body",
                        model_name=base.cite_name, tools=[])
    mocker.patch.object(evaluation_snapshot, "get_model_records", return_value=[row])
    snapshot = evaluation_snapshot.export_snapshot(
        agent, [selected], "query", [], tenant_id="tenant-a", conversation_id=-91,
        language="en", agent_model_overrides={} if change == "unpersisted" else override,
    )
    if change == "unpersisted":
        assert snapshot is None
        return

    assert snapshot.models.llm.provider_body_revision
    assert "private-value" not in snapshot.model_dump_json()
    lookup = mocker.patch.object(prepared_evaluation, "read_agent_model_overrides", return_value=override)
    mocker.patch.object(prepared_evaluation, "get_model_by_model_id", return_value=row)
    if change == "body":
        override["11"]["extra_params"]["__custom__"]["provider"] = "changed"
    elif change == "removed":
        lookup.return_value = None

    actor = ServicePrincipal("user-a", "tenant-a")
    if change is None:
        model = prepared_evaluation._materialize_model(snapshot.models.llm, actor, snapshot.resource)
        assert model.extra_body == {"inherited": 1, "provider": "private-value"}
        assert model.temperature == 0.2
    else:
        with pytest.raises(HTTPException) as error:
            prepared_evaluation._materialize_model(snapshot.models.llm, actor, snapshot.resource)
        assert error.value.status_code == 409
        assert error.value.detail["code"] == "AGENTOS_MODEL_BODY_REVISION_MISMATCH"
    lookup.assert_called_once_with(8, 3, "tenant-a")
