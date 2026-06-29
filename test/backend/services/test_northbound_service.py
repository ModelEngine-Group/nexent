"""
Tests for backend.services.northbound_service module.

This module tests the northbound-facing service layer functions including:
- Streaming chat (start/stop)
- Conversation management (list, history, title update)
- Agent info listing
- Rate limiting and idempotency
"""
import sys
import os
import types
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

# =============================================================================
# Mock all required modules BEFORE importing northbound_service
# =============================================================================

# Mock consts.exceptions
class LimitExceededError(Exception):
    pass

class UnauthorizedError(Exception):
    pass

class ConversationNotFoundError(Exception):
    pass

consts_exceptions_mod = types.ModuleType("consts.exceptions")
consts_exceptions_mod.LimitExceededError = LimitExceededError
consts_exceptions_mod.UnauthorizedError = UnauthorizedError
consts_exceptions_mod.ConversationNotFoundError = ConversationNotFoundError
sys.modules["consts.exceptions"] = consts_exceptions_mod
sys.modules["backend.consts.exceptions"] = consts_exceptions_mod

# Mock consts.const
consts_const_mod = types.ModuleType("consts.const")
consts_const_mod.ASSET_OWNER_TENANT_ID = "asset-owner-tenant"
sys.modules["consts.const"] = consts_const_mod

# Mock consts package
consts_package = types.ModuleType("consts")
consts_package.exceptions = consts_exceptions_mod
consts_package.const = consts_const_mod
sys.modules["consts"] = consts_package

# Mock database modules
db_client_mod = types.ModuleType("database.client")
db_client_mod.get_db_session = MagicMock()
db_client_mod.as_dict = MagicMock()
sys.modules["database.client"] = db_client_mod
sys.modules["backend.database.client"] = db_client_mod

db_package = types.ModuleType("database")
db_package.client = db_client_mod
sys.modules["database"] = db_package

# Mock token_db
token_db_mod = types.ModuleType("database.token_db")
token_db_mod.log_token_usage = MagicMock(return_value=1)
token_db_mod.get_latest_usage_metadata = MagicMock(return_value={"query": "test"})
sys.modules["database.token_db"] = token_db_mod

# Mock conversation_db
conversation_db_mod = types.ModuleType("database.conversation_db")
conversation_db_mod.get_conversation = MagicMock(return_value={"conversation_id": 123})
conversation_db_mod.get_conversation_messages = MagicMock(return_value=[
    {"message_role": "user", "message_content": "Hello"}
])
conversation_db_mod.get_source_searches_by_message = MagicMock(return_value=[])
sys.modules["database.conversation_db"] = conversation_db_mod

# Mock attachment_db
attachment_db_mod = types.ModuleType("database.attachment_db")
attachment_db_mod.build_s3_url = MagicMock(return_value="s3://bucket/file")
attachment_db_mod.get_file_url = MagicMock(return_value={"success": True, "url": "https://proxy.example/file"})
attachment_db_mod.get_file_size_from_minio = MagicMock(return_value=0)
attachment_db_mod._build_mcp_presigned_url = MagicMock(side_effect=lambda url: url)
sys.modules["database.attachment_db"] = attachment_db_mod

# Mock nexent.multi_modal.utils
nexent_utils_mod = types.ModuleType("nexent.multi_modal.utils")
nexent_utils_mod.parse_s3_url = MagicMock(return_value=("bucket", "path/file.txt"))
sys.modules["nexent"] = types.ModuleType("nexent")
sys.modules["nexent.multi_modal"] = types.ModuleType("nexent.multi_modal")
sys.modules["nexent.multi_modal.utils"] = nexent_utils_mod

# Mock services modules
services_package = types.ModuleType("services")

# Mock agent_service
agent_service_mod = types.ModuleType("services.agent_service")
agent_service_mod.run_agent_stream = AsyncMock()
agent_service_mod.stop_agent_tasks = MagicMock(return_value={"message": "stopped"})
agent_service_mod.get_agent_id_by_name = AsyncMock(return_value=1)
sys.modules["services.agent_service"] = agent_service_mod

# Mock conversation_management_service
conv_mgmt_mod = types.ModuleType("services.conversation_management_service")
conv_mgmt_mod.save_conversation_user = MagicMock()
conv_mgmt_mod.get_conversation_list_service = MagicMock(return_value=[
    {"conversation_id": "1", "title": "Test"}
])
conv_mgmt_mod.create_new_conversation = MagicMock(return_value={"conversation_id": 123})
conv_mgmt_mod.update_conversation_title = MagicMock()
sys.modules["services.conversation_management_service"] = conv_mgmt_mod

# Mock agent_version_service
agent_version_mod = types.ModuleType("services.agent_version_service")
agent_version_mod.list_published_agents_impl = AsyncMock(return_value=[
    {"agent_id": 1, "name": "test_agent", "description": "Test agent"}
])
sys.modules["services.agent_version_service"] = agent_version_mod

# Mock file_management_service
file_mgmt_mod = types.ModuleType("services.file_management_service")
file_mgmt_mod.upload_to_minio = AsyncMock(return_value=[])
file_mgmt_mod.resolve_minio_upload_folder = MagicMock(return_value="attachments/user")
file_mgmt_mod.validate_urls_access = MagicMock()
sys.modules["services.file_management_service"] = file_mgmt_mod

# Add to services package
services_package.agent_service = agent_service_mod
services_package.agent_version_service = agent_version_mod
services_package.conversation_management_service = conv_mgmt_mod
services_package.file_management_service = file_mgmt_mod
sys.modules["services"] = services_package

# Mock consts.model - create stub classes
class AgentRequestStub:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

class ToolParamsRequestStub:
    pass

consts_model_mod = types.ModuleType("consts.model")
consts_model_mod.AgentRequest = AgentRequestStub
consts_model_mod.ToolParamsRequest = ToolParamsRequestStub
sys.modules["consts.model"] = consts_model_mod

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
    ns._IDEMPOTENCY_RUNNING.clear()
    ns._RATE_STATE.clear()
    token_db_mod.log_token_usage.reset_mock()
    yield
    ns._IDEMPOTENCY_RUNNING.clear()
    ns._RATE_STATE.clear()


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
        assert key.count(":") == 3

    def test_build_idempotency_key_with_none(self):
        """Test with None values are converted to empty string."""
        key = ns._build_idempotency_key("tenant1", None, "query")
        assert "tenant1" in key
        assert "None" not in key

    def test_build_idempotency_key_long_string_hashed(self):
        """Test with long string gets hashed."""
        long_string = "a" * 100
        key = ns._build_idempotency_key(long_string)
        assert len(key) < 100

    def test_build_idempotency_key_mixed_long_short(self):
        """Test with mixed long and short values."""
        long_val = "x" * 100
        key = ns._build_idempotency_key("short", long_val, "another_short")
        assert len(key) < 200

    def test_build_idempotency_key_empty(self):
        """Test with all empty values."""
        key = ns._build_idempotency_key()
        assert key == ""

    def test_build_idempotency_key_single_value(self):
        """Test with single value."""
        key = ns._build_idempotency_key("only")
        assert key == "only"


