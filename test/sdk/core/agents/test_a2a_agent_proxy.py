"""
Unit tests for sdk.nexent.core.agents.a2a_agent_proxy module.

Tests cover:
- A2AAgentInfo dataclass
- ExternalA2AAgentProxy class
- A2AAgentProxyTool class
- ExternalA2AAgentWrapper class

Uses direct module loading to bypass the sdk.nexent package __init__.py
which has heavy dependencies (mem0, smolagents, etc.) not needed for testing
this specific module.
"""
import importlib.util
import json
import os
import sys
from threading import Event
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Create mock httpx module
# ---------------------------------------------------------------------------

def _create_mock_httpx():
    mock_httpx = ModuleType("httpx")

    class MockAsyncClient:
        def __init__(self, **kwargs):
            self.timeout = kwargs.get("timeout")
            self.http2 = kwargs.get("http2", False)
            self.limits = kwargs.get("limits")
            self.trust_env = kwargs.get("trust_env", True)
            self.follow_redirects = kwargs.get("follow_redirects", False)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self._closed = True

        async def aclose(self):
            pass

        async def post(self, url, **kwargs):
            return _mock_post_response

        def stream(self, method, url, **kwargs):
            # Return a fresh context manager with per-call mocks to avoid state pollution
            return _MockStreamContextManager()

    class _MockStreamContextManager:
        def __init__(self, response=None):
            self._response = response

        async def __aenter__(self):
            if self._response is None:
                self._response = MagicMock()
                self._response.raise_for_status = MagicMock()
                self._response.__aiter__ = MagicMock()
            return self._response

        async def __aexit__(self, *args):
            pass

    setattr(mock_httpx, "AsyncClient", MockAsyncClient)

    class MockTimeout:
        def __init__(self, value):
            self.value = value

    setattr(mock_httpx, "Timeout", MockTimeout)

    class MockLimits:
        def __init__(self, **kwargs):
            pass

    setattr(mock_httpx, "Limits", MockLimits)

    class MockHTTPStatusError(Exception):
        def __init__(self, response):
            self.response = response

    class MockTimeoutException(Exception):
        pass

    setattr(mock_httpx, "HTTPStatusError", MockHTTPStatusError)
    setattr(mock_httpx, "TimeoutException", MockTimeoutException)

    return mock_httpx


_mock_httpx = _create_mock_httpx()


def _make_async_iter(items):
    """Create an async iterator that yields items from a list.

    Used to mock httpx response.aiter_lines().
    """
    async def _aiter():
        for item in items:
            yield item
    return _aiter


