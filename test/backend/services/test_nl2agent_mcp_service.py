"""Focused NL2AGENT service tests."""
# ruff: noqa: F405

from test.backend.services.nl2agent_test_support import *  # noqa: F403


@pytest.mark.asyncio
async def test_bind_mcp_tools_validates_provenance_and_binds(monkeypatch):
    db_session, _ = _mock_database_transaction(monkeypatch)
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_mcp_record_by_id_and_tenant",
        MagicMock(return_value={"mcp_id": 5, "mcp_name": "github"}),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_tools_by_ids_for_tenant",
        MagicMock(
            return_value=[
                {
                    "tool_id": 11,
                    "author": "tenant_1",
                    "source": "mcp",
                    "usage": "github",
                },
            ]
        ),
    )
    bind = MagicMock()
    monkeypatch.setattr(nl2agent_service, "create_or_update_tool_by_tool_info", bind)
    reserve_binding = MagicMock(
        return_value={
            "recommendation_id": "registry:github",
            "discovered_tool_ids": [11],
        }
    )
    complete_binding = MagicMock()
    monkeypatch.setattr(
        nl2agent_service, "reserve_mcp_binding_operation", reserve_binding
    )
    monkeypatch.setattr(
        nl2agent_service, "complete_mcp_binding_operation", complete_binding
    )

    result = await nl2agent_service.bind_mcp_tools(
        agent_id=202, mcp_id=5, tool_ids=[11], tenant_id="tenant_1", user_id="user_1"
    )

    assert result["bound_tool_ids"] == [11]
    assert bind.call_count == 1
    assert bind.call_args.kwargs["db_session"] is db_session
    operation_id = reserve_binding.call_args.args[3]
    complete_binding.assert_called_once_with(
        "tenant_1",
        202,
        "registry:github",
        operation_id,
        "tools_bound",
    )


async def test_bind_mcp_tools_reconciles_after_redis_completion_failure(monkeypatch):
    _mock_database_transaction(monkeypatch)
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={
                "agent_id": 202,
                "name": "draft_test",
                "created_by": "user_1",
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_mcp_record_by_id_and_tenant",
        MagicMock(return_value={"mcp_id": 5, "mcp_name": "github"}),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_tools_by_ids_for_tenant",
        MagicMock(
            return_value=[
                {
                    "tool_id": 11,
                    "author": "tenant_1",
                    "source": "mcp",
                    "usage": "github",
                }
            ]
        ),
    )
    bind = MagicMock()
    monkeypatch.setattr(nl2agent_service, "create_or_update_tool_by_tool_info", bind)
    nl2agent_session_catalog.update_mcp_workflow(
        "tenant_1",
        202,
        "registry:github",
        status="connected",
        mcp_id=5,
        discovered_tool_ids=[11],
        bound_tool_ids=[],
    )
    real_complete = nl2agent_service.complete_mcp_binding_operation
    attempts = 0

    def flaky_complete(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise nl2agent_session_catalog.Nl2AgentSessionCatalogError(
                "redis unavailable"
            )
        return real_complete(*args, **kwargs)

    monkeypatch.setattr(
        nl2agent_service, "complete_mcp_binding_operation", flaky_complete
    )

    with pytest.raises(Nl2AgentOperationError, match="Retry binding"):
        await nl2agent_service.bind_mcp_tools(
            agent_id=202,
            mcp_id=5,
            tool_ids=[11],
            tenant_id="tenant_1",
            user_id="user_1",
        )

    state = nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)
    assert state["mcp_workflows"]["registry:github"]["status"] == "binding"

    result = await nl2agent_service.bind_mcp_tools(
        agent_id=202,
        mcp_id=5,
        tool_ids=[11],
        tenant_id="tenant_1",
        user_id="user_1",
    )

    assert result["bound_tool_ids"] == [11]
    assert bind.call_count == 2
    state = nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)
    assert state["mcp_workflows"]["registry:github"]["status"] == "tools_bound"


