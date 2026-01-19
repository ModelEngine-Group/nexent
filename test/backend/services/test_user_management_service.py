import unittest
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock
import sys
import os
import aiohttp

# Patch environment variables before any imports that might use them
# Environment variables are now configured in conftest.py

# Align with the standard pattern used in test_conversation_management_service.py
# Mock external SDKs and patch MinioClient before importing the SUT
sys.modules['boto3'] = MagicMock()
sys.modules['supabase'] = MagicMock()
sys.modules['psycopg2'] = MagicMock()

# Minimal stub to satisfy 'from nexent.memory.memory_service import clear_memory'
sys.modules['nexent'] = MagicMock()
sys.modules['nexent.memory'] = MagicMock()
nexent_memory_service = MagicMock()
sys.modules['nexent.memory.memory_service'] = nexent_memory_service
sys.modules['nexent.storage.storage_client_factory'] = MagicMock()

# Mock services
sys.modules['services'] = MagicMock()
sys.modules['services.invitation_service'] = MagicMock()
sys.modules['services.group_service'] = MagicMock()

from consts.exceptions import NoInviteCodeException, IncorrectInviteCodeException, UserRegistrationException, UnauthorizedError

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_client_mock).start()

with patch('backend.database.client.MinioClient', return_value=minio_client_mock):
    from backend.services.user_management_service import (
        set_auth_token_to_client,
        get_authorized_client,
        get_current_user_from_client,
        validate_token,
        extend_session,
        check_auth_service_health,
        signup_user,
        signup_user_with_invitation,
        parse_supabase_response,
        generate_tts_stt_4_admin,
        verify_invite_code,
        signin_user,
        refresh_user_token,
        get_session_by_authorization,
        revoke_regular_user,
        get_user_info,
        get_permissions_by_role,
    )

# Functions to test


class TestSetAuthTokenToClient(unittest.TestCase):
    """Test set_auth_token_to_client"""

    def test_set_token_with_bearer_prefix(self):
        """Test setting token with Bearer prefix"""
        mock_client = MagicMock()
        token = "Bearer test-jwt-token"

        set_auth_token_to_client(mock_client, token)

        self.assertEqual(mock_client.auth.access_token, "test-jwt-token")

    def test_set_token_without_bearer_prefix(self):
        """Test setting token without Bearer prefix"""
        mock_client = MagicMock()
        token = "test-jwt-token"

        set_auth_token_to_client(mock_client, token)

        self.assertEqual(mock_client.auth.access_token, "test-jwt-token")

    def test_set_token_exception(self):
        """Test exception handling when setting token"""
        mock_client = MagicMock()
        # Mock the auth attribute to raise an exception when access_token is set
        type(mock_client.auth).access_token = PropertyMock(side_effect=Exception("Auth error"))
        token = "test-jwt-token"

        # This should not raise an exception, but should log the error
        set_auth_token_to_client(mock_client, token)


class TestGetAuthorizedClient(unittest.TestCase):
    """Test get_authorized_client"""

    @patch('backend.services.user_management_service.get_supabase_client')
    @patch('backend.services.user_management_service.set_auth_token_to_client')
    def test_get_client_with_authorization(self, mock_set_token, mock_get_client):
        """Test getting client with authorization header"""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        result = get_authorized_client("Bearer test-token")

        self.assertEqual(result, mock_client)
        mock_set_token.assert_called_once_with(mock_client, "test-token")

    @patch('backend.services.user_management_service.get_supabase_client')
    @patch('backend.services.user_management_service.set_auth_token_to_client')
    def test_get_client_without_authorization(self, mock_set_token, mock_get_client):
        """Test getting client without authorization header"""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        result = get_authorized_client(None)

        self.assertEqual(result, mock_client)
        mock_set_token.assert_not_called()