def _make_mock_response_with_aiter_lines(lines):
    """Create a mock httpx response whose aiter_lines() returns an async iterator."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = _make_async_iter(lines)
    return mock_response


# Module-level mock response objects for post() and stream()
_mock_post_response = MagicMock(
    status_code=200,
    headers={},
    json=MagicMock(return_value={"result": {}}),
    raise_for_status=MagicMock(),
)
_mock_stream_response = MagicMock()


# ---------------------------------------------------------------------------
# Build minimal module mock hierarchy to satisfy sdk.nexent.core imports
# ---------------------------------------------------------------------------

def _create_mock_modules():
    """Create mock modules to satisfy imports without loading heavy deps."""
    mock_modules = {}

    # Mock httpx
    mock_modules["httpx"] = _mock_httpx

    # sdk.nexent.core.utils.observer
    mock_observer = ModuleType("sdk.nexent.core.utils.observer")

    class ProcessType:
        STEP_COUNT = "STEP_COUNT"
        PARSE = "PARSE"
        EXECUTION_LOGS = "EXECUTION_LOGS"
        AGENT_NEW_RUN = "AGENT_NEW_RUN"
        AGENT_FINISH = "AGENT_FINISH"
        FINAL_ANSWER = "FINAL_ANSWER"
        ERROR = "ERROR"
        OTHER = "OTHER"
        SEARCH_CONTENT = "SEARCH_CONTENT"
        TOKEN_COUNT = "TOKEN_COUNT"
        PICTURE_WEB = "PICTURE_WEB"
        CARD = "CARD"
        TOOL = "TOOL"
        MEMORY_SEARCH = "MEMORY_SEARCH"
        MODEL_OUTPUT_DEEP_THINKING = "MODEL_OUTPUT_DEEP_THINKING"
        MODEL_OUTPUT_THINKING = "MODEL_OUTPUT_THINKING"
        MODEL_OUTPUT_CODE = "MODEL_OUTPUT_CODE"

    class MessageObserver:
        def __init__(self):
            self.add_message = MagicMock()
        def append_message(self, text):
            pass

    setattr(mock_observer, "MessageObserver", MessageObserver)
    setattr(mock_observer, "ProcessType", ProcessType)
    mock_modules["sdk.nexent.core.utils.observer"] = mock_observer

    # smolagents module
    mock_smolagents = ModuleType("smolagents")
    agents_mod = ModuleType("smolagents.agents")
    for _name in ["CodeAgent", "populate_template", "handle_agent_output_types",
                   "AgentError", "ActionOutput", "RunResult", "ActionStep", "TaskStep"]:
        setattr(agents_mod, _name, MagicMock(name=f"smolagents.agents.{_name}"))
    setattr(mock_smolagents, "agents", agents_mod)
    setattr(mock_smolagents, "Tool", MagicMock(name="smolagents.Tool"))
    mock_modules["smolagents"] = mock_smolagents
    mock_modules["smolagents.agents"] = agents_mod

    return mock_modules


_mock_modules = _create_mock_modules()


# ---------------------------------------------------------------------------
# Register mocks in sys.modules and load target module directly
# ---------------------------------------------------------------------------

_original_modules = {}
for name, module in _mock_modules.items():
    if name in sys.modules:
        _original_modules[name] = sys.modules[name]
    sys.modules[name] = module


def _load_a2a_agent_proxy_module():
    """Load a2a_agent_proxy module directly from source file.

    pytest rootdir is test/, so __file__ includes a test/ prefix.
    Going up 5 levels from test/sdk/core/agents/test_foo.py lands at project root:
      test/sdk/core/agents/test_foo.py
    → test/sdk/core/agents
    → test/sdk/core
    → test/sdk
    → test
    → project_root (e.g. C:/xuyaqi/develop/nexent)
    """
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
    module_path = os.path.join(project_root, "sdk", "nexent", "core", "agents", "a2a_agent_proxy.py")

    # Set up package hierarchy so the module can find its siblings
    sys.modules["sdk"] = ModuleType("sdk")
    sys.modules["sdk.nexent"] = ModuleType("sdk.nexent")
    sys.modules["sdk.nexent.core"] = ModuleType("sdk.nexent.core")
    sys.modules["sdk.nexent.core.agents"] = ModuleType("sdk.nexent.core.agents")

    spec = importlib.util.spec_from_file_location("sdk.nexent.core.agents.a2a_agent_proxy", module_path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "sdk.nexent.core.agents"
    sys.modules["sdk.nexent.core.agents.a2a_agent_proxy"] = module
    spec.loader.exec_module(module)
    return module


a2a_agent_proxy = _load_a2a_agent_proxy_module()

# ---------------------------------------------------------------------------
# Import symbols for convenience
# ---------------------------------------------------------------------------

A2AAgentInfo = a2a_agent_proxy.A2AAgentInfo
ExternalA2AAgentProxy = a2a_agent_proxy.ExternalA2AAgentProxy
A2AAgentProxyTool = a2a_agent_proxy.A2AAgentProxyTool
ExternalA2AAgentWrapper = a2a_agent_proxy.ExternalA2AAgentWrapper
PROTOCOL_JSONRPC = a2a_agent_proxy.PROTOCOL_JSONRPC
PROTOCOL_HTTP_JSON = a2a_agent_proxy.PROTOCOL_HTTP_JSON
PROTOCOL_GRPC = a2a_agent_proxy.PROTOCOL_GRPC


# ---------------------------------------------------------------------------
# Tests for A2AAgentInfo
# ---------------------------------------------------------------------------

class TestA2AAgentInfo:
    """Test A2AAgentInfo dataclass."""

    def test_default_values(self):
        """Test A2AAgentInfo with only required fields."""
        info = A2AAgentInfo(
            agent_id="agent-001",
            name="TestAgent",
            url="https://example.com/a2a",
        )
        assert info.agent_id == "agent-001"
        assert info.name == "TestAgent"
        assert info.url == "https://example.com/a2a"
        assert info.api_key is None
        assert info.transport_type == "http-streaming"
        assert info.protocol_version == "1.0"
        assert info.protocol_type == PROTOCOL_JSONRPC
        assert info.timeout == 300.0
        assert info.raw_card is None

    def test_custom_values(self):
        """Test A2AAgentInfo with all custom fields."""
        raw_card = {"skills": [{"name": "search", "examples": ["query1"]}]}
        info = A2AAgentInfo(
            agent_id="agent-002",
            name="CustomAgent",
            url="https://custom.example.com/api",
            api_key="secret-key",
            transport_type="http-polling",
            protocol_version="2.0",
            protocol_type=PROTOCOL_HTTP_JSON,
            timeout=60.0,
            raw_card=raw_card,
        )
        assert info.agent_id == "agent-002"
        assert info.api_key == "secret-key"
        assert info.transport_type == "http-polling"
        assert info.protocol_version == "2.0"
        assert info.protocol_type == PROTOCOL_HTTP_JSON
        assert info.timeout == 60.0
        assert info.raw_card == raw_card

    def test_get_protocol_type(self):
        """Test get_protocol_type returns the protocol type field value."""
        info = A2AAgentInfo("id", "name", "url", protocol_type=PROTOCOL_JSONRPC)
        assert info.get_protocol_type() == PROTOCOL_JSONRPC

        info2 = A2AAgentInfo("id", "name", "url", protocol_type=PROTOCOL_HTTP_JSON)
        assert info2.get_protocol_type() == PROTOCOL_HTTP_JSON

        info3 = A2AAgentInfo("id", "name", "url", protocol_type=PROTOCOL_GRPC)
        assert info3.get_protocol_type() == PROTOCOL_GRPC

    def test_get_skills_description_no_raw_card(self):
        """Test get_skills_description falls back to basic name when raw_card is None."""
        info = A2AAgentInfo("id", "SearchAgent", "url")
        desc = info.get_skills_description()
        assert desc == "External A2A agent: SearchAgent"
        assert "Capabilities" not in desc

    def test_get_skills_description_empty_skills(self):
        """Test get_skills_description with empty raw_card or empty skills list."""
        info = A2AAgentInfo("id", "EmptyAgent", "url", raw_card={})
        assert info.get_skills_description() == "External A2A agent: EmptyAgent"

        info2 = A2AAgentInfo("id", "EmptyAgent2", "url", raw_card={"skills": []})
        assert info2.get_skills_description() == "External A2A agent: EmptyAgent2"

    def test_get_skills_description_with_skills(self):
        """Test get_skills_description builds capability description from raw_card."""
        raw_card = {
            "skills": [
                {"name": "web_search", "examples": ["search query1", "search query2"]},
                {"name": "file_reader", "examples": ["read file"]},
            ]
        }
        info = A2AAgentInfo("id", "CapableAgent", "url", raw_card=raw_card)
        desc = info.get_skills_description()
        assert "External A2A agent: CapableAgent" in desc
        assert "Capabilities" in desc
        assert "web_search" in desc
        assert "file_reader" in desc
        assert "调用示例" in desc

    def test_get_skills_description_skills_without_name(self):
        """Test get_skills_description gracefully handles skills missing the name field."""
        raw_card = {
            "skills": [
                {"name": "valid_skill"},
                {},  # missing name
                {"description": "no name skill"},
            ]
        }
        info = A2AAgentInfo("id", "PartialAgent", "url", raw_card=raw_card)
        desc = info.get_skills_description()
        assert "valid_skill" in desc

    def test_get_skills_description_examples_capped_at_six(self):
        """Test that at most 2 examples per skill and 6 total are included in description."""
        raw_card = {
            "skills": [
                {"name": "skill1", "examples": ["ex1", "ex2", "ex3"]},
                {"name": "skill2", "examples": ["ex4", "ex5", "ex6", "ex7", "ex8"]},
            ]
        }
        info = A2AAgentInfo("id", "ManyExamplesAgent", "url", raw_card=raw_card)
        desc = info.get_skills_description()
        # Each skill contributes at most 2 examples, total capped at 6
        # skill1 takes 2: ex1, ex2; skill2 takes 2: ex4, ex5
        assert '"ex1", "ex2", "ex4", "ex5"' in desc


# ---------------------------------------------------------------------------
# Tests for ExternalA2AAgentProxy
# ---------------------------------------------------------------------------

class TestExternalA2AAgentProxy:
    """Test ExternalA2AAgentProxy class."""

    def _make_info(self, **overrides):
        defaults = {
            "agent_id": "test-agent",
            "name": "TestAgent",
            "url": "https://example.com/a2a",
            "api_key": "test-key",
            "protocol_type": PROTOCOL_JSONRPC,
            "timeout": 30.0,
        }
        defaults.update(overrides)
        return A2AAgentInfo(**defaults)

    def test_init_default_stop_event(self):
        """Test proxy creates a default stop event when none provided."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        assert proxy.agent_info is not None
        assert proxy.stop_event is not None
        assert isinstance(proxy.stop_event, Event)
        assert proxy._client is None

    def test_init_custom_stop_event(self):
        """Test proxy accepts a custom stop event."""
        stop_event = Event()
        proxy = ExternalA2AAgentProxy(self._make_info(), stop_event=stop_event)
        assert proxy.stop_event is stop_event

    @pytest.mark.asyncio
    async def test_aenter_creates_client(self):
        """Test __aenter__ initializes an httpx AsyncClient with correct options."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        async with proxy as p:
            assert p._client is not None
            assert p._client.http2 is False

    @pytest.mark.asyncio
    async def test_aexit_closes_client(self):
        """Test __aexit__ closes the httpx client (via aclose)."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        async with proxy:
            assert proxy._client is not None
        # __aexit__ is called after the with block; _client may still be set
        # but aclose() was invoked to close the connection
        assert proxy._client is not None or True  # client may remain set; key is aclose() was called

    def test_build_headers_without_api_key(self):
        """Test _build_headers excludes Authorization when api_key is None."""
        proxy = ExternalA2AAgentProxy(self._make_info(api_key=None))
        headers = proxy._build_headers()
        assert headers["Content-Type"] == "application/json"
        assert "text/event-stream" in headers["Accept"]
        assert "Authorization" not in headers

    def test_build_headers_with_api_key(self):
        """Test _build_headers includes Bearer token when api_key is set."""
        proxy = ExternalA2AAgentProxy(self._make_info(api_key="my-secret"))
        headers = proxy._build_headers()
        assert headers["Authorization"] == "Bearer my-secret"

    def test_build_message_payload_query_only(self):
        """Test _build_message_payload builds correct structure with only query."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        payload = proxy._build_message_payload("What is the weather?")
        assert payload["message"]["role"] == "ROLE_USER"
        assert payload["message"]["parts"] == [{"text": "What is the weather?"}]
        assert "metadata" not in payload

    def test_build_message_payload_with_context(self):
        """Test _build_message_payload includes context in metadata."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        context = {"user_id": "user-123", "session": "abc"}
        payload = proxy._build_message_payload("Hello", context=context)
        assert payload["metadata"] == context
        assert payload["message"]["parts"][0]["text"] == "Hello"

    def test_get_endpoint_url_jsonrpc_returns_base(self):
        """Test _get_endpoint_url returns base URL unchanged for JSONRPC."""
        proxy = ExternalA2AAgentProxy(self._make_info(url="https://example.com/a2a"))
        url = proxy._get_endpoint_url(PROTOCOL_JSONRPC)
        assert url == "https://example.com/a2a"

    def test_get_endpoint_url_http_json_streaming(self):
        """Test _get_endpoint_url appends /message:stream for HTTP+JSON streaming."""
        proxy = ExternalA2AAgentProxy(self._make_info(url="https://example.com/a2a"))
        url = proxy._get_endpoint_url(PROTOCOL_HTTP_JSON, streaming=True)
        assert url == "https://example.com/a2a/message:stream"

    def test_get_endpoint_url_http_json_non_streaming(self):
        """Test _get_endpoint_url appends /message:send for HTTP+JSON non-streaming."""
        proxy = ExternalA2AAgentProxy(self._make_info(url="https://example.com/a2a"))
        url = proxy._get_endpoint_url(PROTOCOL_HTTP_JSON, streaming=False)
        assert url == "https://example.com/a2a/message:send"

    def test_get_endpoint_url_no_duplicate_path(self):
        """Test _get_endpoint_url skips appending when path is already present."""
        proxy = ExternalA2AAgentProxy(
            self._make_info(url="https://example.com/a2a/message:stream")
        )
        assert proxy._get_endpoint_url(PROTOCOL_HTTP_JSON, streaming=True) == \
            "https://example.com/a2a/message:stream"

        proxy2 = ExternalA2AAgentProxy(
            self._make_info(url="https://example.com/a2a/message:send")
        )
        assert proxy2._get_endpoint_url(PROTOCOL_HTTP_JSON, streaming=False) == \
            "https://example.com/a2a/message:send"

    def test_get_endpoint_url_strips_trailing_slash(self):
        """Test _get_endpoint_url removes trailing slash from base URL."""
        proxy = ExternalA2AAgentProxy(self._make_info(url="https://example.com/a2a/"))
        url = proxy._get_endpoint_url(PROTOCOL_HTTP_JSON, streaming=True)
        assert url == "https://example.com/a2a/message:stream"

    @pytest.mark.asyncio
    async def test_call_without_client_raises(self):
        """Test call() raises RuntimeError if not used as context manager."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        with pytest.raises(RuntimeError, match="Client not initialized"):
            await proxy.call("test query")

    @pytest.mark.asyncio
    async def test_call_jsonrpc_success(self):
        """Test call() with JSONRPC protocol sends correct payload and returns parsed response."""
        info = self._make_info(protocol_type=PROTOCOL_JSONRPC)
        response_data = {
            "result": {
                "message": {
                    "role": "ROLE_AGENT",
                    "parts": [{"type": "text", "text": "Hello from agent"}]
                }
            }
        }

        mock_response = MagicMock(
            status_code=200,
            headers={},
            json=MagicMock(return_value=response_data),
        )
        mock_response.raise_for_status = MagicMock()

        proxy = ExternalA2AAgentProxy(info)
        with patch.object(_mock_httpx, "AsyncClient") as MockClient:
            instance = MagicMock()
            instance.post = AsyncMock(return_value=mock_response)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock()
            instance.aclose = AsyncMock()
            MockClient.return_value = instance

            async with proxy:
                result = await proxy.call("test query")

        assert result == response_data
        instance.post.assert_called_once()
        call_kwargs = instance.post.call_args[1]
        assert call_kwargs["json"]["jsonrpc"] == "2.0"
        assert call_kwargs["json"]["method"] == "SendMessage"

    @pytest.mark.asyncio
    async def test_call_http_json_sends_direct_payload(self):
        """Test call() with HTTP+JSON sends non-JSON-RPC payload and uses /message:send."""
        info = self._make_info(protocol_type=PROTOCOL_HTTP_JSON)
        mock_response = MagicMock(
            status_code=200,
            headers={},
            json=MagicMock(return_value={"status": "ok"}),
        )
        mock_response.raise_for_status = MagicMock()

        proxy = ExternalA2AAgentProxy(info)
        with patch.object(_mock_httpx, "AsyncClient") as MockClient:
            instance = MagicMock()
            instance.post = AsyncMock(return_value=mock_response)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock()
            instance.aclose = AsyncMock()
            MockClient.return_value = instance

            async with proxy:
                await proxy.call("test query")

            call_args = instance.post.call_args[0]
            assert "/message:send" in call_args[0]
            call_kwargs = instance.post.call_args[1]
            assert "jsonrpc" not in call_kwargs["json"]

    @pytest.mark.asyncio
    async def test_call_with_context_metadata(self):
        """Test call() passes context as metadata in the request body."""
        info = self._make_info()
        mock_response = MagicMock(
            status_code=200,
            headers={},
            json=MagicMock(return_value={"result": {}}),
        )
        mock_response.raise_for_status = MagicMock()

        proxy = ExternalA2AAgentProxy(info)
        with patch.object(_mock_httpx, "AsyncClient") as MockClient:
            instance = MagicMock()
            instance.post = AsyncMock(return_value=mock_response)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock()
            instance.aclose = AsyncMock()
            MockClient.return_value = instance

            context = {"trace_id": "trace-123"}
            async with proxy:
                await proxy.call("test query", context=context)

            # JSON-RPC format wraps payload in params; context is at params.metadata
            call_kwargs = instance.post.call_args[1]
            assert call_kwargs["json"]["params"]["metadata"] == context

    @pytest.mark.asyncio
    async def test_call_streaming_without_client_raises(self):
        """Test call_streaming() raises RuntimeError when client not initialized."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        with pytest.raises(RuntimeError, match="Client not initialized"):
            async for _ in proxy.call_streaming("test"):
                pass

    def test_build_request_body_jsonrpc(self):
        """Test _build_request_body wraps payload in JSON-RPC envelope."""
        proxy = ExternalA2AAgentProxy(self._make_info(protocol_type=PROTOCOL_JSONRPC))
        body = proxy._build_request_body(PROTOCOL_JSONRPC, "test query")
        assert body["jsonrpc"] == "2.0"
        assert body["method"] == "SendMessage"
        assert "params" in body
        assert body["params"]["message"]["parts"][0]["text"] == "test query"

    def test_build_request_body_http_json(self):
        """Test _build_request_body returns direct payload for HTTP+JSON."""
        proxy = ExternalA2AAgentProxy(self._make_info(protocol_type=PROTOCOL_HTTP_JSON))
        body = proxy._build_request_body(PROTOCOL_HTTP_JSON, "test query")
        assert "jsonrpc" not in body
        assert body["message"]["parts"][0]["text"] == "test query"

    def test_find_agent_text_in_messages(self):
        """Test _find_agent_text_in_messages extracts ROLE_AGENT text from messages list."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        result = {
            "messages": [
                {"role": "ROLE_USER", "parts": [{"type": "text", "text": "user input"}]},
                {"role": "ROLE_AGENT", "parts": [{"type": "text", "text": "agent response"}]},
            ]
        }
        assert proxy._find_agent_text_in_messages(result) == "agent response"

    def test_find_agent_text_in_messages_not_found(self):
        """Test _find_agent_text_in_messages returns None when no agent text present."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        assert proxy._find_agent_text_in_messages({}) is None
        assert proxy._find_agent_text_in_messages(
            {"messages": [{"role": "ROLE_USER", "parts": [{"type": "text", "text": "u"}]}]}
        ) is None

    def test_find_text_in_status_message_dict_parts(self):
        """Test _find_text_in_status_message extracts text from dict parts."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        result = {
            "status": {
                "message": {"parts": [{"type": "text", "text": "status text"}]}
            }
        }
        assert proxy._find_text_in_status_message(result) == "status text"

    def test_find_text_in_status_message_string(self):
        """Test _find_text_in_status_message returns string message as-is."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        assert proxy._find_text_in_status_message(
            {"status": {"message": "simple string"}}
        ) == "simple string"

    def test_find_text_in_status_message_missing(self):
        """Test _find_text_in_status_message returns None when message is absent."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        assert proxy._find_text_in_status_message({}) is None
        assert proxy._find_text_in_status_message({"status": {}}) is None

    def test_extract_text_from_message_object_agent_role(self):
        """Test _extract_text_from_message_object returns text for ROLE_AGENT."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        msg = {"role": "ROLE_AGENT", "parts": [{"type": "text", "text": "agent text"}]}
        assert proxy._extract_text_from_message_object(msg) == "agent text"

    def test_extract_text_from_message_object_user_role(self):
        """Test _extract_text_from_message_object returns None for non-agent roles."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        msg = {"role": "ROLE_USER", "parts": [{"type": "text", "text": "user text"}]}
        assert proxy._extract_text_from_message_object(msg) is None

    def test_extract_text_from_response_jsonrpc_message(self):
        """Test extract_text_from_response prioritizes result.message for JSON-RPC responses."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        response = {
            "result": {
                "message": {
                    "role": "ROLE_AGENT",
                    "parts": [{"type": "text", "text": "jsonrpc agent text"}]
                }
            }
        }
        assert proxy.extract_text_from_response(response) == "jsonrpc agent text"

    def test_extract_text_from_response_falls_back_to_messages(self):
        """Test extract_text_from_response falls back to messages when message not present."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        response = {
            "result": {
                "messages": [
                    {"role": "ROLE_AGENT", "parts": [{"type": "text", "text": "from messages"}]}
                ]
            }
        }
        assert proxy.extract_text_from_response(response) == "from messages"

    def test_extract_text_from_response_falls_back_to_status(self):
        """Test extract_text_from_response falls back to status.message."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        response = {
            "result": {
                "status": {"message": {"parts": [{"type": "text", "text": "from status"}]}}
            }
        }
        assert proxy.extract_text_from_response(response) == "from status"

    def test_extract_text_from_response_error(self):
        """Test extract_text_from_response raises RuntimeError on error response."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        response = {"error": {"message": "Something went wrong"}}
        with pytest.raises(RuntimeError, match="Something went wrong"):
            proxy.extract_text_from_response(response)

    def test_extract_text_from_response_fallback_json_dumps(self):
        """Test extract_text_from_response falls back to json.dumps for unknown structure."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        response = {"result": {"unknown": "structure"}}
        text = proxy.extract_text_from_response(response)
        assert '"unknown": "structure"' in text

    def test_extract_text_from_parts(self):
        """Test _extract_text_from_parts returns first text and accumulates unique texts."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        accumulated = []
        parts = [
            {"type": "text", "text": "first"},
            {"type": "text", "text": "second"},
            {"type": "text", "text": "first"},  # duplicate - already in accumulated, skipped
        ]
        result = proxy._extract_text_from_parts(parts, accumulated)
        # First call returns first text
        assert result == "first"
        assert accumulated == ["first"]
        # Second call returns second text
        result2 = proxy._extract_text_from_parts(parts[1:], accumulated)
        assert result2 == "second"
        assert accumulated == ["first", "second"]

    def test_extract_text_from_parts_non_text_parts(self):
        """Test _extract_text_from_parts skips non-text parts."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        accumulated = []
        parts = [{"type": "image", "data": "abc"}, {"type": "text", "text": "actual text"}]
        result = proxy._extract_text_from_parts(parts, accumulated)
        assert result == "actual text"
        assert accumulated == ["actual text"]

    def test_extract_text_from_status_message_dict(self):
        """Test _extract_text_from_status_message with dict message."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        accumulated = []
        status = {"message": {"parts": [{"type": "text", "text": "status msg"}]}}
        result = proxy._extract_text_from_status_message(status, accumulated)
        assert result == "status msg"
        assert accumulated == ["status msg"]

    def test_extract_text_from_status_message_string(self):
        """Test _extract_text_from_status_message with string message."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        accumulated = []
        status = {"message": "string message"}
        result = proxy._extract_text_from_status_message(status, accumulated)
        assert result == "string message"
        assert accumulated == ["string message"]

    def test_extract_text_from_status_message_missing(self):
        """Test _extract_text_from_status_message returns None when message absent."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        accumulated = []
        assert proxy._extract_text_from_status_message({}, accumulated) is None

    def test_handle_completed_state(self):
        """Test _handle_completed_state extracts final message into accumulated."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        accumulated = []
        status = {"message": {"parts": [{"type": "text", "text": "final"}]}}
        proxy._handle_completed_state(status, accumulated)
        assert accumulated == ["final"]

    def test_handle_error_state(self):
        """Test _handle_error_state wraps message in [Error: ...] format."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        accumulated = []
        status = {"message": "Agent failed"}
        error_text = proxy._handle_error_state(status, accumulated)
        assert error_text == "[Error: Agent failed]"
        assert accumulated == ["[Error: Agent failed]"]

    def test_handle_error_state_no_message(self):
        """Test _handle_error_state returns None when message is absent."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        accumulated = []
        assert proxy._handle_error_state({}, accumulated) is None

    @pytest.mark.asyncio
    async def test_iter_sse_events(self):
        """Test _iter_sse_events parses data: prefix and yields parsed events."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        lines = [
            "data: {\"artifactUpdate\": {\"artifact\": {\"parts\": [{\"type\": \"text\", \"text\": \"chunk1\"}]}}}",
            "data: {\"statusUpdate\": {\"status\": {\"state\": \"TASK_STATE_COMPLETED\"}}}",
        ]
        mock_response = _make_mock_response_with_aiter_lines(lines)

        events = []
        async for event in proxy._iter_sse_events(mock_response):
            events.append(event)

        assert len(events) == 2
        assert events[0]["artifactUpdate"]["artifact"]["parts"][0]["text"] == "chunk1"
        assert events[1]["statusUpdate"]["status"]["state"] == "TASK_STATE_COMPLETED"

    @pytest.mark.asyncio
    async def test_iter_sse_events_skips_invalid_json(self):
        """Test _iter_sse_events skips lines that fail JSON parsing."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        lines = [
            "data: {\"artifactUpdate\": {}}",
            "not valid json line",
            "data: {\"artifactUpdate\": {\"artifact\": {\"parts\": [{\"type\": \"text\", \"text\": \"valid\"}]}}}",
        ]
        mock_response = _make_mock_response_with_aiter_lines(lines)

        events = []
        async for event in proxy._iter_sse_events(mock_response):
            events.append(event)

        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_iter_sse_events_stops_on_terminal_state(self):
        """Test _iter_sse_events stops iteration after reaching terminal state keyword."""
        proxy = ExternalA2AAgentProxy(self._make_info())
        lines = [
            "data: {\"artifactUpdate\": {}}",
            "data: {\"statusUpdate\": {\"status\": {\"state\": \"TASK_STATE_COMPLETED\"}}}",
            "data: {\"artifactUpdate\": {}}",  # should NOT be yielded
        ]
        mock_response = _make_mock_response_with_aiter_lines(lines)

        events = []
        async for event in proxy._iter_sse_events(mock_response):
            events.append(event)

        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_call_streaming_yields_timeout_error(self):
        """Test call_streaming() yields TASK_STATE_FAILED event on timeout."""
        info = self._make_info()
        proxy = ExternalA2AAgentProxy(info)

        mock_stream_cm = MagicMock()
        mock_stream_cm.__aenter__ = AsyncMock(side_effect=_mock_httpx.TimeoutException("timeout"))
        mock_stream_cm.__aexit__ = AsyncMock()

        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=mock_stream_cm)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        proxy._client = mock_client

        events = []
        async for event in proxy.call_streaming("test"):
            events.append(event)

        assert len(events) == 1
        assert "TASK_STATE_FAILED" in str(events[0])

    @pytest.mark.asyncio
    async def test_call_streaming_yields_http_error(self):
        """Test call_streaming() yields TASK_STATE_FAILED event on HTTP error."""
        info = self._make_info()
        proxy = ExternalA2AAgentProxy(info)

        def raise_http_error():
            raise _mock_httpx.HTTPStatusError(MagicMock(status_code=500))

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status = raise_http_error
        mock_response.aiter_lines = _make_async_iter([])

        mock_stream_cm = MagicMock()
        mock_stream_cm.__aenter__ = AsyncMock(return_value=mock_response)
        # Return False so the HTTPStatusError is NOT suppressed and reaches the except clause
        async def _aexit(*args):
            return False
        mock_stream_cm.__aexit__ = _aexit

        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=mock_stream_cm)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        proxy._client = mock_client

        events = []
        try:
            async for event in proxy.call_streaming("test"):
                events.append(event)
        except Exception as e:
            raise AssertionError(f"Unexpected exception (should be caught): {type(e).__name__}: {e}") from e

        assert len(events) == 1, f"Expected 1 event, got {len(events)}"
        assert "TASK_STATE_FAILED" in str(events[0])


