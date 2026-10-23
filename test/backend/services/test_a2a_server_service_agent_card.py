"""
Unit tests for A2A Server Service - Agent Card operations.

This module contains tests for:
- get_agent_card method
- _resolve_base_url, _resolve_agent_url methods
- _build_agent_card_base, _build_supported_interfaces, _build_skills_from_agent methods
"""
import pytest
from unittest.mock import MagicMock, patch


# Mock database modules before importing the service
import sys
_agent_db_mock = MagicMock()
sys.modules['database.agent_db'] = _agent_db_mock
sys.modules['backend.database.agent_db'] = _agent_db_mock


class TestResolveBaseUrl:
    """Test class for _resolve_base_url method."""

    def test_uses_northbound_url(self):
        """Test uses NORTHBOUND_EXTERNAL_URL when use_northbound=True."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.NORTHBOUND_EXTERNAL_URL", "https://api.example.com"):
            result = service._resolve_base_url(use_northbound=True, base_url="https://other.com")
            assert result == "https://api.example.com"

    def test_uses_base_url_when_no_northbound(self):
        """Test uses base_url when use_northbound=False."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._resolve_base_url(use_northbound=False, base_url="https://other.com")
        assert result == "https://other.com"

    def test_returns_empty_when_no_url(self):
        """Test returns empty string when no URL available."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.NORTHBOUND_EXTERNAL_URL", ""):
            result = service._resolve_base_url(use_northbound=True, base_url=None)
            assert result == ""


class TestResolveAgentUrl:
    """Test class for _resolve_agent_url method."""

    def test_prefers_stored_url(self):
        """Test prefers stored URL over base."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._resolve_agent_url(
            stored_url="https://stored.com",
            effective_base="https://base.com"
        )
        assert result == "https://stored.com"

    def test_uses_base_when_no_stored(self):
        """Test uses base URL when no stored URL."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._resolve_agent_url(
            stored_url=None,
            effective_base="https://base.com/"
        )
        assert result == "https://base.com"

    def test_handles_empty_base(self):
        """Test handles empty base URL."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._resolve_agent_url(
            stored_url=None,
            effective_base=""
        )
        assert result == ""


