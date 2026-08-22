"""
Unit tests for A2A Server Service - Registration and Settings.

This module contains tests for:
- register_agent, unregister_agent, get_registration, list_registrations methods
- enable_a2a, disable_a2a, update_settings methods
"""
import pytest
from unittest.mock import MagicMock, patch


class TestA2AServerServiceExceptions:
    """Test class for A2A Server Service exceptions."""

    def test_base_exception_exists(self):
        """Test A2AServerServiceError exception exists."""
        from backend.services.a2a_server_service import A2AServerServiceError

        exc = A2AServerServiceError("Test error")
        assert str(exc) == "Test error"

    def test_endpoint_not_found_error_exists(self):
        """Test EndpointNotFoundError exception exists."""
        from backend.services.a2a_server_service import EndpointNotFoundError

        exc = EndpointNotFoundError("Endpoint not found")
        assert str(exc) == "Endpoint not found"

    def test_agent_not_enabled_error_exists(self):
        """Test AgentNotEnabledError exception exists."""
        from backend.services.a2a_server_service import AgentNotEnabledError

        exc = AgentNotEnabledError("Agent not enabled")
        assert str(exc) == "Agent not enabled"

    def test_task_not_found_error_exists(self):
        """Test TaskNotFoundError exception exists."""
        from backend.services.a2a_server_service import TaskNotFoundError

        exc = TaskNotFoundError("Task not found")
        assert str(exc) == "Task not found"

    def test_unsupported_operation_error_exists(self):
        """Test UnsupportedOperationError exception exists."""
        from backend.services.a2a_server_service import UnsupportedOperationError

        exc = UnsupportedOperationError("Unsupported operation")
        assert str(exc) == "Unsupported operation"


class TestRegisterAgent:
    """Test class for register_agent method."""

    def test_register_agent_success(self):
        """Test successful agent registration."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_result = {
            "agent_id": 1,
            "endpoint_id": "a2a_1_abc123",
            "tenant_id": "tenant-1",
            "user_id": "user-1",
            "name": "Test Agent",
            "is_enabled": False
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.create_server_agent.return_value = mock_result

            result = service.register_agent(
                agent_id=1,
                user_id="user-1",
                tenant_id="tenant-1",
                name="Test Agent"
            )

            assert result["agent_id"] == 1
            mock_db.create_server_agent.assert_called_once()

    def test_register_agent_with_all_params(self):
        """Test agent registration with all parameters."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_result = {
            "agent_id": 1,
            "endpoint_id": "a2a_1_abc123",
            "name": "Full Agent",
            "description": "A complete agent",
            "version": "2.0.0",
            "streaming": True
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.create_server_agent.return_value = mock_result

            result = service.register_agent(
                agent_id=1,
                user_id="user-1",
                tenant_id="tenant-1",
                name="Full Agent",
                description="A complete agent",
                version="2.0.0",
                agent_url="https://agent.example.com",
                streaming=True,
                supported_interfaces=[{"protocolBinding": "http-json-rpc"}],
                card_overrides={"capabilities": {"streaming": True}}
            )

            mock_db.create_server_agent.assert_called_once()
            call_kwargs = mock_db.create_server_agent.call_args.kwargs
            assert call_kwargs["name"] == "Full Agent"
            assert call_kwargs["version"] == "2.0.0"
            assert call_kwargs["streaming"] is True


class TestUnregisterAgent:
    """Test class for unregister_agent method."""

    def test_unregister_agent_success(self):
        """Test successful agent unregistration."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.disable_server_agent.return_value = True

            result = service.unregister_agent(
                agent_id=1,
                tenant_id="tenant-1",
                user_id="user-1"
            )

            assert result is True
            mock_db.disable_server_agent.assert_called_once_with(1, "tenant-1", "user-1")

    def test_unregister_agent_not_found(self):
        """Test unregister when agent not found."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.disable_server_agent.return_value = False

            result = service.unregister_agent(
                agent_id=999,
                tenant_id="tenant-1",
                user_id="user-1"
            )

            assert result is False


class TestGetRegistration:
    """Test class for get_registration method."""

    def test_get_registration_found(self):
        """Test getting existing registration."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_registration = {
            "agent_id": 1,
            "endpoint_id": "a2a_1_abc123",
            "name": "Test Agent",
            "is_enabled": True
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_agent_id.return_value = mock_registration

            result = service.get_registration(agent_id=1, tenant_id="tenant-1")

            assert result == mock_registration
            mock_db.get_server_agent_by_agent_id.assert_called_once_with(1, "tenant-1")

    def test_get_registration_not_found(self):
        """Test getting non-existent registration."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_agent_id.return_value = None

            result = service.get_registration(agent_id=999, tenant_id="tenant-1")

            assert result is None


class TestListRegistrations:
    """Test class for list_registrations method."""

    def test_list_registrations_all(self):
        """Test listing all registrations for tenant."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_list = [
            {"agent_id": 1, "name": "Agent 1"},
            {"agent_id": 2, "name": "Agent 2"}
        ]

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.list_server_agents.return_value = mock_list

            result = service.list_registrations(tenant_id="tenant-1")

            assert len(result) == 2
            mock_db.list_server_agents.assert_called_once_with("tenant-1", None)

    def test_list_registrations_filtered_by_user(self):
        """Test listing registrations filtered by user."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_list = [
            {"agent_id": 1, "name": "Agent 1", "user_id": "user-1"}
        ]

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.list_server_agents.return_value = mock_list

            result = service.list_registrations(tenant_id="tenant-1", user_id="user-1")

            mock_db.list_server_agents.assert_called_once_with("tenant-1", "user-1")


