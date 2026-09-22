from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services import official_agent_sync_service as sync_service


def _agent(agent_id: int = 101, managed_agents=None, **overrides):
    values = {
        "agent_id": agent_id,
        "name": "medical_assistant",
        "display_name": "Medical Assistant",
        "description": "Medical assistant",
        "author": "Nexent",
        "max_steps": 15,
        "provide_run_summary": True,
        "allow_chat_metadata": False,
        "verification_config": {"enabled": False},
        "context_policy": "default",
        "duty_prompt": "duty",
        "constraint_prompt": "constraint",
        "few_shots_prompt": [],
        "enabled": True,
        "model_ids": [1],
        "business_logic_model_id": 2,
        "business_logic_model_name": "model",
        "prompt_template_id": 3,
        "prompt_template_name": "template",
        "greeting_message": "hello",
        "example_questions": ["question"],
        "managed_agents": managed_agents or [],
        "tools": [],
        "version_no": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_source_agent_payload_copies_agent_fields():
    agent = _agent()

    payload = sync_service._source_agent_payload(agent)

    assert payload == {
        "name": "medical_assistant",
        "display_name": "Medical Assistant",
        "description": "Medical assistant",
        "author": "Nexent",
        "max_steps": 15,
        "provide_run_summary": True,
        "allow_chat_metadata": False,
        "verification_config": {"enabled": False},
        "context_policy": "default",
        "duty_prompt": "duty",
        "constraint_prompt": "constraint",
        "few_shots_prompt": [],
        "enabled": True,
        "model_ids": [1],
        "business_logic_model_id": 2,
        "business_logic_model_name": "model",
        "prompt_template_id": 3,
        "prompt_template_name": "template",
        "greeting_message": "hello",
        "example_questions": ["question"],
    }


def test_find_or_create_source_agent_reuses_existing_agent():
    with patch.object(sync_service, "find_agent_id_by_agent_name", return_value="17") as search:
        with patch.object(sync_service, "create_agent") as create:
            result = sync_service._find_or_create_source_agent(_agent())

    assert result == 17
    search.assert_called_once_with("medical_assistant", sync_service.OFFICIAL_AGENT_TENANT_ID)
    create.assert_not_called()


def test_find_or_create_source_agent_creates_when_source_is_missing():
    agent = _agent()
    with patch.object(
        sync_service, "find_agent_id_by_agent_name", return_value=None
    ) as search:
        with patch.object(sync_service, "create_agent", return_value={"agent_id": 23}) as create:
            result = sync_service._find_or_create_source_agent(agent)

    assert result == 23
    search.assert_called_once_with("medical_assistant", sync_service.OFFICIAL_AGENT_TENANT_ID)
    create.assert_called_once_with(
        sync_service._source_agent_payload(agent),
        tenant_id=sync_service.OFFICIAL_AGENT_TENANT_ID,
        user_id=sync_service.OFFICIAL_AGENT_USER_ID,
    )


def test_materialize_snapshot_remaps_agent_and_managed_agent_ids():
    child = _agent(202)
    root = _agent(101, managed_agents=[202])
    child_copy = _agent(602)
    root_copy = _agent(601, managed_agents=[602])
    child.model_copy = MagicMock(return_value=child_copy)
    root.model_copy = MagicMock(return_value=root_copy)
    snapshot = SimpleNamespace(
        agent_id=101,
        agent_info={"101": root, "202": child},
        model_copy=MagicMock(return_value="remapped-snapshot"),
    )
    bundle = SimpleNamespace(snapshot=snapshot)

    with patch.object(
        sync_service, "_find_or_create_source_agent", side_effect=[601, 602]
    ) as find_source:
        result = sync_service._materialize_snapshot(bundle)

    assert result == "remapped-snapshot"
    assert find_source.call_args_list[0].args[0] is root
    assert find_source.call_args_list[1].args[0] is child
    root.model_copy.assert_called_once_with(
        update={
            "agent_id": 601,
            "tenant_id": sync_service.OFFICIAL_AGENT_TENANT_ID,
            "managed_agents": [602],
        }
    )
    child.model_copy.assert_called_once_with(
        update={
            "agent_id": 602,
            "tenant_id": sync_service.OFFICIAL_AGENT_TENANT_ID,
            "managed_agents": [],
        }
    )
    snapshot.model_copy.assert_called_once_with(
        update={
            "agent_id": 601,
            "agent_info": {"601": root_copy, "602": child_copy},
        }
    )


def test_sync_bundle_upserts_official_repository_record():
    root = _agent(601, display_name="Root Agent", description="Root description", author="")
    snapshot = SimpleNamespace(
        agent_id=601,
        agent_info={"601": root},
        model_dump=MagicMock(return_value={"agent_id": 601}),
    )
    bundle = SimpleNamespace(
        name="medical-assistant",
        display_name="",
        description="",
        tags=None,
        icon="medical-icon",
    )

    with patch.object(sync_service, "_materialize_snapshot", return_value=snapshot):
        with patch.object(
            sync_service,
            "upsert_agent_repository_record",
            return_value=(88, True),
        ) as upsert:
            with patch.object(sync_service, "update_agent_repository_by_id") as update:
                result = sync_service._sync_bundle(bundle)

    assert result == {"name": "medical-assistant", "agent_repository_id": 88, "updated": True}
    repository_data = upsert.call_args.args[0]
    assert repository_data == {
        "agent_id": 601,
        "version_no": 1,
        "name": "medical-assistant",
        "display_name": "Root Agent",
        "description": "Root description",
        "author": "Nexent",
        "submitted_by": sync_service.OFFICIAL_AGENT_USER_ID,
        "version_name": "Official",
        "agent_info_json": {"agent_id": 601},
        "status": sync_service.STATUS_SHARED,
        "tags": [],
        "icon": "medical-icon",
        "tool_count": 0,
        "content": "Official Nexent agent",
    }
    upsert.assert_called_once_with(
        repository_data,
        publisher_tenant_id=sync_service.OFFICIAL_AGENT_TENANT_ID,
        publisher_user_id=sync_service.OFFICIAL_AGENT_USER_ID,
    )
    update.assert_called_once_with(
        repository_id=88,
        publisher_tenant_id=sync_service.OFFICIAL_AGENT_TENANT_ID,
        user_id=sync_service.OFFICIAL_AGENT_USER_ID,
        updates={"name": "medical-assistant"},
    )


@pytest.mark.asyncio
async def test_sync_official_agents_keeps_successful_bundles_when_one_fails():
    successful_bundle = SimpleNamespace(name="medical-assistant")
    failed_bundle = SimpleNamespace(name="broken-agent")
    with patch.object(sync_service, "parse_official_agent_profiles", return_value=["medical"]):
        with patch.object(
            sync_service,
            "load_official_bundles",
            return_value=[successful_bundle, failed_bundle],
        ) as load:
            with patch.object(
                sync_service,
                "_sync_bundle",
                side_effect=[{"name": "medical-assistant", "agent_repository_id": 88, "updated": False},
                             RuntimeError("invalid bundle")],
            ) as sync_bundle:
                result = await sync_service.sync_official_agents(
                    base_dir="/tmp/official-agents", profiles="medical"
                )

    assert result == [{"name": "medical-assistant", "agent_repository_id": 88, "updated": False}]
    load.assert_called_once_with("/tmp/official-agents", ["medical"])
    assert sync_bundle.call_count == 2


@pytest.mark.asyncio
async def test_sync_official_agents_uses_default_arguments_and_returns_empty_result():
    with patch.object(sync_service, "parse_official_agent_profiles", return_value=[]):
        with patch.object(sync_service, "load_official_bundles", return_value=[]) as load:
            result = await sync_service.sync_official_agents()

    assert result == []
    load.assert_called_once_with(sync_service.OFFICIAL_AGENTS_PATH, [])