@pytest.mark.asyncio
async def test_bind_mcp_tools_rolls_back_when_later_tool_fails(monkeypatch):
    _, transaction = _mock_database_transaction(monkeypatch)
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_mcp_record_by_id_and_tenant",
        MagicMock(return_value={"mcp_id": 5, "mcp_name": "github"}),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_tools_by_ids_for_tenant",
        MagicMock(
            return_value=[
                {
                    "tool_id": tool_id,
                    "author": "tenant_1",
                    "source": "mcp",
                    "usage": "github",
                }
                for tool_id in (11, 12)
            ]
        ),
    )
    bind = MagicMock(side_effect=[None, RuntimeError("second tool failed")])
    monkeypatch.setattr(nl2agent_service, "create_or_update_tool_by_tool_info", bind)
    reserve_binding = MagicMock(
        return_value={
            "recommendation_id": "registry:github",
            "discovered_tool_ids": [11, 12],
        }
    )
    release_binding = MagicMock()
    monkeypatch.setattr(
        nl2agent_service, "reserve_mcp_binding_operation", reserve_binding
    )
    monkeypatch.setattr(
        nl2agent_service, "release_mcp_binding_operation", release_binding
    )

    with pytest.raises(
        Nl2AgentOperationError,
        match="Failed to bind MCP tools",
    ):
        await nl2agent_service.bind_mcp_tools(
            agent_id=202,
            mcp_id=5,
            tool_ids=[11, 12],
            tenant_id="tenant_1",
            user_id="user_1",
        )

    assert bind.call_count == 2
    assert transaction.__exit__.call_args.args[0] is RuntimeError
    operation_id = reserve_binding.call_args.args[3]
    release_binding.assert_called_once_with(
        "tenant_1",
        202,
        "registry:github",
        operation_id,
    )


@pytest.mark.asyncio
async def test_skip_mcp_tool_binding_resolves_connected_workflow(monkeypatch):
    db_session, _ = _mock_database_transaction(monkeypatch)
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_mcp_record_by_id_and_tenant",
        MagicMock(return_value={"mcp_id": 5, "mcp_name": "github"}),
    )
    reserve_binding = MagicMock(
        return_value={
            "recommendation_id": "registry:github",
            "discovered_tool_ids": [11, 12],
        }
    )
    complete_binding = MagicMock()
    monkeypatch.setattr(
        nl2agent_service, "reserve_mcp_binding_operation", reserve_binding
    )
    monkeypatch.setattr(
        nl2agent_service, "complete_mcp_binding_operation", complete_binding
    )
    delete_instances = MagicMock()
    monkeypatch.setattr(
        nl2agent_service,
        "delete_tool_instances_by_ids",
        delete_instances,
    )

    result = await nl2agent_service.skip_mcp_tool_binding(
        202,
        5,
        "tenant_1",
        "user_1",
    )

    assert result["status"] == "binding_skipped"
    delete_instances.assert_called_once_with(
        agent_id=202,
        tool_ids=[11, 12],
        tenant_id="tenant_1",
        user_id="user_1",
        version_no=0,
        db_session=db_session,
    )
    operation_id = reserve_binding.call_args.args[3]
    complete_binding.assert_called_once_with(
        "tenant_1",
        202,
        "registry:github",
        operation_id,
        "binding_skipped",
    )