class TestBuildTitleUpdateIdempotencyKey:
    """Tests for _build_title_update_idempotency_key function."""

    def test_title_update_key_format(self):
        """Test that title is hashed in the key."""
        key = ns._build_title_update_idempotency_key("tenant1", 123, "My Title")
        assert "tenant1" in key
        assert "123" in key
        # Title should be hashed (SHA256 hex = 64 chars)
        parts = key.split(":")
        assert len(parts) == 3
        assert len(parts[2]) == 64  # SHA256 hex digest

    def test_title_update_key_different_titles_different_keys(self):
        """Test that different titles produce different keys."""
        key1 = ns._build_title_update_idempotency_key("tenant", 1, "Title A")
        key2 = ns._build_title_update_idempotency_key("tenant", 1, "Title B")
        assert key1 != key2

    def test_title_update_key_same_inputs_same_key(self):
        """Test that same inputs produce same key."""
        key1 = ns._build_title_update_idempotency_key("tenant", 1, "Same Title")
        key2 = ns._build_title_update_idempotency_key("tenant", 1, "Same Title")
        assert key1 == key2


class TestIdempotencyStartEnd:
    """Tests for idempotency_start and idempotency_end functions."""

    @pytest.mark.asyncio
    async def test_idempotency_start_new_key(self):
        """Test starting idempotency with new key succeeds."""
        await ns.idempotency_start("new-key")
        assert "new-key" in ns._IDEMPOTENCY_RUNNING

    @pytest.mark.asyncio
    async def test_idempotency_start_duplicate_key_raises(self):
        """Test that duplicate key raises LimitExceededError."""
        await ns.idempotency_start("duplicate-key")
        with pytest.raises(LimitExceededError):
            await ns.idempotency_start("duplicate-key")

    @pytest.mark.asyncio
    async def test_idempotency_end_removes_key(self):
        """Test that idempotency_end removes the key."""
        await ns.idempotency_start("end-key")
        assert "end-key" in ns._IDEMPOTENCY_RUNNING
        await ns.idempotency_end("end-key")
        assert "end-key" not in ns._IDEMPOTENCY_RUNNING

    @pytest.mark.asyncio
    async def test_idempotency_end_nonexistent_key(self):
        """Test that ending nonexistent key does not raise."""
        await ns.idempotency_end("nonexistent-key")  # Should not raise

    @pytest.mark.asyncio
    async def test_idempotency_expired_key_can_be_reused(self, reset_test_isolation):
        """Test that expired keys can be reused after TTL."""
        # Use a very short TTL
        await ns.idempotency_start("expire-key", ttl_seconds=1)
        assert "expire-key" in ns._IDEMPOTENCY_RUNNING
        # Wait for expiration
        import asyncio
        await asyncio.sleep(1.1)
        # Should be able to start again with same key
        await ns.idempotency_start("expire-key", ttl_seconds=1)