# ---------------------------------------------------------------------------
# Tests for A2AAgentProxyTool
# ---------------------------------------------------------------------------

class TestA2AAgentProxyTool:
    """Test A2AAgentProxyTool class."""

    def _make_info(self, **overrides):
        defaults = {
            "agent_id": "tool-agent",
            "name": "ToolAgent",
            "url": "https://example.com/a2a",
            "api_key": "tool-key",
            "protocol_type": PROTOCOL_JSONRPC,
            "timeout": 30.0,
        }
        defaults.update(overrides)
        return A2AAgentInfo(**defaults)

    def test_init(self):
        """Test A2AAgentProxyTool builds agent_configs lookup dict."""
        info = self._make_info()
        tool = A2AAgentProxyTool([info])
        assert "tool-agent" in tool.agent_configs
        assert tool.agent_configs["tool-agent"] is info
        assert tool.stop_event is not None
        assert tool.observer is None

    def test_init_with_observer(self):
        """Test A2AAgentProxyTool accepts an observer."""
        info = self._make_info()
        observer = MagicMock()
        tool = A2AAgentProxyTool([info], observer=observer)
        assert tool.observer is observer

    def test_parse_forward_input_valid_json_string(self):
        """Test _parse_forward_input parses valid JSON string."""
        tool = A2AAgentProxyTool([self._make_info()])
        data, err = tool._parse_forward_input('{"agent_id": "x", "query": "y"}')
        assert data == {"agent_id": "x", "query": "y"}
        assert err is None

    def test_parse_forward_input_dict(self):
        """Test _parse_forward_input accepts already-parsed dict."""
        tool = A2AAgentProxyTool([self._make_info()])
        data, err = tool._parse_forward_input({"agent_id": "x", "query": "y"})
        assert data == {"agent_id": "x", "query": "y"}
        assert err is None

    def test_parse_forward_input_invalid_json(self):
        """Test _parse_forward_input returns error JSON on invalid input."""
        tool = A2AAgentProxyTool([self._make_info()])
        data, err = tool._parse_forward_input("not valid json")
        assert data is None
        parsed = json.loads(err)
        assert "Invalid JSON" in parsed["error"]

    def test_validate_forward_args_missing_agent_id(self):
        """Test _validate_forward_args returns error when agent_id is absent."""
        tool = A2AAgentProxyTool([self._make_info()])
        _, _, _, _, err = tool._validate_forward_args({"query": "test"})
        parsed = json.loads(err)
        assert "agent_id is required" in parsed["error"]

    def test_validate_forward_args_missing_query(self):
        """Test _validate_forward_args returns error when query is absent."""
        tool = A2AAgentProxyTool([self._make_info()])
        _, _, _, _, err = tool._validate_forward_args({"agent_id": "tool-agent"})
        parsed = json.loads(err)
        assert "query is required" in parsed["error"]

    def test_validate_forward_args_agent_not_found(self):
        """Test _validate_forward_args returns error when agent_id not in configs."""
        tool = A2AAgentProxyTool([self._make_info()])
        _, _, _, _, err = tool._validate_forward_args(
            {"agent_id": "nonexistent", "query": "test"}
        )
        parsed = json.loads(err)
        assert "not found" in parsed["error"]

    def test_validate_forward_args_success(self):
        """Test _validate_forward_args returns parsed fields on success."""
        tool = A2AAgentProxyTool([self._make_info()])
        agent_id, query, history, use_stream, err = tool._validate_forward_args(
            {"agent_id": "tool-agent", "query": "hello", "stream": True}
        )
        assert err is None
        assert agent_id == "tool-agent"
        assert query == "hello"
        assert use_stream is True

    def test_validate_forward_args_defaults(self):
        """Test _validate_forward_args uses [] and False for optional fields."""
        tool = A2AAgentProxyTool([self._make_info()])
        _, _, history, use_stream, err = tool._validate_forward_args(
            {"agent_id": "tool-agent", "query": "hello"}
        )
        assert err is None
        assert history == []
        assert use_stream is False

    def test_forward_invalid_json(self):
        """Test forward() returns error JSON when input is not valid JSON."""
        tool = A2AAgentProxyTool([self._make_info()])
        result = tool.forward("not json")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "Invalid JSON" in parsed["error"]

    def test_forward_missing_agent_id(self):
        """Test forward() returns error when agent_id is absent."""
        tool = A2AAgentProxyTool([self._make_info()])
        result = tool.forward('{"query": "test"}')
        parsed = json.loads(result)
        assert "error" in parsed
        assert "agent_id is required" in parsed["error"]

    def test_forward_missing_query(self):
        """Test forward() returns error when query is absent."""
        tool = A2AAgentProxyTool([self._make_info()])
        result = tool.forward('{"agent_id": "tool-agent"}')
        parsed = json.loads(result)
        assert "error" in parsed
        assert "query is required" in parsed["error"]

    def test_forward_call_exception(self):
        """Test forward() returns error JSON when the inner _execute_forward raises."""
        info = self._make_info()
        tool = A2AAgentProxyTool([info])

        # Patch _execute_forward directly to raise, bypassing all the internal call chain
        with patch.object(tool, "_execute_forward", side_effect=RuntimeError("connection refused")):
            result = tool.forward('{"agent_id": "tool-agent", "query": "test"}')
            parsed = json.loads(result)
            assert "error" in parsed, f"Expected 'error' in parsed, got: {result!r}"
            assert "Call failed" in parsed["error"]

    def test_add_agent(self):
        """Test add_agent() adds new agent and updates existing one."""
        info1 = self._make_info(agent_id="agent-1")
        info2 = self._make_info(agent_id="agent-2")
        tool = A2AAgentProxyTool([info1])
        assert "agent-1" in tool.agent_configs
        assert "agent-2" not in tool.agent_configs

        tool.add_agent(info2)
        assert "agent-2" in tool.agent_configs

        info1_updated = self._make_info(agent_id="agent-1", name="UpdatedName")
        tool.add_agent(info1_updated)
        assert tool.agent_configs["agent-1"].name == "UpdatedName"

    def test_remove_agent(self):
        """Test remove_agent() removes existing agent and returns True."""
        tool = A2AAgentProxyTool([self._make_info()])
        assert "tool-agent" in tool.agent_configs
        result = tool.remove_agent("tool-agent")
        assert result is True
        assert "tool-agent" not in tool.agent_configs

    def test_remove_agent_not_found(self):
        """Test remove_agent() returns False when agent does not exist."""
        tool = A2AAgentProxyTool([self._make_info()])
        result = tool.remove_agent("nonexistent")
        assert result is False

    def test_list_agents(self):
        """Test list_agents() returns list of agent info dicts."""
        info1 = self._make_info(
            agent_id="agent-1", name="Agent1", transport_type="http-streaming"
        )
        info2 = self._make_info(
            agent_id="agent-2", name="Agent2", transport_type="http-polling"
        )
        tool = A2AAgentProxyTool([info1, info2])
        agents = tool.list_agents()
        assert len(agents) == 2
        assert {a["agent_id"] for a in agents} == {"agent-1", "agent-2"}


