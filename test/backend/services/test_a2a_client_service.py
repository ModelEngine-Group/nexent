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


class TestSingletonInstance:
    """Test class for singleton instance."""

    def test_singleton_exists(self):
        """Test that singleton instance exists."""
        from backend.services.a2a_client_service import a2a_client_service

        assert a2a_client_service is not None
