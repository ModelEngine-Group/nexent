from backend.consts.exceptions import UnauthorizedError, SignatureValidationError, LimitExceededError
import time
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import types
import pytest

# Ensure repository root and sdk/ are importable before any patch() that resolves modules.
# Pytest rootdir is set to test/, so we must extend sys.path explicitly here.
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "sdk"))

# Patch environment variables before any imports that might use them
# Environment variables are now configured in conftest.py

# ---------------------------------------------------------------------------
# Pre-mock heavy dependencies BEFORE importing the module under test.
# This avoids side-effects such as Minio/S3 network calls that are triggered
# during import time of database.client when auth_utils is imported.
# ---------------------------------------------------------------------------

# Stub `nexent.storage.*` modules early so unittest.mock.patch does not import the real
# SDK package (which may pull optional heavy dependencies during __init__).
_nexent_mod = types.ModuleType("nexent")
_nexent_storage_mod = types.ModuleType("nexent.storage")
_nexent_storage_factory_mod = types.ModuleType("nexent.storage.storage_client_factory")
_nexent_minio_config_mod = types.ModuleType("nexent.storage.minio_config")

_nexent_storage_factory_mod.create_storage_client_from_config = lambda *args, **kwargs: None

class _MinIOStorageConfig:
    def validate(self):
        return None

_nexent_minio_config_mod.MinIOStorageConfig = _MinIOStorageConfig

_nexent_mod.storage = _nexent_storage_mod
_nexent_storage_mod.storage_client_factory = _nexent_storage_factory_mod
_nexent_storage_mod.minio_config = _nexent_minio_config_mod

sys.modules["nexent"] = _nexent_mod
sys.modules["nexent.storage"] = _nexent_storage_mod
sys.modules["nexent.storage.storage_client_factory"] = _nexent_storage_factory_mod
sys.modules["nexent.storage.minio_config"] = _nexent_minio_config_mod

# Stub `backend.database.client` early so patch() can resolve the target even when
# backend/ and backend/database/ are namespace packages (no __init__.py).
_backend_mod = sys.modules.get("backend") or types.ModuleType("backend")
_backend_database_mod = types.ModuleType("backend.database")
_backend_database_client_mod = types.ModuleType("backend.database.client")
_backend_database_client_mod.MinioClient = MagicMock()

_backend_mod.database = _backend_database_mod
_backend_database_mod.client = _backend_database_client_mod

sys.modules["backend"] = _backend_mod
sys.modules["backend.database"] = _backend_database_mod
sys.modules["backend.database.client"] = _backend_database_client_mod

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_client_mock).start()

# Stub out the database package hierarchy expected by auth_utils
sys.modules['database'] = MagicMock()

# Mock MinioClient class to prevent initialization errors
mock_minio_class = MagicMock()
mock_minio_class.return_value = MagicMock()

# Provide a lightweight module for database.client with the attributes used
# by auth_utils so that any direct attribute access works as expected.
db_client_stub = types.ModuleType("database.client")
db_client_stub.MinioClient = mock_minio_class
db_client_stub.get_db_session = MagicMock()
db_client_stub.as_dict = MagicMock()

# Mock the global minio_client instance
mock_minio_instance = MagicMock()
db_client_stub.minio_client = mock_minio_instance
db_client_stub.db_client = MagicMock()

sys.modules['database.client'] = db_client_stub

# Stub database.user_tenant_db to avoid real DB interactions
sys.modules['database.user_tenant_db'] = MagicMock(
    get_user_tenant_by_user_id=MagicMock(return_value=None))

# Stub database.token_db to avoid real DB interactions (used by auth_utils)
sys.modules['database.token_db'] = MagicMock(
    get_token_by_access_key=MagicMock(return_value=None))

# Pre-mock nexent core dependency pulled by consts.model
sys.modules['consts'] = MagicMock()

# Mock consts.const but provide real LANGUAGE values for tests
consts_const_mock = MagicMock()
consts_const_mock.LANGUAGE = {"ZH": "zh", "EN": "en"}
consts_const_mock.DEFAULT_USER_ID = "user_id"
consts_const_mock.DEFAULT_TENANT_ID = "tenant_id"
consts_const_mock.IS_SPEED_MODE = False
sys.modules['consts.const'] = consts_const_mock

