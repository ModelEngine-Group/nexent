# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import pytest
from fastapi import HTTPException

from infrastructure.agent_model_config import create_model_config_from_record
from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent.preparation import evaluation_snapshot, model_bindings
from nexent.core.agents.contracts.config import AgentConfig
from nexent.core.model_service.profiles.runtime_parameters import merge_agent_parameters
from runtime.agentos import prepared_evaluation
from runtime.model import parameters

from test.backend.app.test_agentos_prepared_evaluation import model_record
from test.backend.services.model_profile_helpers import stub_resolved_model_catalog


@pytest.mark.parametrize("change", [None, "parameters", "removed", "unpersisted"])
def test_evaluation_rebuilds_only_pinned_persisted_model_parameters(mocker, change):
    row = model_record()
    base = create_model_config_from_record(row)
    entry = {"parameter_values": {"temperature": 0.2}}
    resolved = merge_agent_parameters(base.resolved_profile, entry)
    selected = base.model_copy(update={"resolved_profile": resolved})
    override = {"11": entry}
    agent = AgentConfig(agent_id=8, version_no=3, name="evaluate", description="Model body",
                        model_name=base.cite_name, tools=[])
    stub_resolved_model_catalog(mocker, row)
    model_bindings.read_agent_model_overrides.return_value = {} if change == "unpersisted" else override
    snapshot = evaluation_snapshot.export_snapshot(
        agent, [selected], "query", [], tenant_id="tenant-a", conversation_id=-91,
        language="en",
    )
    if change == "unpersisted":
        assert snapshot is None
        return

    assert snapshot.models.llm.agent_parameters == entry
    assert row["api_key"] not in snapshot.model_dump_json()
    lookup = parameters.read_agent_model_overrides
    lookup.return_value = override
    mocker.patch.object(prepared_evaluation, "get_model_by_model_id", return_value=row)
    if change == "parameters":
        lookup.return_value = {"11": {"parameter_values": {"temperature": 0.4}}}
    elif change == "removed":
        lookup.return_value = None

    actor = ServicePrincipal("user-a", "tenant-a")
    if change is None:
        model = prepared_evaluation._materialize_model(snapshot.models.llm, actor, snapshot.resource)
        assert model.resolved_profile.parameter_values["temperature"] == 0.2
    else:
        with pytest.raises(HTTPException) as error:
            prepared_evaluation._materialize_model(snapshot.models.llm, actor, snapshot.resource)
        assert error.value.status_code == 409
        assert error.value.detail["code"] == "AGENTOS_MODEL_PARAMETERS_REVISION_MISMATCH"
    lookup.assert_called_once_with(8, 3, "tenant-a")
