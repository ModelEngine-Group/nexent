"""
Unit tests for A2A Client Service.

Tests the A2AClientService class in backend/services/a2a_client_service.py.
"""
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import sys
from types import ModuleType


class TestA2AClientServiceExceptions:
    """Test class for A2A Client Service exceptions."""

    def test_base_exception_exists(self):
        """Test A2AClientServiceError exception exists."""
        from backend.services.a2a_client_service import A2AClientServiceError

        exc = A2AClientServiceError("Test error")
        assert str(exc) == "Test error"

    def test_agent_discovery_error_exists(self):
        """Test AgentDiscoveryError exception exists."""
        from backend.services.a2a_client_service import AgentDiscoveryError

        exc = AgentDiscoveryError("Discovery failed")
        assert str(exc) == "Discovery failed"

    def test_agent_call_error_exists(self):
        """Test AgentCallError exception exists."""
        from backend.services.a2a_client_service import AgentCallError

        exc = AgentCallError("Call failed")
        assert str(exc) == "Call failed"


class TestA2AClientServiceInit:
    """Test class for A2AClientService initialization."""

    def test_initialization(self):
        """Test service can be instantiated."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()
        assert service is not None


class TestExtractAgentUrl:
    """Test class for _extract_agent_url method."""

    def test_extract_from_supported_interfaces_json_rpc(self):
        """Test extracting URL from supportedInterfaces with json-rpc."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        card = {
            "supportedInterfaces": [
                {"protocolBinding": "http-json-rpc", "url": "https://example.com/v1"},
                {"protocolBinding": "http+json", "url": "https://example.com/rest"}
            ]
        }

        result = service._extract_agent_url(card)
        assert result == "https://example.com/v1"

    def test_extract_from_supported_interfaces_fallback(self):
        """Test extracting URL from supportedInterfaces (no json-rpc)."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        card = {
            "supportedInterfaces": [
                {"protocolBinding": "http+json", "url": "https://example.com/rest"}
            ]
        }

        result = service._extract_agent_url(card)
        assert result == "https://example.com/rest"

    def test_extract_from_endpoints(self):
        """Test extracting URL from endpoints dict."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        card = {
            "endpoints": {
                "http-streaming": "https://stream.example.com",
                "http-polling": "https://poll.example.com"
            }
        }

        result = service._extract_agent_url(card)
        assert result == "https://stream.example.com"

    def test_extract_from_provider(self):
        """Test extracting URL from provider dict."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        card = {
            "provider": {
                "organization": "Test Corp",
                "url": "https://provider.example.com"
            }
        }

        result = service._extract_agent_url(card)
        assert result == "https://provider.example.com"

    def test_extract_from_url_field(self):
        """Test extracting URL from url field."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        card = {
            "url": "https://agent.example.com/a2a"
        }

        result = service._extract_agent_url(card)
        assert result == "https://agent.example.com/a2a"

    def test_returns_empty_when_no_url(self):
        """Test returns empty string when no URL found."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        card = {
            "name": "Test Agent",
            "description": "No URL"
        }

        result = service._extract_agent_url(card)
        assert result == ""


class TestFindUrlInInterfaces:
    """Test class for _find_url_in_interfaces method."""

    def test_prefers_json_rpc(self):
        """Test preferring http-json-rpc protocol."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        interfaces = [
            {"protocolBinding": "http+json", "url": "https://rest.example.com"},
            {"protocolBinding": "http-json-rpc", "url": "https://rpc.example.com"}
        ]

        result = service._find_url_in_interfaces(interfaces)
        assert result == "https://rpc.example.com"

    def test_fallback_to_first_url(self):
        """Test fallback to first URL when no json-rpc."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        interfaces = [
            {"protocolBinding": "grpc", "url": "https://grpc.example.com"},
            {"protocolBinding": "http+json", "url": "https://rest.example.com"}
        ]

        result = service._find_url_in_interfaces(interfaces)
        assert result == "https://grpc.example.com"

    def test_returns_empty_for_empty_interfaces(self):
        """Test returns empty string for empty interfaces."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        result = service._find_url_in_interfaces([])
        assert result == ""

    def test_skips_interfaces_without_url(self):
        """Test skips interfaces without URL."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        interfaces = [
            {"protocolBinding": "grpc"},
            {"protocolBinding": "http+json", "url": "https://rest.example.com"}
        ]

        result = service._find_url_in_interfaces(interfaces)
        assert result == "https://rest.example.com"


class TestFindUrlInEndpoints:
    """Test class for _find_url_in_endpoints method."""

    def test_prefers_streaming(self):
        """Test preferring http-streaming."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        endpoints = {
            "http-polling": "https://poll.example.com",
            "http-streaming": "https://stream.example.com"
        }

        result = service._find_url_in_endpoints(endpoints)
        assert result == "https://stream.example.com"

    def test_fallback_to_polling(self):
        """Test fallback to http-polling."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        endpoints = {
            "http-polling": "https://poll.example.com"
        }

        result = service._find_url_in_endpoints(endpoints)
        assert result == "https://poll.example.com"

    def test_returns_first_key_if_no_preference_match(self):
        """Test returns first key when no preference matches."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        endpoints = {
            "grpc": "https://grpc.example.com",
            "websocket": "https://ws.example.com"
        }

        result = service._find_url_in_endpoints(endpoints)
        assert result in ["https://grpc.example.com", "https://ws.example.com"]

    def test_returns_empty_for_empty_endpoints(self):
        """Test returns empty string for empty endpoints."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        result = service._find_url_in_endpoints({})
        assert result == ""


class TestBuildEndpointUrl:
    """Test class for _build_endpoint_url method."""

    def test_build_json_rpc_url(self):
        """Test building JSON-RPC endpoint URL."""
        from backend.services.a2a_client_service import A2AClientService
        from database.a2a_agent_db import PROTOCOL_JSONRPC

        service = A2AClientService()

        result = service._build_endpoint_url(
            agent_url="https://example.com/a2a",
            protocol_type=PROTOCOL_JSONRPC,
            streaming=False
        )

        assert result == "https://example.com/a2a/v1"

    def test_build_http_json_streaming_url(self):
        """Test building HTTP+JSON streaming endpoint URL."""
        from backend.services.a2a_client_service import A2AClientService
        from database.a2a_agent_db import PROTOCOL_HTTP_JSON

        service = A2AClientService()

        result = service._build_endpoint_url(
            agent_url="https://example.com/a2a",
            protocol_type=PROTOCOL_HTTP_JSON,
            streaming=True
        )

        assert result == "https://example.com/a2a/message:stream"

    def test_build_http_json_non_streaming_url(self):
        """Test building HTTP+JSON non-streaming endpoint URL."""
        from backend.services.a2a_client_service import A2AClientService
        from database.a2a_agent_db import PROTOCOL_HTTP_JSON

        service = A2AClientService()

        result = service._build_endpoint_url(
            agent_url="https://example.com/a2a",
            protocol_type=PROTOCOL_HTTP_JSON,
            streaming=False
        )

        assert result == "https://example.com/a2a/message:send"

    def test_does_not_duplicate_path(self):
        """Test URL path is not duplicated."""
        from backend.services.a2a_client_service import A2AClientService
        from database.a2a_agent_db import PROTOCOL_HTTP_JSON

        service = A2AClientService()

        # URL already has path
        result = service._build_endpoint_url(
            agent_url="https://example.com/a2a/message:send",
            protocol_type=PROTOCOL_HTTP_JSON,
            streaming=False
        )

        # Should not duplicate /message:send
        assert result == "https://example.com/a2a/message:send"

    def test_handles_url_without_trailing_slash(self):
        """Test handles URL without trailing slash."""
        from backend.services.a2a_client_service import A2AClientService
        from database.a2a_agent_db import PROTOCOL_JSONRPC

        service = A2AClientService()

        result = service._build_endpoint_url(
            agent_url="https://example.com",
            protocol_type=PROTOCOL_JSONRPC,
            streaming=False
        )

        assert result == "https://example.com/v1"


class TestGetProtocolPath:
    """Test class for _get_protocol_path method."""

    def test_http_json_streaming(self):
        """Test HTTP+JSON streaming path."""
        from backend.services.a2a_client_service import A2AClientService
        from database.a2a_agent_db import PROTOCOL_HTTP_JSON

        service = A2AClientService()

        result = service._get_protocol_path(PROTOCOL_HTTP_JSON, streaming=True)
        assert result == "/message:stream"

    def test_http_json_non_streaming(self):
        """Test HTTP+JSON non-streaming path."""
        from backend.services.a2a_client_service import A2AClientService
        from database.a2a_agent_db import PROTOCOL_HTTP_JSON

        service = A2AClientService()

        result = service._get_protocol_path(PROTOCOL_HTTP_JSON, streaming=False)
        assert result == "/message:send"

    def test_json_rpc(self):
        """Test JSON-RPC path."""
        from backend.services.a2a_client_service import A2AClientService
        from database.a2a_agent_db import PROTOCOL_JSONRPC

        service = A2AClientService()

        result = service._get_protocol_path(PROTOCOL_JSONRPC, streaming=False)
        assert result == "/v1"

    def test_unknown_protocol(self):
        """Test unknown protocol returns empty path."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        result = service._get_protocol_path("unknown", streaming=False)
        assert result == ""


