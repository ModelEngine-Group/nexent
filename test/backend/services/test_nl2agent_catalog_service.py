"""Focused NL2AGENT service tests."""
# ruff: noqa: F405

import json

from nexent.core.tools.nl2agent.search_web_skills_tool import (
    get_search_web_skills_tool,
)
from utils.nl2agent_catalog_snapshot import create_catalog_snapshot

from test.backend.services.nl2agent_test_support import *  # noqa: F403


def _snapshot_catalogs(tool_catalog):
    return {
        "tool_catalog": tool_catalog,
        "skill_catalog": [],
        "registry_results": [],
        "community_results": [],
        "official_skills": [],
    }


def test_catalog_snapshot_hash_is_normalized_and_version_independent():
    first = create_catalog_snapshot(
        _snapshot_catalogs(
            [
                {
                    "tool_id": 2,
                    "name": " beta ",
                    "metadata": {"b": 2, "a": 1, "label": "Ａ"},
                },
                {"tool_id": 1, "name": " alpha "},
            ]
        ),
        catalog_version="catalog_11111111111111111111111111111111",
    )
    equivalent = create_catalog_snapshot(
        _snapshot_catalogs(
            [
                {"name": "alpha", "tool_id": 1},
                {
                    "metadata": {"a": 1, "b": 2, "label": "A"},
                    "name": "beta",
                    "tool_id": 2,
                },
            ]
        ),
        catalog_version="catalog_22222222222222222222222222222222",
    )

    assert first["catalog_hash"] == equivalent["catalog_hash"]
    assert first["catalog_version"] != equivalent["catalog_version"]
    assert first["tool_catalog"] == equivalent["tool_catalog"]


def test_catalog_snapshot_preserves_semantically_ordered_nested_arrays():
    first = create_catalog_snapshot(
        _snapshot_catalogs(
            [{"tool_id": 1, "parameters": [{"name": "first"}, {"name": "second"}]}]
        ),
        catalog_version="catalog_11111111111111111111111111111111",
    )
    reordered = create_catalog_snapshot(
        _snapshot_catalogs(
            [{"tool_id": 1, "parameters": [{"name": "second"}, {"name": "first"}]}]
        ),
        catalog_version="catalog_22222222222222222222222222222222",
    )

    assert first["catalog_hash"] != reordered["catalog_hash"]


def test_catalog_snapshot_hash_changes_with_catalog_content():
    first = create_catalog_snapshot(
        _snapshot_catalogs([{"tool_id": 1, "name": "alpha"}]),
        catalog_version="catalog_11111111111111111111111111111111",
    )
    changed = create_catalog_snapshot(
        _snapshot_catalogs([{"tool_id": 1, "name": "changed"}]),
        catalog_version="catalog_22222222222222222222222222222222",
    )

    assert first["catalog_hash"] != changed["catalog_hash"]


def test_tool_catalog_redacts_sensitive_parameter_defaults():
    params = [
        {"name": "api_key", "type": "string", "default": "secret-value"},
        {"name": "limit", "type": "integer", "default": 5},
    ]

    assert redact_tool_parameter_defaults(params) == [
        {"name": "api_key", "type": "string", "default": None},
        {"name": "limit", "type": "integer", "default": 5},
    ]
    assert params[0]["default"] == "secret-value"


def test_web_skill_configuration_is_authoritative_and_redacts_secrets():
    dependencies = MagicMock()
    dependencies.get_owned_draft.return_value = {"agent_id": 202}
    dependencies.get_session_catalogs.return_value = {
        "official_skills": [
            {"skill_id": 12, "skill_name": "writer", "status": "installable"}
        ]
    }
    dependencies.get_official_configuration.return_value = {
        "skill_name": "writer",
        "config_schemas": [
            {
                "name": "api_key",
                "type": "string",
                "required": True,
                "default": "schema-secret",
            },
            {"name": "tone", "type": "string", "required": False},
        ],
        "config_values": {"api_key": "never-return", "tone": "formal"},
    }

    result = nl2agent_catalog_service.get_web_skill_configuration(
        dependencies,
        agent_id=202,
        tenant_id="tenant_1",
        skill_id=12,
        skill_name="writer",
    )

    assert result["config_values"] == {"tone": "formal"}
    assert result["config_schemas"][0]["value"] is None
    assert result["config_schemas"][0]["default"] is None
    assert "never-return" not in str(result)
    assert "schema-secret" not in str(result)


