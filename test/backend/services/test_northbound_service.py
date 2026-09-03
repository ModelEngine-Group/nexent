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
from enum import Enum
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

# =============================================================================
# Mock all required modules BEFORE importing northbound_service
# =============================================================================

class ErrorCode:
    CHAT_METADATA_INVALID = "010106"
    CHAT_METADATA_TOO_LARGE = "010107"


class RuntimeMetadataValidationCode(str, Enum):
    INVALID_METADATA_TYPE = "INVALID_METADATA_TYPE"
    METADATA_TOO_LARGE = "METADATA_TOO_LARGE"


class AppException(Exception):
    def __init__(self, error_code, message=None, details=None):
        self.error_code = error_code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class RuntimeMetadataValidationError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


# Mock consts.exceptions
class LimitExceededError(Exception):
    pass

class UnauthorizedError(Exception):
    pass

class ConversationNotFoundError(Exception):
    pass

class RuntimeServiceTimeoutError(Exception):
    pass

class RuntimeServiceUnavailableError(Exception):
    pass

class RuntimeUpstreamError(Exception):
    pass


consts_exceptions_mod = types.ModuleType("consts.exceptions")
consts_exceptions_mod.LimitExceededError = LimitExceededError
consts_exceptions_mod.UnauthorizedError = UnauthorizedError
consts_exceptions_mod.ConversationNotFoundError = ConversationNotFoundError
consts_exceptions_mod.RuntimeServiceTimeoutError = RuntimeServiceTimeoutError
consts_exceptions_mod.RuntimeServiceUnavailableError = RuntimeServiceUnavailableError
consts_exceptions_mod.RuntimeUpstreamError = RuntimeUpstreamError
consts_exceptions_mod.AppException = AppException
consts_exceptions_mod.RuntimeMetadataValidationError = RuntimeMetadataValidationError
sys.modules["consts.exceptions"] = consts_exceptions_mod
sys.modules["backend.consts.exceptions"] = consts_exceptions_mod

consts_error_code_mod = types.ModuleType("consts.error_code")
consts_error_code_mod.ErrorCode = ErrorCode
consts_error_code_mod.RuntimeMetadataValidationCode = RuntimeMetadataValidationCode
sys.modules["consts.error_code"] = consts_error_code_mod
sys.modules["backend.consts.error_code"] = consts_error_code_mod

# Mock consts.const
consts_const_mod = types.ModuleType("consts.const")
consts_const_mod.AIDP_API_KEY = "test-aidp-api-key"
consts_const_mod.AIDP_SERVER_URL = "https://aidp.example"
consts_const_mod.ASSET_OWNER_TENANT_ID = "asset-owner-tenant"
consts_const_mod.RUNTIME_STATE_REDIS_URL = ""
consts_const_mod.RUNTIME_STREAM_TTL_SECONDS = 86400
consts_const_mod.RUNTIME_STREAM_MAX_LEN = 10000
consts_const_mod.RUNTIME_RUN_TTL_SECONDS = 86400
consts_const_mod.RUNTIME_CANCEL_TTL_SECONDS = 86400
consts_const_mod.RUNTIME_COMPLETED_TTL_SECONDS = 300
consts_const_mod.NORTHBOUND_IDEMPOTENCY_TTL_SECONDS = 600
consts_const_mod.NORTHBOUND_RATE_LIMIT_ENABLED = True
consts_const_mod.NORTHBOUND_RATE_LIMIT_PER_MINUTE = 120
sys.modules["consts.const"] = consts_const_mod

# Mock consts package
consts_package = types.ModuleType("consts")
consts_package.exceptions = consts_exceptions_mod
consts_package.const = consts_const_mod
consts_package.error_code = consts_error_code_mod
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
conversation_db_mod.get_conversation_list = MagicMock(return_value=[
    {"conversation_id": "1", "title": "Test"}
])
conversation_db_mod.get_conversation_messages = MagicMock(return_value=[
    {"message_role": "user", "message_content": "Hello"}
])
conversation_db_mod.get_source_searches_by_message = MagicMock(return_value=[])
sys.modules["database.conversation_db"] = conversation_db_mod

knowledge_db_mod = types.ModuleType("database.knowledge_db")
knowledge_db_mod.get_knowledge_info_by_tenant_id = MagicMock(return_value=[])
sys.modules["database.knowledge_db"] = knowledge_db_mod

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

# Mock runtime_state_service
runtime_state_service_mod = types.ModuleType("services.runtime_state_service")
runtime_state_service_mod.runtime_state_service = MagicMock()
runtime_state_service_mod.runtime_state_service.enabled = False
runtime_state_service_mod.runtime_state_service.acquire_idempotency_async = AsyncMock(return_value=True)
runtime_state_service_mod.runtime_state_service.release_idempotency_async = AsyncMock()
runtime_state_service_mod.runtime_state_service.consume_rate_limit_async = AsyncMock(return_value=1)
sys.modules["services.runtime_state_service"] = runtime_state_service_mod

# Mock agent_service
agent_service_mod = types.ModuleType("management.services.agent.service")
agent_service_mod.get_agent_by_name_impl = MagicMock(return_value={"agent_id": 1, "latest_version_no": 1})
sys.modules["management.services.agent.service"] = agent_service_mod

# Mock runtime forwarding service
runtime_proxy_mod = types.ModuleType("services.runtime_proxy_service")
runtime_proxy_mod.forward_agent_run = AsyncMock()
runtime_proxy_mod.forward_agent_stop = AsyncMock(return_value={"message": "stopped"})
sys.modules["services.runtime_proxy_service"] = runtime_proxy_mod