class TestGetExternalAgent:
    """Test class for get_external_agent method."""

    def test_returns_agent_when_found(self):
        """Test returns agent when found."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_agent = {
            "id": 1,
            "name": "Test Agent",
            "agent_url": "https://example.com"
        }

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = mock_agent

            result = service.get_external_agent(external_agent_id=1, tenant_id="tenant-1")

            assert result == mock_agent
            mock_db.get_external_agent_by_id.assert_called_once_with(1, "tenant-1")

    def test_returns_none_when_not_found(self):
        """Test returns None when agent not found."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = None

            result = service.get_external_agent(external_agent_id=999, tenant_id="tenant-1")

            assert result is None


class TestListExternalAgents:
    """Test class for list_external_agents method."""

    def test_calls_db_with_filters(self):
        """Test calls database with filters."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_agents = [
            {"id": 1, "name": "Agent 1"},
            {"id": 2, "name": "Agent 2"}
        ]

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.list_external_agents.return_value = mock_agents

            result = service.list_external_agents(
                tenant_id="tenant-1",
                source_type="url",
                is_available=True
            )

            assert len(result) == 2
            mock_db.list_external_agents.assert_called_once_with(
                tenant_id="tenant-1",
                source_type="url",
                is_available=True
            )

    def test_calls_db_without_filters(self):
        """Test calls database without filters."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.list_external_agents.return_value = []

            service.list_external_agents(tenant_id="tenant-1")

            mock_db.list_external_agents.assert_called_once_with(
                tenant_id="tenant-1",
                source_type=None,
                is_available=None
            )


class TestUpdateAgentProtocol:
    """Test class for update_agent_protocol method."""

    def test_updates_protocol(self):
        """Test updating agent protocol."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_result = {
            "id": 1,
            "name": "Test Agent",
            "protocol_type": "JSONRPC"
        }

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.update_external_agent_protocol.return_value = mock_result

            result = service.update_agent_protocol(
                external_agent_id=1,
                tenant_id="tenant-1",
                protocol_type="JSONRPC"
            )

            assert result == mock_result
            mock_db.update_external_agent_protocol.assert_called_once_with(
                external_agent_id=1,
                tenant_id="tenant-1",
                protocol_type="JSONRPC"
            )

    def test_returns_none_when_not_found(self):
        """Test returns None when agent not found."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.update_external_agent_protocol.return_value = None

            result = service.update_agent_protocol(
                external_agent_id=999,
                tenant_id="tenant-1",
                protocol_type="JSONRPC"
            )

            assert result is None


class TestDeleteExternalAgent:
    """Test class for delete_external_agent method."""

    def test_deletes_agent(self):
        """Test deleting external agent."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.delete_external_agent.return_value = True

            result = service.delete_external_agent(
                external_agent_id=1,
                tenant_id="tenant-1"
            )

            assert result is True
            mock_db.delete_external_agent.assert_called_once_with(1, "tenant-1")

    def test_returns_false_when_not_found(self):
        """Test returns False when agent not found."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.delete_external_agent.return_value = False

            result = service.delete_external_agent(
                external_agent_id=999,
                tenant_id="tenant-1"
            )

            assert result is False