def test_resolve_skill_config_values_validates_and_preserves_internal_defaults():
    schemas = [
        {"name": "enabled", "type": "boolean", "required": True},
        {
            "name": "endpoint",
            "type": "string",
            "required": True,
            "depends_on": "enabled",
        },
        {"name": "region", "type": "string", "optional": False},
    ]

    assert nl2agent_catalog_service._resolve_skill_config_values(
        12,
        schemas,
        {
            "internal": "kept",
            "enabled": False,
            "endpoint": "ignored",
            "region": "us-east-1",
        },
        {},
    ) == {"internal": "kept", "enabled": False, "region": "us-east-1"}
    with pytest.raises(Nl2AgentValidationError, match="requires configuration field"):
        nl2agent_catalog_service._resolve_skill_config_values(
            12, schemas, {"enabled": True, "region": "us-east-1"}, {}
        )
    with pytest.raises(Nl2AgentValidationError, match="requires configuration field"):
        nl2agent_catalog_service._resolve_skill_config_values(
            12, schemas, {"enabled": False}, {}
        )
    with pytest.raises(Nl2AgentValidationError, match="unknown configuration"):
        nl2agent_catalog_service._resolve_skill_config_values(
            12,
            schemas,
            {"enabled": False, "region": "us-east-1"},
            {"unknown": "value"},
        )


@pytest.mark.parametrize(
    ("items_key", "nested_cursor_key", "first_page", "second_page"),
    [
        (
            "servers",
            "metadata",
            {"servers": [{"name": "first"}], "metadata": {"nextCursor": "page-2"}},
            {"servers": [{"name": "second"}], "metadata": {}},
        ),
        (
            "items",
            None,
            {"items": [{"name": "first"}], "nextCursor": "page-2"},
            {"items": [{"name": "second"}], "nextCursor": None},
        ),
    ],
)
async def test_marketplace_loader_reads_every_cursor_page(
    items_key,
    nested_cursor_key,
    first_page,
    second_page,
):
    provider = AsyncMock(side_effect=[first_page, second_page])

    result = await nl2agent_catalog_service._load_marketplace_pages(
        provider,
        items_key=items_key,
        nested_cursor_key=nested_cursor_key,
    )

    assert [item["name"] for item in result] == ["first", "second"]
    assert [call.kwargs["cursor"] for call in provider.await_args_list] == [
        None,
        "page-2",
    ]
    assert all(call.kwargs["limit"] == 100 for call in provider.await_args_list)


@pytest.mark.asyncio
async def test_marketplace_loader_rejects_unbounded_unique_cursors():
    provider = AsyncMock(
        side_effect=[
            {"items": [{"name": "first"}], "nextCursor": "page-2"},
            {"items": [{"name": "second"}], "nextCursor": "page-3"},
        ]
    )

    with pytest.raises(Nl2AgentExternalServiceError, match="page budget"):
        await nl2agent_catalog_service._load_marketplace_pages(
            provider,
            items_key="items",
            max_pages=2,
        )

    assert provider.await_count == 2


@pytest.mark.asyncio
async def test_marketplace_loader_rejects_item_and_byte_budget_overflow():
    provider = AsyncMock(
        return_value={"items": [{"name": "first"}, {"name": "second"}]}
    )
    with pytest.raises(Nl2AgentExternalServiceError, match="item budget"):
        await nl2agent_catalog_service._load_marketplace_pages(
            provider,
            items_key="items",
            max_items=1,
        )

    provider = AsyncMock(return_value={"items": [{"description": "large"}]})
    with pytest.raises(Nl2AgentExternalServiceError, match="byte budget"):
        await nl2agent_catalog_service._load_marketplace_pages(
            provider,
            items_key="items",
            max_bytes=5,
        )


@pytest.mark.asyncio
async def test_marketplace_loader_enforces_total_time_budget():
    async def stalled_provider(**_kwargs):
        await asyncio.Event().wait()

    with pytest.raises(Nl2AgentExternalServiceError, match="time budget"):
        await nl2agent_catalog_service._load_marketplace_pages(
            stalled_provider,
            items_key="items",
            timeout_seconds=0.01,
        )