@pytest.mark.asyncio
async def test_install_recommended_mcp_resolves_cached_remote_and_redacts_secrets(
    monkeypatch,
):
    catalogs = {
        "tool_catalog": [],
        "skill_catalog": [],
        "registry_results": [
            {
                "server": {
                    "name": "github",
                    "description": "Repository automation",
                    "remotes": [
                        {
                            "url": "https://${workspace}.example/{region}/sse",
                            "type": "sse",
                            "variables": [
                                {"name": "workspace", "isRequired": True},
                                {"name": "region", "isRequired": True},
                            ],
                            "headers": [
                                {
                                    "name": "Authorization",
                                    "isRequired": True,
                                    "isSecret": True,
                                }
                            ],
                        }
                    ],
                }
            }
        ],
        "community_results": [],
        "official_skills": [],
    }
    nl2agent_session_catalog.set_nl2agent_session_catalogs("tenant_1", 202, catalogs)
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_nl2agent_session_catalogs",
        MagicMock(return_value=catalogs),
    )
    add_mcp = AsyncMock(return_value=5)
    monkeypatch.setattr(nl2agent_service, "add_mcp_service", add_mcp)
    monkeypatch.setattr(
        nl2agent_service,
        "get_mcp_records_by_tenant",
        MagicMock(
            return_value=[
                {
                    "mcp_id": 5,
                    "mcp_name": "github",
                    "mcp_server": "https://mcp.example/sse",
                }
            ]
        ),
    )
    discover_tools = AsyncMock(return_value=[MagicMock()])
    monkeypatch.setattr(
        nl2agent_service,
        "get_tool_from_remote_mcp_server",
        discover_tools,
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_mcp_record_by_id_and_tenant",
        MagicMock(
            return_value={
                "mcp_id": 5,
                "mcp_name": "github",
                "mcp_server": "https://mcp.example/sse",
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "upsert_discovered_mcp_tools",
        MagicMock(
            return_value=[
                {"tool_id": 11, "name": "create_issue", "description": "Create issue"}
            ]
        ),
    )
    result = await nl2agent_service.install_recommended_mcp(
        agent_id=202,
        recommendation_id="registry:github",
        option_id="remote-0",
        config_values={
            "fields": {
                "variable:workspace:0": "acme",
                "variable:region:1": "eu",
                "header:Authorization:0": "secret-token",
            }
        },
        tenant_id="tenant_1",
        user_id="user_1",
    )

    assert result == {
        "agent_id": 202,
        "mcp_id": 5,
        "status": "connected",
        "tools": [
            {"tool_id": 11, "name": "create_issue", "description": "Create issue"}
        ],
    }
    assert "secret-token" not in str(result)
    nl2agent_service.validate_nl2agent_remote_mcp_url.assert_called_once_with(
        "https://acme.example/eu/sse"
    )
    assert add_mcp.call_args.kwargs["server_url"] == "https://acme.example/eu/sse"
    assert add_mcp.call_args.kwargs["authorization_token"] == "secret-token"
    pinned_factory = nl2agent_service.build_pinned_httpx_client_factory.return_value
    assert add_mcp.call_args.kwargs["httpx_client_factory"] is pinned_factory
    assert discover_tools.call_args.kwargs["httpx_client_factory"] is pinned_factory
    assert [
        call.args[0]
        for call in nl2agent_service.build_pinned_httpx_client_factory.call_args_list
    ] == [
        "https://acme.example/eu/sse",
        "https://mcp.example/sse",
    ]
    assert len(get_nl2agent_session_catalogs("tenant_1", 202)["registry_results"]) == 1
    assert (
        nl2agent_session_catalog.get_nl2agent_search_catalogs("tenant_1", 202)[
            "registry_results"
        ]
        == []
    )


@pytest.mark.asyncio
async def test_install_recommended_mcp_resumes_existing_installation_by_provenance(
    monkeypatch,
):
    catalogs = {
        "tool_catalog": [],
        "skill_catalog": [],
        "registry_results": [
            {
                "server": {
                    "name": "github",
                    "remotes": [
                        {
                            "url": "https://{workspace}.example/sse",
                            "type": "sse",
                            "variables": [{"name": "workspace", "isRequired": True}],
                            "headers": [
                                {
                                    "name": "Authorization",
                                    "isRequired": True,
                                    "isSecret": True,
                                }
                            ],
                        }
                    ],
                }
            }
        ],
        "community_results": [],
        "official_skills": [],
    }
    nl2agent_session_catalog.set_nl2agent_session_catalogs("tenant_1", 202, catalogs)
    installation_key = nl2agent_service._mcp_installation_key(
        202, "registry:github", "remote-0"
    )
    record = {
        "mcp_id": 5,
        "mcp_name": "github",
        "mcp_server": "https://old.example/sse",
        "registry_json": {"nl2agent_installation_key": installation_key},
    }
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_nl2agent_session_catalogs",
        MagicMock(return_value=catalogs),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_mcp_records_by_tenant",
        MagicMock(return_value=[record]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_mcp_record_by_id_and_tenant",
        MagicMock(return_value=record),
    )
    add_mcp = AsyncMock()
    monkeypatch.setattr(nl2agent_service, "add_mcp_service", add_mcp)
    update_mcp = MagicMock()
    monkeypatch.setattr(nl2agent_service, "update_mcp_service", update_mcp)
    monkeypatch.setattr(
        nl2agent_service,
        "get_tool_from_remote_mcp_server",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "upsert_discovered_mcp_tools",
        MagicMock(return_value=[]),
    )

    result = await nl2agent_service.install_recommended_mcp(
        agent_id=202,
        recommendation_id="registry:github",
        option_id="remote-0",
        config_values={
            "fields": {
                "variable:workspace:0": "corrected",
                "header:Authorization:0": "corrected-token",
            }
        },
        tenant_id="tenant_1",
        user_id="user_1",
    )

    assert result["mcp_id"] == 5
    add_mcp.assert_not_called()
    update_mcp.assert_called_once_with(
        tenant_id="tenant_1",
        user_id="user_1",
        mcp_id=5,
        new_name="github",
        description="",
        server_url="https://corrected.example/sse",
        authorization_token="corrected-token",
        custom_headers=None,
        tags=[],
    )
    workflow = nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)[
        "mcp_workflows"
    ]["registry:github"]
    assert workflow["installation_key"] == installation_key
    assert workflow["status"] == "connected"


@pytest.mark.asyncio
async def test_install_recommended_mcp_rejects_missing_declared_remote_variable(
    monkeypatch,
):
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_nl2agent_session_catalogs",
        MagicMock(
            return_value={
                "tool_catalog": [],
                "skill_catalog": [],
                "community_results": [],
                "official_skills": [],
                "registry_results": [
                    {
                        "server": {
                            "name": "required-config",
                            "remotes": [
                                {
                                    "url": "https://{workspace}.example/mcp",
                                    "variables": [
                                        {"name": "workspace", "isRequired": True}
                                    ],
                                }
                            ],
                        }
                    }
                ],
            }
        ),
    )

    with pytest.raises(
        Nl2AgentValidationError,
        match="Missing required MCP configuration",
    ):
        await nl2agent_service.install_recommended_mcp(
            agent_id=202,
            recommendation_id="registry:required-config",
            option_id="remote-0",
            config_values={"fields": {}},
            tenant_id="tenant_1",
            user_id="user_1",
        )

    workflow = nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)[
        "mcp_workflows"
    ]["registry:required-config"]
    assert workflow["status"] == "failed"
    assert "config_values" not in workflow