class TestEnableA2A:
    """Test class for enable_a2a method."""

    def test_enable_a2a_success(self):
        """Test successful A2A enable."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_result = {
            "agent_id": 1,
            "endpoint_id": "a2a_1_abc123",
            "name": "Test Agent",
            "is_enabled": True
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.enable_server_agent.return_value = mock_result

            with patch("backend.services.a2a_server_service.logger") as mock_logger:
                result = service.enable_a2a(
                    agent_id=1,
                    tenant_id="tenant-1",
                    user_id="user-1"
                )

                assert result["is_enabled"] is True
                mock_logger.info.assert_called_once()
                assert "Enabled A2A Server for agent 1" in mock_logger.info.call_args[0]

    def test_enable_a2a_not_found(self):
        """Test enable A2A when registration not found."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            EndpointNotFoundError
        )

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.enable_server_agent.return_value = None

            with pytest.raises(EndpointNotFoundError) as exc_info:
                service.enable_a2a(
                    agent_id=999,
                    tenant_id="tenant-1",
                    user_id="user-1"
                )

            assert "No registration found" in str(exc_info.value)

    def test_enable_a2a_with_custom_settings(self):
        """Test enable A2A with custom name and description."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_result = {
            "agent_id": 1,
            "name": "Updated Agent",
            "description": "Updated description",
            "is_enabled": True
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.enable_server_agent.return_value = mock_result

            result = service.enable_a2a(
                agent_id=1,
                tenant_id="tenant-1",
                user_id="user-1",
                name="Updated Agent",
                description="Updated description",
                version="2.0.0"
            )

            call_kwargs = mock_db.enable_server_agent.call_args.kwargs
            assert call_kwargs["name"] == "Updated Agent"


class TestDisableA2A:
    """Test class for disable_a2a method."""

    def test_disable_a2a_success(self):
        """Test successful A2A disable."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.disable_server_agent.return_value = True

            with patch("backend.services.a2a_server_service.logger") as mock_logger:
                result = service.disable_a2a(
                    agent_id=1,
                    tenant_id="tenant-1",
                    user_id="user-1"
                )

                assert result is True
                mock_logger.info.assert_called_once()
                assert "Disabled A2A Server for agent 1" in mock_logger.info.call_args[0]

    def test_disable_a2a_not_found(self):
        """Test disable A2A when registration not found."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            EndpointNotFoundError
        )

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.disable_server_agent.return_value = False

            with pytest.raises(EndpointNotFoundError) as exc_info:
                service.disable_a2a(
                    agent_id=999,
                    tenant_id="tenant-1",
                    user_id="user-1"
                )

            assert "No registration found" in str(exc_info.value)


class TestUpdateSettings:
    """Test class for update_settings method."""

    def test_update_settings_enable(self):
        """Test update_settings to enable A2A."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_current = {
            "agent_id": 1,
            "name": "Test Agent",
            "is_enabled": False
        }

        mock_enabled = {
            "agent_id": 1,
            "name": "Test Agent",
            "is_enabled": True
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_agent_id.return_value = mock_current
            mock_db.enable_server_agent.return_value = mock_enabled

            result = service.update_settings(
                agent_id=1,
                tenant_id="tenant-1",
                user_id="user-1",
                is_enabled=True
            )

            assert result["is_enabled"] is True

    def test_update_settings_disable(self):
        """Test update_settings to disable A2A."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_current = {
            "agent_id": 1,
            "name": "Test Agent",
            "is_enabled": True
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_agent_id.return_value = mock_current
            mock_db.disable_server_agent.return_value = True

            result = service.update_settings(
                agent_id=1,
                tenant_id="tenant-1",
                user_id="user-1",
                is_enabled=False
            )

            assert result["is_enabled"] is False

    def test_update_settings_not_found(self):
        """Test update_settings when registration not found."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            EndpointNotFoundError
        )

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_agent_id.return_value = None

            with pytest.raises(EndpointNotFoundError):
                service.update_settings(
                    agent_id=999,
                    tenant_id="tenant-1",
                    user_id="user-1"
                )

    def test_update_settings_card_overrides_only(self):
        """Test update_settings with only card_overrides (no is_enabled change)."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_current = {
            "agent_id": 1,
            "name": "Test Agent",
            "is_enabled": True,
            "card_overrides": {}
        }

        mock_updated = {
            "agent_id": 1,
            "name": "Test Agent",
            "is_enabled": True,
            "card_overrides": {"provider": {"organization": "Custom Org"}}
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_agent_id.side_effect = [mock_current, mock_updated]

            with patch("backend.services.a2a_server_service.get_db_session") as mock_session:
                mock_agent = MagicMock()
                mock_session.return_value.__enter__.return_value.query.return_value.filter.return_value.first.return_value = mock_agent

                result = service.update_settings(
                    agent_id=1,
                    tenant_id="tenant-1",
                    user_id="user-1",
                    card_overrides={"provider": {"organization": "Custom Org"}}
                )

                assert mock_agent.card_overrides == {"provider": {"organization": "Custom Org"}}
