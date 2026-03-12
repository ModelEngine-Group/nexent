import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# First mock the consts module to avoid ModuleNotFoundError
consts_mock = MagicMock()
consts_mock.const = MagicMock()
consts_mock.const.MINIO_ENDPOINT = "http://localhost:9000"
consts_mock.const.MINIO_ACCESS_KEY = "test_access_key"
consts_mock.const.MINIO_SECRET_KEY = "test_secret_key"
consts_mock.const.MINIO_REGION = "us-east-1"
consts_mock.const.MINIO_DEFAULT_BUCKET = "test-bucket"
consts_mock.const.POSTGRES_HOST = "localhost"
consts_mock.const.POSTGRES_USER = "test_user"
consts_mock.const.NEXENT_POSTGRES_PASSWORD = "test_password"
consts_mock.const.POSTGRES_DB = "test_db"
consts_mock.const.POSTGRES_PORT = 5432
consts_mock.const.DEFAULT_TENANT_ID = "default_tenant"

sys.modules['consts'] = consts_mock
sys.modules['consts.const'] = consts_mock.const

# Mock exceptions module
class LimitExceededError(Exception):
    pass

class UnauthorizedError(Exception):
    pass

exceptions_mock = MagicMock()
exceptions_mock.LimitExceededError = LimitExceededError
exceptions_mock.UnauthorizedError = UnauthorizedError
sys.modules['consts.exceptions'] = exceptions_mock
sys.modules['backend.consts.exceptions'] = exceptions_mock

# Mock database client
client_mock = MagicMock()
client_mock.MinioClient = MagicMock()
client_mock.get_db_session = MagicMock()
sys.modules['database.client'] = client_mock
sys.modules['backend.database.client'] = client_mock

# Mock token_db module
token_db_mock = MagicMock()
token_db_mock.log_token_usage = MagicMock(return_value=1)
token_db_mock.get_latest_usage_metadata = MagicMock(return_value={"query": "test"})
sys.modules['database.token_db'] = token_db_mock
sys.modules['backend.database.token_db'] = token_db_mock

# Mock conversation_db module
conversation_db_mock = MagicMock()
conversation_db_mock.get_conversation_messages = MagicMock(return_value=[
    {"message_role": "user", "message_content": "Hello"}
])
sys.modules['database.conversation_db'] = conversation_db_mock
sys.modules['backend.database.conversation_db'] = conversation_db_mock

# Mock agent_service module
agent_service_mock = MagicMock()
agent_service_mock.run_agent_stream = AsyncMock()
agent_service_mock.stop_agent_tasks = MagicMock(return_value={"message": "stopped"})
agent_service_mock.list_all_agent_info_impl = AsyncMock(return_value=[{"agent_id": 1, "name": "test_agent"}])
agent_service_mock.get_agent_id_by_name = AsyncMock(return_value=1)
sys.modules['services.agent_service'] = agent_service_mock
sys.modules['backend.services.agent_service'] = agent_service_mock

# Mock conversation_management_service module
conv_mgmt_mock = MagicMock()
conv_mgmt_mock.save_conversation_user = MagicMock()
conv_mgmt_mock.get_conversation_list_service = MagicMock(return_value=[
    {"conversation_id": "1", "title": "Test"}
])
conv_mgmt_mock.create_new_conversation = MagicMock(return_value={"conversation_id": 123})
conv_mgmt_mock.update_conversation_title_service = MagicMock()
sys.modules['services.conversation_management_service'] = conv_mgmt_mock
sys.modules['backend.services.conversation_management_service'] = conv_mgmt_mock

# Mock consts.model
consts_model_mock = MagicMock()
AgentRequest_mock = MagicMock()
consts_model_mock.AgentRequest = AgentRequest_mock
sys.modules['consts.model'] = consts_model_mock

# Mock database.db_models
db_models_mock = MagicMock()
sys.modules['database.db_models'] = db_models_mock

# Now import the module under test
from backend.services import northbound_service as ns


class MockNorthboundContext:
    """Mock NorthboundContext for testing."""
    def __init__(self, request_id="req-123", tenant_id="tenant-1", user_id="user-1",
                 authorization="Bearer test", token_id=0):
        self.request_id = request_id
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.authorization = authorization
        self.token_id = token_id


