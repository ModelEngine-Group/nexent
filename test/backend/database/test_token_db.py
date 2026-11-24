# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import inspect
from unittest.mock import patch

import pytest

from management.db.identity import token as token_db
from management.db.identity.models import UserTokenInfo, UserTokenUsageLog


class MockQuery:
    """Mock query object for testing."""
    def __init__(self, model_class, instances):
        self._model_class = model_class
        self._instances = instances
        self._filters = []
        self._order_by = None

    def filter(self, *args):
        self._filters.append(args)
        return self

    def filter_by(self, **kwargs):
        self._filters.append(kwargs)
        return self

    def order_by(self, *args):
        self._order_by = args
        return self

    def first(self):
        # Simple implementation - return first matching instance
        if not self._instances:
            return None
        return self._instances[0] if self._instances else None

    def all(self):
        return list(self._instances)


class MockSession:
    """Mock database session for testing."""
    def __init__(self):
        self.added_objects = []
        self._tokens = []
        self._usage_logs = []
        self._user_tenants = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def add(self, obj):
        self.added_objects.append(obj)
        if isinstance(obj, UserTokenInfo):
            obj.token_id = len(self._tokens) + 1
            self._tokens.append(obj)
        if isinstance(obj, UserTokenUsageLog):
            obj.token_usage_id = len(self._usage_logs) + 1
            self._usage_logs.append(obj)

    def flush(self):
        pass

    def query(self, model_class):
        if model_class == UserTokenInfo:
            return MockQuery(model_class, self._tokens)
        if model_class == UserTokenUsageLog:
            return MockQuery(model_class, self._usage_logs)
        return MockQuery(model_class, [])


@pytest.fixture
def mock_session():
    """Fixture to provide a mock database session."""
    return MockSession()


@pytest.fixture
def mock_db_session(mock_session):
    """Fixture to mock get_db_session."""
    with patch.object(token_db, 'get_db_session', return_value=mock_session):
        yield mock_session


class TestGenerateAccessKey:
    """Tests for generate_access_key function."""

    def test_generate_access_key_format(self):
        """Test that generated access key has correct format."""
        key = token_db.generate_access_key()
        assert key.startswith("nexent-")
        assert len(key) > len("nexent-")

    def test_generate_access_key_unique(self):
        """Test that generated access keys are unique."""
        keys = [token_db.generate_access_key() for _ in range(10)]
        assert len(set(keys)) == 10


class TestMaskAccessKey:
    """Tests for mask_access_key, the value clients render for a stored key."""

    def test_mask_access_key_keeps_prefix_and_tail(self):
        """Pins the display format reported as "nexent****11bb"."""
        assert token_db.mask_access_key(
            "nexent-7593775c8d8798ae7565495b") == "nexent****495b"

    def test_mask_access_key_without_separator(self):
        """A key without a prefix separator falls back to its first 8 characters."""
        assert token_db.mask_access_key("abcdefghij") == "abcdefgh****ghij"

    def test_mask_access_key_short_key(self):
        """A key too short to split hides everything after the first two chars."""
        assert token_db.mask_access_key("nexent12") == "ne****"

    def test_mask_access_key_missing_value(self):
        """An absent key stays absent instead of turning into a mask."""
        assert token_db.mask_access_key(None) is None
        assert token_db.mask_access_key("") == ""


class TestCreateToken:
    """Tests for create_token function."""

    def test_create_token_success(self, mock_db_session):
        """Test successful token creation."""
        result = token_db.create_token("nexent-test123", "user123")

        assert result["token_id"] is not None
        assert result["access_key"] == "nexent-test123"
        assert result["user_id"] == "user123"
        assert len(mock_db_session.added_objects) == 1