def test_marketplace_metadata_redaction_removes_declared_and_container_secrets():
    sanitized = nl2agent_catalog_service.redact_mcp_marketplace_metadata(
        {
            "headers": [
                {
                    "name": "Authorization",
                    "isSecret": True,
                    "value": "registry-secret",
                },
                {
                    "name": "X-Credential",
                    "is_secret": True,
                    "default": "snake-case-secret",
                },
            ],
            "configJson": {
                "mcpServers": {
                    "example": {
                        "command": "npx",
                        "env": {"API_TOKEN": "community-secret", "REGION": "eu"},
                    }
                }
            },
        }
    )

    assert sanitized["headers"][0]["value"] is None
    assert sanitized["headers"][1]["default"] is None
    environment = sanitized["configJson"]["mcpServers"]["example"]["env"]
    assert environment == {"API_TOKEN": None, "REGION": "eu"}
    snapshot = create_catalog_snapshot(
        {
            "tool_catalog": [],
            "skill_catalog": [],
            "registry_results": [sanitized],
            "community_results": [],
            "official_skills": [],
        },
        catalog_version="catalog_11111111111111111111111111111111",
    )
    serialized = json.dumps(snapshot, ensure_ascii=False)
    assert "registry-secret" not in serialized
    assert "snake-case-secret" not in serialized
    assert "community-secret" not in serialized


@pytest.mark.asyncio
async def test_local_catalog_queries_are_bounded_at_provider_boundary():
    list_tools = AsyncMock(return_value=[])
    list_skills = MagicMock(return_value=[])
    dependencies = nl2agent_catalog_service.CatalogDependencies(
        list_all_tools=list_tools,
        list_tenant_skills=list_skills,
        list_registry_mcp_services=AsyncMock(return_value={"servers": []}),
        list_community_mcp_services=AsyncMock(return_value={"items": []}),
        get_official_skills_with_status=MagicMock(return_value=[]),
    )

    await nl2agent_catalog_service.load_session_catalogs("tenant_1", dependencies)

    list_tools.assert_awaited_once_with(
        tenant_id="tenant_1",
        labels=None,
        limit=2_000,
    )
    list_skills.assert_called_once_with(tenant_id="tenant_1", limit=2_000)


@pytest.mark.asyncio
async def test_resource_missing_official_skill_is_online_recoverable_only():
    dependencies = nl2agent_catalog_service.CatalogDependencies(
        list_all_tools=AsyncMock(return_value=[]),
        list_tenant_skills=MagicMock(
            return_value=[
                {"skill_id": 3, "name": "create-docx", "description": "Missing"},
                {"skill_id": 4, "name": "working-local", "description": "Ready"},
            ]
        ),
        list_registry_mcp_services=AsyncMock(return_value={"servers": []}),
        list_community_mcp_services=AsyncMock(return_value={"items": []}),
        get_official_skills_with_status=MagicMock(
            return_value=[
                {
                    "skill_id": 3,
                    "skill_name": "create-docx",
                    "name": "create-docx",
                    "status": "resource_missing",
                },
                {
                    "skill_id": 5,
                    "skill_name": "web-search",
                    "name": "web-search",
                    "status": "installable",
                },
                {
                    "skill_id": 6,
                    "skill_name": "installed-official",
                    "name": "installed-official",
                    "status": "installed",
                },
            ]
        ),
    )

    catalogs, missing_names = await nl2agent_catalog_service.load_session_catalogs(
        "tenant_1",
        dependencies,
    )

    assert [item["name"] for item in catalogs["skill_catalog"]] == [
        "working-local"
    ]
    assert [item["name"] for item in catalogs["official_skills"]] == [
        "create-docx",
        "web-search",
    ]
    assert missing_names == ["create-docx"]

    recorded = []
    tool = get_search_web_skills_tool(
        draft_agent_id=202,
        tenant_id="tenant_1",
        official_skills=catalogs["official_skills"],
        requirements_confirmed=True,
        record_search_result=lambda **result: recorded.append(result),
    )

    payload = json.loads(tool(query="docx"))

    assert [(item["skill_id"], item["status"]) for item in payload["items"]] == [
        (3, "resource_missing")
    ]
    assert recorded[0]["resource_type"] == "skill"