class TestGetCurrentUserFromClient(unittest.TestCase):
    """Test get_current_user_from_client"""

    def test_get_user_success(self):
        """Test successful user retrieval"""
        mock_client = MagicMock()
        mock_user = MagicMock()
        mock_response = MagicMock()
        mock_response.user = mock_user
        mock_client.auth.get_user.return_value = mock_response

        result = get_current_user_from_client(mock_client)

        self.assertEqual(result, mock_user)

    def test_get_user_no_user(self):
        """Test when no user is returned"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.user = None
        mock_client.auth.get_user.return_value = mock_response

        result = get_current_user_from_client(mock_client)

        self.assertIsNone(result)

    def test_get_user_no_response(self):
        """Test when no response is returned"""
        mock_client = MagicMock()
        mock_client.auth.get_user.return_value = None

        result = get_current_user_from_client(mock_client)

        self.assertIsNone(result)

    def test_get_user_exception(self):
        """Test exception handling"""
        mock_client = MagicMock()
        mock_client.auth.get_user.side_effect = Exception("Get user error")

        result = get_current_user_from_client(mock_client)

        self.assertIsNone(result)


class TestValidateToken(unittest.TestCase):
    """Test validate_token"""

    @patch('backend.services.user_management_service.get_current_user_from_client')
    @patch('backend.services.user_management_service.set_auth_token_to_client')
    @patch('backend.services.user_management_service.get_supabase_client')
    def test_validate_token_success(self, mock_get_client, mock_set_token, mock_get_user):
        """Test successful token validation"""
        mock_client = MagicMock()
        mock_user = MagicMock()
        mock_get_client.return_value = mock_client
        mock_get_user.return_value = mock_user

        is_valid, user = validate_token("test-token")

        self.assertTrue(is_valid)
        self.assertEqual(user, mock_user)
        mock_set_token.assert_called_once_with(mock_client, "test-token")

    @patch('backend.services.user_management_service.get_current_user_from_client')
    @patch('backend.services.user_management_service.set_auth_token_to_client')
    @patch('backend.services.user_management_service.get_supabase_client')
    def test_validate_token_no_user(self, mock_get_client, mock_set_token, mock_get_user):
        """Test token validation with no user"""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_get_user.return_value = None

        is_valid, user = validate_token("test-token")

        self.assertFalse(is_valid)
        self.assertIsNone(user)

    @patch('backend.services.user_management_service.get_current_user_from_client')
    @patch('backend.services.user_management_service.set_auth_token_to_client')
    @patch('backend.services.user_management_service.get_supabase_client')
    def test_validate_token_exception(self, mock_get_client, mock_set_token, mock_get_user):
        """Test token validation exception"""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_get_user.side_effect = Exception("Validation error")

        is_valid, user = validate_token("test-token")

        self.assertFalse(is_valid)
        self.assertIsNone(user)


class TestExtendSession(unittest.IsolatedAsyncioTestCase):
    """Test extend_session"""

    @patch('backend.services.user_management_service.get_jwt_expiry_seconds')
    @patch('backend.services.user_management_service.calculate_expires_at')
    def test_extend_session_success(self, mock_calc_expires, mock_get_expiry):
        """Test successful session extension"""
        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_session.access_token = "new-access-token"
        mock_session.refresh_token = "new-refresh-token"
        mock_response = MagicMock()
        mock_response.session = mock_session
        mock_client.auth.refresh_session.return_value = mock_response
        mock_calc_expires.return_value = "2024-01-01T00:00:00Z"
        mock_get_expiry.return_value = 3600

        result = extend_session(mock_client, "refresh-token")

        expected = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_at": "2024-01-01T00:00:00Z",
            "expires_in_seconds": 3600
        }
        self.assertEqual(result, expected)

    def test_extend_session_no_session(self):
        """Test session extension with no session returned"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.session = None
        mock_client.auth.refresh_session.return_value = mock_response

        result = extend_session(mock_client, "refresh-token")

        self.assertIsNone(result)

    def test_extend_session_no_response(self):
        """Test session extension with no response"""
        mock_client = MagicMock()
        mock_client.auth.refresh_session.return_value = None

        result = extend_session(mock_client, "refresh-token")

        self.assertIsNone(result)

    def test_extend_session_exception(self):
        """Test session extension exception"""
        mock_client = MagicMock()
        mock_client.auth.refresh_session.side_effect = Exception("Refresh error")

        result = extend_session(mock_client, "refresh-token")

        self.assertIsNone(result)