# Mock exceptions module with real exception classes
consts_exceptions_mock = MagicMock()
consts_exceptions_mock.UnauthorizedError = UnauthorizedError
consts_exceptions_mock.SignatureValidationError = SignatureValidationError
consts_exceptions_mock.LimitExceededError = LimitExceededError
sys.modules['consts.exceptions'] = consts_exceptions_mock
sys.modules['nexent'] = MagicMock()
sys.modules['nexent.core'] = MagicMock()
sys.modules['nexent.core.agents'] = MagicMock()
sys.modules['nexent.core.agents.agent_model'] = MagicMock()

# Mock supabase module
supabase_mock = MagicMock()
supabase_mock.create_client = MagicMock()
sys.modules['supabase'] = supabase_mock

sys.modules['boto3'] = MagicMock()
sys.modules['psycopg2'] = MagicMock()
sys.modules['psycopg2.extras'] = MagicMock()
sys.modules['botocore'] = MagicMock()
sys.modules['botocore.client'] = MagicMock()
sys.modules['botocore.exceptions'] = MagicMock()

# Mock additional dependencies that might be imported
sys.modules['sqlalchemy'] = MagicMock()
sys.modules['sqlalchemy.orm'] = MagicMock()

# Now import the module under test
from backend.utils import auth_utils as au

# Ensure exceptions in module under test are real exception classes, not mocks
au.UnauthorizedError = UnauthorizedError
au.SignatureValidationError = SignatureValidationError

# Ensure constants in module under test are real values, not mocks
au.LANGUAGE = {"ZH": "zh", "EN": "en"}
au.DEFAULT_USER_ID = "user_id"
au.DEFAULT_TENANT_ID = "tenant_id"


def test_calculate_hmac_signature_stability():
    sig1 = au.calculate_hmac_signature(
        "secret", "access", "1234567890", "body")
    sig2 = au.calculate_hmac_signature(
        "secret", "access", "1234567890", "body")
    assert sig1 == sig2
    assert len(sig1) == 64  # sha256 hex


def test_validate_timestamp_window(monkeypatch):
    now = int(time.time())
    assert au.validate_timestamp(str(now))
    # Too old/new should fail
    old = now - (au.TIMESTAMP_VALIDITY_WINDOW + 10)
    assert not au.validate_timestamp(str(old))


def test_extract_aksk_headers_success():
    access_key, ts, sig = au.extract_aksk_headers({
        "X-Access-Key": "ak",
        "X-Timestamp": "123",
        "X-Signature": "sig",
    })
    assert access_key == "ak" and ts == "123" and sig == "sig"


def test_extract_aksk_headers_missing():
    with pytest.raises(UnauthorizedError):
        au.extract_aksk_headers({})


def test_verify_aksk_signature_success(monkeypatch):
    # Arrange matching ak and computed signature
    monkeypatch.setattr(au, "get_aksk_config", lambda tenant_id: ("ak", "sk"))
    ts = str(int(time.time()))
    expected = au.calculate_hmac_signature("sk", "ak", ts, "body")
    ok = au.verify_aksk_signature("ak", ts, expected, "body")
    assert ok is True


def test_verify_aksk_signature_invalid(monkeypatch):
    monkeypatch.setattr(au, "get_aksk_config", lambda tenant_id: ("ak", "sk"))
    ts = str(int(time.time()))
    assert au.verify_aksk_signature("wrong", ts, "sig", "") is False


def test_validate_aksk_authentication(monkeypatch):
    monkeypatch.setattr(au, "verify_aksk_signature", lambda a, b, c, d: True)
    ok = au.validate_aksk_authentication({
        "X-Access-Key": "ak",
        "X-Timestamp": str(int(time.time())),
        "X-Signature": "sig",
    }, "body")
    assert ok is True


def test_validate_aksk_authentication_invalid(monkeypatch):
    monkeypatch.setattr(au, "verify_aksk_signature", lambda a, b, c, d: False)
    with pytest.raises(SignatureValidationError):
        au.validate_aksk_authentication({
            "X-Access-Key": "ak",
            "X-Timestamp": str(int(time.time())),
            "X-Signature": "sig",
        }, "body")