class TestRateLimiting:
    """Tests for rate limiting functionality."""

    @pytest.mark.asyncio
    async def test_rate_limit_first_request_allowed(self):
        """Test first request under limit is allowed."""
        await ns.check_and_consume_rate_limit("tenant-rate")
        assert ns._RATE_STATE["tenant-rate"].get(ns._minute_bucket(), 0) == 1

    @pytest.mark.asyncio
    async def test_rate_limit_multiple_requests(self):
        """Test multiple requests increment counter."""
        for _ in range(5):
            await ns.check_and_consume_rate_limit("tenant-multi")
        assert ns._RATE_STATE["tenant-multi"].get(ns._minute_bucket(), 0) == 5

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_raises(self):
        """Test that exceeding limit raises LimitExceededError."""
        # Fill up to limit
        for _ in range(ns._RATE_LIMIT_PER_MINUTE):
            await ns.check_and_consume_rate_limit("tenant-limit")
        with pytest.raises(LimitExceededError):
            await ns.check_and_consume_rate_limit("tenant-limit")

    @pytest.mark.asyncio
    async def test_rate_limit_different_tenants(self):
        """Test that different tenants have separate limits."""
        for _ in range(10):
            await ns.check_and_consume_rate_limit("tenant-a")
        for _ in range(5):
            await ns.check_and_consume_rate_limit("tenant-b")
        assert ns._RATE_STATE["tenant-a"].get(ns._minute_bucket(), 0) == 10
        assert ns._RATE_STATE["tenant-b"].get(ns._minute_bucket(), 0) == 5

    @pytest.mark.asyncio
    async def test_rate_limit_cleanup_old_buckets(self):
        """Test that old minute buckets are cleaned up."""
        # First, add a request to create an old bucket
        old_bucket = str(int(ns._now_seconds() // 60) - 1)
        ns._RATE_STATE["tenant-cleanup"] = {old_bucket: 50}

        # Make a new request - should trigger cleanup of old bucket
        await ns.check_and_consume_rate_limit("tenant-cleanup")

        # Old bucket should be cleaned up, new bucket should have 1 request
        current_bucket = ns._minute_bucket()
        assert old_bucket not in ns._RATE_STATE["tenant-cleanup"]
        assert ns._RATE_STATE["tenant-cleanup"].get(current_bucket, 0) == 1


@pytest.mark.asyncio
class TestStartStreamingChat:
    """Tests for start_streaming_chat function."""

    async def test_start_streaming_chat_creates_conversation(self):
        """Test that new conversation is created when conversation_id is None."""
        ctx = MockNorthboundContext(token_id=0)

        mock_response = MagicMock()
        mock_response.headers = {}
        agent_service_mod.run_agent_stream.return_value = mock_response

        with patch.object(ns, 'check_and_consume_rate_limit', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_start', new_callable=AsyncMock), \
                patch.object(ns, 'get_conversation_history_internal', new_callable=AsyncMock) as mock_history:
            mock_history.return_value = {"data": {"history": []}}

            await ns.start_streaming_chat(
                ctx=ctx,
                conversation_id=None,
                agent_name="test_agent",
                query="test query"
            )

            conv_mgmt_mod.create_new_conversation.assert_called()

    async def test_start_streaming_chat_logs_token_usage(self):
        """Test that token usage is logged when token_id > 0."""
        ctx = MockNorthboundContext(token_id=1)

        mock_response = MagicMock()
        mock_response.headers = {}
        agent_service_mod.run_agent_stream.return_value = mock_response

        with patch.object(ns, 'check_and_consume_rate_limit', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_start', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_end', new_callable=AsyncMock), \
                patch.object(ns, 'get_conversation_history_internal', new_callable=AsyncMock) as mock_history:
            mock_history.return_value = {"data": {"history": []}}

            await ns.start_streaming_chat(
                ctx=ctx,
                conversation_id=123,
                agent_name="test_agent",
                query="test query",
                meta_data={"key": "value"}
            )

            token_db_mod.log_token_usage.assert_called()

    async def test_start_streaming_chat_rate_limit_exceeded(self):
        """Test that rate limit exceeded is properly propagated."""
        ctx = MockNorthboundContext(token_id=0)

        with patch.object(ns, 'check_and_consume_rate_limit', new_callable=AsyncMock) as mock_limit:
            mock_limit.side_effect = LimitExceededError("Rate exceeded")
            with pytest.raises(LimitExceededError):
                await ns.start_streaming_chat(
                    ctx=ctx,
                    conversation_id=123,
                    agent_name="test_agent",
                    query="test query"
                )

    async def test_start_streaming_chat_uses_existing_conversation(self):
        """Test that existing conversation_id is used without creating new one."""
        ctx = MockNorthboundContext(token_id=0)
        conv_mgmt_mod.create_new_conversation.reset_mock()

        mock_response = MagicMock()
        mock_response.headers = {}
        agent_service_mod.run_agent_stream.return_value = mock_response

        async def mock_get_history(*args, **kwargs):
            return {"data": {"history": []}}

        with patch.object(ns, 'check_and_consume_rate_limit', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_start', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_end', new_callable=AsyncMock), \
                patch.object(ns, 'get_conversation_history_internal', side_effect=mock_get_history):
            await ns.start_streaming_chat(
                ctx=ctx,
                conversation_id=456,
                agent_name="test_agent",
                query="test query"
            )

            conv_mgmt_mod.create_new_conversation.assert_not_called()

    async def test_start_streaming_chat_no_token_id_no_logging(self):
        """Test that token usage is not logged when token_id is 0."""
        ctx = MockNorthboundContext(token_id=0)
        token_db_mod.log_token_usage.reset_mock()

        mock_response = MagicMock()
        mock_response.headers = {}
        agent_service_mod.run_agent_stream.return_value = mock_response

        async def mock_get_history(*args, **kwargs):
            return {"data": {"history": []}}

        with patch.object(ns, 'check_and_consume_rate_limit', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_start', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_end', new_callable=AsyncMock), \
                patch.object(ns, 'get_conversation_history_internal', side_effect=mock_get_history):
            await ns.start_streaming_chat(
                ctx=ctx,
                conversation_id=123,
                agent_name="test_agent",
                query="test query"
            )

            token_db_mod.log_token_usage.assert_not_called()

    async def test_start_streaming_chat_with_attachments(self):
        """Test streaming chat with attachment normalization."""
        ctx = MockNorthboundContext(token_id=0)
        attachments = ["s3://bucket/file.txt"]

        mock_response = MagicMock()
        mock_response.headers = {}
        agent_service_mod.run_agent_stream.return_value = mock_response

        with patch.object(ns, 'check_and_consume_rate_limit', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_start', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_end', new_callable=AsyncMock), \
                patch.object(ns, 'get_conversation_history_internal', new_callable=AsyncMock) as mock_history, \
                patch.object(ns, '_normalize_northbound_attachments', return_value=[{"name": "file.txt"}]) as mock_norm:
            mock_history.return_value = {"data": {"history": []}}

            await ns.start_streaming_chat(
                ctx=ctx,
                conversation_id=123,
                agent_name="test_agent",
                query="test query",
                attachments=attachments
            )

            mock_norm.assert_called_once()

    async def test_start_streaming_chat_with_model_id_override(self):
        """Test that model_id is passed through to AgentRequest to override the agent's default model."""
        ctx = MockNorthboundContext(token_id=0)
        override_model_id = 42

        mock_response = MagicMock()
        mock_response.headers = {}
        agent_service_mod.run_agent_stream.return_value = mock_response

        async def mock_get_history(*args, **kwargs):
            return {"data": {"history": []}}

        with patch.object(ns, 'check_and_consume_rate_limit', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_start', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_end', new_callable=AsyncMock), \
                patch.object(ns, 'get_conversation_history_internal', side_effect=mock_get_history):
            await ns.start_streaming_chat(
                ctx=ctx,
                conversation_id=123,
                agent_name="test_agent",
                query="test query",
                model_id=override_model_id
            )

            # Verify run_agent_stream was called with an AgentRequest that has the override model_id
            call_kwargs = agent_service_mod.run_agent_stream.call_args.kwargs
            agent_request = call_kwargs.get("agent_request")
            assert agent_request is not None
            assert getattr(agent_request, "model_id", None) == override_model_id

    async def test_start_streaming_chat_model_id_null_uses_agent_default(self):
        """Test that omitting model_id results in None, preserving agent's default model."""
        ctx = MockNorthboundContext(token_id=0)

        mock_response = MagicMock()
        mock_response.headers = {}
        agent_service_mod.run_agent_stream.return_value = mock_response

        async def mock_get_history(*args, **kwargs):
            return {"data": {"history": []}}

        with patch.object(ns, 'check_and_consume_rate_limit', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_start', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_end', new_callable=AsyncMock), \
                patch.object(ns, 'get_conversation_history_internal', side_effect=mock_get_history):
            await ns.start_streaming_chat(
                ctx=ctx,
                conversation_id=123,
                agent_name="test_agent",
                query="test query",
                # model_id not provided -> defaults to None
            )

            call_kwargs = agent_service_mod.run_agent_stream.call_args.kwargs
            agent_request = call_kwargs.get("agent_request")
            assert agent_request is not None
            assert getattr(agent_request, "model_id", None) is None

    async def test_start_streaming_chat_with_model_id_and_attachments(self):
        """Test streaming chat with both model_id override and attachments."""
        ctx = MockNorthboundContext(token_id=0)
        attachments = ["s3://bucket/file.txt"]

        mock_response = MagicMock()
        mock_response.headers = {}
        agent_service_mod.run_agent_stream.return_value = mock_response

        with patch.object(ns, 'check_and_consume_rate_limit', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_start', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_end', new_callable=AsyncMock), \
                patch.object(ns, 'get_conversation_history_internal', new_callable=AsyncMock) as mock_history, \
                patch.object(ns, '_normalize_northbound_attachments', return_value=[{"name": "file.txt"}]) as mock_norm:
            mock_history.return_value = {"data": {"history": []}}

            await ns.start_streaming_chat(
                ctx=ctx,
                conversation_id=123,
                agent_name="test_agent",
                query="test query",
                attachments=attachments,
                model_id=99
            )

            mock_norm.assert_called_once()
            call_kwargs = agent_service_mod.run_agent_stream.call_args.kwargs
            agent_request = call_kwargs.get("agent_request")
            assert agent_request is not None
            assert getattr(agent_request, "model_id", None) == 99


@pytest.mark.asyncio
class TestStopChat:
    """Tests for stop_chat function."""

    async def test_stop_chat_success(self):
        """Test successful stop chat."""
        ctx = MockNorthboundContext(token_id=1)
        agent_service_mod.stop_agent_tasks.return_value = {"message": "stopped"}

        result = await ns.stop_chat(ctx=ctx, conversation_id=123)

        assert result["message"] == "stopped"
        assert result["data"] == 123

    async def test_stop_chat_logs_token_usage(self):
        """Test that token usage is logged when token_id > 0."""
        ctx = MockNorthboundContext(token_id=1)
        token_db_mod.log_token_usage.reset_mock()

        await ns.stop_chat(ctx=ctx, conversation_id=123, meta_data={"test": "data"})

        token_db_mod.log_token_usage.assert_called()

    async def test_stop_chat_no_token_id_no_logging(self):
        """Test that token usage is not logged when token_id is 0."""
        ctx = MockNorthboundContext(token_id=0)
        token_db_mod.log_token_usage.reset_mock()

        await ns.stop_chat(ctx=ctx, conversation_id=123)

        token_db_mod.log_token_usage.assert_not_called()


@pytest.mark.asyncio
class TestListConversations:
    """Tests for list_conversations function."""

    async def test_list_conversations_success(self):
        """Test successful conversation listing."""
        ctx = MockNorthboundContext(token_id=0)

        result = await ns.list_conversations(ctx=ctx)

        assert result["message"] == "success"
        assert "data" in result

    async def test_list_conversations_with_metadata(self):
        """Test that metadata is added when token_id > 0."""
        ctx = MockNorthboundContext(token_id=1)
        token_db_mod.get_latest_usage_metadata.return_value = {"query": "test query"}

        result = await ns.list_conversations(ctx=ctx)

        token_db_mod.get_latest_usage_metadata.assert_called()


@pytest.mark.asyncio
class TestGetConversationHistory:
    """Tests for get_conversation_history function."""

    async def test_get_conversation_history_success(self):
        """Test successful history retrieval."""
        ctx = MockNorthboundContext(token_id=1)
        conversation_db_mod.get_conversation_messages.return_value = [
            {"message_role": "user", "message_content": "Hello"},
            {"message_role": "assistant", "message_content": "Hi there"}
        ]

        result = await ns.get_conversation_history(ctx=ctx, conversation_id=123)

        assert result["message"] == "success"
        assert "data" in result
        assert "history" in result["data"]

    async def test_get_conversation_history_fields_transformed(self):
        """Test that message fields are properly transformed."""
        ctx = MockNorthboundContext(token_id=0)
        conversation_db_mod.get_conversation_messages.return_value = [
            {"message_role": "user", "message_content": "Hello"}
        ]

        result = await ns.get_conversation_history(ctx=ctx, conversation_id=123)

        history = result["data"]["history"]
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello"


@pytest.mark.asyncio
class TestGetConversationHistoryInternal:
    """Tests for get_conversation_history_internal function."""

    async def test_get_conversation_history_internal_success(self):
        """Test internal history retrieval without logging."""
        ctx = MockNorthboundContext(token_id=0)
        conversation_db_mod.get_conversation_messages.return_value = [
            {"message_role": "user", "message_content": "Hello"}
        ]

        result = await ns.get_conversation_history_internal(ctx=ctx, conversation_id=123)

        assert result["message"] == "success"
        assert len(result["data"]["history"]) == 1
        assert result["data"]["history"][0]["role"] == "user"

    async def test_get_conversation_history_internal_no_logging(self):
        """Test that internal function does not log token usage."""
        ctx = MockNorthboundContext(token_id=1)
        conversation_db_mod.get_conversation_messages.return_value = []
        token_db_mod.log_token_usage.reset_mock()

        await ns.get_conversation_history_internal(ctx=ctx, conversation_id=123)

        token_db_mod.log_token_usage.assert_not_called()


@pytest.mark.asyncio
class TestGetAgentInfoList:
    """Tests for get_agent_info_list function."""

    async def test_get_agent_info_list_success(self):
        """Test successful agent info list retrieval for asset owner tenant."""
        # Use asset owner tenant to avoid merging asset owner agents
        ctx = MockNorthboundContext(tenant_id="asset-owner-tenant", token_id=1)
        agent_version_mod.list_published_agents_impl.return_value = [
            {"agent_id": 1, "name": "test_agent", "description": "Test"}
        ]

        result = await ns.get_agent_info_list(ctx=ctx)

        assert result["message"] == "success"
        assert len(result["data"]) == 1
        assert "agent_id" not in result["data"][0]

    async def test_get_agent_info_list_includes_asset_owner_agents(self):
        """Test that asset owner agents are included for non-asset-owner tenants."""
        ctx = MockNorthboundContext(tenant_id="other-tenant", token_id=0)
        agent_version_mod.list_published_agents_impl.side_effect = [
            [{"agent_id": 1, "name": "local_agent"}],
            [{"agent_id": 2, "name": "asset_agent"}]
        ]

        result = await ns.get_agent_info_list(ctx=ctx)

        assert len(result["data"]) == 2
        agent_version_mod.list_published_agents_impl.assert_called()


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
        """Test that token usage is logged when token_id > 0."""
        ctx = MockNorthboundContext(token_id=1)
        token_db_mod.log_token_usage.reset_mock()

        await ns.update_conversation_title(
            ctx=ctx,
            conversation_id=123,
            title="New Title",
            meta_data={"source": "api"}
        )

        token_db_mod.log_token_usage.assert_called()

    async def test_update_conversation_title_custom_idempotency_key(self):
        """Test that custom idempotency key is used when provided."""
        ctx = MockNorthboundContext(tenant_id="tenant-1", token_id=1)

        result = await ns.update_conversation_title(
            ctx=ctx,
            conversation_id=123,
            title="New Title",
            idempotency_key="custom-key"
        )

        assert result["idempotency_key"] == "custom-key"

    async def test_update_conversation_title_idempotency_prevents_duplicate(self):
        """Test that duplicate requests within TTL are prevented."""
        ctx = MockNorthboundContext(tenant_id="tenant-1", token_id=0)

        # First call should succeed
        await ns.update_conversation_title(
            ctx=ctx,
            conversation_id=123,
            title="New Title"
        )

        # Second call with same params should raise LimitExceededError
        with pytest.raises(LimitExceededError):
            await ns.update_conversation_title(
                ctx=ctx,
                conversation_id=123,
                title="New Title"
            )


class TestReleaseIdempotencyAfterDelay:
    """Tests for _release_idempotency_after_delay function."""

    @pytest.mark.asyncio
    async def test_release_after_delay(self):
        """Test that idempotency key is released after delay."""
        import asyncio

        await ns.idempotency_start("delayed-key")
        assert "delayed-key" in ns._IDEMPOTENCY_RUNNING

        asyncio.create_task(ns._release_idempotency_after_delay("delayed-key", seconds=0.1))
        await asyncio.sleep(0.2)

        assert "delayed-key" not in ns._IDEMPOTENCY_RUNNING


class TestMinuteBucket:
    """Tests for _minute_bucket helper function."""

    def test_minute_bucket_returns_string(self):
        """Test that minute bucket is a string."""
        bucket = ns._minute_bucket()
        assert isinstance(bucket, str)

    def test_minute_bucket_consistent_for_same_time(self):
        """Test that same time produces same bucket."""
        ts = 1234567890.0
        bucket1 = ns._minute_bucket(ts)
        bucket2 = ns._minute_bucket(ts)
        assert bucket1 == bucket2

    def test_minute_bucket_different_for_different_minutes(self):
        """Test that different minutes produce different buckets."""
        ts1 = 1000000.0
        ts2 = ts1 + 60
        bucket1 = ns._minute_bucket(ts1)
        bucket2 = ns._minute_bucket(ts2)
        assert bucket1 != bucket2


class TestStartStreamingChatErrorHandling:
    """Tests for error handling in start_streaming_chat function."""

    async def test_start_streaming_chat_unauthorized_error(self):
        """Test that UnauthorizedError is properly propagated."""
        ctx = MockNorthboundContext(token_id=0)

        with patch.object(ns, 'check_and_consume_rate_limit', new_callable=AsyncMock) as mock_limit:
            mock_limit.side_effect = UnauthorizedError("Unauthorized")
            with pytest.raises(UnauthorizedError):
                await ns.start_streaming_chat(
                    ctx=ctx,
                    conversation_id=123,
                    agent_name="test_agent",
                    query="test query"
                )

    async def test_start_streaming_chat_get_agent_id_error(self):
        """Test that get_agent_id_by_name error is wrapped properly."""
        ctx = MockNorthboundContext(token_id=0)

        with patch.object(ns, 'check_and_consume_rate_limit', new_callable=AsyncMock), \
                patch.object(ns, 'get_conversation_history_internal', new_callable=AsyncMock) as mock_history, \
                patch.object(ns, 'get_agent_id_by_name', new_callable=AsyncMock) as mock_get_id:
            mock_history.return_value = {"data": {"history": []}}
            mock_get_id.side_effect = Exception("Agent not found")

            with pytest.raises(Exception) as exc_info:
                await ns.start_streaming_chat(
                    ctx=ctx,
                    conversation_id=123,
                    agent_name="nonexistent_agent",
                    query="test query"
                )
            # The exception is wrapped in the outer try/except block
            assert "Agent not found" in str(exc_info.value)

    async def test_start_streaming_chat_save_message_error(self):
        """Test that save_conversation_user error is wrapped properly."""
        ctx = MockNorthboundContext(token_id=0)

        mock_response = MagicMock()
        mock_response.headers = {}
        agent_service_mod.run_agent_stream.return_value = mock_response

        async def mock_get_history(*args, **kwargs):
            return {"data": {"history": []}}

        with patch.object(ns, 'check_and_consume_rate_limit', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_start', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_end', new_callable=AsyncMock), \
                patch.object(ns, 'get_conversation_history_internal', side_effect=mock_get_history), \
                patch.object(ns, 'save_conversation_user', side_effect=Exception("DB error")):
            with pytest.raises(Exception) as exc_info:
                await ns.start_streaming_chat(
                    ctx=ctx,
                    conversation_id=123,
                    agent_name="test_agent",
                    query="test query"
                )
            assert "Failed to persist user message" in str(exc_info.value)

    async def test_start_streaming_chat_token_logging_failure(self):
        """Test that token logging failure is handled gracefully."""
        ctx = MockNorthboundContext(token_id=1)

        mock_response = MagicMock()
        mock_response.headers = {}
        agent_service_mod.run_agent_stream.return_value = mock_response
        token_db_mod.log_token_usage.side_effect = Exception("Logging failed")

        async def mock_get_history(*args, **kwargs):
            return {"data": {"history": []}}

        with patch.object(ns, 'check_and_consume_rate_limit', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_start', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_end', new_callable=AsyncMock), \
                patch.object(ns, 'get_conversation_history_internal', side_effect=mock_get_history):
            # Should not raise even if token logging fails
            result = await ns.start_streaming_chat(
                ctx=ctx,
                conversation_id=123,
                agent_name="test_agent",
                query="test query",
                meta_data={"key": "value"}
            )
            assert result is not None


class TestStopChatErrorHandling:
    """Tests for error handling in stop_chat function."""

    async def test_stop_chat_error(self):
        """Test that errors in stop_chat are wrapped properly."""
        ctx = MockNorthboundContext(token_id=0)
        agent_service_mod.stop_agent_tasks.side_effect = Exception("Stop failed")

        with pytest.raises(Exception) as exc_info:
            await ns.stop_chat(ctx=ctx, conversation_id=123)
        assert "Failed to stop chat" in str(exc_info.value)

    async def test_stop_chat_token_logging_failure(self):
        """Test that token logging failure is handled gracefully."""
        ctx = MockNorthboundContext(token_id=1)
        token_db_mod.log_token_usage.side_effect = Exception("Logging failed")

        with patch("backend.services.northbound_service.stop_agent_tasks", return_value={"message": "stopped"}):
            # Should not raise even if token logging fails
            result = await ns.stop_chat(ctx=ctx, conversation_id=123, meta_data={"key": "value"})
            assert result is not None


class TestListConversationsErrorHandling:
    """Tests for error handling in list_conversations function."""

    async def test_list_conversations_with_metadata_error(self):
        """Test that metadata fetch error is handled gracefully."""
        ctx = MockNorthboundContext(token_id=1)
        conv_mgmt_mod.get_conversation_list_service.return_value = [
            {"conversation_id": "1", "title": "Test"}
        ]
        token_db_mod.get_latest_usage_metadata.side_effect = Exception("DB error")

        # Should not raise even if metadata fetch fails
        result = await ns.list_conversations(ctx=ctx)
        assert result["message"] == "success"

    async def test_list_conversations_empty_meta_data_removed(self):
        """Test that empty meta_data keys are removed from items."""
        ctx = MockNorthboundContext(token_id=1)
        conv_mgmt_mod.get_conversation_list_service.return_value = [
            {"conversation_id": "1", "title": "Test", "meta_data": {}}
        ]

        result = await ns.list_conversations(ctx=ctx)
        assert "meta_data" not in result["data"][0]

    async def test_list_conversations_meta_data_with_no_usage_record(self):
        """Test that meta_data is removed when get_latest_usage_metadata returns empty."""
        ctx = MockNorthboundContext(token_id=1)
        conv_mgmt_mod.get_conversation_list_service.return_value = [
            {"conversation_id": "1", "title": "Test"}
        ]
        token_db_mod.get_latest_usage_metadata.return_value = None

        result = await ns.list_conversations(ctx=ctx)
        assert "meta_data" not in result["data"][0]

    async def test_list_conversations_meta_data_set_when_present(self):
        """Test that meta_data is set on item when get_latest_usage_metadata returns a non-empty value."""
        ctx = MockNorthboundContext(token_id=1)
        conv_mgmt_mod.get_conversation_list_service.return_value = [
            {"conversation_id": "1", "title": "Test"}
        ]
        # Reset side_effect and set return_value
        token_db_mod.get_latest_usage_metadata.side_effect = None
        token_db_mod.get_latest_usage_metadata.return_value = {"query": "test query"}

        result = await ns.list_conversations(ctx=ctx)
        assert "meta_data" in result["data"][0]
        assert result["data"][0]["meta_data"]["query"] == "test query"

    async def test_list_conversations_meta_data_empty_dict_removed(self):
        """Test that empty meta_data (empty dict) is removed from item."""
        ctx = MockNorthboundContext(token_id=1)
        conv_mgmt_mod.get_conversation_list_service.return_value = [
            {"conversation_id": "1", "title": "Test"}
        ]
        # Reset side_effect and set return_value to empty dict (falsy)
        token_db_mod.get_latest_usage_metadata.side_effect = None
        token_db_mod.get_latest_usage_metadata.return_value = {}

        result = await ns.list_conversations(ctx=ctx)
        # Empty dict is falsy, so meta_data should be popped
        assert "meta_data" not in result["data"][0]


class TestGetConversationHistoryErrorHandling:
    """Tests for error handling in get_conversation_history function."""

    async def test_get_conversation_history_error(self):
        """Test that errors in get_conversation_history are wrapped properly."""
        ctx = MockNorthboundContext(token_id=0)
        # Mock get_conversation_messages to raise an error
        conversation_db_mod.get_conversation_messages.side_effect = Exception("DB error")

        with pytest.raises(Exception) as exc_info:
            await ns.get_conversation_history(ctx=ctx, conversation_id=123)
        assert "Failed to get conversation history" in str(exc_info.value)


class TestGetAgentInfoListErrorHandling:
    """Tests for get_agent_info_list function."""

    @pytest.mark.asyncio
    async def test_get_agent_info_by_name_success(self):
        """Test successful agent ID retrieval."""
        agent_service_mod.get_agent_id_by_name.return_value = 42

        result = await ns.get_agent_info_by_name("test_agent", "tenant-1")
        assert result == 42

    @pytest.mark.asyncio
    async def test_get_agent_info_by_name_error(self):
        """Test that errors are wrapped properly."""
        agent_service_mod.get_agent_id_by_name.side_effect = Exception("Agent not found")

        with pytest.raises(Exception) as exc_info:
            await ns.get_agent_info_by_name("nonexistent", "tenant-1")
        assert "Failed to get agent id" in str(exc_info.value)
        assert "nonexistent" in str(exc_info.value)
        assert "tenant-1" in str(exc_info.value)

    async def test_get_agent_info_list_error(self):
        """Test that errors in get_agent_info_list are wrapped properly."""
        ctx = MockNorthboundContext(tenant_id="asset-owner-tenant", token_id=0)
        agent_version_mod.list_published_agents_impl.side_effect = Exception("DB error")

        with pytest.raises(Exception) as exc_info:
            await ns.get_agent_info_list(ctx=ctx)
        assert "Failed to get agent info list" in str(exc_info.value)


class TestUpdateConversationTitleErrorHandling:
    """Tests for error handling in update_conversation_title function."""

    async def test_update_conversation_title_error(self):
        """Test that errors in update_conversation_title are wrapped properly."""
        ctx = MockNorthboundContext(token_id=0)
        conv_mgmt_mod.update_conversation_title.side_effect = Exception("DB error")

        with pytest.raises(Exception) as exc_info:
            await ns.update_conversation_title(
                ctx=ctx,
                conversation_id=123,
                title="New Title"
            )
        assert "Failed to update conversation title" in str(exc_info.value)

    async def test_update_conversation_title_token_logging_failure(self):
        """Test that token logging failure is handled gracefully."""
        ctx = MockNorthboundContext(token_id=1)
        token_db_mod.log_token_usage.side_effect = Exception("Logging failed")
        # Ensure update_conversation_title_service succeeds
        conv_mgmt_mod.update_conversation_title.side_effect = None
        conv_mgmt_mod.update_conversation_title.return_value = True

        # Should not raise even if token logging fails
        result = await ns.update_conversation_title(
            ctx=ctx,
            conversation_id=123,
            title="New Title",
            meta_data={"key": "value"}
        )
        assert result["message"] == "success"

    async def test_update_conversation_title_conversation_not_found(self):
        """Test that ConversationNotFoundError is propagated without wrapping."""
        ctx = MockNorthboundContext(token_id=0)
        conv_mgmt_mod.update_conversation_title.side_effect = ConversationNotFoundError("Not found")

        with pytest.raises(ConversationNotFoundError):
            await ns.update_conversation_title(
                ctx=ctx,
                conversation_id=123,
                title="New Title"
            )


class TestNormalizeAttachmentsErrorHandling:
    """Tests for error handling in _normalize_northbound_attachments function."""

    def test_normalize_attachments_parse_s3_url_error(self):
        """Test that parse_s3_url ValueError is converted to ValueError."""
        with patch("backend.services.northbound_service.parse_s3_url", side_effect=ValueError("Parse error")):
            with pytest.raises(ValueError) as exc_info:
                ns._normalize_northbound_attachments(
                    ["s3://bucket/file.txt"],
                    "user123",
                    "tenant123"
                )
            assert "Invalid S3 URL format" in str(exc_info.value)

    def test_normalize_attachments_permission_error_invalid_url(self):
        """Test that PermissionError with invalid URL is converted to ValueError."""
        with patch("backend.services.northbound_service.parse_s3_url", return_value=("bucket", "path/file.txt")), \
                patch("backend.services.northbound_service.validate_urls_access",
                      side_effect=PermissionError("Invalid S3 URL format: bad")):
            with pytest.raises(ValueError) as exc_info:
                ns._normalize_northbound_attachments(
                    ["s3://bucket/path/file.txt"],
                    "user123",
                    "tenant123"
                )
            assert "Invalid S3 URL format" in str(exc_info.value)

    def test_normalize_attachments_invalid_type(self):
        """Test that non-list attachments raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            ns._normalize_northbound_attachments("s3://bucket/file.txt", "user123", "tenant123")
        assert "attachments must be an array" in str(exc_info.value)

    def test_normalize_attachments_empty_list(self):
        """Test that an empty list returns an empty list."""
        assert ns._normalize_northbound_attachments([], "user123", "tenant123") == []

    def test_normalize_attachments_invalid_url(self):
        """Test that an unsupported URL scheme raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            ns._normalize_northbound_attachments(["https://example.com/file.txt"], "user123", "tenant123")
        assert "Invalid attachment format" in str(exc_info.value) or "Invalid S3 URL format" in str(exc_info.value)

    def test_normalize_attachments_empty_string(self):
        """Test that an empty-string attachment raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            ns._normalize_northbound_attachments([""], "user123", "tenant123")
        assert "non-empty" in str(exc_info.value)

    def test_normalize_attachments_whitespace_string(self):
        """Test that a whitespace-only attachment raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            ns._normalize_northbound_attachments(["  "], "user123", "tenant123")
        assert "non-empty" in str(exc_info.value)

    def test_normalize_attachments_permission_denied(self):
        """Test that a generic PermissionError is re-raised as-is."""
        with patch(
            "backend.services.northbound_service.validate_urls_access",
            side_effect=PermissionError("Access denied: You don't have permission to access this file")
        ):
            with pytest.raises(PermissionError) as exc_info:
                ns._normalize_northbound_attachments(["s3://bucket/attachments/other/file.txt"], "user123", "tenant123")
            assert "Access denied" in str(exc_info.value)

    def test_normalize_attachments_s3_url_success(self):
        """Test successful normalization of an s3:// URL with assertions on collaborator calls."""
        with patch("backend.services.northbound_service.validate_urls_access") as mock_validate, \
                patch("backend.services.northbound_service.get_file_url", return_value={
                    "success": True,
                    "url": "https://proxy.example/file"
                }) as mock_get_url, \
                patch("backend.services.northbound_service.parse_s3_url", return_value=("nexent", "attachments/user123/report.pdf")):
            result = ns._normalize_northbound_attachments(
                ["s3://nexent/attachments/user123/report.pdf"],
                "user123",
                "tenant123",
            )

        mock_validate.assert_called_once_with(
            ["s3://nexent/attachments/user123/report.pdf"],
            "user123",
            "tenant123",
        )
        mock_get_url.assert_called_once_with(
            object_name="attachments/user123/report.pdf",
            expires=86400,
        )
        assert result == [{
            "name": "report.pdf",
            "object_name": "attachments/user123/report.pdf",
            "url": "/nexent/attachments/user123/report.pdf",
            "type": "file",
            "size": 0,
            "description": "",
            "presigned_url": "https://proxy.example/file",
        }]

    def test_normalize_attachments_no_presigned_url(self):
        """Test that presigned_url is omitted when get_file_url returns no url."""
        with patch("backend.services.northbound_service.validate_urls_access"), \
                patch("backend.services.northbound_service.get_file_url", return_value={
                    "success": True,
                    "url": None
                }), \
                patch("backend.services.northbound_service.parse_s3_url", return_value=("nexent", "attachments/user123/report.pdf")):
            result = ns._normalize_northbound_attachments(
                ["s3://nexent/attachments/user123/report.pdf"],
                "user123",
                "tenant123",
            )
        assert "presigned_url" not in result[0]

    def test_normalize_attachments_relative_path(self):
        """Test support for attachments/xxx.md relative path format."""
        with patch("backend.services.northbound_service.validate_urls_access") as mock_validate, \
                patch("backend.services.northbound_service.get_file_url", return_value={
                    "success": True,
                    "url": "https://proxy.example/file"
                }) as mock_get_url:
            result = ns._normalize_northbound_attachments(
                ["attachments/user123/report.pdf"],
                "user123",
                "tenant123",
            )

        mock_validate.assert_called_once_with(
            ["s3://nexent/attachments/user123/report.pdf"],
            "user123",
            "tenant123",
        )
        mock_get_url.assert_called_once_with(
            object_name="attachments/user123/report.pdf",
            expires=86400,
        )
        assert result == [{
            "name": "report.pdf",
            "object_name": "attachments/user123/report.pdf",
            "url": "/nexent/attachments/user123/report.pdf",
            "type": "file",
            "size": 0,
            "description": "",
            "presigned_url": "https://proxy.example/file",
        }]

    def test_normalize_attachments_nexent_path(self):
        """Test support for nexent/xxx.md path format."""
        with patch("backend.services.northbound_service.validate_urls_access") as mock_validate, \
                patch("backend.services.northbound_service.get_file_url", return_value={
                    "success": True,
                    "url": "https://proxy.example/file"
                }) as mock_get_url:
            result = ns._normalize_northbound_attachments(
                ["nexent/attachments/user123/report.pdf"],
                "user123",
                "tenant123",
            )

        mock_validate.assert_called_once_with(
            ["s3://nexent/nexent/attachments/user123/report.pdf"],
            "user123",
            "tenant123",
        )
        mock_get_url.assert_called_once_with(
            object_name="nexent/attachments/user123/report.pdf",
            expires=86400,
        )
        assert result == [{
            "name": "report.pdf",
            "object_name": "nexent/attachments/user123/report.pdf",
            "url": "/nexent/nexent/attachments/user123/report.pdf",
            "type": "file",
            "size": 0,
            "description": "",
            "presigned_url": "https://proxy.example/file",
        }]

    def test_normalize_attachments_absolute_path(self):
        """Test support for /nexent/xxx.md absolute path format."""
        with patch("backend.services.northbound_service.validate_urls_access") as mock_validate, \
                patch("backend.services.northbound_service.get_file_url", return_value={
                    "success": True,
                    "url": "https://proxy.example/file"
                }) as mock_get_url:
            result = ns._normalize_northbound_attachments(
                ["/nexent/attachments/user123/report.pdf"],
                "user123",
                "tenant123",
            )

        mock_validate.assert_called_once_with(
            ["s3://nexent/attachments/user123/report.pdf"],
            "user123",
            "tenant123",
        )
        mock_get_url.assert_called_once_with(
            object_name="attachments/user123/report.pdf",
            expires=86400,
        )
        assert result == [{
            "name": "report.pdf",
            "object_name": "attachments/user123/report.pdf",
            "url": "/nexent/attachments/user123/report.pdf",
            "type": "file",
            "size": 0,
            "description": "",
            "presigned_url": "https://proxy.example/file",
        }]


class TestNorthboundFileDescriptorAndUpload:
    """Tests for _build_northbound_file_descriptor and upload_files_for_northbound."""

    def test_build_file_descriptor_defaults(self):
        """Test that descriptor uses file_name and includes presigned_url when present."""
        result = ns._build_northbound_file_descriptor({
            "file_name": "report.pdf",
            "object_name": "attachments/user123/report.pdf",
            "presigned_url": "https://proxy.example/file",
        })

        assert result["name"] == "report.pdf"
        assert result["object_name"] == "attachments/user123/report.pdf"
        assert result["type"] == "file"
        assert result["size"] == 0
        assert result["url"] == "/nexent/attachments/user123/report.pdf"
        assert result["description"] == ""
        assert result["presigned_url"] == "https://proxy.example/file"

    def test_build_file_descriptor_with_original_filename(self):
        """Test that original_file_name parameter takes precedence over upload_result file_name."""
        result = ns._build_northbound_file_descriptor({
            "file_name": "auto_generated_name.md",
            "object_name": "attachments/user123/20260101120000_abc123.md",
            "file_size": 0,
        }, original_file_name="original-document.pdf", file_size=2048)

        assert result["name"] == "original-document.pdf"
        assert result["object_name"] == "attachments/user123/20260101120000_abc123.md"
        assert result["type"] == "file"
        assert result["size"] == 2048
        assert result["url"] == "/nexent/attachments/user123/20260101120000_abc123.md"
        assert result["description"] == ""

    def test_build_file_descriptor_with_type_and_size(self):
        """Test that explicit file_type and file_size override upload_result values."""
        result = ns._build_northbound_file_descriptor({
            "file_name": "image.png",
            "object_name": "attachments/user123/image.png",
            "file_size": 1024,
            "content_type": "image/png",
        }, file_type="image", file_size=2048)

        assert result["name"] == "image.png"
        assert result["object_name"] == "attachments/user123/image.png"
        assert result["type"] == "image"
        assert result["size"] == 2048
        assert result["url"] == "/nexent/attachments/user123/image.png"
        assert result["description"] == ""

    def test_build_file_descriptor_no_filename(self):
        """Test that basename(object_name) is used when no filename is provided."""
        result = ns._build_northbound_file_descriptor({
            "object_name": "attachments/user123/report.pdf",
        })
        assert result["name"] == "report.pdf"
        assert result["object_name"] == "attachments/user123/report.pdf"
        assert result["type"] == "file"

    def test_build_file_descriptor_no_presigned_url(self):
        """Test that presigned_url is omitted when not present in upload_result."""
        result = ns._build_northbound_file_descriptor({
            "file_name": "report.pdf",
            "object_name": "attachments/user123/report.pdf",
        })
        assert "presigned_url" not in result

    @pytest.mark.asyncio
    async def test_upload_files_for_northbound_success(self):
        """Test successful upload returns normalized descriptors and summary counts."""
        ctx = ns.NorthboundContext(
            request_id="req-123",
            tenant_id="tenant123",
            user_id="user123",
            authorization="Bearer token",
            token_id=1,
        )
        mock_file = MagicMock()
        mock_file.filename = "report.pdf"

        with patch(
            "backend.services.northbound_service.resolve_minio_upload_folder",
            return_value="attachments/user123"
        ), patch(
            "backend.services.northbound_service.upload_to_minio",
            AsyncMock(return_value=[{
                "success": True,
                "file_name": "report.pdf",
                "object_name": "attachments/user123/report.pdf",
                "content_type": "application/pdf",
                "file_size": 1024,
                "presigned_url": "https://proxy.example/file",
            }])
        ):
            result = await ns.upload_files_for_northbound(ctx, [mock_file])

        assert result["summary"]["uploaded"] == 1
        assert result["summary"]["failed"] == 0
        assert result["files"][0]["object_name"] == "attachments/user123/report.pdf"
        assert result["files"][0]["name"] == "report.pdf"
        assert result["files"][0]["type"] == "file"
        assert result["files"][0]["size"] == 1024
        assert result["files"][0]["url"] == "/nexent/attachments/user123/report.pdf"
        assert result["files"][0]["description"] == ""

    @pytest.mark.asyncio
    async def test_upload_files_for_northbound_no_files(self):
        """Test that uploading with no files raises ValueError."""
        ctx = ns.NorthboundContext(
            request_id="req-123",
            tenant_id="tenant123",
            user_id="user123",
            authorization="Bearer token",
        )
        with pytest.raises(ValueError) as exc_info:
            await ns.upload_files_for_northbound(ctx, [])
        assert "No files in the request" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_upload_files_for_northbound_all_failed(self):
        """Test that all-failed uploads raise ValueError."""
        ctx = ns.NorthboundContext(
            request_id="req-123",
            tenant_id="tenant123",
            user_id="user123",
            authorization="Bearer token",
        )
        mock_file = MagicMock()
        mock_file.filename = "report.pdf"

        with patch(
            "backend.services.northbound_service.resolve_minio_upload_folder",
            return_value="attachments/user123"
        ), patch(
            "backend.services.northbound_service.upload_to_minio",
            AsyncMock(return_value=[{
                "success": False,
                "file_name": "report.pdf",
                "object_name": None,
            }])
        ):
            with pytest.raises(ValueError) as exc_info:
                await ns.upload_files_for_northbound(ctx, [mock_file])
        assert "No valid files uploaded" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_upload_files_for_northbound_mixed_results(self):
        """Test that mixed success/failure results are reflected in the summary counts."""
        ctx = ns.NorthboundContext(
            request_id="req-123",
            tenant_id="tenant123",
            user_id="user123",
            authorization="Bearer token",
        )
        mock_file1 = MagicMock()
        mock_file1.filename = "report.pdf"
        mock_file2 = MagicMock()
        mock_file2.filename = "image.png"

        with patch(
            "backend.services.northbound_service.resolve_minio_upload_folder",
            return_value="attachments/user123"
        ), patch(
            "backend.services.northbound_service.upload_to_minio",
            AsyncMock(return_value=[
                {
                    "success": True,
                    "file_name": "report.pdf",
                    "object_name": "attachments/user123/report.pdf",
                },
                {
                    "success": False,
                    "file_name": "image.png",
                    "object_name": None,
                },
            ])
        ):
            result = await ns.upload_files_for_northbound(ctx, [mock_file1, mock_file2])

        assert result["summary"]["total"] == 2
        assert result["summary"]["uploaded"] == 1
        assert result["summary"]["failed"] == 1