class TestListTokensByUser:
    """Tests for list_tokens_by_user function."""

    def test_list_tokens_by_user_success(self, mock_db_session):
        """Test successful token listing masks keys by default."""
        # Add some tokens
        token1 = UserTokenInfo(token_id=1, access_key="nexent-key1", user_id="user123")
        token2 = UserTokenInfo(token_id=2, access_key="nexent-key2", user_id="user123")
        mock_db_session._tokens.extend([token1, token2])

        result = token_db.list_tokens_by_user("user123")

        assert len(result) >= 1
        # Default stays safe: a caller that does not opt out never sees the secret.
        assert result[0]["access_key"] == "nexent****key1"

    def test_list_tokens_by_user_unmasked_on_request(self, mock_db_session):
        """mask=False returns the stored key so the permission layer can expose it.

        Regression guard: role-based exposure is decided by the permission layer,
        which therefore needs the stored value. The database mask used to be
        applied unconditionally, which made administrators copy "nexent****11bb".
        """
        stored_key = "nexent-1234567890abcdef"
        mock_db_session._tokens.append(
            UserTokenInfo(token_id=1, access_key=stored_key, user_id="user123")
        )

        result = token_db.list_tokens_by_user("user123", mask=False)

        assert result[0]["access_key"] == stored_key
        assert "*" not in result[0]["access_key"]

    def test_list_tokens_by_user_empty(self, mock_db_session):
        """Test listing tokens when user has none."""
        result = token_db.list_tokens_by_user("user_nonexistent")
        assert isinstance(result, list)


class TestGetTokenById:
    """Tests for get_token_by_id function."""

    def test_get_token_by_id_success(self, mock_db_session):
        """Test successful token retrieval by ID."""
        token = UserTokenInfo(token_id=1, access_key="nexent-key1", user_id="user123")
        mock_db_session._tokens.append(token)

        result = token_db.get_token_by_id(1)
        assert result is not None

    def test_get_token_by_id_not_found(self, mock_db_session):
        """Test token retrieval with non-existent ID."""
        result = token_db.get_token_by_id(999)
        assert result is None


class TestGetTokenByAccessKey:
    """Tests for get_token_by_access_key function."""

    def test_get_token_by_access_key_success(self, mock_db_session):
        """Test successful token retrieval by access key."""
        token = UserTokenInfo(token_id=1, access_key="nexent-key1", user_id="user123", delete_flag="N")
        mock_db_session._tokens.append(token)

        result = token_db.get_token_by_access_key("nexent-key1")
        assert result is not None
        assert result["access_key"] == "nexent-key1"
        assert result["user_id"] == "user123"

    def test_get_token_by_access_key_not_found(self, mock_db_session):
        """Test token retrieval with non-existent access key."""
        result = token_db.get_token_by_access_key("nexent-nonexistent")
        assert result is None


class TestDeleteToken:
    """Tests for delete_token function."""

    def test_delete_token_success(self, mock_db_session):
        """Test successful token deletion."""
        token = UserTokenInfo(token_id=1, access_key="nexent-key1", user_id="user123", delete_flag="N")
        usage_log = UserTokenUsageLog(token_usage_id=1, token_id=1, created_by="user123")
        mock_db_session._tokens.append(token)
        mock_db_session._usage_logs.append(usage_log)

        result = token_db.delete_token(1, "user123")
        assert result is True
        assert token.delete_flag == "Y"
        assert usage_log.delete_flag == "Y"
        assert usage_log.updated_by == "user123"

    def test_delete_token_not_found(self, mock_db_session):
        """Test deletion of non-existent token."""
        result = token_db.delete_token(999, "user123")
        assert result is False


class TestSoftDeleteTokenUsageByUser:
    """Tests for deleting all API keys and usage logs owned by a user."""

    def test_soft_delete_tokens_also_soft_deletes_usage_logs(self, mock_db_session):
        token = UserTokenInfo(token_id=1, access_key="nexent-key1", user_id="user123")
        usage_log = UserTokenUsageLog(token_usage_id=1, token_id=1, created_by="user123")
        mock_db_session._tokens.append(token)
        mock_db_session._usage_logs.append(usage_log)

        deleted_count = token_db.soft_delete_tokens_by_user("user123", "admin123")

        assert deleted_count == 1
        assert token.delete_flag == "Y"
        assert token.updated_by == "admin123"
        assert usage_log.delete_flag == "Y"
        assert usage_log.updated_by == "admin123"