def test_generate_test_jwt_and_get_expiry_seconds(monkeypatch):
    token = au.generate_test_jwt("user-1", expires_in=1234)
    # ensure not in speed mode and no DEBUG_JWT_EXPIRE_SECONDS was set for this test
    monkeypatch.setattr(au, "IS_SPEED_MODE", False)
    monkeypatch.setattr(au, "DEBUG_JWT_EXPIRE_SECONDS", 0)
    seconds = au.get_jwt_expiry_seconds(token)
    assert seconds == 1234


def test_calculate_expires_at_speed_mode(monkeypatch):
    monkeypatch.setattr(au, "IS_SPEED_MODE", True)
    exp = au.calculate_expires_at("irrelevant")
    # far future (> 1 year)
    assert exp > int(time.time()) + 3600 * 24 * 365


def test_extract_user_id_from_jwt_token(monkeypatch):
    monkeypatch.setattr(au, "IS_SPEED_MODE", False)
    monkeypatch.setattr(au, "SUPABASE_JWT_SECRET", au.MOCK_JWT_SECRET_KEY)
    token = au.generate_test_jwt("user-xyz", expires_in=3600)
    uid = au._extract_user_id_from_jwt_token("Bearer " + token)
    assert uid == "user-xyz"


def test_extract_user_id_no_jwt_secret_raises(monkeypatch):
    """Test that missing SUPABASE_JWT_SECRET raises UnauthorizedError"""
    monkeypatch.setattr(au, "IS_SPEED_MODE", False)
    monkeypatch.setattr(au, "SUPABASE_JWT_SECRET", "")
    token = au.generate_test_jwt("user-xyz", expires_in=3600)

    with pytest.raises(UnauthorizedError, match="JWT verification is not configured"):
        au._extract_user_id_from_jwt_token("Bearer " + token)


def test_extract_user_id_invalid_signature_raises(monkeypatch):
    """Test that token signed with wrong secret raises UnauthorizedError"""
    monkeypatch.setattr(au, "IS_SPEED_MODE", False)
    monkeypatch.setattr(au, "SUPABASE_JWT_SECRET", "wrong-secret")
    token = au.generate_test_jwt("user-xyz", expires_in=3600)

    with pytest.raises(UnauthorizedError, match="Invalid or expired"):
        au._extract_user_id_from_jwt_token("Bearer " + token)


def test_extract_user_id_expired_token_raises(monkeypatch):
    """Test that expired token raises UnauthorizedError (ExpiredSignatureError path)"""
    monkeypatch.setattr(au, "IS_SPEED_MODE", False)
    monkeypatch.setattr(au, "SUPABASE_JWT_SECRET", au.MOCK_JWT_SECRET_KEY)
    # Token expired 1 hour ago
    token = au.generate_test_jwt("user-xyz", expires_in=-3600)

    with pytest.raises(UnauthorizedError, match="Token has expired"):
        au._extract_user_id_from_jwt_token("Bearer " + token)


def test_extract_user_id_malformed_token_raises(monkeypatch):
    """Test that malformed JWT raises UnauthorizedError (InvalidTokenError path)"""
    monkeypatch.setattr(au, "IS_SPEED_MODE", False)
    monkeypatch.setattr(au, "SUPABASE_JWT_SECRET", au.MOCK_JWT_SECRET_KEY)

    with pytest.raises(UnauthorizedError, match="Invalid or expired"):
        au._extract_user_id_from_jwt_token("Bearer invalid.jwt.here")


def test_extract_user_id_unauthorized_error_re_raised(monkeypatch):
    """Test that UnauthorizedError from inner code is re-raised without wrapping"""
    monkeypatch.setattr(au, "SUPABASE_JWT_SECRET", "any-secret")

    def mock_decode_raises_unauthorized(*args, **kwargs):
        raise UnauthorizedError("Inner auth error")

    # Patch only jwt.decode to preserve real exception classes for except clauses
    monkeypatch.setattr(au.jwt, "decode", mock_decode_raises_unauthorized)

    with pytest.raises(UnauthorizedError, match="Inner auth error"):
        au._extract_user_id_from_jwt_token("Bearer fake-token")