class TestBuildAgentCardBase:
    """Test class for _build_agent_card_base method."""

    def test_builds_complete_card(self):
        """Test building complete agent card."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._build_agent_card_base(
            name="Test Agent",
            description="A test agent",
            version="1.0.0",
            streaming=True,
            effective_base_url="https://api.example.com",
            supported_interfaces=[{"protocolBinding": "http-json-rpc", "url": "https://api.example.com/v1"}],
            agent_url="https://api.example.com",
            agent_info={"name": "Test Agent", "description": "Test"}
        )

        assert result["name"] == "Test Agent"
        assert result["description"] == "A test agent"
        assert result["version"] == "1.0.0"
        assert result["capabilities"]["streaming"] is True
        assert result["capabilities"]["pushNotifications"] is False
        assert "provider" in result
        assert result["provider"]["organization"] == "Nexent"

    def test_includes_default_modes(self):
        """Test includes default input/output modes."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._build_agent_card_base(
            name="Test",
            description="Test",
            version="1.0",
            streaming=False,
            effective_base_url="https://api.example.com",
            supported_interfaces=[],
            agent_url="https://api.example.com",
            agent_info={}
        )

        assert "text/plain" in result["defaultInputModes"]
        assert "text/plain" in result["defaultOutputModes"]

    def test_includes_skills(self):
        """Test includes skills from agent info."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._build_agent_card_base(
            name="Test Agent",
            description="Test agent",
            version="1.0",
            streaming=False,
            effective_base_url="https://api.example.com",
            supported_interfaces=[],
            agent_url="https://api.example.com",
            agent_info={"name": "Test Agent", "description": "A helpful agent"}
        )

        assert len(result["skills"]) > 0
        assert result["skills"][0]["id"] == "chat"


class TestBuildSupportedInterfaces:
    """Test class for _build_supported_interfaces method."""

    def test_builds_interfaces_with_prefix(self):
        """Test building supported interfaces with prefix."""
        from backend.services.a2a_server_service import A2AServerService
        from database.a2a_agent_db import PROTOCOL_HTTP_JSON, PROTOCOL_JSONRPC

        service = A2AServerService()

        result = service._build_supported_interfaces(
            base_url="https://api.example.com",
            endpoint_id="test-endpoint",
            prefix="/nb/a2a"
        )

        assert len(result) == 2
        assert result[0]["protocolBinding"] == PROTOCOL_JSONRPC
        assert "/nb/a2a/test-endpoint/v1" in result[0]["url"]
        assert result[1]["protocolBinding"] == PROTOCOL_HTTP_JSON
        assert "/nb/a2a/test-endpoint" in result[1]["url"]

    def test_handles_base_url_without_trailing_slash(self):
        """Test handles base URL without trailing slash."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._build_supported_interfaces(
            base_url="https://api.example.com",
            endpoint_id="test",
            prefix="/a2a"
        )

        assert result[0]["url"].startswith("https://api.example.com/a2a/")

    def test_handles_empty_base_url(self):
        """Test handles empty base URL."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._build_supported_interfaces(
            base_url="",
            endpoint_id="test",
            prefix="/a2a"
        )

        assert result[0]["url"] == "/a2a/test/v1"


class TestBuildSkillsFromAgent:
    """Test class for _build_skills_from_agent method."""

    def test_builds_default_skill(self):
        """Test building default chat skill."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._build_skills_from_agent({
            "name": "Test Agent",
            "description": "A test agent"
        })

        assert len(result) == 1
        assert result[0]["id"] == "chat"
        assert result[0]["name"] == "Test Agent"
        assert "chat" in result[0]["tags"]
        assert "conversation" in result[0]["tags"]

    def test_handles_missing_fields(self):
        """Test handles missing agent info fields."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._build_skills_from_agent({})

        assert result[0]["name"] == "Nexent Agent"


class TestGetAgentCard:
    """Test class for get_agent_card method."""

    def test_raises_error_when_not_found(self):
        """Test raises error when endpoint not found."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            EndpointNotFoundError
        )

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_endpoint.return_value = None

            with pytest.raises(EndpointNotFoundError) as exc_info:
                service.get_agent_card("nonexistent")

            assert "not found" in str(exc_info.value)

    def test_raises_error_when_disabled(self):
        """Test raises error when endpoint is disabled."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            EndpointNotFoundError
        )

        service = A2AServerService()

        mock_agent = {
            "endpoint_id": "test-endpoint",
            "is_enabled": False
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_endpoint.return_value = mock_agent

            with pytest.raises(EndpointNotFoundError) as exc_info:
                service.get_agent_card("test-endpoint")

            assert "not enabled" in str(exc_info.value)

    def test_returns_agent_card(self):
        """Test returns valid agent card."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_server_agent = {
            "endpoint_id": "test-endpoint",
            "agent_id": 1,
            "tenant_id": "tenant-1",
            "is_enabled": True,
            "name": "Test Agent",
            "description": "A test agent",
            "version": "1.0.0",
            "streaming": True
        }

        mock_agent_info = {
            "name": "Test Agent",
            "description": "A test agent"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_endpoint.return_value = mock_server_agent
            mock_db.search_agent_info_by_agent_id.return_value = mock_agent_info

            with patch("backend.services.a2a_server_service.NORTHBOUND_EXTERNAL_URL", "https://api.example.com"):
                result = service.get_agent_card("test-endpoint")

                assert result["name"] == "Test Agent"
                assert result["capabilities"]["streaming"] is True
                assert "supportedInterfaces" in result


# =============================================================================
# Extended tests
# =============================================================================

class TestResolveBaseUrlEdgeCases:
    """Extended tests for _resolve_base_url edge cases."""

    def test_resolve_base_url_prefers_northbound_over_base_url(self):
        """Test _resolve_base_url prefers NORTHBOUND_EXTERNAL_URL over base_url."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.NORTHBOUND_EXTERNAL_URL", "https://northbound.example.com"):
            result = service._resolve_base_url(
                use_northbound=True,
                base_url="https://base.example.com"
            )

            assert result == "https://northbound.example.com"

    def test_resolve_base_url_logs_warning_when_empty(self):
        """Test _resolve_base_url logs warning when no URL available."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.NORTHBOUND_EXTERNAL_URL", ""):
            with patch("backend.services.a2a_server_service.logger") as mock_logger:
                result = service._resolve_base_url(
                    use_northbound=False,
                    base_url=None
                )

                assert result == ""
                mock_logger.warning.assert_called_once()