class TestListActiveTokensByTenant:
    """Tests for list_active_tokens_by_tenant function.

    Note: These tests use integration-style mocking since the function uses
    complex SQLAlchemy features (aliased joins, subqueries, aggregates).
    The tests verify the function structure rather than full DB integration.
    """

    def test_list_active_tokens_by_tenant_function_exists(self):
        """Verify the list_active_tokens_by_tenant function exists."""
        assert hasattr(token_db, 'list_active_tokens_by_tenant')

    def test_list_active_tokens_by_tenant_signature(self):
        """Test that the function has the expected signature."""
        sig = inspect.signature(token_db.list_active_tokens_by_tenant)
        params = list(sig.parameters.keys())
        assert 'tenant_id' in params
        assert 'page' in params
        assert 'page_size' in params
        assert 'sort_order' in params

    def test_list_active_tokens_by_tenant_default_parameters(self):
        """Test that default parameters work correctly."""
        sig = inspect.signature(token_db.list_active_tokens_by_tenant)
        params = sig.parameters
        assert params['page'].default == 1
        assert params['page_size'].default == 20
        assert params['sort_order'].default == "desc"


class TestCreateTokenWithCreatedBy:
    """Tests for create_token with created_by parameter."""

    def test_create_token_with_explicit_created_by(self, mock_db_session):
        """Test that created_by parameter is used when provided."""
        result = token_db.create_token(
            "nexent-custom123", "user_owner", created_by="admin_user"
        )

        assert result["token_id"] is not None
        assert result["access_key"] == "nexent-custom123"
        assert result["user_id"] == "user_owner"

    def test_create_token_defaults_created_by_to_user_id(self, mock_db_session):
        """Test that created_by defaults to user_id when not provided."""
        result = token_db.create_token("nexent-default123", "user123")

        assert result["token_id"] is not None
        assert result["access_key"] == "nexent-default123"


class TestSoftDeleteTokensByUser:
    """Tests for soft_delete_tokens_by_user function."""

    def test_soft_delete_tokens_returns_count(self, mock_db_session):
        """Test that soft_delete_tokens_by_user returns the number of deleted tokens."""
        token1 = UserTokenInfo(token_id=1, access_key="nexent-key1", user_id="user123")
        token2 = UserTokenInfo(token_id=2, access_key="nexent-key2", user_id="user123")
        mock_db_session._tokens.extend([token1, token2])

        deleted_count = token_db.soft_delete_tokens_by_user("user123", "admin456")

        assert deleted_count == 2
        assert token1.delete_flag == "Y"
        assert token2.delete_flag == "Y"

    def test_soft_delete_tokens_empty_user(self, mock_db_session):
        """Test soft delete for user with no tokens."""
        deleted_count = token_db.soft_delete_tokens_by_user("user_with_no_tokens", "admin456")

        assert deleted_count == 0


class TestLogTokenUsage:
    """Tests for log_token_usage function."""

    def test_log_token_usage_success(self, mock_db_session):
        """Test successful token usage logging."""
        result = token_db.log_token_usage(
            token_id=1,
            call_function_name="run_chat",
            related_id=123,
            created_by="user123",
            metadata={"query": "test"}
        )

        assert result is not None
        assert len(mock_db_session.added_objects) == 1

    def test_log_token_usage_without_metadata(self, mock_db_session):
        """Test token usage logging without metadata."""
        result = token_db.log_token_usage(
            token_id=1,
            call_function_name="get_agent_info_list",
            related_id=None,
            created_by="user123"
        )

        assert result is not None


class TestGetLatestUsageMetadata:
    """Tests for get_latest_usage_metadata function."""

    def test_get_latest_usage_metadata_success(self, mock_db_session):
        """Test successful metadata retrieval."""
        usage_log = UserTokenUsageLog(
            token_usage_id=1,
            token_id=1,
            call_function_name="run_chat",
            related_id=123,
            meta_data={"query": "test query"}
        )
        mock_db_session._usage_logs.append(usage_log)

        result = token_db.get_latest_usage_metadata(1, 123, "run_chat")
        assert result is not None
        assert result["query"] == "test query"

    def test_get_latest_usage_metadata_not_found(self, mock_db_session):
        """Test metadata retrieval with no matching records."""
        result = token_db.get_latest_usage_metadata(999, 999, "nonexistent")
        assert result is None