class TestDiscoverFromUrl:
    """Test class for discover_from_url async method."""

    @pytest.mark.asyncio
    async def test_discovers_agent_from_url(self):
        """Test discovering agent from URL."""
        from backend.services.a2a_client_service import (
            A2AClientService,
            AgentDiscoveryError
        )

        service = A2AClientService()

        mock_card = {
            "name": "Test Agent",
            "description": "A test agent",
            "capabilities": {"streaming": True}
        }

        mock_result = {
            "id": 1,
            "name": "Test Agent",
            "agent_url": "https://example.com"
        }

        with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.get_json = AsyncMock(return_value=mock_card)

            with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
                mock_db.create_external_agent_from_url.return_value = mock_result

                result = await service.discover_from_url(
                    url="https://example.com/agent.json",
                    tenant_id="tenant-1",
                    user_id="user-1"
                )

                assert result == mock_result
                mock_db.create_external_agent_from_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_discovers_with_agent_id_field(self):
        """Test discovering agent with agent_id field in card."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_card = {
            "agent_id": "agent-123",
            "name": "Test Agent",
            "description": "A test agent"
        }

        mock_result = {"id": 1, "name": "Test Agent"}

        with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.get_json = AsyncMock(return_value=mock_card)

            with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
                mock_db.create_external_agent_from_url.return_value = mock_result

                await service.discover_from_url(
                    url="https://example.com/agent.json",
                    tenant_id="tenant-1",
                    user_id="user-1"
                )

                call_kwargs = mock_db.create_external_agent_from_url.call_args[1]
                assert "source_url" in call_kwargs

    @pytest.mark.asyncio
    async def test_generates_hash_based_agent_id_when_no_id_field(self):
        """Test name is used when no hash-based ID generation is triggered."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_card = {
            "name": "Test Agent",
            "description": "A test agent"
            # No agent_id, id, endpoint_id
        }

        mock_result = {"id": 1, "name": "Test Agent"}

        with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.get_json = AsyncMock(return_value=mock_card)

            with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
                mock_db.create_external_agent_from_url.return_value = mock_result

                await service.discover_from_url(
                    url="https://example.com/agent.json",
                    tenant_id="tenant-1",
                    user_id="user-1"
                )

                call_kwargs = mock_db.create_external_agent_from_url.call_args[1]
                # The name "Test Agent" is used as fallback for agent_id
                assert call_kwargs["name"] == "Test Agent"

    @pytest.mark.asyncio
    async def test_raises_agent_discovery_error_on_http_error(self):
        """Test AgentDiscoveryError is raised on HTTP error with traceback."""
        from backend.services.a2a_client_service import (
            A2AClientService,
            AgentDiscoveryError
        )
        import aiohttp

        service = A2AClientService()
        test_url = "https://example.com/agent.json"

        with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.get_json = AsyncMock(
                side_effect=aiohttp.ClientError("Connection failed")
            )

            with pytest.raises(AgentDiscoveryError) as exc_info:
                await service.discover_from_url(
                    url=test_url,
                    tenant_id="tenant-1",
                    user_id="user-1"
                )

            error_msg = str(exc_info.value)
            assert "Discovery failed" in error_msg
            assert "ClientError" in error_msg
            assert "Connection failed" in error_msg

    @pytest.mark.asyncio
    async def test_raises_agent_discovery_error_on_generic_exception(self):
        """Test AgentDiscoveryError is raised on generic exception."""
        from backend.services.a2a_client_service import (
            A2AClientService,
            AgentDiscoveryError
        )

        service = A2AClientService()

        with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.get_json = AsyncMock(side_effect=ValueError("Invalid JSON"))

            with pytest.raises(AgentDiscoveryError) as exc_info:
                await service.discover_from_url(
                    url="https://example.com/agent.json",
                    tenant_id="tenant-1",
                    user_id="user-1"
                )

            error_msg = str(exc_info.value)
            assert "Discovery failed" in error_msg
            assert "ValueError" in error_msg
            assert "Invalid JSON" in error_msg


class TestDiscoverFromNacos:
    """Test class for discover_from_nacos async method."""

    @pytest.mark.asyncio
    async def test_raises_error_when_config_not_found(self):
        """Test raises error when Nacos config not found."""
        from backend.services.a2a_client_service import (
            A2AClientService,
            AgentDiscoveryError
        )

        service = A2AClientService()

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_nacos_config_by_id.return_value = None

            with pytest.raises(AgentDiscoveryError, match="not found"):
                await service.discover_from_nacos(
                    nacos_config_id="config-1",
                    agent_names=["agent-1"],
                    tenant_id="tenant-1",
                    user_id="user-1"
                )

    @pytest.mark.asyncio
    async def test_raises_error_when_config_inactive(self):
        """Test raises error when Nacos config is inactive."""
        from backend.services.a2a_client_service import (
            A2AClientService,
            AgentDiscoveryError
        )

        service = A2AClientService()

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_nacos_config_by_id.return_value = {
                "config_id": "config-1",
                "is_active": False
            }

            with pytest.raises(AgentDiscoveryError, match="not active"):
                await service.discover_from_nacos(
                    nacos_config_id="config-1",
                    agent_names=["agent-1"],
                    tenant_id="tenant-1",
                    user_id="user-1"
                )

    @pytest.mark.asyncio
    async def test_discovers_multiple_agents_from_nacos(self):
        """Test discovering multiple agents from Nacos."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_nacos_config = {
            "config_id": "config-1",
            "is_active": True,
            "namespace_id": "public"
        }

        mock_agent_info_1 = {"id": 1, "name": "Agent 1"}
        mock_agent_info_2 = {"id": 2, "name": "Agent 2"}

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_nacos_config_by_id.return_value = mock_nacos_config
            mock_db.update_nacos_config_last_scan.return_value = None

            with patch.object(
                service, "_discover_single_from_nacos"
            ) as mock_discover:
                mock_discover.side_effect = [mock_agent_info_1, mock_agent_info_2]

                result = await service.discover_from_nacos(
                    nacos_config_id="config-1",
                    agent_names=["agent-1", "agent-2"],
                    tenant_id="tenant-1",
                    user_id="user-1"
                )

                assert len(result) == 2
                assert result[0]["name"] == "Agent 1"
                assert result[1]["name"] == "Agent 2"
                mock_db.update_nacos_config_last_scan.assert_called_once_with(
                    "config-1", "tenant-1"
                )

    @pytest.mark.asyncio
    async def test_handles_partial_discoveries(self):
        """Test handling partial discovery failures."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_nacos_config = {
            "config_id": "config-1",
            "is_active": True,
            "namespace_id": "public"
        }

        mock_agent_info = {"id": 1, "name": "Agent 1"}

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_nacos_config_by_id.return_value = mock_nacos_config
            mock_db.update_nacos_config_last_scan.return_value = None

            with patch.object(
                service, "_discover_single_from_nacos"
            ) as mock_discover:
                # First succeeds, second fails
                mock_discover.side_effect = [
                    mock_agent_info,
                    Exception("Connection failed")
                ]

                result = await service.discover_from_nacos(
                    nacos_config_id="config-1",
                    agent_names=["agent-1", "agent-2"],
                    tenant_id="tenant-1",
                    user_id="user-1"
                )

                # Should return partial results
                assert len(result) == 1
                assert result[0]["name"] == "Agent 1"

    @pytest.mark.asyncio
    async def test_raises_error_when_all_discoveries_fail(self):
        """Test raises AgentDiscoveryError when all agent discoveries fail."""
        from backend.services.a2a_client_service import (
            A2AClientService,
            AgentDiscoveryError
        )

        service = A2AClientService()

        mock_nacos_config = {
            "config_id": "config-1",
            "is_active": True,
            "namespace_id": "public"
        }

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_nacos_config_by_id.return_value = mock_nacos_config
            mock_db.update_nacos_config_last_scan.return_value = None

            with patch.object(
                service, "_discover_single_from_nacos"
            ) as mock_discover:
                mock_discover.side_effect = Exception("Connection failed")

                with pytest.raises(AgentDiscoveryError) as exc_info:
                    await service.discover_from_nacos(
                        nacos_config_id="config-1",
                        agent_names=["agent-1"],
                        tenant_id="tenant-1",
                        user_id="user-1"
                    )

                error_msg = str(exc_info.value)
                assert "All agent discoveries failed" in error_msg
                assert "Connection failed" in error_msg

    @pytest.mark.asyncio
    async def test_uses_namespace_from_config(self):
        """Test uses namespace from config when not provided."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_nacos_config = {
            "config_id": "config-1",
            "is_active": True,
            "namespace_id": "custom-namespace"
        }

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_nacos_config_by_id.return_value = mock_nacos_config
            mock_db.update_nacos_config_last_scan.return_value = None

            with patch.object(
                service, "_discover_single_from_nacos"
            ) as mock_discover:
                mock_discover.return_value = {"id": 1, "name": "Agent 1"}

                await service.discover_from_nacos(
                    nacos_config_id="config-1",
                    agent_names=["agent-1"],
                    tenant_id="tenant-1",
                    user_id="user-1"
                )

                # Verify namespace is passed correctly
                call_kwargs = mock_discover.call_args[1]
                assert call_kwargs["namespace"] == "custom-namespace"

    @pytest.mark.asyncio
    async def test_overrides_namespace_when_provided(self):
        """Test provided namespace overrides config namespace."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_nacos_config = {
            "config_id": "config-1",
            "is_active": True,
            "namespace_id": "config-namespace"
        }

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_nacos_config_by_id.return_value = mock_nacos_config
            mock_db.update_nacos_config_last_scan.return_value = None

            with patch.object(
                service, "_discover_single_from_nacos"
            ) as mock_discover:
                mock_discover.return_value = {"id": 1, "name": "Agent 1"}

                await service.discover_from_nacos(
                    nacos_config_id="config-1",
                    agent_names=["agent-1"],
                    tenant_id="tenant-1",
                    user_id="user-1",
                    namespace="override-namespace"
                )

                # Verify namespace is overridden
                call_kwargs = mock_discover.call_args[1]
                assert call_kwargs["namespace"] == "override-namespace"