class TestResolveAgentUrlEdgeCases:
    """Extended tests for _resolve_agent_url edge cases."""

    def test_resolve_agent_url_with_slash_in_base(self):
        """Test _resolve_agent_url strips trailing slash from base URL."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._resolve_agent_url(
            stored_url=None,
            effective_base="https://api.example.com/"
        )

        assert result == "https://api.example.com"

    def test_resolve_agent_url_returns_empty_when_both_empty(self):
        """Test _resolve_agent_url returns empty when both URLs are empty."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._resolve_agent_url(
            stored_url=None,
            effective_base=""
        )

        assert result == ""


class TestBuildAgentCardBaseExtended:
    """Extended tests for _build_agent_card_base method."""

    def test_build_agent_card_base_with_empty_agent_info(self):
        """Test _build_agent_card_base handles empty agent_info."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._build_agent_card_base(
            name="Test Agent",
            description="Test description",
            version="1.0.0",
            streaming=False,
            effective_base_url="https://api.example.com",
            supported_interfaces=[],
            agent_url="https://api.example.com",
            agent_info={}
        )

        assert result["name"] == "Test Agent"
        assert "skills" in result
        assert len(result["skills"]) == 1

    def test_build_agent_card_base_skills_uses_fallback(self):
        """Test _build_agent_card_base skills uses fallback for missing name/description."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._build_agent_card_base(
            name="Test",
            description="Test",
            version="1.0",
            streaming=False,
            effective_base_url="",
            supported_interfaces=[],
            agent_url="",
            agent_info={}
        )

        assert result["skills"][0]["name"] == "Nexent Agent"
        assert result["skills"][0]["description"] == "AI conversation assistant"

    def test_build_agent_card_base_includes_security_fields(self):
        """Test _build_agent_card_base includes security-related fields."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._build_agent_card_base(
            name="Test",
            description="Test",
            version="1.0",
            streaming=True,
            effective_base_url="https://api.example.com",
            supported_interfaces=[],
            agent_url="https://api.example.com",
            agent_info={}
        )

        assert "securitySchemes" in result
        assert "security" in result
        assert result["security"] == []


class TestBuildSkillsFromAgentEdgeCases:
    """Extended tests for _build_skills_from_agent edge cases."""

    def test_build_skills_includes_examples(self):
        """Test _build_skills_from_agent includes example conversations."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._build_skills_from_agent({
            "name": "Test Agent",
            "description": "A test agent"
        })

        assert "examples" in result[0]
        assert len(result[0]["examples"]) == 2

    def test_build_skills_with_special_characters_in_name(self):
        """Test _build_skills_from_agent handles special characters."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._build_skills_from_agent({
            "name": "Test Agent <>&'\"",
            "description": "Test & Description"
        })

        assert result[0]["name"] == "Test Agent <>&'\""
        assert result[0]["description"] == "Test & Description"


class TestBuildSupportedInterfacesEdgeCases:
    """Extended tests for _build_supported_interfaces edge cases."""

    def test_protocol_bindings_are_correct(self):
        """Test built interfaces have correct protocol bindings."""
        from backend.services.a2a_server_service import A2AServerService
        from database.a2a_agent_db import PROTOCOL_HTTP_JSON, PROTOCOL_JSONRPC

        service = A2AServerService()

        result = service._build_supported_interfaces(
            base_url="https://api.example.com",
            endpoint_id="test-endpoint"
        )

        assert result[0]["protocolBinding"] == PROTOCOL_JSONRPC
        assert result[1]["protocolBinding"] == PROTOCOL_HTTP_JSON

    def test_urls_are_absolute_when_base_provided(self):
        """Test built interfaces produce absolute URLs when base provided."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._build_supported_interfaces(
            base_url="https://api.example.com",
            endpoint_id="my-endpoint"
        )

        for iface in result:
            assert iface["url"].startswith("https://api.example.com")


