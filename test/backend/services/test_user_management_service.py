import unittest
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock
import sys
import os
import aiohttp

# Add path for correct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))
sys.modules['boto3'] = MagicMock()

# Import exception classes
from consts.exceptions import NoInviteCodeException, IncorrectInviteCodeException, UserRegistrationException

# Functions to test
with patch('backend.database.client.MinioClient', MagicMock()):
    from backend.services.user_management_service import (
        set_auth_token_to_client,
        get_authorized_client,
        get_current_user_from_client,
        validate_token,
        extend_session,
        check_auth_service_health,
        signup_user,
        parse_supabase_response,
        generate_tts_stt_4_admin,
        verify_invite_code,
        signin_user,
        refresh_user_token,
        get_session_by_authorization
    )


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

    @patch('backend.services.user_management_service.logging')
    def test_set_token_exception(self, mock_logging):
        """Test exception handling when setting token"""
        mock_client = MagicMock()
        # Mock the auth attribute to raise an exception when access_token is set
        type(mock_client.auth).access_token = PropertyMock(side_effect=Exception("Auth error"))
        token = "test-jwt-token"
        
        # This should not raise an exception, but should log the error
        set_auth_token_to_client(mock_client, token)
        
        # Verify that the error was logged
        mock_logging.error.assert_called_once_with("Set access token failed: Auth error")


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

    @patch('backend.services.user_management_service.logging')
    def test_get_user_exception(self, mock_logging):
        """Test exception handling"""
        mock_client = MagicMock()
        mock_client.auth.get_user.side_effect = Exception("Get user error")
        
        result = get_current_user_from_client(mock_client)
        
        self.assertIsNone(result)
        mock_logging.error.assert_called_once_with("Get current user failed: Get user error")


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

    @patch('backend.services.user_management_service.logging')
    @patch('backend.services.user_management_service.get_current_user_from_client')
    @patch('backend.services.user_management_service.set_auth_token_to_client')
    @patch('backend.services.user_management_service.get_supabase_client')
    def test_validate_token_exception(self, mock_get_client, mock_set_token, mock_get_user, mock_logging):
        """Test token validation exception"""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_get_user.side_effect = Exception("Validation error")
        
        is_valid, user = validate_token("test-token")
        
        self.assertFalse(is_valid)
        self.assertIsNone(user)
        mock_logging.error.assert_called_once_with("Token validation failed: Validation error")


class TestExtendSession(unittest.TestCase):
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

    @patch('backend.services.user_management_service.logging')
    def test_extend_session_exception(self, mock_logging):
        """Test session extension exception"""
        mock_client = MagicMock()
        mock_client.auth.refresh_session.side_effect = Exception("Refresh error")
        
        result = extend_session(mock_client, "refresh-token")
        
        self.assertIsNone(result)
        mock_logging.error.assert_called_once_with("Extend session failed: Refresh error")


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
            result = await check_auth_service_health()
            self.assertTrue(result)

    @patch.dict(os.environ, {'SUPABASE_URL': 'http://test.supabase.co', 'SUPABASE_KEY': 'test-key'})
    async def test_health_check_wrong_service(self):
        """Test health check with wrong service name"""
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
            result = await check_auth_service_health()
            self.assertFalse(result)

    @patch.dict(os.environ, {'SUPABASE_URL': 'http://test.supabase.co', 'SUPABASE_KEY': 'test-key'})
    async def test_health_check_not_ok(self):
        """Test health check with non-OK response"""
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
            result = await check_auth_service_health()
            self.assertFalse(result)

    @patch.dict(os.environ, {'SUPABASE_URL': 'http://test.supabase.co', 'SUPABASE_KEY': 'test-key'})
    @patch('backend.services.user_management_service.logging')
    @patch('backend.services.user_management_service.aiohttp.ClientSession')
    async def test_health_check_connection_error(self, mock_session_cls, mock_logging):
        """Test health check with connection error"""
        mock_session_cls.side_effect = aiohttp.ClientError("Connection failed")
        
        result = await check_auth_service_health()
        
        self.assertFalse(result)
        mock_logging.error.assert_called_with("Auth service connection failed: Connection failed")

    @patch.dict(os.environ, {'SUPABASE_URL': 'http://test.supabase.co', 'SUPABASE_KEY': 'test-key'})
    @patch('backend.services.user_management_service.logging')
    @patch('backend.services.user_management_service.aiohttp.ClientSession')
    async def test_health_check_general_exception(self, mock_session_cls, mock_logging):
        """Test health check with general exception"""
        mock_session_cls.side_effect = Exception("General error")
        
        result = await check_auth_service_health()
        
        self.assertFalse(result)
        mock_logging.error.assert_called_with("Auth service health check failed: General error")