class TestDiscoverSingleFromNacos:
    """Test class for _discover_single_from_nacos async method.

    Note: NacosClient is lazily imported, so tests mock the entire method.
    """

    @pytest.mark.asyncio
    async def test_returns_none_when_nacos_client_import_fails(self):
        """Test returns None when NacosClient import fails."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_nacos_config = {
            "config_id": "config-1",
            "nacos_addr": "http://nacos:8848",
            "nacos_username": "nacos",
            "nacos_password": "nacos"
        }

        # Mock the import to fail
        with patch("builtins.__import__", side_effect=ImportError("Module not found")):
            result = await service._discover_single_from_nacos(
                nacos_config=mock_nacos_config,
                agent_name="test-agent",
                namespace="public",
                tenant_id="tenant-1",
                user_id="user-1"
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_calls_nacos_client_with_correct_params(self):
        """Test that Nacos client is initialized and called with correct parameters."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_nacos_config = {
            "config_id": "config-1",
            "nacos_addr": "http://nacos:8848",
            "nacos_username": "testuser",
            "nacos_password": "testpass"
        }

        mock_instance = {
            "ip": "192.168.1.100",
            "port": 8080,
            "metadata": {"a2a_card_url": "https://example.com/agent.json"}
        }

        mock_card = {
            "name": "Test Agent",
            "description": "A test agent",
            "supportedInterfaces": [
                {"protocolBinding": "http-json-rpc", "url": "https://agent.example.com/v1"}
            ],
            "capabilities": {"streaming": True}
        }

        mock_client = AsyncMock()
        mock_client.query_service_instance = AsyncMock(return_value=mock_instance)
        mock_client.close = AsyncMock()

        # Create mock for nacos_client module
        mock_nacos_module = MagicMock()
        mock_nacos_module.NacosClient.return_value = mock_client

        with patch.dict(sys.modules, {"utils.nacos_client": mock_nacos_module}):
            with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
                mock_http = MockClient.return_value.__aenter__.return_value
                mock_http.get_json = AsyncMock(return_value=mock_card)

                with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
                    mock_db.create_external_agent_from_nacos.return_value = {
                        "id": 1,
                        "name": "Test Agent"
                    }

                    result = await service._discover_single_from_nacos(
                        nacos_config=mock_nacos_config,
                        agent_name="test-agent",
                        namespace="public",
                        tenant_id="tenant-1",
                        user_id="user-1"
                    )

                    assert result is not None
                    # Verify NacosClient was instantiated with correct params
                    mock_nacos_module.NacosClient.assert_called_once_with(
                        "http://nacos:8848", "testuser", "testpass"
                    )

    @pytest.mark.asyncio
    async def test_handles_missing_instance_gracefully(self):
        """Test handles case when service instance is not found."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_nacos_config = {
            "config_id": "config-1",
            "nacos_addr": "http://nacos:8848"
        }

        mock_client = AsyncMock()
        mock_client.query_service_instance = AsyncMock(return_value=None)
        mock_client.close = AsyncMock()

        # Create mock for nacos_client module
        mock_nacos_module = MagicMock()
        mock_nacos_module.NacosClient.return_value = mock_client

        with patch.dict(sys.modules, {"utils.nacos_client": mock_nacos_module}):
            result = await service._discover_single_from_nacos(
                nacos_config=mock_nacos_config,
                agent_name="test-agent",
                namespace="public",
                tenant_id="tenant-1",
                user_id="user-1"
            )

            assert result is None


class TestRefreshAgentCard:
    """Test class for refresh_agent_card async method."""

    @pytest.mark.asyncio
    async def test_raises_error_when_agent_not_found(self):
        """Test raises error when agent not found."""
        from backend.services.a2a_client_service import (
            A2AClientService,
            AgentDiscoveryError
        )

        service = A2AClientService()

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = None

            with pytest.raises(AgentDiscoveryError, match="not found"):
                await service.refresh_agent_card(
                    external_agent_id=999,
                    tenant_id="tenant-1",
                    user_id="user-1"
                )

    @pytest.mark.asyncio
    async def test_refreshes_agent_card(self):
        """Test refreshing agent card."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_agent = {
            "id": 1,
            "name": "Old Name",
            "source_url": "https://example.com/agent.json"
        }

        mock_card = {
            "name": "New Name",
            "description": "Updated description"
        }

        mock_result = {
            "id": 1,
            "name": "New Name",
            "description": "Updated description"
        }

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = mock_agent
            mock_db.refresh_external_agent_cache.return_value = mock_result

            with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
                mock_client = MockClient.return_value.__aenter__.return_value
                mock_client.get_json = AsyncMock(return_value=mock_card)

                result = await service.refresh_agent_card(
                    external_agent_id=1,
                    tenant_id="tenant-1",
                    user_id="user-1"
                )

                assert result == mock_result