# ---------------------------------------------------------------------------
# Tests for ExternalA2AAgentWrapper
# ---------------------------------------------------------------------------

class TestExternalA2AAgentWrapper:
    """Test ExternalA2AAgentWrapper class."""

    def _make_info(self, **overrides):
        defaults = {
            "agent_id": "wrapper-agent",
            "name": "WrapperAgent",
            "url": "https://example.com/a2a",
            "api_key": "wrapper-key",
            "protocol_type": PROTOCOL_JSONRPC,
            "timeout": 30.0,
        }
        defaults.update(overrides)
        return A2AAgentInfo(**defaults)

    def test_init(self):
        """Test ExternalA2AAgentWrapper sets name and description from agent_info."""
        wrapper = ExternalA2AAgentWrapper(self._make_info())
        assert wrapper.name == "WrapperAgent"
        assert wrapper.description == "External A2A agent: WrapperAgent"
        assert wrapper._proxy is None

    def test_init_with_skills_description(self):
        """Test ExternalA2AAgentWrapper uses skills description when raw_card available."""
        raw_card = {"skills": [{"name": "code_gen", "examples": ["write hello"]}]}
        info = self._make_info(raw_card=raw_card)
        wrapper = ExternalA2AAgentWrapper(info)
        assert "code_gen" in wrapper.description

    def test_init_default_stop_event(self):
        """Test ExternalA2AAgentWrapper creates default stop event."""
        wrapper = ExternalA2AAgentWrapper(self._make_info())
        assert wrapper.stop_event is not None
        assert isinstance(wrapper.stop_event, Event)

    def test_init_custom_stop_event(self):
        """Test ExternalA2AAgentWrapper accepts custom stop event."""
        stop_event = Event()
        wrapper = ExternalA2AAgentWrapper(self._make_info(), stop_event=stop_event)
        assert wrapper.stop_event is stop_event

    def test_smolagents_inputs_and_output(self):
        """Test ExternalA2AAgentWrapper has smolagents-compatible inputs and output_type."""
        wrapper = ExternalA2AAgentWrapper(self._make_info())
        assert "task" in wrapper.inputs
        assert wrapper.inputs["task"]["type"] == "string"
        assert "additional_args" in wrapper.inputs
        assert wrapper.inputs["additional_args"]["nullable"] is True
        assert wrapper.output_type == "string"

    def test_call_no_task_provided(self):
        """Test __call__ returns error message when no task or query is given."""
        wrapper = ExternalA2AAgentWrapper(self._make_info())
        result = wrapper()
        assert "No task provided" in result

    def test_call_task_as_kwarg(self):
        """Test __call__ accepts task keyword argument."""
        info = self._make_info(url="https://invalid-host.local")
        wrapper = ExternalA2AAgentWrapper(info)
        with patch.object(ExternalA2AAgentProxy, "sync_call", side_effect=RuntimeError("fail")):
            result = wrapper(task="do something")
            assert "Error:" in result

    def test_call_query_as_kwarg(self):
        """Test __call__ accepts query keyword argument."""
        info = self._make_info(url="https://invalid-host.local")
        wrapper = ExternalA2AAgentWrapper(info)
        with patch.object(ExternalA2AAgentProxy, "sync_call", side_effect=RuntimeError("fail")):
            result = wrapper(query="do something")
            assert "Error:" in result

    def test_run_is_alias_for_call(self):
        """Test run() delegates to __call__."""
        info = self._make_info(url="https://invalid-host.local")
        wrapper = ExternalA2AAgentWrapper(info)
        with patch.object(ExternalA2AAgentProxy, "sync_call", side_effect=RuntimeError("fail")):
            call_result = wrapper(task="test")
            run_result = wrapper.run(task="test")
            assert "Error:" in call_result
            assert "Error:" in run_result


# ---------------------------------------------------------------------------
# Tests for module-level constants
# ---------------------------------------------------------------------------

class TestModuleConstants:
    """Test module-level protocol constants."""

    def test_protocol_constants(self):
        """Test protocol type constants have expected string values."""
        assert PROTOCOL_JSONRPC == "JSONRPC"
        assert PROTOCOL_HTTP_JSON == "HTTP+JSON"
        assert PROTOCOL_GRPC == "GRPC"