def test_extract_user_id_generic_exception_raises(monkeypatch):
    """Test that generic Exception during decode raises UnauthorizedError"""
    monkeypatch.setattr(au, "SUPABASE_JWT_SECRET", au.MOCK_JWT_SECRET_KEY)

    def mock_decode_raises_value_error(*args, **kwargs):
        raise ValueError("Unexpected decode error")

    # Patch only jwt.decode to preserve real exception classes for except clauses
    monkeypatch.setattr(au.jwt, "decode", mock_decode_raises_value_error)

    with pytest.raises(UnauthorizedError, match="Invalid or expired authentication token"):
        au._extract_user_id_from_jwt_token("Bearer any-token")


def test_get_current_user_id_speed_mode(monkeypatch):
    monkeypatch.setattr(au, "IS_SPEED_MODE", True)
    uid, tid = au.get_current_user_id("Bearer anything")
    assert uid == au.DEFAULT_USER_ID and tid == au.DEFAULT_TENANT_ID


def test_get_current_user_id_with_mapping(monkeypatch):
    monkeypatch.setattr(au, "IS_SPEED_MODE", False)
    monkeypatch.setattr(au, "SUPABASE_JWT_SECRET", au.MOCK_JWT_SECRET_KEY)
    token = au.generate_test_jwt("user-a", 1000)
    # user->tenant mapping
    monkeypatch.setattr(au, "get_user_tenant_by_user_id",
                        lambda u: {"tenant_id": "tenant-a"})
    uid, tid = au.get_current_user_id(token)
    assert uid == "user-a" and tid == "tenant-a"


def test_get_user_language_from_cookie():
    class Req:
        cookies = {"NEXT_LOCALE": "en"}

    assert au.get_user_language(Req()) == "en"
    assert au.get_user_language(None) == "zh"