class TestCallAgent:
    """Test class for call_agent async method."""

    @pytest.mark.asyncio
    async def test_raises_error_when_agent_not_found(self):
        """Test raises error when agent not found."""
        from backend.services.a2a_client_service import (
            A2AClientService,
            AgentCallError
        )

        service = A2AClientService()

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = None

            with pytest.raises(AgentCallError, match="not found"):
                await service.call_agent(
                    external_agent_id=999,
                    tenant_id="tenant-1",
                    message={"text": "test"}
                )

    @pytest.mark.asyncio
    async def test_raises_error_when_agent_unavailable(self):
        """Test raises error when agent is unavailable."""
        from backend.services.a2a_client_service import (
            A2AClientService,
            AgentCallError
        )

        service = A2AClientService()

        mock_agent = {
            "id": 1,
            "name": "Test Agent",
            "agent_url": "https://example.com",
            "is_available": False
        }

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = mock_agent

            with pytest.raises(AgentCallError, match="not available"):
                await service.call_agent(
                    external_agent_id=1,
                    tenant_id="tenant-1",
                    message={"text": "test"}
                )

    @pytest.mark.asyncio
    async def test_builds_json_rpc_payload_and_calls_agent(self):
        """Test builds JSON-RPC payload and calls agent."""
        from backend.services.a2a_client_service import (
            A2AClientService,
            AgentCallError
        )
        from database.a2a_agent_db import PROTOCOL_JSONRPC

        service = A2AClientService()

        mock_agent = {
            "id": 1,
            "name": "Test Agent",
            "agent_url": "https://example.com/a2a",
            "protocol_type": PROTOCOL_JSONRPC,
            "is_available": True
        }

        mock_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "success"}
        }

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = mock_agent

            with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
                mock_client = MockClient.return_value.__aenter__.return_value
                mock_client.post_json = AsyncMock(return_value=mock_response)
                # Mock __aexit__ for context manager
                MockClient.return_value.__aexit__ = AsyncMock()

                result = await service.call_agent(
                    external_agent_id=1,
                    tenant_id="tenant-1",
                    message={"text": "test message"}
                )

                assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_builds_http_json_payload(self):
        """Test builds HTTP+JSON payload for non-JSONRPC protocol."""
        from backend.services.a2a_client_service import A2AClientService
        from database.a2a_agent_db import PROTOCOL_HTTP_JSON

        service = A2AClientService()

        mock_agent = {
            "id": 1,
            "name": "Test Agent",
            "agent_url": "https://example.com/a2a",
            "protocol_type": PROTOCOL_HTTP_JSON,
            "is_available": True
        }

        mock_response = {"status": "success"}

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = mock_agent

            with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
                mock_client = MockClient.return_value.__aenter__.return_value
                mock_client.post_json = AsyncMock(return_value=mock_response)
                MockClient.return_value.__aexit__ = AsyncMock()

                result = await service.call_agent(
                    external_agent_id=1,
                    tenant_id="tenant-1",
                    message={"text": "test message"}
                )

                assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_raises_error_on_agent_error_response(self):
        """Test raises AgentCallError on agent error response."""
        from backend.services.a2a_client_service import (
            A2AClientService,
            AgentCallError
        )
        from database.a2a_agent_db import PROTOCOL_JSONRPC

        service = A2AClientService()

        mock_agent = {
            "id": 1,
            "name": "Test Agent",
            "agent_url": "https://example.com/a2a",
            "protocol_type": PROTOCOL_JSONRPC,
            "is_available": True
        }

        mock_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32600, "message": "Invalid Request"}
        }

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = mock_agent

            with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
                mock_client = MockClient.return_value.__aenter__.return_value
                mock_client.post_json = AsyncMock(return_value=mock_response)
                MockClient.return_value.__aexit__ = AsyncMock()

                with pytest.raises(AgentCallError) as exc_info:
                    await service.call_agent(
                        external_agent_id=1,
                        tenant_id="tenant-1",
                        message={"text": "test"}
                    )

                error_msg = str(exc_info.value)
                assert "Agent error" in error_msg
                assert "Invalid Request" in error_msg

    @pytest.mark.asyncio
    async def test_raises_error_on_client_error(self):
        """Test raises AgentCallError on client error."""
        from backend.services.a2a_client_service import (
            A2AClientService,
            AgentCallError
        )
        import aiohttp

        service = A2AClientService()

        mock_agent = {
            "id": 1,
            "name": "Test Agent",
            "agent_url": "https://example.com/a2a",
            "is_available": True
        }

        async def mock_post_json(*args, **kwargs):
            raise aiohttp.ClientError("Connection refused")

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = mock_agent

            with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
                mock_client = MockClient.return_value.__aenter__.return_value
                mock_client.post_json = mock_post_json

                with pytest.raises(AgentCallError) as exc_info:
                    await service.call_agent(
                        external_agent_id=1,
                        tenant_id="tenant-1",
                        message={"text": "test"}
                    )

                error_msg = str(exc_info.value)
                assert "Call failed" in error_msg
                assert "Connection refused" in error_msg

    @pytest.mark.asyncio
    async def test_returns_result_from_response(self):
        """Test returns result from response when no error."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_agent = {
            "id": 1,
            "name": "Test Agent",
            "agent_url": "https://example.com/a2a",
            "is_available": True
        }

        mock_response = {
            "result": {"task_id": "123", "status": "completed"}
        }

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = mock_agent

            with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
                mock_client = MockClient.return_value.__aenter__.return_value
                mock_client.post_json = AsyncMock(return_value=mock_response)
                MockClient.return_value.__aexit__ = AsyncMock()

                result = await service.call_agent(
                    external_agent_id=1,
                    tenant_id="tenant-1",
                    message={"text": "test"}
                )

                assert result["task_id"] == "123"
                assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_uses_default_protocol_when_not_specified(self):
        """Test uses JSON-RPC as default protocol when not specified."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_agent = {
            "id": 1,
            "name": "Test Agent",
            "agent_url": "https://example.com/a2a",
            "protocol_type": None,
            "is_available": True
        }

        mock_response = {"result": {"status": "ok"}}

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = mock_agent

            with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
                mock_client = MockClient.return_value.__aenter__.return_value
                mock_client.post_json = AsyncMock(return_value=mock_response)
                MockClient.return_value.__aexit__ = AsyncMock()

                await service.call_agent(
                    external_agent_id=1,
                    tenant_id="tenant-1",
                    message={"text": "test"}
                )

                # Verify post_json was called
                mock_client.post_json.assert_called_once()