class TestSignupUser(unittest.IsolatedAsyncioTestCase):
    """Test signup_user"""

    @patch('backend.services.user_management_service.parse_supabase_response')
    @patch('backend.services.user_management_service.generate_tts_stt_4_admin')
    @patch('backend.services.user_management_service.insert_user_tenant')
    @patch('backend.services.user_management_service.verify_invite_code')
    @patch('backend.services.user_management_service.get_supabase_client')
    @patch('backend.services.user_management_service.logging')
    async def test_signup_user_regular_user(self, mock_logging, mock_get_client, mock_verify_code,
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
        
        result = await signup_user("test@example.com", "password123", False)
        
        self.assertEqual(result, {"user": "data"})
        mock_verify_code.assert_not_called()
        mock_generate_tts.assert_not_called()
        mock_insert_tenant.assert_called_once_with(user_id="user-123", tenant_id="tenant_id")
        mock_parse_response.assert_called_once_with(False, mock_response, "user")

    @patch('backend.services.user_management_service.parse_supabase_response')
    @patch('backend.services.user_management_service.generate_tts_stt_4_admin')
    @patch('backend.services.user_management_service.insert_user_tenant')
    @patch('backend.services.user_management_service.verify_invite_code')
    @patch('backend.services.user_management_service.get_supabase_client')
    @patch('backend.services.user_management_service.logging')
    async def test_signup_user_admin(self, mock_logging, mock_get_client, mock_verify_code,
                                   mock_insert_tenant, mock_generate_tts, mock_parse_response):
        """Test admin user signup"""
        mock_client = MagicMock()
        mock_user = MagicMock()
        mock_user.id = "admin-123"
        mock_response = MagicMock()
        mock_response.user = mock_user
        mock_client.auth.sign_up.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_parse_response.return_value = {"user": "data"}
        
        result = await signup_user("admin@example.com", "password123", True, "invite-code")
        
        self.assertEqual(result, {"user": "data"})
        mock_verify_code.assert_called_once_with("invite-code")
        mock_generate_tts.assert_called_once_with("admin-123", "admin-123")
        mock_insert_tenant.assert_called_once_with(user_id="admin-123", tenant_id="admin-123")
        mock_parse_response.assert_called_once_with(True, mock_response, "admin")

    @patch('backend.services.user_management_service.get_supabase_client')
    @patch('backend.services.user_management_service.logging')
    async def test_signup_user_no_user_returned(self, mock_logging, mock_get_client):
        """Test signup when no user is returned"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.user = None
        mock_client.auth.sign_up.return_value = mock_response
        mock_get_client.return_value = mock_client
        
        with self.assertRaises(UserRegistrationException) as context:
            await signup_user("test@example.com", "password123")
        
        self.assertIn("Registration service is temporarily unavailable", str(context.exception))


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
    @patch('backend.services.user_management_service.logging')
    async def test_verify_invite_code_success(self, mock_logging):
        """Test successful invite code verification"""
        # Should not raise exception
        await verify_invite_code('correct-code')
        mock_logging.info.assert_called()

    @patch('backend.services.user_management_service.INVITE_CODE', None)
    @patch('backend.services.user_management_service.logging')
    async def test_verify_invite_code_no_system_code(self, mock_logging):
        """Test when system has no invite code configured"""
        with self.assertRaises(NoInviteCodeException) as context:
            await verify_invite_code('any-code')
        
        self.assertIn("The system has not configured the admin invite code", str(context.exception))

    @patch('backend.services.user_management_service.INVITE_CODE', 'correct-code')
    @patch('backend.services.user_management_service.logging')
    async def test_verify_invite_code_no_user_code(self, mock_logging):
        """Test when user provides no invite code"""
        with self.assertRaises(IncorrectInviteCodeException) as context:
            await verify_invite_code(None)
        
        self.assertIn("Please enter the invite code", str(context.exception))

    @patch('backend.services.user_management_service.INVITE_CODE', 'correct-code')
    @patch('backend.services.user_management_service.logging')
    async def test_verify_invite_code_wrong_code(self, mock_logging):
        """Test when user provides wrong invite code"""
        with self.assertRaises(IncorrectInviteCodeException) as context:
            await verify_invite_code('wrong-code')
        
        self.assertIn("Please enter the correct admin invite code", str(context.exception))


class TestSigninUser(unittest.IsolatedAsyncioTestCase):
    """Test signin_user"""

    @patch('backend.services.user_management_service.get_jwt_expiry_seconds')
    @patch('backend.services.user_management_service.calculate_expires_at')
    @patch('backend.services.user_management_service.get_supabase_client')
    @patch('backend.services.user_management_service.logging')
    async def test_signin_user_success(self, mock_logging, mock_get_client, mock_calc_expires, mock_get_expiry):
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
    @patch('backend.services.user_management_service.logging')
    async def test_refresh_token_success(self, mock_logging, mock_get_client, mock_extend_session):
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
    @patch('backend.services.user_management_service.logging')
    async def test_refresh_token_failure(self, mock_logging, mock_get_client, mock_extend_session):
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
        
        with self.assertRaises(ValueError) as context:
            await get_session_by_authorization("Bearer invalid-token")
        
        self.assertEqual(str(context.exception), "Session is invalid")


class TestIntegrationScenarios(unittest.IsolatedAsyncioTestCase):
    """Integration test scenarios"""

    @patch('backend.services.user_management_service.parse_supabase_response')
    @patch('backend.services.user_management_service.generate_tts_stt_4_admin')
    @patch('backend.services.user_management_service.insert_user_tenant')
    @patch('backend.services.user_management_service.verify_invite_code')
    @patch('backend.services.user_management_service.get_supabase_client')
    async def test_admin_signup_and_validation(self, mock_get_client, 
                                             mock_verify_code, mock_insert_tenant, 
                                             mock_generate_tts, mock_parse_response):
        """Test complete admin signup and token validation flow"""
        # Setup signup
        mock_client = MagicMock()
        mock_user = MagicMock()
        mock_user.id = "admin-123"
        mock_response = MagicMock()
        mock_response.user = mock_user
        mock_client.auth.sign_up.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_parse_response.return_value = {"user": {"id": "admin-123"}}
        
        # Test signup
        signup_result = await signup_user("admin@example.com", "password123", True, "invite-code")
        self.assertEqual(signup_result["user"]["id"], "admin-123")
        
        # Verify that the correct functions were called
        mock_verify_code.assert_called_once_with("invite-code")
        mock_generate_tts.assert_called_once_with("admin-123", "admin-123")
        mock_insert_tenant.assert_called_once_with(user_id="admin-123", tenant_id="admin-123")


if __name__ == '__main__':
    unittest.main() 