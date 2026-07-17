"""Focused NL2AGENT service tests."""
# ruff: noqa: F405

from test.backend.services.nl2agent_test_support import *  # noqa: F403


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
    sanitized = nl2agent_service._redact_mcp_marketplace_metadata(
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