class TestCallAgentStreaming:
    """Test class for call_agent_streaming async method."""

    @pytest.mark.asyncio
    async def test_raises_error_when_agent_not_found(self):
        """Test raises error when agent not found."""
        from backend.services.a2a_client_service import (
            A2AClientService,
            AgentCallError
        )

        service = A2AClientService()

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = None

            with pytest.raises(AgentCallError, match="not found"):
                # Must consume the async generator
                result_gen = service.call_agent_streaming(
                    external_agent_id=999,
                    tenant_id="tenant-1",
                    message={"text": "test"}
                )
                async for _ in result_gen:
                    pass

    @pytest.mark.asyncio
    async def test_raises_error_when_agent_unavailable(self):
        """Test raises error when agent is unavailable."""
        from backend.services.a2a_client_service import (
            A2AClientService,
            AgentCallError
        )

        service = A2AClientService()

        mock_agent = {
            "id": 1,
            "name": "Test Agent",
            "agent_url": "https://example.com",
            "is_available": False
        }

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = mock_agent

            with pytest.raises(AgentCallError, match="not available"):
                result_gen = service.call_agent_streaming(
                    external_agent_id=1,
                    tenant_id="tenant-1",
                    message={"text": "test"}
                )
                async for _ in result_gen:
                    pass

    @pytest.mark.asyncio
    async def test_builds_json_rpc_payload_for_streaming(self):
        """Test builds JSON-RPC payload for streaming call."""
        from backend.services.a2a_client_service import A2AClientService
        from database.a2a_agent_db import PROTOCOL_JSONRPC

        service = A2AClientService()

        mock_agent = {
            "id": 1,
            "name": "Test Agent",
            "agent_url": "https://example.com/a2a",
            "protocol_type": PROTOCOL_JSONRPC,
            "is_available": True
        }

        async def mock_stream(*args, **kwargs):
            yield {"type": "taskProgress", "data": {"status": "processing"}}
            yield {"type": "taskCompleted", "data": {"result": "done"}}

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = mock_agent

            with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
                mock_client = MockClient.return_value.__aenter__.return_value
                mock_client.post_stream = mock_stream

                events = []
                result_gen = service.call_agent_streaming(
                    external_agent_id=1,
                    tenant_id="tenant-1",
                    message={"text": "test"}
                )
                async for event in result_gen:
                    events.append(event)

                assert len(events) == 2
                assert events[0]["type"] == "taskProgress"

    @pytest.mark.asyncio
    async def test_builds_http_json_payload_for_streaming(self):
        """Test builds HTTP+JSON payload for streaming with HTTP+JSON protocol."""
        from backend.services.a2a_client_service import A2AClientService
        from database.a2a_agent_db import PROTOCOL_HTTP_JSON

        service = A2AClientService()

        mock_agent = {
            "id": 1,
            "name": "Test Agent",
            "agent_url": "https://example.com/a2a",
            "protocol_type": PROTOCOL_HTTP_JSON,
            "is_available": True
        }

        async def mock_stream(*args, **kwargs):
            yield {"data": "chunk1"}

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = mock_agent

            with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
                mock_client = MockClient.return_value.__aenter__.return_value
                mock_client.post_stream = mock_stream

                events = []
                result_gen = service.call_agent_streaming(
                    external_agent_id=1,
                    tenant_id="tenant-1",
                    message={"text": "test"}
                )
                async for event in result_gen:
                    events.append(event)

                assert len(events) == 1

    @pytest.mark.asyncio
    async def test_uses_api_key_in_headers(self):
        """Test uses API key in headers when provided."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_agent = {
            "id": 1,
            "name": "Test Agent",
            "agent_url": "https://example.com/a2a",
            "is_available": True
        }

        async def mock_stream(*args, **kwargs):
            yield {"data": "done"}

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = mock_agent

            with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
                mock_client = MockClient.return_value.__aenter__.return_value
                mock_client.post_stream = mock_stream

                with patch("backend.services.a2a_client_service.build_a2a_headers") as mock_headers:
                    mock_headers.return_value = {"Authorization": "Bearer test-key"}

                    result_gen = service.call_agent_streaming(
                        external_agent_id=1,
                        tenant_id="tenant-1",
                        message={"text": "test"},
                        api_key="test-key"
                    )
                    async for _ in result_gen:
                        pass

                    mock_headers.assert_called_once_with("test-key")

    @pytest.mark.asyncio
    async def test_raises_error_on_client_error(self):
        """Test raises AgentCallError on client error during streaming."""
        from backend.services.a2a_client_service import (
            A2AClientService,
            AgentCallError
        )
        import aiohttp

        service = A2AClientService()

        mock_agent = {
            "id": 1,
            "name": "Test Agent",
            "agent_url": "https://example.com/a2a",
            "is_available": True
        }

        async def mock_stream(*args, **kwargs):
            raise aiohttp.ClientError("Stream failed")
            yield  # Make this an async generator

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = mock_agent

            with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
                mock_client = MockClient.return_value.__aenter__.return_value
                mock_client.post_stream = mock_stream

                with pytest.raises(AgentCallError) as exc_info:
                    result_gen = service.call_agent_streaming(
                        external_agent_id=1,
                        tenant_id="tenant-1",
                        message={"text": "test"}
                    )
                    async for _ in result_gen:
                        pass

                error_msg = str(exc_info.value)
                assert "Streaming call failed" in error_msg
                assert "Stream failed" in error_msg

    @pytest.mark.asyncio
    async def test_builds_streaming_url_with_message_stream_path(self):
        """Test builds streaming URL with /message:stream path."""
        from backend.services.a2a_client_service import A2AClientService
        from database.a2a_agent_db import PROTOCOL_HTTP_JSON

        service = A2AClientService()

        mock_agent = {
            "id": 1,
            "name": "Test Agent",
            "agent_url": "https://example.com/a2a",
            "protocol_type": PROTOCOL_HTTP_JSON,
            "is_available": True
        }

        async def mock_stream(*args, **kwargs):
            yield {"done": True}

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = mock_agent

            with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
                mock_client = MockClient.return_value.__aenter__.return_value
                mock_client.post_stream = mock_stream

                result_gen = service.call_agent_streaming(
                    external_agent_id=1,
                    tenant_id="tenant-1",
                    message={"text": "test"}
                )
                events = []
                async for event in result_gen:
                    events.append(event)

                # Verify post_stream was called and yielded results
                assert len(events) == 1

    @pytest.mark.asyncio
    async def test_uses_default_protocol_for_streaming(self):
        """Test uses JSON-RPC as default protocol for streaming."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_agent = {
            "id": 1,
            "name": "Test Agent",
            "agent_url": "https://example.com/a2a",
            "protocol_type": None,
            "is_available": True
        }

        async def mock_stream(*args, **kwargs):
            yield {"done": True}

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = mock_agent

            with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
                mock_client = MockClient.return_value.__aenter__.return_value
                mock_client.post_stream = mock_stream

                result_gen = service.call_agent_streaming(
                    external_agent_id=1,
                    tenant_id="tenant-1",
                    message={"text": "test"}
                )
                events = []
                async for event in result_gen:
                    events.append(event)

                # Verify post_stream was called and yielded results
                assert len(events) == 1


