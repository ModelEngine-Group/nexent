"""Regression coverage for Workbench mounts across the durable HITL boundary."""

from types import SimpleNamespace

import pytest


def _request(*, workbench=None):
    from consts.model import AgentRequest

    return AgentRequest(
        query="test",
        agent_id=111,
        conversation_id=42,
        entrypoint="workbench",
        workbench=workbench,
    )


def test_hitl_restores_dynamic_agents_and_skills_after_request_round_trip(mocker):
    from services.human_interaction import application
    from services import workbench_service

    request = _request(
        workbench={
            "schema_version": 3,
            "mode": "multi_agent_chat",
            "agent_mounts": [{"agent_id": 20}, {"agent_id": 82}],
            "skill_mounts": [{"skill_id": 115}],
        }
    )
    request.__dict__["_runtime_skill_snapshot"] = [{"skill_id": 115}]
    request.__dict__["_runtime_mount_plan"] = object()
    restored = type(request).model_validate(request.model_dump(mode="json"))
    assert getattr(restored, "_runtime_skill_snapshot", None) is None
    assert getattr(restored, "_runtime_mount_plan", None) is None
    identity = SimpleNamespace(
        agent_id=111,
        version_no=2,
        runtime_ref="agent:111:v2",
        invocation_name="workbench_main",
        display_name="Workbench",
        origin="SYSTEM",
    )
    plan = SimpleNamespace(
        root=SimpleNamespace(identity=identity),
        child_mounts=(SimpleNamespace(agent_id=20), SimpleNamespace(agent_id=82)),
        root_skills=(SimpleNamespace(skill_id=115),),
        overlay=SimpleNamespace(model_id=None, requested_output_tokens=None),
    )
    mocker.patch.object(
        workbench_service, "resolve_workbench_config", return_value=(restored.workbench, plan)
    )
    mocker.patch.object(
        workbench_service,
        "runtime_skill_snapshot",
        return_value=[{"skill_id": 115, "name": "date-skill"}],
    )
    mocker.patch.object(workbench_service, "attach_runtime_knowledge_tree", return_value=plan)
    mocker.patch("services.knowledge_scope_service.snapshot_runtime_knowledge_tree", return_value=[])

    application._restore_workbench_runtime(restored, tenant_id="tenant", user_id="owner")

    assert restored._runtime_mount_plan.child_mounts == plan.child_mounts
    assert restored._runtime_skill_snapshot == [{"skill_id": 115, "name": "date-skill"}]
    assert restored.agent_id == 111
    assert restored.version_no == 2


def test_hitl_rejects_restored_workbench_root_mismatch(mocker):
    from services.human_interaction import application
    from services.human_interaction.models import InteractionError
    from services import workbench_service

    request = _request(workbench={"schema_version": 3, "mode": "generic_chat"})
    plan = SimpleNamespace(root=SimpleNamespace(identity=SimpleNamespace(agent_id=999)))
    mocker.patch.object(workbench_service, "resolve_workbench_config", return_value=(request.workbench, plan))

    with pytest.raises(InteractionError, match="Agent is no longer accessible"):
        application._restore_workbench_runtime(request, tenant_id="tenant", user_id="owner")


def test_hitl_non_workbench_request_does_not_restore_mounts(mocker):
    from consts.model import AgentRequest
    from services.human_interaction import application
    from services import workbench_service

    resolver = mocker.patch.object(workbench_service, "resolve_workbench_config")
    request = AgentRequest(query="ordinary chat", agent_id=20, conversation_id=42)

    application._restore_workbench_runtime(request, tenant_id="tenant", user_id="owner")

    resolver.assert_not_called()
    assert getattr(request, "_runtime_mount_plan", None) is None


def test_hitl_restores_workbench_config_from_conversation_when_payload_omits_it(mocker):
    from management.services.agent import run
    from services import conversation_management_service, workbench_service
    from services.human_interaction import application

    request = _request()
    stored_config = {"schema_version": 3, "mode": "generic_chat"}
    lookup = mocker.patch.object(
        conversation_management_service,
        "get_conversation_service",
        return_value={"workbench_config": stored_config},
    )
    plan = SimpleNamespace(root=SimpleNamespace(identity=SimpleNamespace(agent_id=111)))
    mocker.patch.object(workbench_service, "resolve_workbench_config", return_value=(request.workbench, plan))
    apply_plan = mocker.patch.object(run, "apply_workbench_runtime_plan")

    application._restore_workbench_runtime(request, tenant_id="tenant", user_id="owner")

    lookup.assert_called_once_with(42, "owner", "tenant")
    apply_plan.assert_called_once()
    assert apply_plan.call_args.args[0] is request
