import json

import pytest

from services import workbench_creation_history_service as service


def config(mode):
    return {
        "schema_version": 3,
        "mode": mode,
        "generation_config": {"deep_thinking": False},
        "agent_mounts": [],
        "skill_mounts": [],
    }


def test_new_creation_session_persists_user_and_returns_assistant_index(mocker):
    create = mocker.patch.object(
        service, "create_new_conversation", return_value={"conversation_id": 42}
    )
    save = mocker.patch.object(service, "save_message", return_value=101)
    conversation_id, assistant_index = service.prepare_creation_history(
        conversation_id=None, mode="skill_create", query="Create a PDF Skill",
        minio_files=None, workbench_config=config("skill_create"), agent_id=None,
        user_id="user", tenant_id="tenant",
    )
    assert (conversation_id, assistant_index) == (42, 1)
    assert create.call_args.kwargs["workbench_config"]["mode"] == "skill_create"
    assert save.call_args.args[0].message_idx == 0
    assert save.call_args.args[0].message[0].content == "Create a PDF Skill"


def test_creation_session_rejects_other_agent_or_mode(mocker):
    mocker.patch.object(service, "get_conversation_history", return_value={
        "workbench_config": config("agent_create"),
        "agent_id": 17,
        "message_records": [{"message_index": 1}],
    })
    mocker.patch.object(service, "query_agent_records_for_nl2agent", return_value=[
        {"delete_flag": "N"},
    ])
    save = mocker.patch.object(service, "save_message")
    with pytest.raises(ValueError, match="Agent does not match"):
        service.prepare_creation_history(
            conversation_id=42, mode="agent_create", query="continue",
            minio_files=None, workbench_config=None, agent_id=18,
            user_id="user", tenant_id="tenant",
        )
    save.assert_not_called()


def test_deleted_agent_creation_session_rebinds_and_keeps_history(mocker):
    mocker.patch.object(service, "get_conversation_history", return_value={
        "workbench_config": config("agent_create"),
        "agent_id": 17,
        "message_records": [{"message_index": 0}, {"message_index": 1}],
    })
    mocker.patch.object(service, "query_agent_records_for_nl2agent", return_value=[
        {"delete_flag": "Y", "version_no": 0},
    ])
    rebind = mocker.patch.object(service, "rebind_conversation_agent_id", return_value=True)
    save = mocker.patch.object(service, "save_message")

    assert service.prepare_creation_history(
        conversation_id=42, mode="agent_create", query="Create another agent",
        minio_files=None, workbench_config=None, agent_id=18,
        user_id="user", tenant_id="tenant",
    ) == (42, 3)
    rebind.assert_called_once_with(42, 17, 18, "user")
    assert save.call_args.args[0].message_idx == 2


@pytest.mark.parametrize("records", [[], [{"delete_flag": "N"}],
    [{"delete_flag": "Y"}, {"delete_flag": "N"}]])
def test_creation_session_cannot_rebind_unowned_or_live_agent(mocker, records):
    mocker.patch.object(service, "get_conversation_history", return_value={
        "workbench_config": config("agent_create"),
        "agent_id": 17,
        "message_records": [],
    })
    mocker.patch.object(service, "query_agent_records_for_nl2agent", return_value=records)
    rebind = mocker.patch.object(service, "rebind_conversation_agent_id")
    with pytest.raises(ValueError, match="Agent does not match"):
        service.prepare_creation_history(
            conversation_id=42, mode="agent_create", query="continue",
            minio_files=None, workbench_config=None, agent_id=18,
            user_id="user", tenant_id="tenant",
        )
    rebind.assert_not_called()


def test_deleted_agent_creation_session_rejects_stale_rebind(mocker):
    mocker.patch.object(service, "get_conversation_history", return_value={
        "workbench_config": config("agent_create"),
        "agent_id": 17,
        "message_records": [],
    })
    mocker.patch.object(service, "query_agent_records_for_nl2agent", return_value=[
        {"delete_flag": "Y"},
    ])
    mocker.patch.object(service, "rebind_conversation_agent_id", return_value=False)
    save = mocker.patch.object(service, "save_message")
    with pytest.raises(ValueError, match="Agent does not match"):
        service.prepare_creation_history(
            conversation_id=42, mode="agent_create", query="continue",
            minio_files=None, workbench_config=None, agent_id=18,
            user_id="user", tenant_id="tenant",
        )
    save.assert_not_called()