# Mock conversation_management_service
conv_mgmt_mod = types.ModuleType("services.conversation_management_service")
conv_mgmt_mod.save_conversation_user = MagicMock()
conv_mgmt_mod.create_new_conversation = MagicMock(return_value={"conversation_id": 123})
conv_mgmt_mod.generate_conversation_title_service = AsyncMock(return_value="Generated title")
conv_mgmt_mod.update_conversation_title = MagicMock()
sys.modules["services.conversation_management_service"] = conv_mgmt_mod

# Mock model_management_service
model_mgmt_mod = types.ModuleType("services.model_management_service")
model_mgmt_mod.list_models_for_tenant = AsyncMock(return_value=[])
sys.modules["services.model_management_service"] = model_mgmt_mod

# Mock agent_version_service
agent_version_mod = types.ModuleType("services.agent_version_service")
agent_version_mod.list_published_agents_impl = AsyncMock(return_value=[
    {"agent_id": 1, "name": "test_agent", "description": "Test agent"}
])
sys.modules["services.agent_version_service"] = agent_version_mod

knowledge_scope_service_mod = types.ModuleType("services.knowledge_scope_service")
knowledge_scope_service_mod.LOCAL_TOOL_CLASS = "KnowledgeBaseSearchTool"
knowledge_scope_service_mod.AIDP_TOOL_CLASS = "AidpSearchTool"
knowledge_scope_service_mod.get_agent_knowledge_capabilities = MagicMock()
sys.modules["services.knowledge_scope_service"] = knowledge_scope_service_mod

vectordatabase_service_mod = types.ModuleType("management.services.knowledge_base.service")
vectordatabase_service_mod.ElasticSearchService = MagicMock()
vectordatabase_service_mod.ElasticSearchService.filter_accessible_indices = MagicMock(
    return_value=[]
)
sys.modules["management.services.knowledge_base.service"] = vectordatabase_service_mod

model_resolver_mod = types.ModuleType("management.services.model.resolver")
model_resolver_mod.get_model_descriptor = MagicMock(
    return_value=types.SimpleNamespace(is_multimodal=False)
)
sys.modules["management.services.model.resolver"] = model_resolver_mod

# Mock file_management_service
file_mgmt_mod = types.ModuleType("services.file_management_service")
file_mgmt_mod.upload_to_minio = AsyncMock(return_value=[])
file_mgmt_mod.resolve_minio_upload_folder = MagicMock(return_value="attachments/user")
file_mgmt_mod.validate_urls_access = MagicMock()
sys.modules["services.file_management_service"] = file_mgmt_mod