class TestSingletonInstance:
    """Test class for singleton instance."""

    def test_singleton_exists(self):
        """Test that singleton instance exists."""
        from backend.services.a2a_client_service import a2a_client_service

        assert a2a_client_service is not None


class TestDiscoverFromUrlHashGeneration:
    """Additional tests for hash-based agent ID generation in discover_from_url."""

    @pytest.mark.asyncio
    async def test_generates_hash_based_agent_id_with_no_name(self):
        """Test generates hash-based agent_id when card has no ID fields and no name."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_card = {
            "description": "A test agent with no name"
            # No agent_id, id, endpoint_id, or name
        }

        mock_result = {"id": 1, "name": "unknown-abc12345"}

        with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.get_json = AsyncMock(return_value=mock_card)

            with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
                mock_db.create_external_agent_from_url.return_value = mock_result

                await service.discover_from_url(
                    url="https://example.com/agent.json",
                    tenant_id="tenant-1",
                    user_id="user-1"
                )

                call_kwargs = mock_db.create_external_agent_from_url.call_args[1]
                # Should generate a hash-based name like "unknown-xxxxx"
                assert call_kwargs["name"].startswith("unknown-")
                assert len(call_kwargs["name"]) >= 15  # "unknown-" plus 8-char hash


class TestDiscoverFromUrlExceptionHandling:
    """Additional tests for exception handling in discover_from_url."""

    @pytest.mark.asyncio
    async def test_logs_traceback_on_exception(self):
        """Test that exceptions are logged with full traceback."""
        from backend.services.a2a_client_service import A2AClientService, AgentDiscoveryError
        import traceback

        service = A2AClientService()

        with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.get_json = AsyncMock(side_effect=RuntimeError("Test error"))

            with patch("backend.services.a2a_client_service.logger") as mock_logger:
                with pytest.raises(AgentDiscoveryError) as exc_info:
                    await service.discover_from_url(
                        url="https://example.com/agent.json",
                        tenant_id="tenant-1",
                        user_id="user-1"
                    )

                # Verify error was logged with traceback
                assert mock_logger.error.called
                error_call = mock_logger.error.call_args[0][0]
                assert "Agent discovery failed" in error_call
                assert "RuntimeError" in error_call
                assert "Test error" in error_call


class TestDiscoverFromNacosErrors:
    """Additional tests for discover_from_nacos error handling."""

    @pytest.mark.asyncio
    async def test_collects_errors_from_failed_discoveries(self):
        """Test that errors from individual agent discoveries are collected."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_nacos_config = {
            "config_id": "config-1",
            "is_active": True,
            "namespace_id": "public"
        }

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_nacos_config_by_id.return_value = mock_nacos_config
            mock_db.update_nacos_config_last_scan.return_value = None

            with patch.object(service, "_discover_single_from_nacos") as mock_discover:
                # First succeeds, second fails, third succeeds
                mock_discover.side_effect = [
                    {"id": 1, "name": "Agent 1"},
                    Exception("Agent 2 failed"),
                    {"id": 3, "name": "Agent 3"}
                ]

                result = await service.discover_from_nacos(
                    nacos_config_id="config-1",
                    agent_names=["agent-1", "agent-2", "agent-3"],
                    tenant_id="tenant-1",
                    user_id="user-1"
                )

                assert len(result) == 2
                assert result[0]["name"] == "Agent 1"
                assert result[1]["name"] == "Agent 3"