class TestCheckAuthServiceHealth(unittest.IsolatedAsyncioTestCase):
    """Test check_auth_service_health"""

    @patch.dict(os.environ, {'SUPABASE_URL': 'http://test.supabase.co', 'SUPABASE_KEY': 'test-key'})
    async def test_health_check_success(self):
        """Test successful health check"""
        # Create a proper async context manager mock
        class MockResponse:
            def __init__(self):
                self.ok = True

            async def json(self):
                return {"name": "GoTrue"}

        class MockGet:
            def __init__(self):
                self.response = MockResponse()

            async def __aenter__(self):
                return self.response

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        class MockSession:
            def get(self, *args, **kwargs):
                return MockGet()

        class MockClientSession:
            async def __aenter__(self):
                return MockSession()

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        # Patch the ClientSession
        with patch('backend.services.user_management_service.aiohttp.ClientSession', MockClientSession):
            # Function should not raise exception and should not return anything
            result = await check_auth_service_health()
            self.assertIsNone(result)

    @patch.dict(os.environ, {'SUPABASE_URL': 'http://test.supabase.co', 'SUPABASE_KEY': 'test-key'})
    async def test_health_check_not_ok_response(self):
        """Test health check with non-OK response (covers line 97)"""
        # Create a proper async context manager mock
        class MockResponse:
            def __init__(self):
                self.ok = False

        class MockGet:
            def __init__(self):
                self.response = MockResponse()

            async def __aenter__(self):
                return self.response

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        class MockSession:
            def get(self, *args, **kwargs):
                return MockGet()

        class MockClientSession:
            async def __aenter__(self):
                return MockSession()

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        # Patch the ClientSession
        with patch('backend.services.user_management_service.aiohttp.ClientSession', MockClientSession):
            # Function should raise ConnectionError for non-OK response
            with self.assertRaises(ConnectionError) as context:
                await check_auth_service_health()

            self.assertIn("Auth service is unavailable", str(context.exception))

    @patch.dict(os.environ, {'SUPABASE_URL': 'http://test.supabase.co', 'SUPABASE_KEY': 'test-key'})
    async def test_health_check_wrong_service_name(self):
        """Test health check with wrong service name (covers line 103)"""
        # Create a proper async context manager mock
        class MockResponse:
            def __init__(self):
                self.ok = True

            async def json(self):
                return {"name": "WrongService"}

        class MockGet:
            def __init__(self):
                self.response = MockResponse()

            async def __aenter__(self):
                return self.response

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        class MockSession:
            def get(self, *args, **kwargs):
                return MockGet()

        class MockClientSession:
            async def __aenter__(self):
                return MockSession()

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        # Patch the ClientSession
        with patch('backend.services.user_management_service.aiohttp.ClientSession', MockClientSession):
            # Function should raise ConnectionError for wrong service name
            with self.assertRaises(ConnectionError) as context:
                await check_auth_service_health()

            self.assertIn("Auth service is unavailable", str(context.exception))

    @patch.dict(os.environ, {'SUPABASE_URL': 'http://test.supabase.co', 'SUPABASE_KEY': 'test-key'})
    async def test_health_check_empty_response(self):
        """Test health check with empty response data (covers line 103)"""
        # Create a proper async context manager mock
        class MockResponse:
            def __init__(self):
                self.ok = True

            async def json(self):
                return None  # Empty response

        class MockGet:
            def __init__(self):
                self.response = MockResponse()

            async def __aenter__(self):
                return self.response

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        class MockSession:
            def get(self, *args, **kwargs):
                return MockGet()

        class MockClientSession:
            async def __aenter__(self):
                return MockSession()

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        # Patch the ClientSession
        with patch('backend.services.user_management_service.aiohttp.ClientSession', MockClientSession):
            # Function should raise ConnectionError for empty response
            with self.assertRaises(ConnectionError) as context:
                await check_auth_service_health()

            self.assertIn("Auth service is unavailable", str(context.exception))

    @patch.dict(os.environ, {'SUPABASE_URL': 'http://test.supabase.co', 'SUPABASE_KEY': 'test-key'})
    async def test_health_check_missing_name_field(self):
        """Test health check with response missing name field (covers line 103)"""
        # Create a proper async context manager mock
        class MockResponse:
            def __init__(self):
                self.ok = True

            async def json(self):
                return {"status": "ok"}  # Missing "name" field

        class MockGet:
            def __init__(self):
                self.response = MockResponse()

            async def __aenter__(self):
                return self.response

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        class MockSession:
            def get(self, *args, **kwargs):
                return MockGet()

        class MockClientSession:
            async def __aenter__(self):
                return MockSession()

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        # Patch the ClientSession
        with patch('backend.services.user_management_service.aiohttp.ClientSession', MockClientSession):
            # Function should raise ConnectionError for missing name field
            with self.assertRaises(ConnectionError) as context:
                await check_auth_service_health()

            self.assertIn("Auth service is unavailable", str(context.exception))

    @patch.dict(os.environ, {'SUPABASE_URL': 'http://test.supabase.co', 'SUPABASE_KEY': 'test-key'})
    @patch('backend.services.user_management_service.aiohttp.ClientSession')
    async def test_health_check_connection_error(self, mock_session_cls):
        """Test health check with connection error"""
        mock_session_cls.side_effect = aiohttp.ClientError("Connection failed")

        # Function should raise the original exception
        with self.assertRaises(aiohttp.ClientError) as context:
            await check_auth_service_health()

        self.assertIn("Connection failed", str(context.exception))

    @patch.dict(os.environ, {'SUPABASE_URL': 'http://test.supabase.co', 'SUPABASE_KEY': 'test-key'})
    @patch('backend.services.user_management_service.aiohttp.ClientSession')
    async def test_health_check_general_exception(self, mock_session_cls):
        """Test health check with general exception"""
        mock_session_cls.side_effect = Exception("General error")

        # Function should raise the original exception
        with self.assertRaises(Exception) as context:
            await check_auth_service_health()

        self.assertIn("General error", str(context.exception))

    @patch.dict(os.environ, {'SUPABASE_URL': 'http://test.supabase.co', 'SUPABASE_KEY': 'test-key'})
    async def test_health_check_empty_data_dict(self):
        """Test health check with empty data dictionary (covers line 103)"""
        # Create a proper async context manager mock
        class MockResponse:
            def __init__(self):
                self.ok = True

            async def json(self):
                return {}  # Empty dictionary - data exists but no "name" field

        class MockGet:
            def __init__(self):
                self.response = MockResponse()

            async def __aenter__(self):
                return self.response

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        class MockSession:
            def get(self, *args, **kwargs):
                return MockGet()

        class MockClientSession:
            async def __aenter__(self):
                return MockSession()

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        # Patch the ClientSession
        with patch('backend.services.user_management_service.aiohttp.ClientSession', MockClientSession):
            # Function should raise ConnectionError for empty data dictionary
            with self.assertRaises(ConnectionError) as context:
                await check_auth_service_health()

            self.assertIn("Auth service is unavailable", str(context.exception))


