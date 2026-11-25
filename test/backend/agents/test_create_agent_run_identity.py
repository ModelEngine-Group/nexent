# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""The signed run ID selects a stable Runtime workspace and tool scope."""

from contracts.constants import environment
from contracts.agentos import PreparedAgentRun
from infrastructure.agentos_identity import ServicePrincipal
from runtime.agentos import prepared_evaluation
from test.backend.app.test_agentos_prepared_evaluation import evaluation_payload, model_record


def test_run_identity_is_not_regenerated_inside_builder(mocker, tmp_path):
    request = evaluation_payload()
    request.update(run_id="a" * 32, conversation_id=7)
    payload = PreparedAgentRun.model_validate(request)
    actor = ServicePrincipal("user-a", "tenant-a")
    mocker.patch.object(prepared_evaluation, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    mocker.patch.object(prepared_evaluation, "get_model_by_model_id", return_value=model_record())
    mocker.patch.object(environment, "NEXENT_SANDBOX_DEFAULT_LEVEL", "local")
    mocker.patch.object(prepared_evaluation, "get_coordinator", return_value=None)
    mocker.patch("runtime.model.parameters.read_agent_model_overrides", return_value={})
    first = prepared_evaluation.prepare_run_snapshot(payload, actor)
    retry = prepared_evaluation.prepare_run_snapshot(payload, actor)
    assert first.workspace_run_id == retry.workspace_run_id == payload.run_id
    assert first.workspace_path == retry.workspace_path == str(tmp_path / actor.user_id / payload.run_id)