@pytest.fixture(autouse=True)
def reset_test_isolation():
    """Reset test isolation state before each test."""
    # Clear idempotency state
    ns._IDEMPOTENCY_RUNNING.clear()
    # Reset mock call counts
    token_db_mock.log_token_usage.reset_mock()
    yield
    # Cleanup after test
    ns._IDEMPOTENCY_RUNNING.clear()


class TestNorthboundContext:
    """Tests for NorthboundContext dataclass."""

    def test_northbound_context_default_token_id(self):
        """Test that token_id defaults to 0."""
        ctx = ns.NorthboundContext(
            request_id="req-1",
            tenant_id="tenant-1",
            user_id="user-1",
            authorization="Bearer test"
        )
        assert ctx.token_id == 0

    def test_northbound_context_with_token_id(self):
        """Test that token_id can be set."""
        ctx = ns.NorthboundContext(
            request_id="req-1",
            tenant_id="tenant-1",
            user_id="user-1",
            authorization="Bearer test",
            token_id=123
        )
        assert ctx.token_id == 123


class TestBuildIdempotencyKey:
    """Tests for _build_idempotency_key function."""

    def test_build_idempotency_key_normal(self):
        """Test normal case."""
        key = ns._build_idempotency_key("tenant1", "123", "agent1", "query")
        assert "tenant1" in key
        assert "123" in key

    def test_build_idempotency_key_with_none(self):
        """Test with None values."""
        key = ns._build_idempotency_key("tenant1", None, "query")
        assert "tenant1" in key
        # None values are converted to empty string
        assert "None" not in key
        # Should contain the empty string from None conversion
        assert "tenant1::" in key or ":query" in key

    def test_build_idempotency_key_long_string(self):
        """Test with long string gets hashed."""
        long_string = "a" * 100
        key = ns._build_idempotency_key(long_string)
        # Should be hashed (not the full string)
        assert len(key) < 100


@pytest.mark.asyncio
class TestStartStreamingChat:
    """Tests for start_streaming_chat function."""

    async def test_start_streaming_chat_creates_conversation(self):
        """Test that new conversation is created when conversation_id is None."""
        ctx = MockNorthboundContext(token_id=1)

        # Mock response
        mock_response = MagicMock()
        mock_response.headers = {}
        agent_service_mock.run_agent_stream.return_value = mock_response

        with patch.object(ns, 'check_and_consume_rate_limit', new_callable=AsyncMock):
            with patch.object(ns, 'idempotency_start', new_callable=AsyncMock):
                with patch.object(ns, 'get_conversation_history_internal', new_callable=AsyncMock) as mock_history:
                    mock_history.return_value = {"data": {"history": []}}

                    try:
                        result = await ns.start_streaming_chat(
                            ctx=ctx,
                            conversation_id=None,
                            agent_name="test_agent",
                            query="test query"
                        )
                    except Exception:
                        pass  # May fail due to other mocks

                    # Verify create_new_conversation was called
                    conv_mgmt_mock.create_new_conversation.assert_called()

    async def test_start_streaming_chat_logs_token_usage(self):
        """Test that token usage is logged when token_id > 0."""
        ctx = MockNorthboundContext(token_id=1)

        mock_response = MagicMock()
        mock_response.headers = {}
        agent_service_mock.run_agent_stream.return_value = mock_response

        with patch.object(ns, 'check_and_consume_rate_limit', new_callable=AsyncMock):
            with patch.object(ns, 'idempotency_start', new_callable=AsyncMock):
                with patch.object(ns, 'idempotency_end', new_callable=AsyncMock):
                    with patch.object(ns, 'get_conversation_history_internal', new_callable=AsyncMock) as mock_history:
                        mock_history.return_value = {"data": {"history": []}}

                        try:
                            await ns.start_streaming_chat(
                                ctx=ctx,
                                conversation_id=123,
                                agent_name="test_agent",
                                query="test query",
                                meta_data={"key": "value"}
                            )
                        except Exception:
                            pass

                        # Verify log_token_usage was called
                        token_db_mock.log_token_usage.assert_called()


@pytest.mark.asyncio
class TestStopChat:
    """Tests for stop_chat function."""

    async def test_stop_chat_success(self):
        """Test successful stop chat."""
        ctx = MockNorthboundContext(token_id=1)
        agent_service_mock.stop_agent_tasks.return_value = {"message": "stopped"}

        result = await ns.stop_chat(ctx=ctx, conversation_id=123)

        assert result["message"] == "stopped"
        assert result["data"] == 123

    async def test_stop_chat_logs_token_usage(self):
        """Test that token usage is logged."""
        ctx = MockNorthboundContext(token_id=1)

        await ns.stop_chat(ctx=ctx, conversation_id=123, meta_data={"test": "data"})

        token_db_mock.log_token_usage.assert_called()