@pytest.mark.asyncio
async def test_install_recommended_package_preserves_registry_arguments_and_environment(
    monkeypatch,
):
    catalogs = {
        "tool_catalog": [],
        "skill_catalog": [],
        "community_results": [],
        "official_skills": [],
        "registry_results": [
            {
                "server": {
                    "name": "package-mcp",
                    "packages": [
                        {
                            "registryType": "npm",
                            "runtimeHint": "npx",
                            "identifier": "@example/package-mcp",
                            "transport": {"type": "stdio"},
                            "runtimeArguments": [
                                {"type": "positional", "value": "--yes"}
                            ],
                            "packageArguments": [
                                {"type": "named", "name": "--mode", "value": "safe"}
                            ],
                            "environmentVariables": [{"name": "REGION", "value": "eu"}],
                        }
                    ],
                }
            }
        ],
    }
    nl2agent_session_catalog.set_nl2agent_session_catalogs("tenant_1", 202, catalogs)
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_nl2agent_session_catalogs",
        MagicMock(return_value=catalogs),
    )
    add_container = AsyncMock(return_value={"mcp_id": 6})
    monkeypatch.setattr(nl2agent_service, "add_container_mcp_service", add_container)
    monkeypatch.setattr(
        nl2agent_service,
        "get_mcp_records_by_tenant",
        MagicMock(
            return_value=[
                {"mcp_id": 6, "mcp_name": "package-mcp", "mcp_server": "container"}
            ]
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_mcp_record_by_id_and_tenant",
        MagicMock(
            return_value={
                "mcp_id": 6,
                "mcp_name": "package-mcp",
                "mcp_server": "container",
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_service, "get_tool_from_remote_mcp_server", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        nl2agent_service, "upsert_discovered_mcp_tools", MagicMock(return_value=[])
    )
    await nl2agent_service.install_recommended_mcp(
        agent_id=202,
        recommendation_id="registry:package-mcp",
        option_id="package-0",
        config_values={"fields": {"container:port:0": "5010"}},
        tenant_id="tenant_1",
        user_id="user_1",
    )

    server = add_container.call_args.kwargs["mcp_config"].mcpServers["package-mcp"]
    assert server.command == "npx"
    assert server.args == ["--yes", "@example/package-mcp", "--mode=safe"]
    assert server.env == {"REGION": "eu"}


@pytest.mark.asyncio
async def test_install_recommended_package_reconfigures_existing_container(
    monkeypatch,
):
    catalogs = {
        "tool_catalog": [],
        "skill_catalog": [],
        "community_results": [],
        "official_skills": [],
        "registry_results": [
            {
                "server": {
                    "name": "package-mcp",
                    "packages": [
                        {
                            "registryType": "npm",
                            "runtimeHint": "npx",
                            "identifier": "@example/package-mcp",
                            "transport": {"type": "stdio"},
                            "environmentVariables": [{"name": "REGION", "value": "eu"}],
                        }
                    ],
                }
            }
        ],
    }
    installation_key = nl2agent_service._mcp_installation_key(
        202,
        "registry:package-mcp",
        "package-0",
    )
    record = {
        "mcp_id": 6,
        "mcp_name": "package-mcp",
        "mcp_server": "http://old-container/mcp",
        "registry_json": {"nl2agent_installation_key": installation_key},
    }
    nl2agent_session_catalog.set_nl2agent_session_catalogs(
        "tenant_1",
        202,
        catalogs,
    )
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_nl2agent_session_catalogs",
        MagicMock(return_value=catalogs),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_mcp_records_by_tenant",
        MagicMock(return_value=[record]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_mcp_record_by_id_and_tenant",
        MagicMock(return_value=record),
    )
    add_container = AsyncMock()
    reconfigure_container = AsyncMock()
    monkeypatch.setattr(
        nl2agent_service,
        "add_container_mcp_service",
        add_container,
    )
    monkeypatch.setattr(
        nl2agent_service,
        "reconfigure_container_mcp_service",
        reconfigure_container,
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_tool_from_remote_mcp_server",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "upsert_discovered_mcp_tools",
        MagicMock(return_value=[]),
    )

    result = await nl2agent_service.install_recommended_mcp(
        agent_id=202,
        recommendation_id="registry:package-mcp",
        option_id="package-0",
        config_values={
            "fields": {
                "environment:REGION:0": "us",
                "container:port:0": "5011",
            }
        },
        tenant_id="tenant_1",
        user_id="user_1",
    )

    assert result["mcp_id"] == 6
    add_container.assert_not_called()
    reconfigure_container.assert_awaited_once()
    kwargs = reconfigure_container.call_args.kwargs
    assert kwargs["mcp_id"] == 6
    assert kwargs["port"] == 5011
    assert kwargs["mcp_config"].mcpServers["package-mcp"].env == {"REGION": "us"}


@pytest.mark.asyncio
async def test_install_community_container_merges_card_secret_without_persisting_it(
    monkeypatch,
):
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    raw = {
        "communityId": 55,
        "name": "community-container",
        "transportType": "container",
        "configJson": {
            "mcpServers": {
                "community-container": {
                    "command": "npx",
                    "args": ["package"],
                    "env": {"API_TOKEN": None},
                }
            }
        },
    }
    catalogs = {
        "tool_catalog": [],
        "skill_catalog": [],
        "registry_results": [],
        "community_results": [raw],
        "official_skills": [],
    }
    nl2agent_session_catalog.set_nl2agent_session_catalogs("tenant_1", 202, catalogs)
    monkeypatch.setattr(
        nl2agent_service,
        "get_nl2agent_session_catalogs",
        MagicMock(return_value=catalogs),
    )
    add_container = AsyncMock(return_value={"mcp_id": 7})
    monkeypatch.setattr(nl2agent_service, "add_container_mcp_service", add_container)
    monkeypatch.setattr(
        nl2agent_service,
        "get_mcp_records_by_tenant",
        MagicMock(
            return_value=[
                {
                    "mcp_id": 7,
                    "mcp_name": "community-container",
                    "mcp_server": "container",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_mcp_record_by_id_and_tenant",
        MagicMock(
            return_value={
                "mcp_id": 7,
                "mcp_name": "community-container",
                "mcp_server": "container",
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_service, "get_tool_from_remote_mcp_server", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        nl2agent_service, "upsert_discovered_mcp_tools", MagicMock(return_value=[])
    )
    await nl2agent_service.install_recommended_mcp(
        agent_id=202,
        recommendation_id="community:55",
        option_id="community-container",
        config_values={
            "fields": {
                "container:port:0": "5020",
                "environment:API_TOKEN:0": "secret-token",
            }
        },
        tenant_id="tenant_1",
        user_id="user_1",
    )

    config = add_container.call_args.kwargs["mcp_config"]
    assert config.mcpServers["community-container"].env == {"API_TOKEN": "secret-token"}
    workflow = nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)[
        "mcp_workflows"
    ]["community:55"]
    assert "secret-token" not in str(workflow)


@pytest.mark.asyncio
async def test_install_web_skill_installs_by_skill_name(monkeypatch):
    _prepare_required_online_review()
    install_from_zip = MagicMock(return_value=["search-web-tavily"])
    bind_skill = MagicMock()
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_service, "install_skills_from_zip_for_tenant", install_from_zip
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_tenant_skill_by_name",
        MagicMock(return_value={"skill_id": 112, "skill_name": "search-web-tavily"}),
    )
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_skill_by_skill_info", bind_skill
    )
    nl2agent_session_catalog.set_nl2agent_session_catalogs(
        "tenant_1",
        202,
        {
            **_EXPECTED_SESSION_CATALOGS,
            "official_skills": [
                {
                    "skill_id": 12,
                    "skill_name": "search-web-tavily",
                    "status": "installable",
                },
                {
                    "skill_id": 13,
                    "skill_name": "code-review",
                    "status": "installable",
                },
            ],
        },
    )

    result = await nl2agent_service.install_web_skill(
        agent_id=202,
        skill_id=0,
        skill_name="search-web-tavily",
        tenant_id="tenant_1",
        user_id="user_1",
        locale="en",
    )
    Nl2AgentWebSkillInstallResponse.model_validate(result)

    install_from_zip.assert_called_once_with(
        skill_names=["search-web-tavily"],
        tenant_id="tenant_1",
        user_id="user_1",
        locale="en",
    )
    assert result == {
        "skill_id": 112,
        "skill_name": "search-web-tavily",
        "installed": True,
        "bound": True,
        "installed_ids": [],
        "installed_names": ["search-web-tavily"],
    }
    skill_request = bind_skill.call_args.kwargs["skill_info"]
    assert skill_request.skill_id == 112
    assert skill_request.agent_id == 202
    assert skill_request.enabled is True
    assert get_nl2agent_session_catalogs("tenant_1", 202)["official_skills"] == [
        {
            "skill_id": 12,
            "skill_name": "search-web-tavily",
            "status": "installable",
        },
        {
            "skill_id": 13,
            "skill_name": "code-review",
            "status": "installable",
        },
    ]
    assert (
        nl2agent_session_catalog.get_nl2agent_search_catalogs("tenant_1", 202)[
            "official_skills"
        ][0]["status"]
        == "installed"
    )

    retried = await nl2agent_service.install_web_skill(
        agent_id=202,
        skill_id=0,
        skill_name="search-web-tavily",
        tenant_id="tenant_1",
        user_id="user_1",
        locale="en",
    )
    assert retried == result
    install_from_zip.assert_called_once()
    bind_skill.assert_called_once()


@pytest.mark.asyncio
async def test_install_web_skill_reconciles_after_workflow_completion_failure(
    monkeypatch,
):
    _prepare_required_online_review()
    install_from_zip = MagicMock(return_value=["search-web-tavily"])
    bind_skill = MagicMock()
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={
                "agent_id": 202,
                "name": "draft_test",
                "created_by": "user_1",
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "install_skills_from_zip_for_tenant",
        install_from_zip,
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_tenant_skill_by_name",
        MagicMock(
            return_value={
                "skill_id": 112,
                "skill_name": "search-web-tavily",
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "create_or_update_skill_by_skill_info",
        bind_skill,
    )
    nl2agent_session_catalog.set_nl2agent_session_catalogs(
        "tenant_1",
        202,
        {
            **_EXPECTED_SESSION_CATALOGS,
            "official_skills": [
                {
                    "skill_id": 12,
                    "skill_name": "search-web-tavily",
                    "status": "installable",
                }
            ],
        },
    )
    real_complete = nl2agent_service.complete_online_installation
    attempts = 0

    def flaky_complete(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise nl2agent_session_catalog.Nl2AgentSessionCatalogError(
                "redis unavailable"
            )
        return real_complete(*args, **kwargs)

    monkeypatch.setattr(
        nl2agent_service,
        "complete_online_installation",
        flaky_complete,
    )

    with pytest.raises(Nl2AgentOperationError, match="Retry installation"):
        await nl2agent_service.install_web_skill(
            agent_id=202,
            skill_id=12,
            skill_name="search-web-tavily",
            tenant_id="tenant_1",
            user_id="user_1",
        )

    state = nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)
    assert next(iter(state["online_installations"].values()))["status"] == "installing"
    with pytest.raises(
        nl2agent_session_catalog.Nl2AgentSessionCatalogError,
        match="Skill installation",
    ):
        nl2agent_session_catalog.complete_online_configuration("tenant_1", 202)

    result = await nl2agent_service.install_web_skill(
        agent_id=202,
        skill_id=12,
        skill_name="search-web-tavily",
        tenant_id="tenant_1",
        user_id="user_1",
    )

    assert result["skill_id"] == 112
    assert install_from_zip.call_count == 2
    assert bind_skill.call_count == 2
    state = nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)
    assert next(iter(state["online_installations"].values()))["status"] == "completed"


@pytest.mark.asyncio
async def test_install_web_skill_still_installs_by_legacy_skill_id(monkeypatch):
    _prepare_required_online_review()
    install_by_id = MagicMock(return_value=[107])
    bind_skill = MagicMock()
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(nl2agent_service, "install_skills_for_tenant", install_by_id)
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_skill_by_skill_info", bind_skill
    )
    nl2agent_session_catalog.set_nl2agent_session_catalogs(
        "tenant_1",
        202,
        {
            **_EXPECTED_SESSION_CATALOGS,
            "official_skills": [
                {
                    "skill_id": 77,
                    "skill_name": "legacy-source",
                    "status": "installable",
                },
                {
                    "skill_id": 88,
                    "skill_name": "keep-me",
                    "status": "installable",
                },
            ],
        },
    )

    result = await nl2agent_service.install_web_skill(
        agent_id=202,
        skill_id=77,
        tenant_id="tenant_1",
        user_id="user_1",
    )

    install_by_id.assert_called_once_with(
        skill_ids=[77], tenant_id="tenant_1", user_id="user_1"
    )
    assert result == {
        "skill_id": 107,
        "installed": True,
        "bound": True,
        "installed_ids": [107],
    }
    assert bind_skill.call_args.kwargs["skill_info"].skill_id == 107
    assert get_nl2agent_session_catalogs("tenant_1", 202)["official_skills"] == [
        {"skill_id": 77, "skill_name": "legacy-source", "status": "installable"},
        {"skill_id": 88, "skill_name": "keep-me", "status": "installable"},
    ]
    assert (
        nl2agent_session_catalog.get_nl2agent_search_catalogs("tenant_1", 202)[
            "official_skills"
        ][0]["status"]
        == "installed"
    )


@pytest.mark.asyncio
async def test_install_web_skill_keeps_recommendation_when_binding_fails(monkeypatch):
    _prepare_required_online_review()
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "install_skills_from_zip_for_tenant",
        MagicMock(return_value=["search-web-tavily"]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_tenant_skill_by_name",
        MagicMock(return_value={"skill_id": 112, "skill_name": "search-web-tavily"}),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "create_or_update_skill_by_skill_info",
        MagicMock(side_effect=RuntimeError("write failed")),
    )
    recommendation = {
        "skill_id": 12,
        "skill_name": "search-web-tavily",
        "status": "installable",
    }
    nl2agent_session_catalog.set_nl2agent_session_catalogs(
        "tenant_1",
        202,
        {**_EXPECTED_SESSION_CATALOGS, "official_skills": [recommendation]},
    )

    with pytest.raises(Nl2AgentOperationError, match="could not be bound"):
        await nl2agent_service.install_web_skill(
            agent_id=202,
            skill_id=12,
            skill_name="search-web-tavily",
            tenant_id="tenant_1",
            user_id="user_1",
        )

    assert get_nl2agent_session_catalogs("tenant_1", 202)["official_skills"] == [
        recommendation
    ]


@pytest.mark.asyncio
async def test_install_web_skill_rejects_empty_install_result(monkeypatch):
    _prepare_required_online_review()
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "install_skills_from_zip_for_tenant",
        MagicMock(return_value=[]),
    )
    bind_skill = MagicMock()
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_skill_by_skill_info", bind_skill
    )
    nl2agent_session_catalog.set_nl2agent_session_catalogs(
        "tenant_1",
        202,
        {
            **_EXPECTED_SESSION_CATALOGS,
            "official_skills": [
                {
                    "skill_id": 12,
                    "skill_name": "search-web-tavily",
                    "status": "installable",
                }
            ],
        },
    )

    with pytest.raises(Nl2AgentExternalServiceError, match="Failed to install"):
        await nl2agent_service.install_web_skill(
            agent_id=202,
            skill_id=12,
            skill_name="search-web-tavily",
            tenant_id="tenant_1",
            user_id="user_1",
        )

    bind_skill.assert_not_called()


@pytest.mark.asyncio
async def test_install_web_skill_validates_draft_ownership(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(side_effect=ValueError("agent not found")),
    )
    install_from_zip = MagicMock()
    monkeypatch.setattr(
        nl2agent_service, "install_skills_from_zip_for_tenant", install_from_zip
    )

    with pytest.raises(
        nl2agent_service.Nl2AgentDraftNotFoundError,
        match="draft agent not found",
    ):
        await nl2agent_service.install_web_skill(
            agent_id=202,
            skill_id=0,
            skill_name="search-web-tavily",
            tenant_id="other_tenant",
            user_id="user_1",
        )

    install_from_zip.assert_not_called()


def test_get_owned_draft_rejects_different_creator(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={
                "agent_id": 202,
                "name": "draft_test",
                "created_by": "other_user",
            }
        ),
    )

    with pytest.raises(nl2agent_service.Nl2AgentDraftNotFoundError):
        nl2agent_service._get_owned_draft(202, "tenant_1", user_id="user_1")


def test_validate_nl2agent_run_context_accepts_exact_user_session_binding(monkeypatch):
    query_agent = MagicMock(
        side_effect=[
            {"agent_id": 101, "name": "nl2agent"},
            {"agent_id": 202, "name": "draft_test", "created_by": "user_1"},
        ]
    )
    get_conversation = MagicMock(return_value={"conversation_id": 902})
    monkeypatch.setattr(nl2agent_service, "search_agent_info_by_agent_id", query_agent)
    monkeypatch.setattr(nl2agent_service, "get_conversation", get_conversation)

    nl2agent_service.validate_nl2agent_run_context(
        runner_agent_id=101,
        draft_agent_id=202,
        conversation_id=902,
        tenant_id="tenant_1",
        user_id="user_1",
    )

    get_conversation.assert_called_once_with(902, user_id="user_1")


def test_validate_nl2agent_run_context_rejects_redis_conversation_mismatch(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            side_effect=[
                {"agent_id": 101, "name": "nl2agent"},
                {"agent_id": 202, "name": "draft_test", "created_by": "user_1"},
            ]
        ),
    )
    get_conversation = MagicMock()
    monkeypatch.setattr(nl2agent_service, "get_conversation", get_conversation)

    with pytest.raises(nl2agent_service.Nl2AgentDraftNotFoundError):
        nl2agent_service.validate_nl2agent_run_context(
            runner_agent_id=101,
            draft_agent_id=202,
            conversation_id=903,
            tenant_id="tenant_1",
            user_id="user_1",
        )

    get_conversation.assert_not_called()


def test_validate_nl2agent_run_context_rejects_conversation_not_owned_by_user(
    monkeypatch,
):
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            side_effect=[
                {"agent_id": 101, "name": "nl2agent"},
                {"agent_id": 202, "name": "draft_test", "created_by": "user_1"},
            ]
        ),
    )
    monkeypatch.setattr(
        nl2agent_service, "get_conversation", MagicMock(return_value=None)
    )

    with pytest.raises(nl2agent_service.Nl2AgentDraftNotFoundError):
        nl2agent_service.validate_nl2agent_run_context(
            runner_agent_id=101,
            draft_agent_id=202,
            conversation_id=902,
            tenant_id="tenant_1",
            user_id="user_1",
        )


