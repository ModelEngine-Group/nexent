# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from unittest.mock import AsyncMock

import pytest

from management.services.agent.a2a.validation import validate_a2a_agent_name


@pytest.mark.parametrize("name", ["Agent", "agent-one_2", "智能体", "A"])
def test_valid_names_are_preserved(name):
    assert validate_a2a_agent_name(name) == name


@pytest.mark.parametrize("name", ["Agent Name", " Agent", "Agent ", "A\tB", "A\nB", "A\rB",
                                  "A\u3000B", "A\u00a0B", " ", "", None])
def test_invalid_names_are_rejected(name):
    with pytest.raises(ValueError, match="A2A Agent name"):
        validate_a2a_agent_name(name)


@pytest.mark.parametrize("operation", ["discover", "refresh"])
@pytest.mark.parametrize("name", ["Invalid Name", " Invalid", "Invalid\tName", "智能\u3000体"])
@pytest.mark.asyncio
async def test_url_card_rejected_before_persistence(mocker, operation, name):
    from management.services.agent.a2a import catalog

    client = mocker.patch.object(catalog, "A2AHttpClient")
    client.return_value.__aenter__.return_value.get_json = AsyncMock(
        return_value={"name": name, "url": "https://example.com/v1"}
    )
    database = mocker.patch.object(catalog, "a2a_agent_db")
    database.get_external_agent_by_id.return_value = {
        "source_type": "url", "source_url": "https://example.com/card.json"
    }
    service = catalog.A2AClientService()
    with pytest.raises(catalog.AgentDiscoveryError, match="must not contain spaces"):
        if operation == "discover":
            await service.discover_from_url("https://example.com/card.json", "tenant", "user")
        else:
            await service.refresh_agent_card(1, "tenant", "user")
    database.create_external_agent_from_url.assert_not_called()
    database.refresh_external_agent_cache.assert_not_called()
    database.update_agent_availability.assert_not_called()


@pytest.mark.asyncio
async def test_nacos_name_rejected_before_query_or_write(mocker):
    from management.services.agent.a2a import catalog

    database = mocker.patch.object(catalog, "a2a_agent_db")
    with pytest.raises(catalog.AgentDiscoveryError, match="must not contain spaces"):
        await catalog.A2AClientService()._discover_single_from_nacos(
            {}, "Invalid Name", "public", "tenant", "user"
        )
    database.create_external_agent_from_nacos.assert_not_called()


@pytest.mark.parametrize("operation,field", [
    ("register_agent", "name"), ("register_agent", "card_overrides"),
    ("enable_a2a", "name"), ("enable_a2a", "card_overrides"),
    ("update_settings", "card_overrides"),
])
def test_registration_rejects_invalid_names_before_write(mocker, operation, field):
    from management.services.agent.a2a import service as module

    database = mocker.patch.object(module, "a2a_agent_db")
    session = mocker.patch.object(module, "get_db_session")
    kwargs = {"agent_id": 1, "tenant_id": "tenant", "user_id": "user"}
    if operation == "register_agent":
        kwargs["name"] = "Valid-Agent"
    kwargs[field] = "Invalid Name" if field == "name" else {"name": "Invalid Name"}
    with pytest.raises(ValueError, match="must not contain spaces"):
        getattr(module.A2AServerService(), operation)(**kwargs)
    database.create_server_agent.assert_not_called()
    database.enable_server_agent.assert_not_called()
    database.disable_server_agent.assert_not_called()
    session.assert_not_called()


@pytest.mark.parametrize("name", ["Invalid Name", " Agent", "Agent\nName", "智能\u3000体"])
def test_invalid_a2a_publication_has_no_version_side_effects(mocker, name):
    from management.services.agent import versions

    mocker.patch.object(versions, "is_system_agent", return_value=False)
    mocker.patch.object(versions, "query_agent_draft", return_value=(
        {"name": name, "is_a2a": True}, [], []
    ))
    writes = [mocker.patch.object(versions, function) for function in (
        "get_next_version_no", "insert_agent_snapshot", "insert_version", "update_agent_current_version"
    )]
    with pytest.raises(ValueError, match="must not contain spaces"):
        versions.publish_version_impl(1, "tenant", "user")
    for write in writes:
        write.assert_not_called()