class TestGetAgentCardWithBaseUrl:
    """Test class for get_agent_card with base_url parameter."""

    def test_get_agent_card_uses_base_url_when_northbound_disabled(self):
        """Test get_agent_card uses provided base_url when use_northbound=False."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_server_agent = {
            "endpoint_id": "test-endpoint",
            "agent_id": 1,
            "tenant_id": "tenant-1",
            "is_enabled": True,
            "name": "Test Agent",
            "description": "A test agent",
            "version": "1.0.0",
            "streaming": True,
            "agent_url": None
        }

        mock_agent_info = {
            "name": "Local Agent",
            "description": "Local description"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_endpoint.return_value = mock_server_agent
            mock_db.search_agent_info_by_agent_id.return_value = mock_agent_info

            result = service.get_agent_card(
                "test-endpoint",
                base_url="https://custom.example.com",
                use_northbound=False
            )

            assert result["name"] == "Test Agent"
            supported_ifaces = result.get("supportedInterfaces", [])
            if supported_ifaces:
                assert "/a2a/test-endpoint" in supported_ifaces[0]["url"]
                assert "/nb/a2a" not in supported_ifaces[0]["url"]


class TestGetAgentCardEdgeCases:
    """Test class for get_agent_card edge cases."""

    def test_get_agent_card_with_no_name_uses_fallback(self):
        """Test get_agent_card falls back to agent_info name when server_agent name is None."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_server_agent = {
            "endpoint_id": "test-endpoint",
            "agent_id": 1,
            "tenant_id": "tenant-1",
            "is_enabled": True,
            "name": None,  # Name is None, should fallback to agent_info
            "description": None,
            "version": None,
            "streaming": False
        }

        mock_agent_info = {
            "name": "Fallback Agent Name",
            "description": "Fallback description"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_endpoint.return_value = mock_server_agent

            # Mock the database.agent_db module that is imported inside get_agent_card
            mock_agent_db_module = MagicMock()
            mock_agent_db_module.search_agent_info_by_agent_id.return_value = mock_agent_info
            with patch.dict("sys.modules", {"database.agent_db": mock_agent_db_module}):
                with patch("backend.services.a2a_server_service.NORTHBOUND_EXTERNAL_URL", "https://api.example.com"):
                    result = service.get_agent_card("test-endpoint")

                    # Verify fallback to agent_info.name
                    assert result["name"] == "Fallback Agent Name"
                    assert result["description"] == "Fallback description"
                    mock_agent_db_module.search_agent_info_by_agent_id.assert_called_once()

    def test_get_agent_card_with_empty_supported_interfaces(self):
        """Test get_agent_card handles empty base_url case."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_server_agent = {
            "endpoint_id": "test-endpoint",
            "agent_id": 1,
            "tenant_id": "tenant-1",
            "is_enabled": True,
            "name": "Test Agent",
            "description": "Test",
            "version": "1.0.0",
            "streaming": True,
            "agent_url": None
        }

        mock_agent_info = {
            "name": "Test Agent",
            "description": "Test"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_endpoint.return_value = mock_server_agent
            mock_db.search_agent_info_by_agent_id.return_value = mock_agent_info

            with patch("backend.services.a2a_server_service.NORTHBOUND_EXTERNAL_URL", ""):
                result = service.get_agent_card(
                    "test-endpoint",
                    base_url=None,
                    use_northbound=True
                )

                assert result.get("supportedInterfaces", []) == []


class TestGetAgentCardWithCardOverrides:
    """Tests for get_agent_card with card_overrides."""

    def test_get_agent_card_applies_card_overrides(self):
        """Test get_agent_card applies card_overrides from server_agent."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_server_agent = {
            "endpoint_id": "test-endpoint",
            "agent_id": 1,
            "tenant_id": "tenant-1",
            "is_enabled": True,
            "name": "Test Agent",
            "description": "Test",
            "version": "1.0.0",
            "streaming": True,
            "agent_url": None,
            "card_overrides": {
                "capabilities": {"streaming": False},
                "provider": {"organization": "Custom Org"}
            }
        }

        mock_agent_info = {
            "name": "Test Agent",
            "description": "Test"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_endpoint.return_value = mock_server_agent
            mock_db.search_agent_info_by_agent_id.return_value = mock_agent_info

            with patch("backend.services.a2a_server_service.NORTHBOUND_EXTERNAL_URL", "https://api.example.com"):
                result = service.get_agent_card("test-endpoint")

                assert result["capabilities"]["streaming"] is False
                assert result["provider"]["organization"] == "Custom Org"