def test_validate_nl2agent_run_context_rejects_non_builder_runner(monkeypatch):
    query_agent = MagicMock(return_value={"agent_id": 101, "name": "other_agent"})
    monkeypatch.setattr(nl2agent_service, "search_agent_info_by_agent_id", query_agent)

    with pytest.raises(nl2agent_service.Nl2AgentValidationError):
        nl2agent_service.validate_nl2agent_run_context(
            runner_agent_id=101,
            draft_agent_id=202,
            conversation_id=902,
            tenant_id="tenant_1",
            user_id="user_1",
        )

    query_agent.assert_called_once_with(agent_id=101, tenant_id="tenant_1")


@pytest.mark.asyncio
async def test_install_web_skill_rejects_resource_missing_catalog_item(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    install_from_zip = MagicMock()
    monkeypatch.setattr(
        nl2agent_service, "install_skills_from_zip_for_tenant", install_from_zip
    )
    nl2agent_session_catalog.set_nl2agent_session_catalogs(
        "tenant_1",
        202,
        {
            **_EXPECTED_SESSION_CATALOGS,
            "official_skills": [
                {
                    "skill_id": 12,
                    "skill_name": "missing-files",
                    "status": "resource_missing",
                }
            ],
        },
    )

    with pytest.raises(
        nl2agent_service.AgentRunException, match="not available for installation"
    ):
        await nl2agent_service.install_web_skill(
            agent_id=202,
            skill_id=12,
            skill_name="missing-files",
            tenant_id="tenant_1",
            user_id="user_1",
        )

    install_from_zip.assert_not_called()


async def test_install_web_skill_rejects_mismatched_id_and_name(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    install_from_zip = MagicMock()
    monkeypatch.setattr(
        nl2agent_service, "install_skills_from_zip_for_tenant", install_from_zip
    )
    nl2agent_session_catalog.set_nl2agent_session_catalogs(
        "tenant_1",
        202,
        {
            **_EXPECTED_SESSION_CATALOGS,
            "official_skills": [
                {"skill_id": 12, "skill_name": "skill-a", "status": "installable"},
                {"skill_id": 13, "skill_name": "skill-b", "status": "installable"},
            ],
        },
    )

    with pytest.raises(
        nl2agent_service.AgentRunException, match="not available for installation"
    ):
        await nl2agent_service.install_web_skill(
            agent_id=202,
            skill_id=12,
            skill_name="skill-b",
            tenant_id="tenant_1",
            user_id="user_1",
        )

    install_from_zip.assert_not_called()