class TestSignupUser(unittest.IsolatedAsyncioTestCase):
    """Test signup_user"""

    @patch('backend.services.user_management_service.parse_supabase_response')
    @patch('backend.services.user_management_service.generate_tts_stt_4_admin')
    @patch('backend.services.user_management_service.insert_user_tenant')
    @patch('backend.services.user_management_service.verify_invite_code')
    @patch('backend.services.user_management_service.get_supabase_client')
    async def test_signup_user_regular_user(self, mock_get_client, mock_verify_code,
                                          mock_insert_tenant, mock_generate_tts, mock_parse_response):
        """Test regular user signup"""
        mock_client = MagicMock()
        mock_user = MagicMock()
        mock_user.id = "user-123"
        mock_response = MagicMock()
        mock_response.user = mock_user
        mock_client.auth.sign_up.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_parse_response.return_value = {"user": "data"}

        result = await signup_user("test@example.com", "password123")

        self.assertEqual(result, {"user": "data"})
        mock_verify_code.assert_not_called()
        mock_generate_tts.assert_not_called()
        mock_insert_tenant.assert_called_once_with(user_id="user-123", tenant_id="tenant_id")
        mock_parse_response.assert_called_once_with(False, mock_response, "user")

    @patch('backend.services.user_management_service.parse_supabase_response')
    @patch('backend.services.user_management_service.insert_user_tenant')
    @patch('backend.services.user_management_service.get_supabase_client')
    async def test_signup_user_regular_without_invite_code(self, mock_get_client,
                                                          mock_insert_tenant, mock_parse_response):
        """Test regular user signup without invitation code"""
        mock_client = MagicMock()
        mock_user = MagicMock()
        mock_user.id = "user-123"
        mock_response = MagicMock()
        mock_response.user = mock_user
        mock_client.auth.sign_up.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_parse_response.return_value = {"user": "data"}

        result = await signup_user("user@example.com", "password123")

        self.assertEqual(result, {"user": "data"})
        mock_insert_tenant.assert_called_once_with(user_id="user-123", tenant_id="tenant_id")
        mock_parse_response.assert_called_once_with(False, mock_response, "user")

    @patch('backend.services.user_management_service.get_supabase_client')
    async def test_signup_user_no_user_returned(self, mock_get_client):
        """Test signup when no user is returned"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.user = None
        mock_client.auth.sign_up.return_value = mock_response
        mock_get_client.return_value = mock_client

        with self.assertRaises(UserRegistrationException) as context:
            await signup_user("test@example.com", "password123")

        self.assertIn("Registration service is temporarily unavailable", str(context.exception))

    @patch('backend.services.user_management_service.add_user_to_groups')
    @patch('backend.services.user_management_service.parse_supabase_response')
    @patch('backend.services.user_management_service.generate_tts_stt_4_admin')
    @patch('backend.services.user_management_service.insert_user_tenant')
    @patch('backend.services.user_management_service.get_invitation_by_code')
    @patch('backend.services.user_management_service.check_invitation_available')
    @patch('backend.services.user_management_service.use_invitation_code')
    @patch('backend.services.user_management_service.get_supabase_client')
    async def test_signup_user_with_admin_invite_code(self, mock_get_client, mock_use_invite,
                                                     mock_check_available, mock_get_invite_code,
                                                     mock_insert_tenant, mock_generate_tts, mock_parse_response, mock_add_groups):
        """Test user signup with ADMIN_INVITE code"""
        # Setup mocks
        mock_client = MagicMock()
        mock_user = MagicMock()
        mock_user.id = "user-123"
        mock_response = MagicMock()
        mock_response.user = mock_user
        mock_client.auth.sign_up.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Mock invitation code validation
        mock_check_available.return_value = True
        mock_get_invite_code.return_value = {
            "invitation_id": 1,
            "code_type": "ADMIN_INVITE",
            "group_ids": "1,2,3",
            "tenant_id": "tenant_id"
        }
        mock_use_invite.return_value = {
            "invitation_id": 1,
            "code_type": "ADMIN_INVITE",
            "group_ids": "1,2,3"
        }
        mock_parse_response.return_value = {"user": "admin_data"}
        mock_add_groups.return_value = [
            {"group_id": 1, "user_id": "user-123", "already_member": False},
            {"group_id": 2, "user_id": "user-123", "already_member": False},
            {"group_id": 3, "user_id": "user-123", "already_member": False}
        ]

        result = await signup_user_with_invitation("admin@example.com", "password123", invite_code="ADMIN123")

        # Verify generate_tts_stt_4_admin was called for admin user
        mock_generate_tts.assert_called_once_with("tenant_id", "user-123")

        self.assertEqual(result, {"user": "admin_data"})
        mock_insert_tenant.assert_called_once_with(user_id="user-123", tenant_id="tenant_id", user_role="ADMIN")
        mock_use_invite.assert_called_once_with("ADMIN123", "user-123")
        mock_add_groups.assert_called_once_with("user-123", [1, 2, 3], "user-123")
        mock_parse_response.assert_called_once_with(False, mock_response, "ADMIN")

    @patch('backend.services.user_management_service.add_user_to_groups')
    @patch('backend.services.user_management_service.parse_supabase_response')
    @patch('backend.services.user_management_service.insert_user_tenant')
    @patch('backend.services.user_management_service.get_invitation_by_code')
    @patch('backend.services.user_management_service.check_invitation_available')
    @patch('backend.services.user_management_service.use_invitation_code')
    @patch('backend.services.user_management_service.get_supabase_client')
    async def test_signup_user_with_dev_invite_code(self, mock_get_client, mock_use_invite,
                                                   mock_check_available, mock_get_invite_code,
                                                   mock_insert_tenant, mock_parse_response, mock_add_groups):
        """Test user signup with DEV_INVITE code"""
        # Setup mocks
        mock_client = MagicMock()
        mock_user = MagicMock()
        mock_user.id = "user-456"
        mock_response = MagicMock()
        mock_response.user = mock_user
        mock_client.auth.sign_up.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Mock invitation code validation
        mock_check_available.return_value = True
        mock_get_invite_code.return_value = {
            "invitation_id": 2,
            "code_type": "DEV_INVITE",
            "group_ids": "4,5",
            "tenant_id": "tenant_id"
        }
        mock_use_invite.return_value = {
            "invitation_id": 2,
            "code_type": "DEV_INVITE",
            "group_ids": "4,5"
        }
        mock_parse_response.return_value = {"user": "dev_data"}
        mock_add_groups.return_value = [
            {"group_id": 4, "user_id": "user-456", "already_member": False},
            {"group_id": 5, "user_id": "user-456", "already_member": False}
        ]

        result = await signup_user_with_invitation("dev@example.com", "password123", invite_code="DEV456")

        self.assertEqual(result, {"user": "dev_data"})
        mock_insert_tenant.assert_called_once_with(user_id="user-456", tenant_id="tenant_id", user_role="DEV")
        mock_use_invite.assert_called_once_with("DEV456", "user-456")
        mock_add_groups.assert_called_once_with("user-456", [4, 5], "user-456")
        mock_parse_response.assert_called_once_with(False, mock_response, "DEV")

    @patch('backend.services.user_management_service.get_invitation_by_code')
    @patch('backend.services.user_management_service.check_invitation_available')
    @patch('backend.services.user_management_service.get_supabase_client')
    async def test_signup_user_with_invalid_invite_code(self, mock_get_client, mock_check_available, mock_get_invite_code):
        """Test user signup with invalid invitation code"""
        # Mock invitation code validation to fail
        mock_check_available.return_value = False

        with self.assertRaises(IncorrectInviteCodeException) as context:
            await signup_user_with_invitation("test@example.com", "password123", "INVALID")

        self.assertIn("is not available", str(context.exception))

    @patch('backend.services.user_management_service.get_invitation_by_code')
    @patch('backend.services.user_management_service.check_invitation_available')
    async def test_signup_user_with_invite_code_uppercase_conversion(self, mock_check_available, mock_get_invite_code):
        """Test invitation code is converted to uppercase (line 183)"""
        # Mock invitation code validation
        mock_check_available.return_value = True
        mock_get_invite_code.return_value = {
            "invitation_id": 1,
            "code_type": "USER_INVITE",
            "group_ids": [],
            "tenant_id": "tenant_id"
        }

        with patch('backend.services.user_management_service.get_supabase_client') as mock_get_client, \
             patch('backend.services.user_management_service.insert_user_tenant'), \
             patch('backend.services.user_management_service.parse_supabase_response') as mock_parse, \
             patch('backend.services.user_management_service.use_invitation_code'):

            mock_user = MagicMock()
            mock_user.id = "user-123"
            mock_response = MagicMock()
            mock_response.user = mock_user
            mock_client = MagicMock()
            mock_client.auth.sign_up.return_value = mock_response
            mock_get_client.return_value = mock_client
            mock_parse.return_value = {"user": "data"}

            # Use lowercase invite code
            result = await signup_user_with_invitation("test@example.com", "password123", invite_code="lowercase")

            # Verify the code was converted to uppercase in the check
            mock_check_available.assert_called_with("LOWERCASE")
            mock_get_invite_code.assert_called_with("LOWERCASE")

    @patch('backend.services.user_management_service.get_invitation_by_code')
    @patch('backend.services.user_management_service.check_invitation_available')
    async def test_signup_user_with_invite_code_not_found_after_check(self, mock_check_available, mock_get_invite_code):
        """Test when invitation code passes availability check but get_invitation_by_code returns None (lines 191-194)"""
        # Mock invitation code availability check passes but get_invitation_by_code returns None
        mock_check_available.return_value = True
        mock_get_invite_code.return_value = None

        with self.assertRaises(IncorrectInviteCodeException) as context:
            await signup_user_with_invitation("test@example.com", "password123", invite_code="NONEXISTENT")

        self.assertIn("not found", str(context.exception))

    @patch('backend.services.user_management_service.get_invitation_by_code')
    @patch('backend.services.user_management_service.check_invitation_available')
    async def test_signup_user_with_admin_invite_role_assignment(self, mock_check_available, mock_get_invite_code):
        """Test ADMIN role assignment from ADMIN_INVITE code type (lines 198-199)"""
        # Mock invitation code validation
        mock_check_available.return_value = True
        mock_get_invite_code.return_value = {
            "invitation_id": 1,
            "code_type": "ADMIN_INVITE",
            "group_ids": [],
            "tenant_id": "tenant_id"
        }

        with patch('backend.services.user_management_service.get_supabase_client') as mock_get_client, \
             patch('backend.services.user_management_service.insert_user_tenant') as mock_insert_tenant, \
             patch('backend.services.user_management_service.parse_supabase_response') as mock_parse, \
             patch('backend.services.user_management_service.use_invitation_code'), \
             patch('backend.services.user_management_service.generate_tts_stt_4_admin') as mock_generate_tts:

            mock_user = MagicMock()
            mock_user.id = "user-123"
            mock_response = MagicMock()
            mock_response.user = mock_user
            mock_client = MagicMock()
            mock_client.auth.sign_up.return_value = mock_response
            mock_get_client.return_value = mock_client
            mock_parse.return_value = {"user": "data"}

            result = await signup_user_with_invitation("admin@example.com", "password123", invite_code="ADMIN123")

            # Verify ADMIN role was assigned and TTS/STT generation was called
            mock_insert_tenant.assert_called_with(user_id="user-123", tenant_id="tenant_id", user_role="ADMIN")
            mock_generate_tts.assert_called_once_with("tenant_id", "user-123")
            mock_parse.assert_called_with(False, mock_response, "ADMIN")

    @patch('backend.services.user_management_service.get_invitation_by_code')
    @patch('backend.services.user_management_service.check_invitation_available')
    async def test_signup_user_with_dev_invite_role_assignment(self, mock_check_available, mock_get_invite_code):
        """Test DEV role assignment from DEV_INVITE code type (lines 200-201)"""
        # Mock invitation code validation
        mock_check_available.return_value = True
        mock_get_invite_code.return_value = {
            "invitation_id": 1,
            "code_type": "DEV_INVITE",
            "group_ids": [],
            "tenant_id": "tenant_id"
        }

        with patch('backend.services.user_management_service.get_supabase_client') as mock_get_client, \
             patch('backend.services.user_management_service.insert_user_tenant') as mock_insert_tenant, \
             patch('backend.services.user_management_service.parse_supabase_response') as mock_parse, \
             patch('backend.services.user_management_service.use_invitation_code'):

            mock_user = MagicMock()
            mock_user.id = "user-123"
            mock_response = MagicMock()
            mock_response.user = mock_user
            mock_client = MagicMock()
            mock_client.auth.sign_up.return_value = mock_response
            mock_get_client.return_value = mock_client
            mock_parse.return_value = {"user": "data"}

            result = await signup_user_with_invitation("dev@example.com", "password123", invite_code="DEV123")

            # Verify DEV role was assigned and TTS/STT generation was NOT called
            mock_insert_tenant.assert_called_with(user_id="user-123", tenant_id="tenant_id", user_role="DEV")
            mock_parse.assert_called_with(False, mock_response, "DEV")

    @patch('backend.services.user_management_service.check_invitation_available')
    async def test_signup_user_with_invite_code_validation_exception_conversion(self, mock_check_available):
        """Test that other exceptions during invitation validation are converted to IncorrectInviteCodeException (line 208)"""
        # Mock check_invitation_available to raise a generic exception
        mock_check_available.side_effect = Exception("Database connection failed")

        with self.assertRaises(IncorrectInviteCodeException) as context:
            await signup_user_with_invitation("test@example.com", "password123", invite_code="TEST123")

        self.assertIn("Invalid invitation code: Database connection failed", str(context.exception))


class TestParseSupabaseResponse(unittest.IsolatedAsyncioTestCase):
    """Test parse_supabase_response"""

    @patch('backend.services.user_management_service.get_jwt_expiry_seconds')
    @patch('backend.services.user_management_service.calculate_expires_at')
    async def test_parse_response_with_session(self, mock_calc_expires, mock_get_expiry):
        """Test parsing response with session"""
        mock_user = MagicMock()
        mock_user.id = "user-123"
        mock_user.email = "test@example.com"

        mock_session = MagicMock()
        mock_session.access_token = "access-token"
        mock_session.refresh_token = "refresh-token"

        mock_response = MagicMock()
        mock_response.user = mock_user
        mock_response.session = mock_session

        mock_calc_expires.return_value = "2024-01-01T00:00:00Z"
        mock_get_expiry.return_value = 3600

        result = await parse_supabase_response(False, mock_response, "user")

        expected = {
            "user": {
                "id": "user-123",
                "email": "test@example.com",
                "role": "user"
            },
            "session": {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "expires_at": "2024-01-01T00:00:00Z",
                "expires_in_seconds": 3600
            },
            "registration_type": "user"
        }
        self.assertEqual(result, expected)

    async def test_parse_response_without_session(self):
        """Test parsing response without session"""
        mock_user = MagicMock()
        mock_user.id = "user-123"
        mock_user.email = "test@example.com"

        mock_response = MagicMock()
        mock_response.user = mock_user
        mock_response.session = None

        result = await parse_supabase_response(True, mock_response, "admin")

        expected = {
            "user": {
                "id": "user-123",
                "email": "test@example.com",
                "role": "admin"
            },
            "session": None,
            "registration_type": "admin"
        }
        self.assertEqual(result, expected)


class TestGenerateTtsStt4Admin(unittest.IsolatedAsyncioTestCase):
    """Test generate_tts_stt_4_admin"""

    @patch('backend.services.user_management_service.create_model_record')
    async def test_generate_tts_stt_models(self, mock_create_record):
        """Test TTS and STT model generation for admin"""
        await generate_tts_stt_4_admin("tenant-123", "user-123")

        # Should be called twice - once for TTS, once for STT
        self.assertEqual(mock_create_record.call_count, 2)

        # Check TTS model call
        tts_call = mock_create_record.call_args_list[0]
        tts_data = tts_call[0][0]
        self.assertEqual(tts_data["model_name"], "volcano_tts")
        self.assertEqual(tts_data["model_type"], "tts")

        # Check STT model call
        stt_call = mock_create_record.call_args_list[1]
        stt_data = stt_call[0][0]
        self.assertEqual(stt_data["model_name"], "volcano_stt")
        self.assertEqual(stt_data["model_type"], "stt")


class TestVerifyInviteCode(unittest.IsolatedAsyncioTestCase):
    """Test verify_invite_code"""

    @patch('backend.services.user_management_service.INVITE_CODE', 'correct-code')
    async def test_verify_invite_code_success(self):
        """Test successful invite code verification"""
        # Should not raise exception
        await verify_invite_code('correct-code')

    @patch('backend.services.user_management_service.INVITE_CODE', None)
    async def test_verify_invite_code_no_system_code(self):
        """Test when system has no invite code configured"""
        with self.assertRaises(NoInviteCodeException) as context:
            await verify_invite_code('any-code')

        self.assertIn("The system has not configured the admin invite code", str(context.exception))

    @patch('backend.services.user_management_service.INVITE_CODE', 'correct-code')
    async def test_verify_invite_code_no_user_code(self):
        """Test when user provides no invite code"""
        with self.assertRaises(IncorrectInviteCodeException) as context:
            await verify_invite_code(None)

        self.assertIn("Please enter the invite code", str(context.exception))

    @patch('backend.services.user_management_service.INVITE_CODE', 'correct-code')
    async def test_verify_invite_code_wrong_code(self):
        """Test when user provides wrong invite code"""
        with self.assertRaises(IncorrectInviteCodeException) as context:
            await verify_invite_code('wrong-code')

        self.assertIn("Please enter the correct admin invite code", str(context.exception))


class TestSigninUser(unittest.IsolatedAsyncioTestCase):
    """Test signin_user"""

    @patch('backend.services.user_management_service.get_jwt_expiry_seconds')
    @patch('backend.services.user_management_service.calculate_expires_at')
    @patch('backend.services.user_management_service.get_supabase_client')
    async def test_signin_user_success(self, mock_get_client, mock_calc_expires, mock_get_expiry):
        """Test successful user signin"""
        mock_client = MagicMock()
        mock_user = MagicMock()
        mock_user.id = "user-123"
        mock_user.email = "test@example.com"
        mock_user.user_metadata = {"role": "admin"}

        mock_session = MagicMock()
        mock_session.access_token = "access-token"
        mock_session.refresh_token = "refresh-token"

        mock_response = MagicMock()
        mock_response.user = mock_user
        mock_response.session = mock_session

        mock_client.auth.sign_in_with_password.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_calc_expires.return_value = "2024-01-01T00:00:00Z"
        mock_get_expiry.return_value = 3600

        result = await signin_user("test@example.com", "password123")

        expected = {
            "message": "Login successful, session validity is 3600 seconds",
            "data": {
                "user": {
                    "id": "user-123",
                    "email": "test@example.com",
                    "role": "admin"
                },
                "session": {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_at": "2024-01-01T00:00:00Z",
                    "expires_in_seconds": 3600
                }
            }
        }
        self.assertEqual(result, expected)

    @patch('backend.services.user_management_service.get_jwt_expiry_seconds')
    @patch('backend.services.user_management_service.calculate_expires_at')
    @patch('backend.services.user_management_service.get_supabase_client')
    async def test_signin_user_default_role(self, mock_get_client, mock_calc_expires, mock_get_expiry):
        """Test signin with default user role"""
        mock_client = MagicMock()
        mock_user = MagicMock()
        mock_user.id = "user-123"
        mock_user.email = "test@example.com"
        mock_user.user_metadata = {}  # No role in metadata

        mock_session = MagicMock()
        mock_session.access_token = "access-token"
        mock_session.refresh_token = "refresh-token"

        mock_response = MagicMock()
        mock_response.user = mock_user
        mock_response.session = mock_session

        mock_client.auth.sign_in_with_password.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_calc_expires.return_value = "2024-01-01T00:00:00Z"
        mock_get_expiry.return_value = 3600

        result = await signin_user("test@example.com", "password123")

        self.assertEqual(result["data"]["user"]["role"], "user")


class TestRefreshUserToken(unittest.IsolatedAsyncioTestCase):
    """Test refresh_user_token"""

    @patch('backend.services.user_management_service.extend_session')
    @patch('backend.services.user_management_service.get_authorized_client')
    async def test_refresh_token_success(self, mock_get_client, mock_extend_session):
        """Test successful token refresh"""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        session_info = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_at": "2024-01-01T00:00:00Z",
            "expires_in_seconds": 3600
        }
        mock_extend_session.return_value = session_info

        result = await refresh_user_token("Bearer old-token", "refresh-token")

        self.assertEqual(result, session_info)
        mock_get_client.assert_called_once_with("Bearer old-token")
        mock_extend_session.assert_called_once_with(mock_client, "refresh-token")

    @patch('backend.services.user_management_service.extend_session')
    @patch('backend.services.user_management_service.get_authorized_client')
    async def test_refresh_token_failure(self, mock_get_client, mock_extend_session):
        """Test token refresh failure"""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_extend_session.return_value = None

        with self.assertRaises(ValueError) as context:
            await refresh_user_token("Bearer old-token", "refresh-token")

        self.assertEqual(str(context.exception), "Refresh token failed, the token may have expired")


class TestGetSessionByAuthorization(unittest.IsolatedAsyncioTestCase):
    """Test get_session_by_authorization"""

    @patch('backend.services.user_management_service.validate_token')
    async def test_get_session_success(self, mock_validate_token):
        """Test successful session retrieval"""
        mock_user = MagicMock()
        mock_user.id = "user-123"
        mock_user.email = "test@example.com"
        mock_user.user_metadata = {"role": "admin"}
        mock_validate_token.return_value = (True, mock_user)

        result = await get_session_by_authorization("Bearer token")

        expected = {
            "user": {
                "id": "user-123",
                "email": "test@example.com",
                "role": "admin"
            }
        }
        self.assertEqual(result, expected)

    @patch('backend.services.user_management_service.validate_token')
    async def test_get_session_default_role(self, mock_validate_token):
        """Test session retrieval with default role"""
        mock_user = MagicMock()
        mock_user.id = "user-123"
        mock_user.email = "test@example.com"
        mock_user.user_metadata = None
        mock_validate_token.return_value = (True, mock_user)

        result = await get_session_by_authorization("Bearer token")

        self.assertEqual(result["user"]["role"], "user")

    @patch('backend.services.user_management_service.validate_token')
    async def test_get_session_invalid_token(self, mock_validate_token):
        """Test session retrieval with invalid token"""
        mock_validate_token.return_value = (False, None)

        with self.assertRaises(UnauthorizedError) as context:
            await get_session_by_authorization("Bearer invalid-token")

        self.assertEqual(str(context.exception), "Session is invalid or expired")


class TestRevokeRegularUser(unittest.IsolatedAsyncioTestCase):
    """Tests for revoke_regular_user orchestration"""

    @patch('backend.services.user_management_service.soft_delete_user_tenant_by_user_id')
    @patch('backend.services.user_management_service.soft_delete_all_configs_by_user_id')
    @patch('backend.services.user_management_service.soft_delete_all_conversations_by_user')
    @patch('backend.services.user_management_service.build_memory_config')
    @patch('backend.services.user_management_service.clear_memory', new_callable=AsyncMock)
    @patch('backend.services.user_management_service.get_supabase_admin_client')
    async def test_revoke_regular_user_happy_path(self, mock_get_admin, mock_clear, mock_build, mock_soft_conv, mock_soft_cfg, mock_soft_ut):
        mock_admin = MagicMock()
        mock_admin.auth.admin.delete_user = MagicMock()
        mock_get_admin.return_value = mock_admin

        await revoke_regular_user("u1", "t1")

        mock_soft_ut.assert_called_once_with("u1", actor="u1")
        mock_soft_cfg.assert_called_once_with("u1", actor="u1")
        mock_soft_conv.assert_called_once_with("u1")
        mock_build.assert_called_once_with("t1")
        # clear_memory called for user and user_agent
        assert mock_clear.await_count == 2
        mock_get_admin.assert_called_once()
        mock_admin.auth.admin.delete_user.assert_called_once_with("u1")

    @patch('backend.services.user_management_service.soft_delete_user_tenant_by_user_id', side_effect=Exception("db"))
    @patch('backend.services.user_management_service.soft_delete_all_configs_by_user_id', side_effect=Exception("db"))
    @patch('backend.services.user_management_service.soft_delete_all_conversations_by_user', side_effect=Exception("db"))
    @patch('backend.services.user_management_service.build_memory_config', side_effect=Exception("cfg"))
    @patch('backend.services.user_management_service.clear_memory', new_callable=AsyncMock)
    @patch('backend.services.user_management_service.get_supabase_admin_client', side_effect=Exception("admin"))
    async def test_revoke_regular_user_best_effort(self, *_):
        # Should not raise even if all steps fail; function swallows errors for idempotency
        await revoke_regular_user("u1", "t1")

    @patch('backend.services.user_management_service.soft_delete_user_tenant_by_user_id')
    @patch('backend.services.user_management_service.soft_delete_all_configs_by_user_id')
    @patch('backend.services.user_management_service.soft_delete_all_conversations_by_user')
    @patch('backend.services.user_management_service.build_memory_config')
    @patch('backend.services.user_management_service.clear_memory', new_callable=AsyncMock)
    @patch('backend.services.user_management_service.get_supabase_admin_client')
    async def test_revoke_regular_user_admin_client_unavailable(self, mock_get_admin, *_):
        """Cover lines 371-372: admin client None or missing .auth.admin"""
        # Return an object without auth.admin; should trigger RuntimeError branch and be logged
        class NoAdmin:
            pass
        mock_get_admin.return_value = NoAdmin()

        await revoke_regular_user("u1", "t1")
        # No exception should escape

    @patch('backend.services.user_management_service.logging.info', side_effect=Exception("log_fail"))
    async def test_revoke_regular_user_outer_exception_swallowed(self, _mock_log):
        """Cover lines 378-381: unexpected outer exception is swallowed"""
        # Make earlier steps no-op by patching called functions to simple stubs
        with patch('backend.services.user_management_service.soft_delete_user_tenant_by_user_id'), \
                patch('backend.services.user_management_service.soft_delete_all_configs_by_user_id'), \
                patch('backend.services.user_management_service.soft_delete_all_conversations_by_user'), \
                patch('backend.services.user_management_service.build_memory_config', return_value={}), \
                patch('backend.services.user_management_service.clear_memory', new_callable=AsyncMock):
            # Should not raise despite logging.info raising, ensuring outer try/except is covered
            await revoke_regular_user("u1", "t1")


class TestGetUserInfo(unittest.IsolatedAsyncioTestCase):
    """Test get_user_info function"""

    @patch('backend.services.user_management_service.get_user_tenant_by_user_id')
    @patch('backend.services.user_management_service.query_group_ids_by_user')
    async def test_get_user_info_success(self, mock_query_group_ids, mock_get_user_tenant):
        """Test getting user information successfully"""
        # Setup mocks
        mock_get_user_tenant.return_value = {
            "tenant_id": "test_tenant",
            "user_role": "ADMIN"
        }
        mock_query_group_ids.return_value = [1, 2, 3]

        # Execute
        result = await get_user_info("test_user")

        # Assert
        assert result is not None
        assert result["user_id"] == "test_user"
        assert result["tenant_id"] == "test_tenant"
        assert result["user_role"] == "ADMIN"
        assert result["group_ids"] == [1, 2, 3]

        mock_get_user_tenant.assert_called_once_with("test_user")
        mock_query_group_ids.assert_called_once_with("test_user")

    @patch('backend.services.user_management_service.get_user_tenant_by_user_id')
    async def test_get_user_info_user_not_found(self, mock_get_user_tenant):
        """Test getting user information when user doesn't exist"""
        # Setup mocks
        mock_get_user_tenant.return_value = None

        # Execute
        result = await get_user_info("nonexistent_user")

        # Assert
        assert result is None
        mock_get_user_tenant.assert_called_once_with("nonexistent_user")

    @patch('backend.services.user_management_service.get_user_tenant_by_user_id')
    @patch('backend.services.user_management_service.query_group_ids_by_user')
    async def test_get_user_info_exception_handling(self, mock_query_group_ids, mock_get_user_tenant):
        """Test get_user_info handles exceptions gracefully"""
        # Setup mocks to raise exception
        mock_get_user_tenant.side_effect = Exception("Database error")

        # Execute
        result = await get_user_info("test_user")

        # Assert
        assert result is None