def test_new_creation_session_rejects_resources_for_creation_mode(mocker):
    create = mocker.patch.object(service, "create_new_conversation")
    invalid = config("skill_create")
    invalid["knowledge_scope"] = {"source_ids": [1]}
    with pytest.raises(ValueError):
        service.prepare_creation_history(
            conversation_id=None, mode="skill_create", query="Create a Skill",
            minio_files=None, workbench_config=invalid, agent_id=None,
            user_id="user", tenant_id="tenant",
        )
    create.assert_not_called()


@pytest.mark.parametrize("mode,agent_id", [("skill_create", None), ("agent_create", 17)])
def test_creation_retry_reuses_user_boundary_and_branches_assistant(mocker, mode, agent_id):
    mocker.patch.object(service, "get_conversation_history", return_value={
        "workbench_config": config(mode),
        "agent_id": agent_id,
        "message_records": [
            {"message_id": 100, "message_index": 0, "role": "user",
             "message_content": "Create a Skill", "minio_files": None},
            {"message_id": 101, "message_index": 1, "role": "assistant"},
        ],
    })
    save = mocker.patch.object(service, "save_message")
    assert service.prepare_creation_history(
        conversation_id=42, mode=mode, query="Create a Skill",
        minio_files=None, workbench_config=None, agent_id=agent_id,
        user_id="user", tenant_id="tenant", retry_message_index=0,
        retry_user_message_id=100,
    ) == (42, 1)
    save.assert_not_called()


def test_creation_retry_rejects_mismatched_user_boundary(mocker):
    mocker.patch.object(service, "get_conversation_history", return_value={
        "workbench_config": config("skill_create"),
        "agent_id": None,
        "message_records": [
            {"message_id": 100, "message_index": 0, "role": "user",
             "message_content": "original", "minio_files": None},
            {"message_id": 101, "message_index": 1, "role": "assistant"},
        ],
    })
    save = mocker.patch.object(service, "save_message")
    with pytest.raises(ValueError, match="retry"):
        service.prepare_creation_history(
            conversation_id=42, mode="skill_create", query="different",
            minio_files=None, workbench_config=None, agent_id=None,
            user_id="user", tenant_id="tenant", retry_message_index=0,
        )
    save.assert_not_called()


def test_creation_retry_matches_uploaded_files_by_object_name(mocker):
    mocker.patch.object(service, "get_conversation_history", return_value={
        "workbench_config": config("skill_create"),
        "agent_id": None,
        "message_records": [
            {"message_id": 100, "message_index": 0, "role": "user",
             "message_content": "review", "minio_files": [
                 {"object_name": "uploads/contract.pdf", "url": "old-url"}
             ]},
            {"message_id": 101, "message_index": 1, "role": "assistant"},
        ],
    })
    save = mocker.patch.object(service, "save_message")
    assert service.prepare_creation_history(
        conversation_id=42, mode="skill_create", query="review",
        minio_files=[{"object_name": "uploads/contract.pdf", "url": "new-url"}],
        workbench_config=None, agent_id=None, user_id="user", tenant_id="tenant",
        retry_user_message_id=100, retry_message_index=0,
    ) == (42, 1)
    save.assert_not_called()


@pytest.mark.asyncio
async def test_creation_stream_forwards_sse_and_persists_replay_units(mocker):
    save = mocker.patch.object(service, "save_message", return_value=102)
    save_unit = mocker.patch.object(service, "save_message_unit")
    events = [
        {"type": "skill_body", "content": "---\\nname: example", "path": "SKILL.md"},
        {"type": "file_content", "content": "print(1)", "path": "scripts/main.py"},
        {"type": "done", "content": ""},
    ]

    async def stream():
        for event in events:
            yield f"data: {json.dumps(event)}\n\n"

    output = [event async for event in service.persist_creation_stream(
        stream(), conversation_id=42, assistant_index=1,
        user_id="user", tenant_id="tenant",
    )]
    assert len(output) == 3
    assert save.call_args.args[0].message_idx == 1
    assert save.call_args.kwargs["status"] == "completed"
    assert save_unit.call_count == 3
    assert json.loads(save_unit.call_args_list[1].kwargs["unit_content"])["path"] == "scripts/main.py"