def test_get_supabase_client_success(monkeypatch):
    """Test successful Supabase client creation"""
    mock_client = MagicMock()
    monkeypatch.setattr(au, "create_client", lambda url, key: mock_client)
    monkeypatch.setattr(au, "SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setattr(au, "SUPABASE_KEY", "test_key")

    result = au.get_supabase_client()
    assert result == mock_client


def test_get_supabase_client_failure(monkeypatch):
    """Test Supabase client creation failure"""
    def mock_create_client(url, key):
        raise Exception("Connection failed")

    monkeypatch.setattr(au, "create_client", mock_create_client)
    monkeypatch.setattr(au, "SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setattr(au, "SUPABASE_KEY", "test_key")

    result = au.get_supabase_client()
    assert result is None


def test_get_supabase_admin_client_success(monkeypatch):
    """Test successful Supabase admin client creation using SERVICE_ROLE_KEY"""
    mock_client = MagicMock()
    monkeypatch.setattr(au, "create_client", lambda url, key: mock_client)
    monkeypatch.setattr(au, "SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setattr(au, "SERVICE_ROLE_KEY", "svc_key")

    result = au.get_supabase_admin_client()
    assert result == mock_client


def test_get_supabase_admin_client_failure(monkeypatch):
    """Test Supabase admin client creation failure"""
    def mock_create_client(url, key):
        raise Exception("Connection failed")

    monkeypatch.setattr(au, "create_client", mock_create_client)
    monkeypatch.setattr(au, "SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setattr(au, "SERVICE_ROLE_KEY", "svc_key")

    result = au.get_supabase_admin_client()
    assert result is None


def test_validate_aksk_authentication_unexpected_error(monkeypatch):
    """Test unexpected error during AK/SK authentication"""
    def mock_verify_aksk_signature(*args):
        raise Exception("Unexpected error")

    monkeypatch.setattr(au, "verify_aksk_signature",
                        mock_verify_aksk_signature)

    with pytest.raises(UnauthorizedError, match="Authentication failed"):
        au.validate_aksk_authentication({
            "X-Access-Key": "ak",
            "X-Timestamp": str(int(time.time())),
            "X-Signature": "sig",
        }, "body")


def test_get_jwt_expiry_seconds_exception(monkeypatch):
    """Test JWT expiry seconds calculation with exception"""
    monkeypatch.setattr(au, "IS_SPEED_MODE", False)
    monkeypatch.setattr(au, "DEBUG_JWT_EXPIRE_SECONDS", 0)

    # Mock jwt.decode to raise exception
    monkeypatch.setattr(au, "jwt", MagicMock())
    au.jwt.decode.side_effect = Exception("JWT decode failed")

    result = au.get_jwt_expiry_seconds("invalid_token")
    assert result == 3600  # Should return default value


def test_get_current_user_id_no_tenant_mapping(monkeypatch):
    """Test get_current_user_id when no tenant mapping found"""
    monkeypatch.setattr(au, "IS_SPEED_MODE", False)
    monkeypatch.setattr(au, "SUPABASE_JWT_SECRET", au.MOCK_JWT_SECRET_KEY)
    token = au.generate_test_jwt("user-a", 1000)

    # Mock get_user_tenant_by_user_id to return None
    monkeypatch.setattr(au, "get_user_tenant_by_user_id", lambda u: None)

    uid, tid = au.get_current_user_id(token)
    assert uid == "user-a" and tid == au.DEFAULT_TENANT_ID


def test_get_current_user_id_exception(monkeypatch):
    """Test get_current_user_id with exception"""
    monkeypatch.setattr(au, "IS_SPEED_MODE", False)

    # Mock _extract_user_id_from_jwt_token to raise exception
    monkeypatch.setattr(au, "_extract_user_id_from_jwt_token",
                        lambda token: (_ for _ in ()).throw(Exception("Token parsing failed")))

    with pytest.raises(UnauthorizedError, match="Invalid or expired authentication token"):
        au.get_current_user_id("Bearer invalid_token")


# ---------------------------------------------------------------------------
# Bearer Token (API Key) Authentication Tests
# ---------------------------------------------------------------------------

class TestValidateBearerToken:
    """Tests for validate_bearer_token function."""

    def test_validate_bearer_token_success(self, monkeypatch):
        """Test successful Bearer token validation."""
        mock_token_info = {
            "token_id": 1,
            "access_key": "nexent-abc123",
            "user_id": "user123",
            "delete_flag": "N"
        }
        monkeypatch.setattr(au, "get_token_by_access_key", lambda key: mock_token_info)

        is_valid, token_info = au.validate_bearer_token("Bearer nexent-abc123")

        assert is_valid is True
        assert token_info is not None
        assert token_info["user_id"] == "user123"

    def test_validate_bearer_token_without_bearer_prefix(self, monkeypatch):
        """Test Bearer token validation without 'Bearer ' prefix."""
        mock_token_info = {
            "token_id": 1,
            "access_key": "nexent-abc123",
            "user_id": "user123",
            "delete_flag": "N"
        }
        monkeypatch.setattr(au, "get_token_by_access_key", lambda key: mock_token_info)

        is_valid, token_info = au.validate_bearer_token("nexent-abc123")

        assert is_valid is True
        assert token_info is not None

    def test_validate_bearer_token_empty_authorization(self):
        """Test Bearer token validation with empty authorization header."""
        is_valid, token_info = au.validate_bearer_token(None)

        assert is_valid is False
        assert token_info is None

    def test_validate_bearer_token_empty_string(self):
        """Test Bearer token validation with empty string."""
        is_valid, token_info = au.validate_bearer_token("")

        assert is_valid is False
        assert token_info is None

    def test_validate_bearer_token_empty_token(self):
        """Test Bearer token validation with 'Bearer ' only."""
        is_valid, token_info = au.validate_bearer_token("Bearer ")

        assert is_valid is False
        assert token_info is None

    def test_validate_bearer_token_invalid_token(self, monkeypatch):
        """Test Bearer token validation with non-existent token."""
        monkeypatch.setattr(au, "get_token_by_access_key", lambda key: None)

        is_valid, token_info = au.validate_bearer_token("Bearer nexent-nonexistent")

        assert is_valid is False
        assert token_info is None

    def test_validate_bearer_token_deleted(self, monkeypatch):
        """Test Bearer token validation with deleted token."""
        mock_token_info = {
            "token_id": 1,
            "access_key": "nexent-deleted",
            "user_id": "user123",
            "delete_flag": "Y"
        }
        monkeypatch.setattr(au, "get_token_by_access_key", lambda key: mock_token_info)

        is_valid, token_info = au.validate_bearer_token("Bearer nexent-deleted")

        assert is_valid is False
        assert token_info is None

    def test_validate_bearer_token_exception(self, monkeypatch):
        """Test Bearer token validation with exception."""
        def mock_get_token_raises(key):
            raise Exception("Database error")

        monkeypatch.setattr(au, "get_token_by_access_key", mock_get_token_raises)

        is_valid, token_info = au.validate_bearer_token("Bearer nexent-error")

        assert is_valid is False
        assert token_info is None


class TestGetUserAndTenantByAccessKey:
    """Tests for get_user_and_tenant_by_access_key function."""

    def test_get_user_and_tenant_success(self, monkeypatch):
        """Test successful user and tenant retrieval."""
        mock_token_info = {
            "token_id": 1,
            "access_key": "nexent-abc123",
            "user_id": "user123",
            "delete_flag": "N"
        }
        mock_user_tenant = {"tenant_id": "tenant456"}

        monkeypatch.setattr(au, "get_token_by_access_key", lambda key: mock_token_info)
        monkeypatch.setattr(au, "get_user_tenant_by_user_id", lambda uid: mock_user_tenant)

        result = au.get_user_and_tenant_by_access_key("nexent-abc123")

        assert result["user_id"] == "user123"
        assert result["tenant_id"] == "tenant456"
        assert result["token_id"] == 1

    def test_get_user_and_tenant_default_tenant(self, monkeypatch):
        """Test that DEFAULT_TENANT_ID is used when no tenant mapping exists."""
        mock_token_info = {
            "token_id": 1,
            "access_key": "nexent-abc123",
            "user_id": "user123",
            "delete_flag": "N"
        }

        monkeypatch.setattr(au, "get_token_by_access_key", lambda key: mock_token_info)
        monkeypatch.setattr(au, "get_user_tenant_by_user_id", lambda uid: None)

        result = au.get_user_and_tenant_by_access_key("nexent-abc123")

        assert result["user_id"] == "user123"
        assert result["tenant_id"] == au.DEFAULT_TENANT_ID
        assert result["token_id"] == 1

    def test_get_user_and_tenant_empty_tenant_id(self, monkeypatch):
        """Test that DEFAULT_TENANT_ID is used when tenant_id is empty."""
        mock_token_info = {
            "token_id": 1,
            "access_key": "nexent-abc123",
            "user_id": "user123",
            "delete_flag": "N"
        }
        mock_user_tenant = {"tenant_id": ""}

        monkeypatch.setattr(au, "get_token_by_access_key", lambda key: mock_token_info)
        monkeypatch.setattr(au, "get_user_tenant_by_user_id", lambda uid: mock_user_tenant)

        result = au.get_user_and_tenant_by_access_key("nexent-abc123")

        assert result["tenant_id"] == au.DEFAULT_TENANT_ID

    def test_get_user_and_tenant_empty_access_key(self):
        """Test with empty access key."""
        with pytest.raises(UnauthorizedError, match="Invalid access key"):
            au.get_user_and_tenant_by_access_key("")

    def test_get_user_and_tenant_none_access_key(self):
        """Test with None access key."""
        with pytest.raises(UnauthorizedError, match="Invalid access key"):
            au.get_user_and_tenant_by_access_key(None)

    def test_get_user_and_tenant_token_not_found(self, monkeypatch):
        """Test when token is not found."""
        monkeypatch.setattr(au, "get_token_by_access_key", lambda key: None)

        with pytest.raises(UnauthorizedError, match="Invalid or inactive access key"):
            au.get_user_and_tenant_by_access_key("nexent-nonexistent")

    def test_get_user_and_tenant_deleted_token(self, monkeypatch):
        """Test when token is deleted."""
        mock_token_info = {
            "token_id": 1,
            "access_key": "nexent-deleted",
            "user_id": "user123",
            "delete_flag": "Y"
        }
        monkeypatch.setattr(au, "get_token_by_access_key", lambda key: mock_token_info)

        with pytest.raises(UnauthorizedError, match="Invalid or inactive access key"):
            au.get_user_and_tenant_by_access_key("nexent-deleted")

    def test_get_user_and_tenant_no_user_id(self, monkeypatch):
        """Test when token has no user_id."""
        mock_token_info = {
            "token_id": 1,
            "access_key": "nexent-abc123",
            "user_id": None,
            "delete_flag": "N"
        }
        monkeypatch.setattr(au, "get_token_by_access_key", lambda key: mock_token_info)

        with pytest.raises(UnauthorizedError, match="No user associated with this access key"):
            au.get_user_and_tenant_by_access_key("nexent-abc123")