class TestGetRolePermissionsByRole(unittest.IsolatedAsyncioTestCase):
    """Test get_permissions_by_role function"""

    @patch('backend.services.user_management_service.get_role_permissions')
    async def test_get_permissions_by_role_success(self, mock_get_permissions):
        """Test successfully getting role permissions"""
        # Setup mock data
        mock_permissions = [
            {
                "role_permission_id": 1,
                "user_role": "USER",
                "permission_category": "KNOWLEDGE_BASE",
                "permission_type": "KNOWLEDGE",
                "permission_subtype": "READ"
            },
            {
                "role_permission_id": 2,
                "user_role": "USER",
                "permission_category": "AGENT_MANAGEMENT",
                "permission_type": "AGENT",
                "permission_subtype": "READ"
            }
        ]
        mock_get_permissions.return_value = mock_permissions

        # Execute
        result = await get_permissions_by_role("USER")

        # Assert
        assert result["user_role"] == "USER"
        assert len(result["permissions"]) == 2
        assert result["total_permissions"] == 2
        assert "Successfully retrieved 2 permissions" in result["message"]
        mock_get_permissions.assert_called_once_with("USER")

    @patch('backend.services.user_management_service.get_role_permissions')
    async def test_get_permissions_by_role_empty_result(self, mock_get_permissions):
        """Test getting role permissions with empty result"""
        # Setup mock to return empty list
        mock_get_permissions.return_value = []

        # Execute
        result = await get_permissions_by_role("NONEXISTENT_ROLE")

        # Assert
        assert result["user_role"] == "NONEXISTENT_ROLE"
        assert len(result["permissions"]) == 0
        assert result["total_permissions"] == 0
        assert "Successfully retrieved 0 permissions" in result["message"]

    @patch('backend.services.user_management_service.get_role_permissions')
    async def test_get_permissions_by_role_exception_handling(self, mock_get_permissions):
        """Test exception handling in get_permissions_by_role"""
        # Setup mock to raise exception
        mock_get_permissions.side_effect = Exception("Database connection failed")

        # Execute and assert
        with self.assertRaises(Exception) as context:
            await get_permissions_by_role("USER")

        assert "Failed to retrieve permissions for role USER" in str(context.exception)


class TestIntegrationScenarios(unittest.IsolatedAsyncioTestCase):
    """Integration test scenarios"""



if __name__ == '__main__':
    unittest.main()