class TestDiscoverSingleFromNacosDetailed:
    """Detailed tests for _discover_single_from_nacos method."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_card_url_in_metadata(self):
        """Test returns None when a2a_card_url is not in metadata and no host/port."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_nacos_config = {
            "config_id": "config-1",
            "nacos_addr": "http://nacos:8848"
        }

        mock_instance = {
            "ip": "192.168.1.100",
            "port": 8080,
            "metadata": {}  # No a2a_card_url, and no host/port
        }

        mock_client = AsyncMock()
        mock_client.query_service_instance = AsyncMock(return_value=mock_instance)
        mock_client.close = AsyncMock()

        mock_nacos_module = MagicMock()
        mock_nacos_module.NacosClient.return_value = mock_client

        with patch.dict(sys.modules, {"utils.nacos_client": mock_nacos_module}):
            result = await service._discover_single_from_nacos(
                nacos_config=mock_nacos_config,
                agent_name="test-agent",
                namespace="public",
                tenant_id="tenant-1",
                user_id="user-1"
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_constructs_url_from_host_port_when_no_card_url(self):
        """Test constructs agent card URL from host/port when metadata lacks a2a_card_url."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_nacos_config = {
            "config_id": "config-1",
            "nacos_addr": "http://nacos:8848"
        }

        mock_instance = {
            "ip": "192.168.1.100",
            "port": 8080,
            "metadata": {}  # No a2a_card_url
        }

        mock_card = {
            "name": "Test Agent",
            "description": "Test"
        }

        mock_client = AsyncMock()
        mock_client.query_service_instance = AsyncMock(return_value=mock_instance)
        mock_client.close = AsyncMock()

        mock_nacos_module = MagicMock()
        mock_nacos_module.NacosClient.return_value = mock_client

        with patch.dict(sys.modules, {"utils.nacos_client": mock_nacos_module}):
            with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
                mock_http = MockClient.return_value.__aenter__.return_value
                mock_http.get_json = AsyncMock(return_value=mock_card)

                with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
                    mock_db.create_external_agent_from_nacos.return_value = {"id": 1}

                    result = await service._discover_single_from_nacos(
                        nacos_config=mock_nacos_config,
                        agent_name="test-agent",
                        namespace="public",
                        tenant_id="tenant-1",
                        user_id="user-1"
                    )

                    assert result is not None
                    # Verify the agent card URL was constructed from host/port
                    mock_http.get_json.assert_called_once()
                    called_url = mock_http.get_json.call_args[0][0]
                    assert called_url == "http://192.168.1.100:8080/.well-known/agent-test-agent.json"

    @pytest.mark.asyncio
    async def test_handles_client_close_error(self):
        """Test handles errors during Nacos client close gracefully."""
        from backend.services.a2a_client_service import A2AClientService

        service = A2AClientService()

        mock_nacos_config = {
            "config_id": "config-1",
            "nacos_addr": "http://nacos:8848"
        }

        mock_instance = {
            "ip": "192.168.1.100",
            "port": 8080,
            "metadata": {"a2a_card_url": "https://example.com/agent.json"}
        }

        mock_card = {"name": "Test Agent"}

        mock_client = AsyncMock()
        mock_client.query_service_instance = AsyncMock(return_value=mock_instance)
        mock_client.close = AsyncMock(side_effect=Exception("Close failed"))

        mock_nacos_module = MagicMock()
        mock_nacos_module.NacosClient.return_value = mock_client

        with patch.dict(sys.modules, {"utils.nacos_client": mock_nacos_module}):
            with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
                mock_http = MockClient.return_value.__aenter__.return_value
                mock_http.get_json = AsyncMock(return_value=mock_card)

                with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
                    mock_db.create_external_agent_from_nacos.return_value = {"id": 1}

                    # Should not raise even if close fails
                    result = await service._discover_single_from_nacos(
                        nacos_config=mock_nacos_config,
                        agent_name="test-agent",
                        namespace="public",
                        tenant_id="tenant-1",
                        user_id="user-1"
                    )

                    assert result is not None


class TestRefreshAgentCardErrors:
    """Additional tests for refresh_agent_card error handling."""

    @pytest.mark.asyncio
    async def test_updates_availability_on_client_error(self):
        """Test updates agent availability to False on ClientError."""
        from backend.services.a2a_client_service import (
            A2AClientService,
            AgentDiscoveryError
        )
        import aiohttp

        service = A2AClientService()

        mock_agent = {
            "id": 1,
            "name": "Test Agent",
            "source_url": "https://example.com/agent.json"
        }

        async def mock_get_json(*args, **kwargs):
            raise aiohttp.ClientError("Network error")

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = mock_agent

            with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
                mock_client = MockClient.return_value.__aenter__.return_value
                mock_client.get_json = mock_get_json

                with pytest.raises(AgentDiscoveryError) as exc_info:
                    await service.refresh_agent_card(
                        external_agent_id=1,
                        tenant_id="tenant-1",
                        user_id="user-1"
                    )

                assert "Failed to refresh" in str(exc_info.value)

                # Verify availability was updated to False
                mock_db.update_agent_availability.assert_called_once_with(
                    external_agent_id=1,
                    tenant_id="tenant-1",
                    is_available=False,
                    check_result="ERROR"
                )

    @pytest.mark.asyncio
    async def test_raises_error_when_source_url_missing(self):
        """Test raises error when agent has no source URL."""
        from backend.services.a2a_client_service import (
            A2AClientService,
            AgentDiscoveryError
        )

        service = A2AClientService()

        mock_agent = {
            "id": 1,
            "name": "Test Agent"
            # No source_url
        }

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = mock_agent

            with pytest.raises(AgentDiscoveryError, match="No source URL"):
                await service.refresh_agent_card(
                    external_agent_id=1,
                    tenant_id="tenant-1",
                    user_id="user-1"
                )


class TestCallAgentProtocolVariants:
    """Additional tests for call_agent protocol handling."""

    @pytest.mark.asyncio
    async def test_builds_http_json_non_streaming_url_without_duplicate(self):
        """Test HTTP+JSON non-streaming URL doesn't duplicate path."""
        from backend.services.a2a_client_service import A2AClientService
        from database.a2a_agent_db import PROTOCOL_HTTP_JSON

        service = A2AClientService()

        mock_agent = {
            "id": 1,
            "name": "Test Agent",
            "agent_url": "https://example.com/a2a/message:send",
            "protocol_type": PROTOCOL_HTTP_JSON,
            "is_available": True
        }

        mock_response = {"result": {"status": "ok"}}

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = mock_agent

            with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
                mock_client = MockClient.return_value.__aenter__.return_value
                mock_client.post_json = AsyncMock(return_value=mock_response)
                MockClient.return_value.__aexit__ = AsyncMock()

                result = await service.call_agent(
                    external_agent_id=1,
                    tenant_id="tenant-1",
                    message={"text": "test"}
                )

                # Verify URL passed to post_json
                call_args = mock_client.post_json.call_args
                called_url = call_args[0][0]
                assert called_url == "https://example.com/a2a/message:send"


class TestCallAgentStreamingErrors:
    """Additional tests for call_agent_streaming error handling."""

    @pytest.mark.asyncio
    async def test_raises_error_on_streaming_client_error(self):
        """Test raises AgentCallError on aiohttp.ClientError during streaming."""
        from backend.services.a2a_client_service import (
            A2AClientService,
            AgentCallError
        )
        import aiohttp

        service = A2AClientService()

        mock_agent = {
            "id": 1,
            "name": "Test Agent",
            "agent_url": "https://example.com/a2a",
            "protocol_type": "JSONRPC",
            "is_available": True
        }

        class FailingAsyncIterator:
            """Mock async iterator that immediately raises ClientError."""
            def __init__(self, error):
                self.error = error

            def __aiter__(self):
                return self

            async def __anext__(self):
                raise aiohttp.ClientError(self.error)

        with patch("backend.services.a2a_client_service.a2a_agent_db") as mock_db:
            mock_db.get_external_agent_by_id.return_value = mock_agent

            with patch("backend.services.a2a_client_service.A2AHttpClient") as MockClient:
                mock_client = MockClient.return_value.__aenter__.return_value
                mock_client.post_stream = lambda *args, **kwargs: FailingAsyncIterator("Stream connection failed")

                with pytest.raises(AgentCallError) as exc_info:
                    result_gen = service.call_agent_streaming(
                        external_agent_id=1,
                        tenant_id="tenant-1",
                        message={"text": "test"}
                    )
                    async for _ in result_gen:
                        pass

                error_msg = str(exc_info.value)
                assert "Streaming call failed" in error_msg
                assert "Stream connection failed" in error_msg