# Add to services package
services_package.agent_service = agent_service_mod
services_package.runtime_proxy_service = runtime_proxy_mod
services_package.agent_version_service = agent_version_mod
services_package.conversation_management_service = conv_mgmt_mod
services_package.model_management_service = model_mgmt_mod
services_package.file_management_service = file_mgmt_mod
services_package.runtime_state_service = runtime_state_service_mod
services_package.knowledge_scope_service = knowledge_scope_service_mod
services_package.vectordatabase_service = vectordatabase_service_mod
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
    token_db_mod.log_token_usage.reset_mock(side_effect=True)
    token_db_mod.log_token_usage.return_value = 1
    agent_version_mod.list_published_agents_impl.reset_mock(side_effect=True)
    agent_version_mod.list_published_agents_impl.return_value = [
        {"agent_id": 1, "name": "test_agent", "description": "Test agent"}
    ]
    runtime_proxy_mod.forward_agent_run.reset_mock(side_effect=True)
    runtime_proxy_mod.forward_agent_stop.reset_mock(side_effect=True)
    runtime_proxy_mod.forward_agent_stop.return_value = {"message": "stopped"}
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
        await ns.idempotency_end("nonexistent-key")

    @pytest.mark.asyncio
    async def test_idempotency_expired_key_can_be_reused(self, reset_test_isolation):
        """Test that expired keys can be reused after TTL."""
        await ns.idempotency_start("expire-key", ttl_seconds=1)
        assert "expire-key" in ns._IDEMPOTENCY_RUNNING
        import asyncio
        await asyncio.sleep(1.1)
        await ns.idempotency_start("expire-key", ttl_seconds=1)

    @pytest.mark.asyncio
    async def test_idempotency_uses_redis_when_enabled(self):
        """Test Redis-backed idempotency path."""
        fake_runtime_state = MagicMock()
        fake_runtime_state.enabled = True
        fake_runtime_state.acquire_idempotency_async = AsyncMock(return_value=True)

        with patch.object(ns, "runtime_state_service", fake_runtime_state):
            await ns.idempotency_start("redis-key")

        fake_runtime_state.acquire_idempotency_async.assert_awaited_once_with(
            "redis-key",
            ns.NORTHBOUND_IDEMPOTENCY_TTL_SECONDS,
        )

    @pytest.mark.asyncio
    async def test_idempotency_redis_duplicate_raises(self):
        """Test Redis-backed idempotency rejects duplicate in-flight requests."""
        fake_runtime_state = MagicMock()
        fake_runtime_state.enabled = True
        fake_runtime_state.acquire_idempotency_async = AsyncMock(return_value=False)

        with patch.object(ns, "runtime_state_service", fake_runtime_state):
            with pytest.raises(LimitExceededError, match="Duplicate request"):
                await ns.idempotency_start("redis-key")

    @pytest.mark.asyncio
    async def test_idempotency_redis_error_fails_closed(self):
        """Test Redis errors make idempotency fail closed."""
        fake_runtime_state = MagicMock()
        fake_runtime_state.enabled = True
        fake_runtime_state.acquire_idempotency_async = AsyncMock(side_effect=RuntimeError("redis down"))

        with patch.object(ns, "runtime_state_service", fake_runtime_state):
            with pytest.raises(LimitExceededError, match="Idempotency service is unavailable"):
                await ns.idempotency_start("redis-key")

    @pytest.mark.asyncio
    async def test_idempotency_end_uses_redis_and_swallows_release_error(self, caplog):
        """Test Redis-backed idempotency release path and warning handling."""
        fake_runtime_state = MagicMock()
        fake_runtime_state.enabled = True
        fake_runtime_state.release_idempotency_async = AsyncMock(side_effect=RuntimeError("release failed"))

        with patch.object(ns, "runtime_state_service", fake_runtime_state):
            await ns.idempotency_end("redis-key")

        fake_runtime_state.release_idempotency_async.assert_awaited_once_with("redis-key")
        assert "Northbound idempotency release failed" in caplog.text


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
        for _ in range(ns.NORTHBOUND_RATE_LIMIT_PER_MINUTE):
            await ns.check_and_consume_rate_limit("tenant-limit")
        with pytest.raises(LimitExceededError):
            await ns.check_and_consume_rate_limit("tenant-limit")

    @pytest.mark.asyncio
    async def test_rate_limit_uses_redis_when_enabled(self):
        """Test Redis-backed rate limit path."""
        fake_runtime_state = MagicMock()
        fake_runtime_state.enabled = True
        fake_runtime_state.consume_rate_limit_async = AsyncMock(return_value=1)

        with patch.object(ns, "runtime_state_service", fake_runtime_state):
            await ns.check_and_consume_rate_limit("tenant-redis")

        fake_runtime_state.consume_rate_limit_async.assert_awaited_once_with(
            tenant_id="tenant-redis",
            limit_per_minute=ns.NORTHBOUND_RATE_LIMIT_PER_MINUTE,
        )

    @pytest.mark.asyncio
    async def test_rate_limit_disabled_returns_without_state(self):
        """Test disabled rate limit avoids both Redis and local counters."""
        fake_runtime_state = MagicMock()
        fake_runtime_state.enabled = True
        fake_runtime_state.consume_rate_limit_async = AsyncMock()

        with patch.object(ns, "runtime_state_service", fake_runtime_state), \
                patch.object(ns, "NORTHBOUND_RATE_LIMIT_ENABLED", False):
            await ns.check_and_consume_rate_limit("tenant-disabled")

        fake_runtime_state.consume_rate_limit_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rate_limit_redis_value_error_maps_to_limit_exceeded(self):
        """Test Redis rate-limit over-quota result maps to the API exception."""
        fake_runtime_state = MagicMock()
        fake_runtime_state.enabled = True
        fake_runtime_state.consume_rate_limit_async = AsyncMock(side_effect=ValueError("rate limit exceeded"))

        with patch.object(ns, "runtime_state_service", fake_runtime_state):
            with pytest.raises(LimitExceededError, match="Query rate exceeded"):
                await ns.check_and_consume_rate_limit("tenant-redis")

    @pytest.mark.asyncio
    async def test_rate_limit_redis_error_fails_closed(self):
        """Test Redis errors make rate limiting fail closed."""
        fake_runtime_state = MagicMock()
        fake_runtime_state.enabled = True
        fake_runtime_state.consume_rate_limit_async = AsyncMock(side_effect=RuntimeError("redis down"))

        with patch.object(ns, "runtime_state_service", fake_runtime_state):
            with pytest.raises(LimitExceededError, match="Rate limit service is unavailable"):
                await ns.check_and_consume_rate_limit("tenant-redis")

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
        old_bucket = str(int(ns._now_seconds() // 60) - 1)
        ns._RATE_STATE["tenant-cleanup"] = {old_bucket: 50}

        await ns.check_and_consume_rate_limit("tenant-cleanup")

        current_bucket = ns._minute_bucket()
        assert old_bucket not in ns._RATE_STATE["tenant-cleanup"]
        assert ns._RATE_STATE["tenant-cleanup"].get(current_bucket, 0) == 1


@pytest.mark.asyncio
class TestStartStreamingChat:
    """Tests for start_streaming_chat function."""

    async def test_start_streaming_chat_rejects_invalid_metadata(self):
        """Non-object runtime metadata must be rejected with HTTP 422."""
        ctx = MockNorthboundContext(token_id=0)

        with pytest.raises(AppException) as exc_info:
            await ns.start_streaming_chat(
                ctx=ctx,
                conversation_id=None,
                agent_name="test_agent",
                query="test query",
                metadata=["not", "an", "object"],
            )

        assert exc_info.value.error_code == ErrorCode.CHAT_METADATA_INVALID
        assert exc_info.value.details == {"reason": "INVALID_METADATA_TYPE"}

    async def test_start_streaming_chat_oversized_metadata_returns_413(self):
        """METADATA_TOO_LARGE validation failures map to HTTP 413."""
        ctx = MockNorthboundContext(token_id=0)

        with patch.object(
            ns,
            "validate_runtime_metadata",
            side_effect=RuntimeMetadataValidationError(
                RuntimeMetadataValidationCode.METADATA_TOO_LARGE,
                "too large",
            ),
        ):
            with pytest.raises(AppException) as exc_info:
                await ns.start_streaming_chat(
                    ctx=ctx,
                    conversation_id=None,
                    agent_name="test_agent",
                    query="test query",
                    metadata={"payload": "x"},
                )

        assert exc_info.value.error_code == ErrorCode.CHAT_METADATA_TOO_LARGE
        assert exc_info.value.details == {"reason": "METADATA_TOO_LARGE"}

    async def test_start_streaming_chat_creates_conversation(self):
        """Test that new conversation is created when conversation_id is None."""
        ctx = MockNorthboundContext(token_id=0)

        mock_response = MagicMock()
        mock_response.headers = {}

        async def response_chunks():
            yield b"data: {\"type\": \"final_answer\", \"content\": \"ok\"}\n\n"

        mock_response.body_iterator = response_chunks()
        runtime_proxy_mod.forward_agent_run.return_value = mock_response

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

            conv_mgmt_mod.create_new_conversation.assert_called_once_with(
                title="New Conversation",
                user_id=ctx.user_id,
                agent_id=1,
            )

            chunks = [chunk async for chunk in mock_response.body_iterator]
            assert b'"type": "conversation_created"' in chunks[0]
            assert b'"conversation_id": 123' in chunks[0]
            assert chunks[1].startswith(b"data: {\"type\": \"final_answer\"")

    async def test_start_streaming_chat_allows_unpublished_agent(self):
        """Use the resolved agent ID even when it has no published version."""
        ctx = MockNorthboundContext(token_id=0)
        conv_mgmt_mod.create_new_conversation.reset_mock()
        mock_response = MagicMock()
        mock_response.headers = {}
        runtime_proxy_mod.forward_agent_run.return_value = mock_response

        with patch.object(ns, "check_and_consume_rate_limit", new_callable=AsyncMock), \
                patch.object(ns, "idempotency_start", new_callable=AsyncMock), \
                patch.object(ns, "get_conversation_history_internal", new_callable=AsyncMock) as mock_history, \
                patch.object(
                    ns,
                    "get_agent_by_name_impl",
                    return_value={"agent_id": 99, "latest_version_no": None},
                ):
            mock_history.return_value = {"data": {"history": []}}

            await ns.start_streaming_chat(
                ctx=ctx,
                conversation_id=None,
                agent_name="draft_agent",
                query="test query",
            )

        conv_mgmt_mod.create_new_conversation.assert_called_once_with(
            title="New Conversation",
            user_id=ctx.user_id,
            agent_id=99,
        )
        forwarded_request = runtime_proxy_mod.forward_agent_run.call_args.kwargs[
            "agent_request"
        ]
        assert forwarded_request.version_no is None

    async def test_start_streaming_chat_logs_token_usage(self):
        """Test that token usage is logged when token_id > 0."""
        ctx = MockNorthboundContext(token_id=1)

        mock_response = MagicMock()
        mock_response.headers = {}
        runtime_proxy_mod.forward_agent_run.return_value = mock_response

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
        runtime_proxy_mod.forward_agent_run.return_value = mock_response

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
        runtime_proxy_mod.forward_agent_run.return_value = mock_response

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
        runtime_proxy_mod.forward_agent_run.return_value = mock_response

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
            forwarded_request = runtime_proxy_mod.forward_agent_run.call_args.kwargs[
                "agent_request"
            ]
            assert forwarded_request.minio_files == [{"name": "file.txt"}]

    async def test_start_streaming_chat_with_model_id_override(self):
        """Test that model_id is passed through to AgentRequest to override the agent's default model."""
        ctx = MockNorthboundContext(token_id=0)
        override_model_id = 42

        mock_response = MagicMock()
        mock_response.headers = {}
        runtime_proxy_mod.forward_agent_run.return_value = mock_response

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
            call_kwargs = runtime_proxy_mod.forward_agent_run.call_args.kwargs
            agent_request = call_kwargs.get("agent_request")
            assert agent_request is not None
            assert getattr(agent_request, "model_id", None) == override_model_id
            assert call_kwargs["user_id"] == ctx.user_id
            assert call_kwargs["tenant_id"] == ctx.tenant_id

    async def test_start_streaming_chat_model_id_null_uses_agent_default(self):
        """Test that omitting model_id results in None, preserving agent's default model."""
        ctx = MockNorthboundContext(token_id=0)

        mock_response = MagicMock()
        mock_response.headers = {}
        runtime_proxy_mod.forward_agent_run.return_value = mock_response

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

            call_kwargs = runtime_proxy_mod.forward_agent_run.call_args.kwargs
            agent_request = call_kwargs.get("agent_request")
            assert agent_request is not None
            assert getattr(agent_request, "model_id", None) is None

    async def test_start_streaming_chat_with_model_id_and_attachments(self):
        """Test streaming chat with both model_id override and attachments."""
        ctx = MockNorthboundContext(token_id=0)
        attachments = ["s3://bucket/file.txt"]

        mock_response = MagicMock()
        mock_response.headers = {}
        runtime_proxy_mod.forward_agent_run.return_value = mock_response

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
            call_kwargs = runtime_proxy_mod.forward_agent_run.call_args.kwargs
            agent_request = call_kwargs.get("agent_request")
            assert agent_request is not None
            assert getattr(agent_request, "model_id", None) == 99

    async def test_start_streaming_chat_sets_conversation_id_header(self):
        """Test that streaming response sets conversation_id via headers only (no SSE trailer)."""
        ctx = MockNorthboundContext(token_id=0)

        async def _body_iterator():
            yield b"data: hello\n\n"

        mock_response = MagicMock()
        mock_response.headers = {"x-existing": "1"}
        mock_response.media_type = "text/event-stream"
        mock_response.body_iterator = _body_iterator()
        runtime_proxy_mod.forward_agent_run.return_value = mock_response

        with patch.object(ns, "check_and_consume_rate_limit", new_callable=AsyncMock), \
                patch.object(ns, "idempotency_start", new_callable=AsyncMock), \
                patch.object(ns, "get_conversation_history_internal", new_callable=AsyncMock) as mock_history:
            mock_history.return_value = {"data": {"history": []}}

            response = await ns.start_streaming_chat(
                ctx=ctx,
                conversation_id=123,
                agent_name="test_agent",
                query="test query",
            )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        # Stream body is passed through unchanged; conversation_id is only in headers
        assert chunks == [b"data: hello\n\n"]
        assert response.headers["conversation_id"] == "123"
        assert response.headers["X-Request-Id"] == ctx.request_id
        assert response.headers["X-Accel-Buffering"] == "no"
        assert response.headers["x-existing"] == "1"


@pytest.mark.asyncio
class TestStopChat:
    """Tests for stop_chat function."""

    async def test_stop_chat_success(self):
        """Test successful stop chat."""
        ctx = MockNorthboundContext(token_id=1)
        runtime_proxy_mod.forward_agent_stop.return_value = {"message": "stopped"}

        result = await ns.stop_chat(ctx=ctx, conversation_id=123)

        assert result["message"] == "stopped"
        assert result["data"] == 123

    async def test_stop_chat_logs_token_usage(self):
        """Test that token usage is logged when token_id > 0."""
        ctx = MockNorthboundContext(token_id=1)
        token_db_mod.log_token_usage.reset_mock()

        await ns.stop_chat(ctx=ctx, conversation_id=123, meta_data={"test": "data"})

        token_db_mod.log_token_usage.assert_called_once_with(
            token_id=1,
            call_function_name="stop_chat_stream",
            related_id=123,
            created_by=ctx.user_id,
            metadata={"test": "data"},
        )

    async def test_stop_chat_no_token_id_no_logging(self):
        """Test that token usage is not logged when token_id is 0."""
        ctx = MockNorthboundContext(token_id=0)
        token_db_mod.log_token_usage.reset_mock()

        await ns.stop_chat(ctx=ctx, conversation_id=123)

        token_db_mod.log_token_usage.assert_not_called()

    @pytest.mark.parametrize(
        "runtime_error",
        [
            RuntimeServiceTimeoutError("timed out"),
            RuntimeServiceUnavailableError("unavailable"),
            RuntimeUpstreamError("upstream error"),
        ],
    )
    async def test_stop_chat_preserves_runtime_errors(self, runtime_error):
        ctx = MockNorthboundContext(token_id=0)
        runtime_proxy_mod.forward_agent_stop.side_effect = runtime_error

        with pytest.raises(type(runtime_error)) as exc_info:
            await ns.stop_chat(ctx=ctx, conversation_id=123)

        assert exc_info.value is runtime_error


@pytest.mark.asyncio
class TestListConversations:
    """Tests for list_conversations function."""

    async def test_list_conversations_success(self):
        """Test successful conversation listing."""
        ctx = MockNorthboundContext(token_id=0)

        result = await ns.list_conversations(ctx=ctx)

        assert result["message"] == "success"
        assert "data" in result

    async def test_list_conversations_does_not_fetch_metadata(self):
        """Test that listing conversations does not fetch usage metadata."""
        ctx = MockNorthboundContext(token_id=1)
        token_db_mod.get_latest_usage_metadata.reset_mock(side_effect=True)

        result = await ns.list_conversations(ctx=ctx)

        token_db_mod.get_latest_usage_metadata.assert_not_called()
        assert result["message"] == "success"


@pytest.mark.asyncio
class TestNorthboundModelAndGeneratedTitleServices:
    async def test_list_configured_models_uses_context_tenant(self):
        ctx = MockNorthboundContext(tenant_id="tenant-models")
        models = [{"model_id": 7, "display_name": "Main model"}]
        model_mgmt_mod.list_models_for_tenant.reset_mock(side_effect=True)
        model_mgmt_mod.list_models_for_tenant.return_value = models

        result = await ns.list_configured_models(ctx)

        assert result == {
            "message": "success",
            "data": models,
            "requestId": "req-123",
        }
        model_mgmt_mod.list_models_for_tenant.assert_awaited_once_with("tenant-models")

    async def test_generate_conversation_title_uses_context_identity(self):
        ctx = MockNorthboundContext(user_id="user-title", tenant_id="tenant-title")
        conv_mgmt_mod.generate_conversation_title_service.reset_mock(side_effect=True)
        conv_mgmt_mod.generate_conversation_title_service.return_value = "Generated title"

        result = await ns.generate_conversation_title(
            ctx=ctx,
            conversation_id=42,
            question="Summarize this conversation",
            language="en",
        )

        assert result == {
            "message": "success",
            "data": "Generated title",
            "requestId": "req-123",
        }
        conv_mgmt_mod.generate_conversation_title_service.assert_awaited_once_with(
            conversation_id=42,
            question="Summarize this conversation",
            user_id="user-title",
            tenant_id="tenant-title",
            language="en",
        )


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

    async def test_get_conversation_history_internal_minio_files_as_json_string(self):
        """Test that minio_files stored as a JSON string is parsed back into a list.

        Covers the json.loads branch of the try/except at lines 540-542.
        """
        ctx = MockNorthboundContext(token_id=0)
        conversation_db_mod.get_conversation_messages.return_value = [
            {
                "message_id": 1,
                "message_role": "user",
                "message_content": "with attachment",
                "minio_files": '[{"name": "a.txt"}, {"name": "b.png"}]',
            }
        ]

        result = await ns.get_conversation_history_internal(ctx=ctx, conversation_id=123)

        history = result["data"]["history"]
        assert history[0]["minio_files"] == [{"name": "a.txt"}, {"name": "b.png"}]

    async def test_get_conversation_history_internal_minio_files_already_parsed(self):
        """Test that minio_files already deserialized (list) is passed through unchanged.

        Covers the non-string branch (isinstance(raw_minio_files, str) == False)
        of the conditional at line 541.
        """
        ctx = MockNorthboundContext(token_id=0)
        minio_files_value = [{"name": "a.txt"}]
        conversation_db_mod.get_conversation_messages.return_value = [
            {
                "message_id": 1,
                "message_role": "user",
                "message_content": "with attachment",
                "minio_files": minio_files_value,
            }
        ]

        result = await ns.get_conversation_history_internal(ctx=ctx, conversation_id=123)

        history = result["data"]["history"]
        assert history[0]["minio_files"] is minio_files_value

    async def test_get_conversation_history_internal_minio_files_invalid_json(self):
        """Test that an invalid JSON minio_files string falls back to empty list and logs warning.

        Covers the JSONDecodeError branch of the except clause at line 542.
        """
        ctx = MockNorthboundContext(token_id=0)
        conversation_db_mod.get_conversation_messages.return_value = [
            {
                "message_id": 7,
                "message_role": "user",
                "message_content": "corrupt attachment metadata",
                "minio_files": "not valid json {",
            }
        ]

        with patch.object(ns.logger, "warning") as mock_warn:
            result = await ns.get_conversation_history_internal(ctx=ctx, conversation_id=123)

        history = result["data"]["history"]
        assert history[0]["minio_files"] == []
        mock_warn.assert_called_once()
        # First positional arg is the format string; the message_id (7) is the second arg
        assert mock_warn.call_args.args[0] == "Failed to parse minio_files for message %s"
        assert mock_warn.call_args.args[1] == 7


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

    async def test_get_agent_info_by_name_success(self):
        """Test exact-name lookup returns one published agent without its internal ID."""
        ctx = MockNorthboundContext(tenant_id="asset-owner-tenant", token_id=0)
        agent_version_mod.list_published_agents_impl.return_value = [
            {"agent_id": 42, "name": "target_agent", "description": "Target"},
            {"agent_id": 43, "name": "other_agent", "description": "Other"},
        ]

        result = await ns.get_agent_info_by_name_for_northbound(ctx, "target_agent")

        assert result["message"] == "success"
        assert result["data"]["name"] == "target_agent"
        assert "agent_id" not in result["data"]

    async def test_get_agent_info_by_name_not_found(self):
        """Test lookup rejects unpublished or unavailable agent names."""
        ctx = MockNorthboundContext(tenant_id="asset-owner-tenant", token_id=0)
        agent_version_mod.list_published_agents_impl.return_value = []

        with pytest.raises(LookupError, match="Published agent not found"):
            await ns.get_agent_info_by_name_for_northbound(ctx, "missing_agent")

    async def test_get_agent_info_by_name_empty(self):
        """Test that empty/whitespace agent_name raises ValueError."""
        ctx = MockNorthboundContext(tenant_id="asset-owner-tenant", token_id=0)

        with pytest.raises(ValueError, match="agent_name is required"):
            await ns.get_agent_info_by_name_for_northbound(ctx, "   ")

    async def test_get_agent_info_by_name_internal_error(self):
        """Test that internal errors from _get_visible_published_agents are wrapped."""
        ctx = MockNorthboundContext(tenant_id="asset-owner-tenant", token_id=0)
        agent_version_mod.list_published_agents_impl.side_effect = RuntimeError("DB connection lost")

        with pytest.raises(Exception, match="Failed to get agent info for agent_name"):
            await ns.get_agent_info_by_name_for_northbound(ctx, "any_agent")

    async def test_get_agent_knowledge_bases_returns_accessible_local_indices(self):
        ctx = MockNorthboundContext(tenant_id="tenant-1", user_id="user-1")
        agent_version_mod.list_published_agents_impl.return_value = [
            {
                "agent_id": 42,
                "tenant_id": "tenant-1",
                "name": "local_agent",
                "current_version_no": 3,
            }
        ]
        knowledge_scope_service_mod.get_agent_knowledge_capabilities.return_value = {
            "sources": {
                "local": {
                    "enabled": True,
                    "max_select": 50,
                    "default_range_values": ["allowed-index"],
                },
                "aidp": {
                    "enabled": False,
                    "max_select": 10,
                    "default_range_values": [],
                },
            }
        }
        knowledge_db_mod.get_knowledge_info_by_tenant_id.return_value = [
            {
                "knowledge_id": 7,
                "index_name": "allowed-index",
                "knowledge_name": "Allowed KB",
                "knowledge_sources": "elasticsearch",
                "embedding_model_name": "bge-m3",
                "embedding_model_id": 9,
            },
            {
                "knowledge_id": 8,
                "index_name": "denied-index",
                "knowledge_name": "Denied KB",
                "knowledge_sources": "elasticsearch",
            },
        ]
        ns.ElasticSearchService.filter_accessible_indices.return_value = [
            "allowed-index"
        ]

        result = await ns.get_agent_knowledge_bases_for_northbound(
            ctx, "local_agent"
        )

        assert result["data"]["source"] == "local"
        assert result["data"]["tool_name"] == "KnowledgeBaseSearchTool"
        assert result["data"]["range_parameter"] == "index_names"
        assert result["data"]["default_selected_ids"] == ["allowed-index"]
        assert result["data"]["knowledge_bases"] == [{
            "id": "allowed-index",
            "knowledge_id": "7",
            "name": "Allowed KB",
            "embedding_model": "bge-m3",
            "embedding_model_id": 9,
            "is_multimodal": False,
        }]

    async def test_get_agent_knowledge_bases_rejects_source_conflict(self):
        ctx = MockNorthboundContext(tenant_id="tenant-1", user_id="user-1")
        agent_version_mod.list_published_agents_impl.return_value = [
            {
                "agent_id": 42,
                "tenant_id": "tenant-1",
                "name": "conflicting_agent",
                "current_version_no": 3,
            }
        ]
        knowledge_scope_service_mod.get_agent_knowledge_capabilities.return_value = {
            "sources": {
                "local": {"enabled": True},
                "aidp": {"enabled": True},
            }
        }

        with pytest.raises(ValueError, match="both local and AIDP"):
            await ns.get_agent_knowledge_bases_for_northbound(
                ctx, "conflicting_agent"
            )

    async def test_get_agent_knowledge_bases_returns_accessible_aidp_items(self):
        ctx = MockNorthboundContext(tenant_id="tenant-1", user_id="user-1")
        agent_version_mod.list_published_agents_impl.return_value = [{
            "agent_id": 42,
            "name": "aidp_agent",
            "current_version_no": 3,
        }]
        knowledge_scope_service_mod.get_agent_knowledge_capabilities.return_value = {
            "sources": {
                "local": {
                    "enabled": False,
                    "max_select": 50,
                    "default_range_values": [],
                },
                "aidp": {
                    "enabled": True,
                    "max_select": 10,
                    "default_range_values": ["kds-1"],
                },
            }
        }
        permission_service = types.ModuleType(
            "ext_components.aidp.services.aidp_permission_service"
        )
        permission_service.intersect_accessible_kbs = MagicMock(return_value=[{
            "kb_id": "kds-1",
            "kds_name": "Fallback name",
            "resource_status": "ACTIVE",
        }])
        aidp_service = types.ModuleType(
            "ext_components.aidp.services.aidp_service"
        )
        aidp_service.get_aidp_kb_impl = MagicMock(return_value={
            "kds_name": "Policies",
            "document_count": 2,
            "chunk_count": 12,
            "caption_enable": 1,
        })
        aidp_service.fetch_all_aidp_knowledge_bases_impl = MagicMock(return_value={
            "value": [{"kds_id": "kds-1"}],
            "total_count": 1,
            "next_link": None,
        })
        aidp_access_service = types.ModuleType(
            "ext_components.aidp.services.aidp_access_service"
        )
        aidp_access_service.resolve_current_aidp_access = MagicMock(
            return_value=types.SimpleNamespace(
                accessible_rows=[{
                    "kb_id": "kds-1",
                    "kds_name": "Fallback name",
                    "resource_status": "ACTIVE",
                }]
            )
        )
        services_module = types.ModuleType("ext_components.aidp.services")
        services_module.aidp_permission_service = permission_service
        aidp_module = types.ModuleType("ext_components.aidp")
        aidp_module.services = services_module
        ext_components_module = types.ModuleType("ext_components")
        ext_components_module.aidp = aidp_module

        with patch.dict(sys.modules, {
            "ext_components": ext_components_module,
            "ext_components.aidp": aidp_module,
            "ext_components.aidp.services": services_module,
            "ext_components.aidp.services.aidp_permission_service": permission_service,
            "ext_components.aidp.services.aidp_service": aidp_service,
            "ext_components.aidp.services.aidp_access_service": aidp_access_service,
        }):
            result = await ns.get_agent_knowledge_bases_for_northbound(
                ctx, "aidp_agent"
            )

        assert result["data"]["source"] == "aidp"
        assert result["data"]["range_parameter"] == "kds_list"
        assert result["data"]["default_selected_ids"] == ["kds-1"]
        assert result["data"]["knowledge_bases"] == [{
            "id": "kds-1",
            "name": "Policies",
            "document_count": 2,
            "chunk_count": 12,
            "is_multimodal": True,
            "resource_status": "ACTIVE",
        }]
        aidp_service.get_aidp_kb_impl.assert_called_once_with(
            "https://aidp.example",
            "test-aidp-api-key",
            "kds-1",
        )
        aidp_access_service.resolve_current_aidp_access.assert_called_once_with(
            server_url="https://aidp.example",
            api_key="test-aidp-api-key",
            user_id="user-1",
            tenant_id="tenant-1",
            aidp_tenant_id="aidp",
        )


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

        token_db_mod.log_token_usage.assert_called_once_with(
            token_id=1,
            call_function_name="update_conversation_title",
            related_id=123,
            created_by=ctx.user_id,
            metadata={"source": "api"},
        )

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


    async def test_start_streaming_chat_save_message_error(self):
        """Test that save_conversation_user error is wrapped properly."""
        ctx = MockNorthboundContext(token_id=0)

        mock_response = MagicMock()
        mock_response.headers = {}
        runtime_proxy_mod.forward_agent_run.return_value = mock_response

        async def mock_get_history(*args, **kwargs):
            return {"data": {"history": []}}

        with patch.object(ns, 'check_and_consume_rate_limit', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_start', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_end', new_callable=AsyncMock), \
                patch.object(ns, 'get_conversation_history_internal', side_effect=mock_get_history), \
                patch('backend.services.northbound_service.asyncio.to_thread', side_effect=Exception("DB error")):
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
        runtime_proxy_mod.forward_agent_run.return_value = mock_response
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

    async def test_start_streaming_chat_passes_version_no_to_agent_request(self, mocker):
        """Test that latest_version_no from get_agent_by_name_impl is passed as version_no in AgentRequest.

        PR 3498 changed the flow to use get_agent_by_name_impl (which returns agent_id + latest_version_no)
        and pass latest_version_no as version_no in AgentRequest, instead of using get_agent_id_by_name
        which only returned the agent_id (defaulting to draft version_no=0).
        """
        ctx = MockNorthboundContext(token_id=0)

        mock_response = MagicMock()
        mock_response.headers = {}

        async def mock_get_history(*args, **kwargs):
            return {"data": {"history": []}}

        with patch.object(ns, 'check_and_consume_rate_limit', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_start', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_end', new_callable=AsyncMock), \
                patch.object(ns, 'get_conversation_history_internal', side_effect=mock_get_history), \
                patch.object(ns, 'get_agent_by_name_impl', return_value={
                    "agent_id": 42,
                    "latest_version_no": 5
                }), \
                patch.object(ns, 'save_conversation_user', side_effect=lambda *args: None), \
                patch.object(ns, 'forward_agent_run', new_callable=AsyncMock, return_value=mock_response) as mock_stream:
            conv_mgmt_mod.save_conversation_user.reset_mock()

            await ns.start_streaming_chat(
                ctx=ctx,
                conversation_id=123,
                agent_name="test_agent",
                query="test query"
            )

            mock_stream.assert_called_once()
            call_kwargs = mock_stream.call_args.kwargs
            assert call_kwargs["agent_request"].version_no == 5
            assert call_kwargs["agent_request"].agent_id == 42

    async def test_start_streaming_chat_save_conversation_user_via_asyncio_to_thread(self, mocker):
        """Test that save_conversation_user is called via asyncio.to_thread (PR 3498 change).

        PR 3498 changed save_conversation_user from a direct synchronous call to
        asyncio.to_thread(save_conversation_user, ...) to avoid blocking the event loop
        while preserving synchronous commit semantics.
        """
        import asyncio as async_lib
        ctx = MockNorthboundContext(token_id=0)

        mock_response = MagicMock()
        mock_response.headers = {}
        runtime_proxy_mod.forward_agent_run.return_value = mock_response

        async def mock_get_history(*args, **kwargs):
            return {"data": {"history": []}}

        async def mock_to_thread(func, *args):
            func(*args)
            return None

        with patch.object(ns, 'check_and_consume_rate_limit', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_start', new_callable=AsyncMock), \
                patch.object(ns, 'idempotency_end', new_callable=AsyncMock), \
                patch.object(ns, 'get_conversation_history_internal', side_effect=mock_get_history), \
                patch.object(ns, 'save_conversation_user') as mock_save, \
                patch('backend.services.northbound_service.asyncio.to_thread', side_effect=mock_to_thread):
            mock_save.reset_mock()

            await ns.start_streaming_chat(
                ctx=ctx,
                conversation_id=123,
                agent_name="test_agent",
                query="test query"
            )

            assert mock_save.call_count == 1

    async def test_start_streaming_chat_get_agent_by_name_impl_error_wrapped(self):
        """Test that get_agent_by_name_impl error is wrapped by outer exception handler.

        Since get_agent_by_name_impl is synchronous, its exception is caught by
        the outer except Exception and re-raised as "Failed to start streaming chat...".
        """
        ctx = MockNorthboundContext(token_id=0)

        async def mock_get_history(*args, **kwargs):
            return {"data": {"history": []}}

        with patch.object(ns, 'check_and_consume_rate_limit', new_callable=AsyncMock), \
                patch.object(ns, 'get_conversation_history_internal', side_effect=mock_get_history), \
                patch.object(ns, 'get_agent_by_name_impl', side_effect=Exception("Agent not found")):
            with pytest.raises(Exception) as exc_info:
                await ns.start_streaming_chat(
                    ctx=ctx,
                    conversation_id=123,
                    agent_name="nonexistent_agent",
                    query="test query"
                )
            assert "Agent not found" in str(exc_info.value)


class TestStopChatErrorHandling:
    """Tests for error handling in stop_chat function."""

    async def test_stop_chat_error(self):
        """Test that errors in stop_chat are wrapped properly."""
        ctx = MockNorthboundContext(token_id=0)
        runtime_proxy_mod.forward_agent_stop.side_effect = Exception("Stop failed")

        with pytest.raises(Exception) as exc_info:
            await ns.stop_chat(ctx=ctx, conversation_id=123)
        assert "Failed to stop chat" in str(exc_info.value)

    async def test_stop_chat_token_logging_failure(self):
        """Test that token logging failure is handled gracefully."""
        ctx = MockNorthboundContext(token_id=1)
        token_db_mod.log_token_usage.side_effect = Exception("Logging failed")

        with patch(
            "backend.services.northbound_service.forward_agent_stop",
            new_callable=AsyncMock,
            return_value={"message": "stopped"},
        ):
            # Should not raise even if token logging fails
            result = await ns.stop_chat(ctx=ctx, conversation_id=123, meta_data={"key": "value"})
            assert result is not None


class TestListConversationsErrorHandling:
    """Tests for list_conversations behavior with conversation metadata."""

    async def test_list_conversations_preserves_empty_metadata(self):
        """Test that conversation metadata returned by the service is preserved."""
        ctx = MockNorthboundContext(token_id=1)
        conversations = [
            {"conversation_id": "1", "title": "Test", "meta_data": {}}
        ]
        conversation_db_mod.get_conversation_list.return_value = conversations
        token_db_mod.get_latest_usage_metadata.reset_mock(side_effect=True)

        result = await ns.list_conversations(ctx=ctx)

        assert result["data"] == conversations
        assert result["data"][0]["meta_data"] == {}
        token_db_mod.get_latest_usage_metadata.assert_not_called()

    async def test_list_conversations_preserves_metadata_without_usage_lookup(self):
        """Test that listing does not add or remove conversation metadata."""
        ctx = MockNorthboundContext(token_id=1)
        conversations = [
            {"conversation_id": "1", "title": "Test", "meta_data": {"query": "stored query"}}
        ]
        conversation_db_mod.get_conversation_list.return_value = conversations
        token_db_mod.get_latest_usage_metadata.reset_mock(side_effect=True)

        result = await ns.list_conversations(ctx=ctx)

        assert result["data"] == conversations
        token_db_mod.get_latest_usage_metadata.assert_not_called()

    async def test_list_conversations_does_not_add_metadata_from_usage_record(self):
        """Test that usage metadata is not injected into conversation items."""
        ctx = MockNorthboundContext(token_id=1)
        conversations = [{"conversation_id": "1", "title": "Test"}]
        conversation_db_mod.get_conversation_list.return_value = conversations
        token_db_mod.get_latest_usage_metadata.reset_mock(side_effect=True)
        token_db_mod.get_latest_usage_metadata.return_value = {"query": "test query"}

        result = await ns.list_conversations(ctx=ctx)

        assert result["data"] == conversations
        assert "meta_data" not in result["data"][0]
        token_db_mod.get_latest_usage_metadata.assert_not_called()


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
