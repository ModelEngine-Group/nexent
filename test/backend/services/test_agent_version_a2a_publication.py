"""Sequential publication preserves the last A2A publication version."""


def test_ordinary_publish_preserves_last_a2a_version(mocker):
    from backend.services import agent_version_service as module
    from database import a2a_agent_db

    draft = {"agent_id": 7, "tenant_id": "tenant", "name": "Agent", "is_a2a": True}
    mocker.patch.object(module, "is_system_agent", return_value=False)
    mocker.patch.object(module, "query_agent_draft", return_value=(draft, [], []))
    mocker.patch.object(module, "get_next_version_no", side_effect=[1, 2, 3])
    for name in ("insert_agent_snapshot", "insert_tool_snapshot", "insert_relation_snapshot",
                 "insert_skill_snapshot", "insert_version", "update_agent_current_version"):
        mocker.patch.object(module, name, return_value=1)
    mocker.patch("database.skill_db.query_skill_instances_by_agent_id", return_value=[])
    registration = {"agent_id": 7, "endpoint_id": "stable-endpoint", "version": None}
    lookup = mocker.patch.object(a2a_agent_db, "get_server_agent_by_agent_id", return_value=registration)

    def publish_registration(**kwargs):
        registration["version"] = kwargs["version"]
        return dict(registration)

    register = mocker.patch.object(a2a_agent_db, "create_server_agent", side_effect=publish_registration)
    first = module.publish_version_impl(7, "tenant", "owner")
    assert first["version_no"] == 1
    assert registration["version"] == "1"
    draft["is_a2a"] = False
    second = module.publish_version_impl(7, "tenant", "owner")
    assert second["version_no"] == 2
    assert "a2a_agent" not in second
    assert registration["version"] == "1"
    assert register.call_count == 1
    assert lookup.call_count == 1
    draft["is_a2a"] = True
    third = module.publish_version_impl(7, "tenant", "owner")
    assert registration["version"] == "3"
    assert third["a2a_agent"]["endpoint_id"] == first["a2a_agent"]["endpoint_id"]
    assert [call.kwargs["version"] for call in register.call_args_list] == ["1", "3"]