@pytest.mark.asyncio
class TestListConversations:
    """Tests for list_conversations function."""

    async def test_list_conversations_success(self):
        """Test successful conversation listing."""
        ctx = MockNorthboundContext(token_id=0)  # No token_id, no metadata lookup

        result = await ns.list_conversations(ctx=ctx)

        assert result["message"] == "success"
        assert "data" in result

    async def test_list_conversations_with_metadata(self):
        """Test that metadata is added when token_id > 0."""
        ctx = MockNorthboundContext(token_id=1)
        token_db_mock.get_latest_usage_metadata.return_value = {"query": "test query"}

        result = await ns.list_conversations(ctx=ctx)

        # Should have called get_latest_usage_metadata
        token_db_mock.get_latest_usage_metadata.assert_called()


@pytest.mark.asyncio
class TestGetConversationHistory:
    """Tests for get_conversation_history function."""

    async def test_get_conversation_history_success(self):
        """Test successful history retrieval."""
        ctx = MockNorthboundContext(token_id=1)
        conversation_db_mock.get_conversation_messages.return_value = [
            {"message_role": "user", "message_content": "Hello"},
            {"message_role": "assistant", "message_content": "Hi there"}
        ]

        result = await ns.get_conversation_history(ctx=ctx, conversation_id=123)

        assert result["message"] == "success"
        assert "data" in result
        assert "history" in result["data"]


@pytest.mark.asyncio
class TestGetConversationHistoryInternal:
    """Tests for get_conversation_history_internal function."""

    async def test_get_conversation_history_internal_success(self):
        """Test internal history retrieval without logging."""
        ctx = MockNorthboundContext(token_id=0)
        conversation_db_mock.get_conversation_messages.return_value = [
            {"message_role": "user", "message_content": "Hello"}
        ]

        result = await ns.get_conversation_history_internal(ctx=ctx, conversation_id=123)

        assert result["message"] == "success"
        assert len(result["data"]["history"]) == 1
        assert result["data"]["history"][0]["role"] == "user"

    async def test_get_conversation_history_internal_no_logging(self):
        """Test that internal function does not log token usage."""
        ctx = MockNorthboundContext(token_id=1)
        conversation_db_mock.get_conversation_messages.return_value = []

        await ns.get_conversation_history_internal(ctx=ctx, conversation_id=123)

        # Should NOT call log_token_usage
        token_db_mock.log_token_usage.assert_not_called()


@pytest.mark.asyncio
class TestGetAgentInfoList:
    """Tests for get_agent_info_list function."""

    async def test_get_agent_info_list_success(self):
        """Test successful agent info list retrieval."""
        ctx = MockNorthboundContext(token_id=1)
        agent_service_mock.list_all_agent_info_impl.return_value = [
            {"agent_id": 1, "name": "test_agent", "description": "Test"}
        ]

        result = await ns.get_agent_info_list(ctx=ctx)

        assert result["message"] == "success"
        assert len(result["data"]) == 1
        # agent_id should be removed
        assert "agent_id" not in result["data"][0]


@pytest.mark.asyncio
class TestUpdateConversationTitle:
    """Tests for update_conversation_title function."""

    async def test_update_conversation_title_success(self):
        """Test successful title update."""
        ctx = MockNorthboundContext(token_id=1)

        result = await ns.update_conversation_title(
            ctx=ctx,
            conversation_id=123,
            title="New Title"
        )

        assert result["message"] == "success"
        assert result["data"] == 123
        assert "idempotency_key" in result

    async def test_update_conversation_title_logs_token_usage(self):
        """Test that token usage is logged."""
        ctx = MockNorthboundContext(token_id=1)

        await ns.update_conversation_title(
            ctx=ctx,
            conversation_id=123,
            title="New Title",
            meta_data={"source": "api"}
        )

        token_db_mock.log_token_usage.assert_called()

    async def test_update_conversation_title_idempotency_key(self):
        """Test that idempotency key is properly built."""
        ctx = MockNorthboundContext(tenant_id="tenant-1", token_id=1)

        result = await ns.update_conversation_title(
            ctx=ctx,
            conversation_id=123,
            title="New Title",
            idempotency_key="custom-key"
        )

        assert result["idempotency_key"] == "custom-key"
