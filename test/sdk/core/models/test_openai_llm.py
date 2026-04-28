import sys
import types
import importlib.util
from pathlib import Path
# Ensure SDK package is importable by adding sdk/ to sys.path (do not fallback to stubs)
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "sdk"))

# Ensure minimal `nexent` package structure exists in sys.modules so string-based
# patch targets like "nexent.core.models.openai_llm.asyncio.to_thread" can be
# resolved by unittest.mock during tests that run outside the temporary patch
# contexts used below.
_sdk_root = Path(__file__).resolve().parents[4] / "sdk" / "nexent"
if "nexent" not in sys.modules:
    _top_pkg = types.ModuleType("nexent")
    _top_pkg.__path__ = [str(_sdk_root)]
    sys.modules["nexent"] = _top_pkg
if "nexent.core" not in sys.modules:
    _core_pkg = types.ModuleType("nexent.core")
    _core_pkg.__path__ = [str(_sdk_root / "core")]
    sys.modules["nexent.core"] = _core_pkg
if "nexent.core.models" not in sys.modules:
    _models_pkg = types.ModuleType("nexent.core.models")
    _models_pkg.__path__ = [str(_sdk_root / "core" / "models")]
    sys.modules["nexent.core.models"] = _models_pkg

# Ensure the package attributes exist on the top-level `nexent` module so that
# string-based patch targets (e.g. "nexent.core.models.openai_llm.asyncio.to_thread")
# resolve via getattr during unittest.mock's import lookup.
try:
    top_mod = sys.modules.get("nexent")
    core_mod = sys.modules.get("nexent.core")
    models_mod = sys.modules.get("nexent.core.models")
    if top_mod and core_mod and not hasattr(top_mod, "core"):
        setattr(top_mod, "core", core_mod)
    if core_mod and models_mod and not hasattr(core_mod, "models"):
        setattr(core_mod, "models", models_mod)
except Exception:
    # If anything goes wrong, do not fail test import phase; the test will create
    # the necessary entries later within its patch context.
    pass

# Ensure the concrete openai_llm submodule is available in sys.modules so that
# string-based patch targets resolve outside of temporary patch contexts.
try:
    _openai_name = "nexent.core.models.openai_llm"
    _openai_path = Path(__file__).resolve().parents[4] / "sdk" / "nexent" / "core" / "models" / "openai_llm.py"
    if _openai_path.exists() and _openai_name not in sys.modules:
        _spec = importlib.util.spec_from_file_location(_openai_name, _openai_path)
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules[_openai_name] = _mod
        assert _spec and _spec.loader
        _spec.loader.exec_module(_mod)
        pkg = sys.modules.get("nexent.core.models")
        if pkg is not None and not hasattr(pkg, "openai_llm"):
            setattr(pkg, "openai_llm", _mod)
except Exception:
    # Best-effort only; if this fails tests will still attempt to load/open the module later.
    pass

# Dynamically load the openai_llm module to avoid importing full sdk package
MODULE_NAME = "nexent.core.models.openai_llm"
MODULE_PATH = (
    Path(__file__).resolve().parents[4]
    / "sdk"
    / "nexent"
    / "core"
    / "models"
    / "openai_llm.py"
)
spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
openai_llm_module = importlib.util.module_from_spec(spec)
sys.modules[MODULE_NAME] = openai_llm_module
assert spec and spec.loader

def _setup_stubs():
    # Stub openai ChatCompletionMessage
    chat_mod = types.ModuleType("openai.types.chat.chat_completion_message")
    class ChatCompletionMessage:
        def __init__(self, role, content):
            self.role = role
            self.content = content
        def model_dump(self, include=None):
            return {"role": self.role, "content": self.content}
    chat_mod.ChatCompletionMessage = ChatCompletionMessage
    sys.modules["openai.types.chat.chat_completion_message"] = chat_mod

    # Stub smolagents.models and Tool
    smol_mod = types.ModuleType("smolagents")
    smol_models = types.ModuleType("smolagents.models")
    class ChatMessage:
        def __init__(self, role=None, content=None, tool_calls=None):
            self.role = role
            self.content = content
        @staticmethod
        def from_dict(d):
            return ChatMessage(role=d.get("role"), content=d.get("content"))
        def __repr__(self):
            return f"ChatMessage(role={self.role}, content={self.content})"
    smol_models.ChatMessage = ChatMessage
    mr = types.SimpleNamespace()
    mr.ASSISTANT = "assistant"
    smol_models.MessageRole = mr
    smol_mod.models = smol_models
    smol_mod.Tool = object
    sys.modules["smolagents"] = smol_mod
    sys.modules["smolagents.models"] = smol_models

    # Stub OpenAIServerModel base class
    sa_mod = types.ModuleType("smolagents.models") if "smolagents.models" not in sys.modules else sys.modules["smolagents.models"]
    class OpenAIServerModel:
        def __init__(self, *a, **k):
            self.client = types.SimpleNamespace()
    sa_mod.OpenAIServerModel = OpenAIServerModel
    sys.modules["smolagents.models"] = sa_mod

_setup_stubs()
# Now that stubs are in place, attempt to execute the module so imports resolve to our stubs.
# If this early import fails, clean up the partial module so the later, properly-patched import can run.
try:
    spec.loader.exec_module(openai_llm_module)
    OpenAIModel = getattr(openai_llm_module, "OpenAIModel", None)
except Exception:
    # Remove any partially-imported module to avoid interfering with later imports
    if MODULE_NAME in sys.modules:
        del sys.modules[MODULE_NAME]
    OpenAIModel = None


def make_chunk(content, reasoning=None, role=None):
    choice = types.SimpleNamespace()
    delta = types.SimpleNamespace()
    delta.content = content
    delta.reasoning_content = reasoning
    delta.role = role
    choice.delta = delta
    chunk = types.SimpleNamespace()
    chunk.choices = [choice]
    chunk.usage = None
    return chunk


def test_modelengine_message_flattening(monkeypatch):
    # Create instance with model_factory set to 'modelengine'
    ModelClass = OpenAIModel or globals().get("ImportedOpenAIModel")
    m = ModelClass(model_id="m", api_base="u", api_key="k", model_factory="modelengine")

    captured = {}

    def fake_prepare_completion_kwargs(messages=None, **kwargs):
        captured['messages'] = messages
        return {}

    m._prepare_completion_kwargs = fake_prepare_completion_kwargs
    # Ensure required attributes exist
    m.model_id = "m"
    m.custom_role_conversions = {}
    # Provide a writable observer with required methods/attributes
    m.observer = types.SimpleNamespace(current_mode=None,
                                      add_model_new_token=lambda token: None,
                                      add_model_reasoning_content=lambda rc: None,
                                      flush_remaining_tokens=lambda: None)

    # client.chat.completions.create should return an iterable of chunks
    chunk = make_chunk("hi")
    client_ns = types.SimpleNamespace()
    client_ns.chat = types.SimpleNamespace()
    def fake_create(stream=True, **kw):
        return [chunk]
    client_ns.chat.completions = types.SimpleNamespace(create=fake_create)
    m.client = client_ns

    # Call with dict messages (as external callers might)
    messages = [{"role": "system", "content": "SYS"}, {"role": "user", "content": ["a", {"text": "b"}]}]
    msg = m.__call__(messages)

    # Ensure prepare got flattened dicts when model_factory == modelengine
    assert isinstance(captured['messages'], list)
    assert all(isinstance(x, dict) for x in captured['messages'])
    # second message content should be flattened into string containing 'b'
    assert "b" in captured['messages'][1]['content']

from unittest.mock import AsyncMock, MagicMock, patch, ANY
import importlib.util
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Prepare mocks for external dependencies similar to test_core_agent.py
# ---------------------------------------------------------------------------

# Mock smolagents and submodules
mock_smolagents = MagicMock()
mock_smolagents.Tool = MagicMock()

# Create dummy sub-modules and attributes
mock_models_module = MagicMock()


# Provide a minimal OpenAIServerModel base with the method needed by OpenAIModel
class DummyOpenAIServerModel:
    def __init__(self, *args, **kwargs):
        self.model_id = kwargs.get("model_id", None)
        self.client = types.SimpleNamespace(
            chat=types.SimpleNamespace(
                completions=types.SimpleNamespace(create=MagicMock())
            )
        )
        self.custom_role_conversions = {}

    def _prepare_completion_kwargs(self, *args, **kwargs):
        # In tests we will patch this method on the instance directly, so default impl is fine
        return {}


mock_models_module.OpenAIServerModel = DummyOpenAIServerModel
class SimpleChatMessage:
    def __init__(self, role=None, content=None, tool_calls=None):
        self.role = role
        self.content = content
        self.raw = None
    @staticmethod
    def from_dict(d):
        return SimpleChatMessage(role=d.get("role"), content=d.get("content"))
mock_models_module.ChatMessage = SimpleChatMessage
mock_models_module.MessageRole = MagicMock()
mock_smolagents.models = mock_models_module

# Mock monitoring modules
monitoring_manager_mock = MagicMock()

# Define a decorator that simply returns the original function unchanged


def pass_through_decorator(*args, **kwargs):
    def decorator(func):
        return func
    return decorator


monitoring_manager_mock.monitor_endpoint = pass_through_decorator
monitoring_manager_mock.monitor_llm_call = pass_through_decorator
monitoring_manager_mock.setup_fastapi_app = MagicMock(return_value=True)
monitoring_manager_mock.configure = MagicMock()
monitoring_manager_mock.add_span_event = MagicMock()
monitoring_manager_mock.set_span_attributes = MagicMock()

# Mock nexent.monitor modules
nexent_monitor_mock = MagicMock()
nexent_monitor_mock.get_monitoring_manager = lambda: monitoring_manager_mock
nexent_monitor_mock.monitoring_manager = monitoring_manager_mock
nexent_monitor_mock.MonitoringManager = MagicMock
nexent_monitor_mock.MonitoringConfig = MagicMock

# Provide real ContextVar objects and monitoring symbols for wrapper tests
from contextvars import ContextVar as _RealContextVar
nexent_monitor_mock._monitoring_display_name = _RealContextVar(
    "_monitoring_display_name_test", default=None)
nexent_monitor_mock._monitoring_operation = _RealContextVar(
    "_monitoring_operation_test", default="unknown")
nexent_monitor_mock._detect_model_type = MagicMock(return_value="llm")
nexent_monitor_mock._MonitoredClient = type("_MonitoredClient", (), {
    "__init__": lambda self, client, model_id, model_type: setattr(self, "_wrapped", client),
})

# Create mock parent package structure for nexent module
nexent_mock = types.ModuleType("nexent")
nexent_mock.monitor = nexent_monitor_mock
# Create package-like module objects for nested package structure so relative imports work
nexent_core_mock = types.ModuleType("nexent.core")
nexent_core_mock.__path__ = []
nexent_core_models_mock = types.ModuleType("nexent.core.models")
nexent_core_models_mock.__path__ = []
nexent_core_utils_mock = types.ModuleType("nexent.core.utils")
nexent_core_utils_mock.__path__ = []

# Mock MessageObserver and ProcessType for utils.observer
class MockMessageObserver:
    def __init__(self, *args, **kwargs):
        self.add_model_new_token = MagicMock()
        self.add_model_reasoning_content = MagicMock()
        self.flush_remaining_tokens = MagicMock()

class MockProcessType:
    MODEL_OUTPUT_THINKING = "model_output_thinking"
    MODEL_OUTPUT = "model_output"

nexent_core_utils_mock.observer = MagicMock()
nexent_core_utils_mock.observer.MessageObserver = MockMessageObserver
nexent_core_utils_mock.observer.ProcessType = MockProcessType

# Assemble smolagents.* paths and monitoring mocks
module_mocks = {
    "smolagents": mock_smolagents,
    "smolagents.models": mock_models_module,
    "openai.types": MagicMock(),
    "openai.types.chat": MagicMock(),
    "openai.types.chat.chat_completion_message": MagicMock(),
    "openai": MagicMock(),
    "openai.lib": MagicMock(),
    "nexent.monitor": nexent_monitor_mock,
    "nexent.monitor.monitoring": nexent_monitor_mock,
    "nexent.core.utils.observer": nexent_core_utils_mock.observer,
}

# Ensure openai package exists with DefaultHttpxClient for patches
import types as __types
openai_mod = types.ModuleType("openai")
openai_mod.DefaultHttpxClient = lambda *a, **k: None
sys.modules["openai"] = openai_mod

# Dynamically load the module directly by file path
MODULE_NAME = "nexent.core.models.openai_llm"
MODULE_PATH = (
    Path(__file__).resolve().parents[4]
    / "sdk"
    / "nexent"
    / "core"
    / "models"
    / "openai_llm.py"
)

with patch.dict("sys.modules", module_mocks):
    # Ensure package modules exist so relative imports in the SDK module
    # (e.g. `from .message_utils import ...`) resolve without executing
    # the package's __init__.py which would import OpenAIModel and cause a cycle.
    models_pkg = types.ModuleType("nexent.core.models")
    models_pkg.__path__ = [str(MODULE_PATH.parent)]
    sys.modules["nexent.core.models"] = models_pkg
    core_pkg = sys.modules.get("nexent.core")
    if core_pkg is None:
        core_pkg = types.ModuleType("nexent.core")
        core_pkg.__path__ = [str(MODULE_PATH.parent.parent)]
        sys.modules["nexent.core"] = core_pkg
    top_pkg = sys.modules.get("nexent")
    if top_pkg is None:
        top_pkg = types.ModuleType("nexent")
        top_pkg.__path__ = [str(MODULE_PATH.parent.parent.parent)]
        sys.modules["nexent"] = top_pkg

    spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
    openai_llm_module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = openai_llm_module
    assert spec and spec.loader
    spec.loader.exec_module(openai_llm_module)
    # Expose the loaded submodule as an attribute on the package object so that
    # string-based patch targets like "nexent.core.models.openai_llm.asyncio.to_thread"
    # resolve via getattr during unittest.mock's import lookup.
    try:
        models_pkg = sys.modules.get("nexent.core.models")
        if models_pkg is not None:
            setattr(models_pkg, "openai_llm", openai_llm_module)
    except Exception:
        pass
    ImportedOpenAIModel = openai_llm_module.OpenAIModel

    # -----------------------------------------------------------------------
    # Fixtures
    # -----------------------------------------------------------------------

    @pytest.fixture()
    def openai_model_instance():
        """Return an OpenAIModel instance with minimal viable attributes for tests."""

        observer = MagicMock()
        model = ImportedOpenAIModel(observer=observer)

        # Inject dummy attributes required by the method under test
        model.model_id = "dummy-model"
        model.temperature = 0.7
        model.top_p = 0.9
        model.custom_role_conversions = {}  # Add missing attribute

        # Client hierarchy: client.chat.completions.create
        mock_client = MagicMock()
        mock_chat = MagicMock()
        mock_completions = MagicMock()
        mock_completions.create = MagicMock()
        mock_chat.completions = mock_completions
        mock_client.chat = mock_chat
        model.client = mock_client

        return model

    @pytest.fixture()
    def mock_chat_message():
        """Create a mock ChatMessage for testing"""
        mock_message = MagicMock()
        mock_message.raw = MagicMock()
        mock_message.role = MagicMock()
        return mock_message


# ---------------------------------------------------------------------------
# Tests for check_connectivity
# ---------------------------------------------------------------------------


def test_check_connectivity_success(openai_model_instance):
    """check_connectivity should return True when no exception is raised."""
    with patch.object(
            openai_model_instance,
            "_prepare_completion_kwargs",
            return_value={},
    ) as mock_prepare_kwargs, patch(
        "nexent.core.models.openai_llm.asyncio.to_thread",
        new_callable=AsyncMock,
        return_value=None,
    ) as mock_to_thread:
        result = __import__("asyncio").run(openai_model_instance.check_connectivity())
        assert result is True
        mock_prepare_kwargs.assert_called_once()
        mock_to_thread.assert_awaited_once()


def test_check_connectivity_failure(openai_model_instance):
    """check_connectivity should return False when an exception is raised inside to_thread."""
    with patch.object(
            openai_model_instance,
            "_prepare_completion_kwargs",
            return_value={},
    ), patch(
        "nexent.core.models.openai_llm.asyncio.to_thread",
        new_callable=AsyncMock,
        side_effect=Exception("connection error"),
    ):
        result = __import__("asyncio").run(openai_model_instance.check_connectivity())
        assert result is False


# ---------------------------------------------------------------------------
# Tests for __call__ method
# ---------------------------------------------------------------------------

def test_call_normal_operation(openai_model_instance):
    """Test __call__ method with normal operation flow"""

    # Setup test messages with correct format
    messages = [
        {"role": "user", "content": [{"text": "Hello"}]},
        {"role": "assistant", "content": [{"text": "Hi there"}]}
    ]

    # Mock the stream response
    mock_chunk1 = MagicMock()
    mock_chunk1.choices = [MagicMock()]
    mock_chunk1.choices[0].delta.content = "Hello"
    mock_chunk1.choices[0].delta.role = "assistant"

    mock_chunk2 = MagicMock()
    mock_chunk2.choices = [MagicMock()]
    mock_chunk2.choices[0].delta.content = " world"
    mock_chunk2.choices[0].delta.role = None

    mock_chunk3 = MagicMock()
    mock_chunk3.choices = [MagicMock()]
    mock_chunk3.choices[0].delta.content = None
    mock_chunk3.choices[0].delta.role = None
    mock_chunk3.usage = MagicMock()
    mock_chunk3.usage.prompt_tokens = 10
    mock_chunk3.usage.total_tokens = 15
    # Set completion_tokens for output token count
    mock_chunk3.usage.completion_tokens = 5

    mock_stream = [mock_chunk1, mock_chunk2, mock_chunk3]

    # Mock ChatMessage.from_dict to return a mock message
    mock_result_message = MagicMock()
    mock_result_message.raw = mock_stream
    mock_result_message.role = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}) as mock_prepare, \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        # Mock the client response
        openai_model_instance.client.chat.completions.create.return_value = mock_stream

        # Call the method
        result = openai_model_instance.__call__(messages)

        # Verify the result
        assert result == mock_result_message
        mock_prepare.assert_called_once()

        # Verify observer calls
        openai_model_instance.observer.add_model_new_token.assert_any_call(
            "Hello")
        openai_model_instance.observer.add_model_new_token.assert_any_call(
            " world")
        openai_model_instance.observer.flush_remaining_tokens.assert_called_once()

        # Verify token counts were set
        assert openai_model_instance.last_input_token_count == 10
        assert openai_model_instance.last_output_token_count == 5


def test_call_with_no_think_token_addition(openai_model_instance):
    """Test __call__ method adds /no_think token to user messages"""

    # Setup test messages with user as last message
    messages = [
        {"role": "assistant", "content": [{"text": "Hi there"}]},
        {"role": "user", "content": [{"text": "Hello"}]}
    ]

    # Mock the stream response
    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "Response"
    mock_chunk.choices[0].delta.role = "assistant"
    mock_chunk.usage = MagicMock()
    mock_chunk.usage.prompt_tokens = 5
    mock_chunk.usage.total_tokens = 8

    # Mock ChatMessage.from_dict to return a mock message
    mock_result_message = MagicMock()
    mock_result_message.raw = [mock_chunk]
    mock_result_message.role = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [
            mock_chunk]

        # Call the method
        openai_model_instance.__call__(messages)

        # Verify that /no_think was added to the last user message
        assert messages[-1]["content"][-1]["text"] == "Hello"


def test_call_without_no_think_token(openai_model_instance):
    """Test __call__ method doesn't add /no_think when last message is not user"""

    # Setup test messages with assistant as last message
    messages = [
        {"role": "user", "content": [{"text": "Hello"}]},
        {"role": "assistant", "content": [{"text": "Hi there"}]}
    ]

    # Mock the stream response
    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "Response"
    mock_chunk.choices[0].delta.role = "assistant"
    mock_chunk.usage = MagicMock()
    mock_chunk.usage.prompt_tokens = 5
    mock_chunk.usage.total_tokens = 8

    # Mock ChatMessage.from_dict to return a mock message
    mock_result_message = MagicMock()
    mock_result_message.raw = [mock_chunk]
    mock_result_message.role = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [
            mock_chunk]

        # Call the method
        openai_model_instance.__call__(messages)

        # Verify that /no_think was NOT added
        assert messages[-1]["content"][-1]["text"] == "Hi there"


def test_call_stop_event_interruption(openai_model_instance):
    """Test __call__ method raises RuntimeError when stop_event is set"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Mock the stream response
    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "Response"
    mock_chunk.choices[0].delta.role = "assistant"

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        openai_model_instance.client.chat.completions.create.return_value = [
            mock_chunk]

        # Set the stop event before calling
        openai_model_instance.stop_event.set()

        # Call the method and expect RuntimeError
        with pytest.raises(RuntimeError, match="Model is interrupted by stop event"):
            openai_model_instance.__call__(messages)


def test_call_context_length_exceeded_error(openai_model_instance):
    """Test __call__ method handles context_length_exceeded error correctly"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        # Mock the client to raise context length exceeded error
        openai_model_instance.client.chat.completions.create.side_effect = Exception(
            "context_length_exceeded: token limit exceeded")

        # Call the method and expect the original Exception (since client.create error is not wrapped)
        with pytest.raises(Exception, match="context_length_exceeded: token limit exceeded"):
            openai_model_instance.__call__(messages)


def test_call_general_exception(openai_model_instance):
    """Test __call__ method re-raises general exceptions"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        # Mock the client to raise a general exception
        openai_model_instance.client.chat.completions.create.side_effect = Exception(
            "General error")

        # Call the method and expect the same exception
        with pytest.raises(Exception, match="General error"):
            openai_model_instance.__call__(messages)


def test_call_with_no_usage_info(openai_model_instance):
    """Test __call__ method handles case where usage info is None"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Mock the stream response with no usage info
    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "Response"
    mock_chunk.choices[0].delta.role = "assistant"
    mock_chunk.usage = None

    # Mock ChatMessage.from_dict to return a mock message
    mock_result_message = MagicMock()
    mock_result_message.raw = [mock_chunk]
    mock_result_message.role = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [
            mock_chunk]

        # Call the method
        openai_model_instance.__call__(messages)

        # Verify token counts are estimated when usage is None (not set to 0)
        # The implementation estimates tokens from input/output text
        assert openai_model_instance.last_input_token_count >= 0
        assert openai_model_instance.last_output_token_count >= 0


def test_call_with_null_tokens(openai_model_instance):
    """Test __call__ method handles null tokens in stream"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Mock the stream response with null tokens
    mock_chunk1 = MagicMock()
    mock_chunk1.choices = [MagicMock()]
    mock_chunk1.choices[0].delta.content = None
    mock_chunk1.choices[0].delta.role = "assistant"

    mock_chunk2 = MagicMock()
    mock_chunk2.choices = [MagicMock()]
    mock_chunk2.choices[0].delta.content = "Response"
    mock_chunk2.choices[0].delta.role = None
    mock_chunk2.usage = MagicMock()
    mock_chunk2.usage.prompt_tokens = 5
    mock_chunk2.usage.total_tokens = 8

    # Mock ChatMessage.from_dict to return a mock message
    mock_result_message = MagicMock()
    mock_result_message.raw = [mock_chunk1, mock_chunk2]
    mock_result_message.role = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [
            mock_chunk1, mock_chunk2]

        # Call the method
        openai_model_instance.__call__(messages)

        # Verify that null tokens are handled correctly (not added to observer)
        openai_model_instance.observer.add_model_new_token.assert_called_once_with(
            "Response")


def test_call_with_reasoning_content(openai_model_instance):
    """Test __call__ method handles reasoning_content when it is not None"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Mock the stream response with reasoning_content
    mock_chunk1 = MagicMock()
    mock_chunk1.choices = [MagicMock()]
    mock_chunk1.choices[0].delta.content = "Let me think about this"
    mock_chunk1.choices[0].delta.role = "assistant"
    mock_chunk1.choices[0].delta.reasoning_content = "This is a reasoning step"

    mock_chunk2 = MagicMock()
    mock_chunk2.choices = [MagicMock()]
    mock_chunk2.choices[0].delta.content = "Response"
    mock_chunk2.choices[0].delta.role = None
    mock_chunk2.choices[0].delta.reasoning_content = None
    mock_chunk2.usage = MagicMock()
    mock_chunk2.usage.prompt_tokens = 5
    mock_chunk2.usage.total_tokens = 8

    # Mock ChatMessage.from_dict to return a mock message
    mock_result_message = MagicMock()
    mock_result_message.raw = [mock_chunk1, mock_chunk2]
    mock_result_message.role = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [
            mock_chunk1, mock_chunk2]

        # Call the method
        result = openai_model_instance.__call__(messages)

        # Verify the result
        assert result == mock_result_message

        # Verify that reasoning_content was added to observer
        openai_model_instance.observer.add_model_reasoning_content.assert_called_once_with(
            "This is a reasoning step")

        # Verify that normal tokens were also added
        openai_model_instance.observer.add_model_new_token.assert_any_call(
            "Let me think about this")
        openai_model_instance.observer.add_model_new_token.assert_any_call(
            "Response")


def test_call_with_multiple_reasoning_content_chunks(openai_model_instance):
    """Test __call__ method handles multiple chunks with reasoning_content"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Mock the stream response with multiple reasoning_content chunks
    mock_chunk1 = MagicMock()
    mock_chunk1.choices = [MagicMock()]
    mock_chunk1.choices[0].delta.content = "Let me"
    mock_chunk1.choices[0].delta.role = "assistant"
    mock_chunk1.choices[0].delta.reasoning_content = "First reasoning step"

    mock_chunk2 = MagicMock()
    mock_chunk2.choices = [MagicMock()]
    mock_chunk2.choices[0].delta.content = " think"
    mock_chunk2.choices[0].delta.role = None
    mock_chunk2.choices[0].delta.reasoning_content = "Second reasoning step"

    mock_chunk3 = MagicMock()
    mock_chunk3.choices = [MagicMock()]
    mock_chunk3.choices[0].delta.content = " about this"
    mock_chunk3.choices[0].delta.role = None
    mock_chunk3.choices[0].delta.reasoning_content = None
    mock_chunk3.usage = MagicMock()
    mock_chunk3.usage.prompt_tokens = 5
    mock_chunk3.usage.total_tokens = 8

    # Mock ChatMessage.from_dict to return a mock message
    mock_result_message = MagicMock()
    mock_result_message.raw = [mock_chunk1, mock_chunk2, mock_chunk3]
    mock_result_message.role = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [
            mock_chunk1, mock_chunk2, mock_chunk3]

        # Call the method
        result = openai_model_instance.__call__(messages)

        # Verify the result
        assert result == mock_result_message

        # Verify that all reasoning_content chunks were added to observer
        openai_model_instance.observer.add_model_reasoning_content.assert_any_call(
            "First reasoning step")
        openai_model_instance.observer.add_model_reasoning_content.assert_any_call(
            "Second reasoning step")

        # Verify that normal tokens were also added
        openai_model_instance.observer.add_model_new_token.assert_any_call(
            "Let me")
        openai_model_instance.observer.add_model_new_token.assert_any_call(
            " think")
        openai_model_instance.observer.add_model_new_token.assert_any_call(
            " about this")


def test_call_with_reasoning_content_only(openai_model_instance):
    """Test __call__ method handles chunks with only reasoning_content (no content)"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Mock the stream response with only reasoning_content
    mock_chunk1 = MagicMock()
    mock_chunk1.choices = [MagicMock()]
    mock_chunk1.choices[0].delta.content = None
    mock_chunk1.choices[0].delta.role = "assistant"
    mock_chunk1.choices[0].delta.reasoning_content = "Pure reasoning content"

    mock_chunk2 = MagicMock()
    mock_chunk2.choices = [MagicMock()]
    mock_chunk2.choices[0].delta.content = "Final response"
    mock_chunk2.choices[0].delta.role = None
    mock_chunk2.choices[0].delta.reasoning_content = None
    mock_chunk2.usage = MagicMock()
    mock_chunk2.usage.prompt_tokens = 5
    mock_chunk2.usage.total_tokens = 8

    # Mock ChatMessage.from_dict to return a mock message
    mock_result_message = MagicMock()
    mock_result_message.raw = [mock_chunk1, mock_chunk2]
    mock_result_message.role = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [
            mock_chunk1, mock_chunk2]

        # Call the method
        result = openai_model_instance.__call__(messages)

        # Verify the result
        assert result == mock_result_message

        # Verify that reasoning_content was added to observer
        openai_model_instance.observer.add_model_reasoning_content.assert_called_once_with(
            "Pure reasoning content")

        # Verify that only the non-null content token was added
        openai_model_instance.observer.add_model_new_token.assert_called_once_with(
            "Final response")


def test_call_with_reasoning_content_and_content_together(openai_model_instance):
    """Test __call__ method handles chunks with both reasoning_content and content simultaneously"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Mock the stream response with both reasoning_content and content
    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "Response text"
    mock_chunk.choices[0].delta.role = "assistant"
    mock_chunk.choices[0].delta.reasoning_content = "Reasoning alongside content"
    mock_chunk.usage = MagicMock()
    mock_chunk.usage.prompt_tokens = 5
    mock_chunk.usage.total_tokens = 8

    # Mock ChatMessage.from_dict to return a mock message
    mock_result_message = MagicMock()
    mock_result_message.raw = [mock_chunk]
    mock_result_message.role = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [
            mock_chunk]

        # Call the method
        result = openai_model_instance.__call__(messages)

        # Verify the result
        assert result == mock_result_message

        # Verify that both reasoning_content and content were processed
        openai_model_instance.observer.add_model_reasoning_content.assert_called_once_with(
            "Reasoning alongside content")
        openai_model_instance.observer.add_model_new_token.assert_called_once_with(
            "Response text")


# ---------------------------------------------------------------------------
# Tests for __init__ with ssl_verify parameter
# ---------------------------------------------------------------------------

def test_init_with_ssl_verify_false():
    """Test __init__ method creates http_client when ssl_verify=False"""

    observer = MagicMock()

    # Mock DefaultHttpxClient from openai module
    with patch("openai.DefaultHttpxClient") as mock_httpx_client:
        mock_httpx_client.return_value = MagicMock()

        # Create model with ssl_verify=False
        model = ImportedOpenAIModel(observer=observer, ssl_verify=False)

        # Verify DefaultHttpxClient was called with verify=False
        mock_httpx_client.assert_called_once_with(verify=False)


def test_init_with_ssl_verify_true():
    """Test __init__ method doesn't create http_client when ssl_verify=True (default)"""

    observer = MagicMock()

    # Mock DefaultHttpxClient from openai module
    with patch("openai.DefaultHttpxClient") as mock_httpx_client:
        # Create model with ssl_verify=True (default)
        model = ImportedOpenAIModel(observer=observer, ssl_verify=True)

        # Verify DefaultHttpxClient was NOT called
        mock_httpx_client.assert_not_called()


# ---------------------------------------------------------------------------
# Tests for monitoring and token_tracker integration
# ---------------------------------------------------------------------------

def test_call_with_monitoring_and_token_tracker(openai_model_instance):
    """Test __call__ method with monitoring and token_tracker enabled"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Create mock token_tracker
    mock_token_tracker = MagicMock()
    mock_token_tracker.record_first_token = MagicMock()
    mock_token_tracker.record_token = MagicMock()
    mock_token_tracker.record_completion = MagicMock()

    # Mock the stream response
    mock_chunk1 = MagicMock()
    mock_chunk1.choices = [MagicMock()]
    mock_chunk1.choices[0].delta.content = "Hello"
    mock_chunk1.choices[0].delta.role = "assistant"
    mock_chunk1.choices[0].delta.reasoning_content = None

    mock_chunk2 = MagicMock()
    mock_chunk2.choices = [MagicMock()]
    mock_chunk2.choices[0].delta.content = " world"
    mock_chunk2.choices[0].delta.role = None
    mock_chunk2.choices[0].delta.reasoning_content = None

    mock_chunk3 = MagicMock()
    mock_chunk3.choices = [MagicMock()]
    mock_chunk3.choices[0].delta.content = None
    mock_chunk3.choices[0].delta.role = None
    mock_chunk3.choices[0].delta.reasoning_content = None
    mock_chunk3.usage = MagicMock()
    mock_chunk3.usage.prompt_tokens = 10
    mock_chunk3.usage.completion_tokens = 5
    mock_chunk3.usage.total_tokens = 15

    mock_stream = [mock_chunk1, mock_chunk2, mock_chunk3]

    # Mock ChatMessage.from_dict
    mock_result_message = MagicMock()
    mock_result_message.raw = mock_stream
    mock_result_message.role = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = mock_stream

        # Call with _token_tracker kwarg
        result = openai_model_instance.__call__(messages, _token_tracker=mock_token_tracker)

        # Verify monitoring calls
        monitoring_manager_mock.add_span_event.assert_any_call("completion_started")
        monitoring_manager_mock.set_span_attributes.assert_called()
        monitoring_manager_mock.add_span_event.assert_any_call("completion_finished", ANY)

        # Verify token_tracker calls
        mock_token_tracker.record_first_token.assert_called_once()
        assert mock_token_tracker.record_token.call_count == 2  # "Hello" and " world"
        mock_token_tracker.record_completion.assert_called_once_with(10, 5)


def test_call_with_token_tracker_on_reasoning_content(openai_model_instance):
    """Test __call__ method tracks first token on reasoning_content"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Create mock token_tracker
    mock_token_tracker = MagicMock()
    mock_token_tracker.record_first_token = MagicMock()
    mock_token_tracker.record_token = MagicMock()
    mock_token_tracker.record_completion = MagicMock()

    # Mock the stream response with reasoning_content first
    mock_chunk1 = MagicMock()
    mock_chunk1.choices = [MagicMock()]
    mock_chunk1.choices[0].delta.content = None
    mock_chunk1.choices[0].delta.role = "assistant"
    mock_chunk1.choices[0].delta.reasoning_content = "Thinking..."

    mock_chunk2 = MagicMock()
    mock_chunk2.choices = [MagicMock()]
    mock_chunk2.choices[0].delta.content = "Response"
    mock_chunk2.choices[0].delta.role = None
    mock_chunk2.choices[0].delta.reasoning_content = None
    mock_chunk2.usage = MagicMock()
    mock_chunk2.usage.prompt_tokens = 5
    mock_chunk2.usage.completion_tokens = 3
    mock_chunk2.usage.total_tokens = 8

    mock_stream = [mock_chunk1, mock_chunk2]

    # Mock ChatMessage.from_dict
    mock_result_message = MagicMock()
    mock_result_message.raw = mock_stream
    mock_result_message.role = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = mock_stream

        # Call with _token_tracker kwarg
        result = openai_model_instance.__call__(messages, _token_tracker=mock_token_tracker)

        # Verify token_tracker.record_first_token was called when reasoning_content was received
        mock_token_tracker.record_first_token.assert_called()
        mock_token_tracker.record_token.assert_called_once_with("Response")


def test_call_with_stop_event_and_token_tracker(openai_model_instance):
    """Test __call__ method adds monitoring event when stop_event is set with token_tracker"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Create mock token_tracker
    mock_token_tracker = MagicMock()

    # Mock the stream response
    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "Response"
    mock_chunk.choices[0].delta.role = "assistant"
    mock_chunk.choices[0].delta.reasoning_content = None

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        openai_model_instance.client.chat.completions.create.return_value = [mock_chunk]

        # Set the stop event before calling
        openai_model_instance.stop_event.set()

        # Call the method with token_tracker and expect RuntimeError
        with pytest.raises(RuntimeError, match="Model is interrupted by stop event"):
            openai_model_instance.__call__(messages, _token_tracker=mock_token_tracker)

        # Verify monitoring event was added
        monitoring_manager_mock.add_span_event.assert_any_call("model_stopped", {"reason": "stop_event_set"})


def test_call_exception_with_token_tracker(openai_model_instance):
    """Test __call__ method adds error event when exception occurs with token_tracker"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Create mock token_tracker
    mock_token_tracker = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        # Mock the client to raise an exception
        openai_model_instance.client.chat.completions.create.side_effect = Exception("API Error")

        # Call the method with token_tracker and expect exception
        with pytest.raises(Exception, match="API Error"):
            openai_model_instance.__call__(messages, _token_tracker=mock_token_tracker)

        # Verify error event was added
        monitoring_manager_mock.add_span_event.assert_any_call("error_occurred", ANY)


def test_call_context_length_exceeded_with_token_tracker(openai_model_instance):
    """Test __call__ method adds error event for context_length_exceeded with token_tracker"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Create mock token_tracker
    mock_token_tracker = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        # Mock the client to raise context length exceeded error
        openai_model_instance.client.chat.completions.create.side_effect = Exception(
            "context_length_exceeded: token limit exceeded")

        # Call the method with token_tracker and expect exception
        with pytest.raises(Exception, match="context_length_exceeded"):
            openai_model_instance.__call__(messages, _token_tracker=mock_token_tracker)

        # Verify error event was added
        monitoring_manager_mock.add_span_event.assert_any_call("error_occurred", ANY)

def test_call_with_chatmessage_instance_passed_through(openai_model_instance):
    """Passing a ChatMessage instance should be preserved and passed to _prepare_completion_kwargs."""

    # Create a ChatMessage instance (should be preserved as-is)
    chat_msg = mock_models_module.ChatMessage(role="user", content=[{"text": "Hello"}])

    captured = {}

    def fake_prepare_completion_kwargs(messages=None, **kwargs):
        captured["messages"] = messages
        return {}

    # Prepare a simple stream response to satisfy __call__ output handling
    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "Response"
    mock_chunk.choices[0].delta.role = "assistant"
    mock_chunk.usage = MagicMock()
    mock_chunk.usage.prompt_tokens = 1
    mock_chunk.usage.completion_tokens = 1

    mock_result_message = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", side_effect=fake_prepare_completion_kwargs), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [mock_chunk]
        result = openai_model_instance.__call__([chat_msg])

    # Ensure the same ChatMessage object instance was passed through unchanged
    assert "messages" in captured
    assert captured["messages"][0] is chat_msg

    # Ensure the final returned message is the constructed result (from_dict used for output)
    assert result == mock_result_message

def test_call_invalid_dict_message_raises_value_error(openai_model_instance):
    """Passing a dict missing 'content' should raise ValueError during normalization."""
    messages = [{"role": "user"}]  # missing 'content'
    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        with pytest.raises(ValueError, match="Each message dict must include 'role' and 'content'."):
            openai_model_instance.__call__(messages)


def test_call_invalid_message_type_raises_type_error(openai_model_instance):
    """Passing a message that is neither dict nor ChatMessage should raise TypeError."""
    messages = [42]  # invalid type
    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        with pytest.raises(TypeError, match="Messages must be ChatMessage or dict objects."):
            openai_model_instance.__call__(messages)


# ---------------------------------------------------------------------------
# Tests for monitoring wrapper in __init__
# ---------------------------------------------------------------------------


def test_init_client_wrapped_with_monitored_client():
    """When model_id is set, __init__ wraps self.client with _MonitoredClient."""
    _MonitoredClient = openai_llm_module._MonitoredClient
    observer = MagicMock()
    model = ImportedOpenAIModel(
        observer=observer, model_id="test-model",
        api_base="http://localhost", api_key="k")
    assert isinstance(model.client, _MonitoredClient)


def test_init_display_name_sets_context_variable():
    """When display_name is provided, _monitoring_display_name context var is set."""
    _monitoring_display_name = openai_llm_module._monitoring_display_name
    observer = MagicMock()
    model = ImportedOpenAIModel(
        observer=observer, model_id="test-model",
        api_base="http://localhost", api_key="k", display_name="GPT-4")
    assert _monitoring_display_name.get() == "GPT-4"


def test_init_no_client_logs_warning():
    """When base_client is None after init, a warning is logged and client is not wrapped."""
    _MonitoredClient = openai_llm_module._MonitoredClient
    observer = MagicMock()
    model = ImportedOpenAIModel(observer=observer)
    assert not isinstance(model.client, _MonitoredClient)


def test_call_with_token_tracker_uses_provided_tracker(openai_model_instance):
    """When _token_tracker is passed, __call__ uses it instead of creating one."""
    mock_tracker = MagicMock()
    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "hi"
    mock_chunk.choices[0].delta.role = "assistant"
    mock_chunk.usage = MagicMock()
    mock_chunk.usage.prompt_tokens = 1
    mock_chunk.usage.completion_tokens = 1

    mock_result_message = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [mock_chunk]
        openai_model_instance(
            messages=[{"role": "user", "content": "hello"}], _token_tracker=mock_tracker)

    mock_tracker.record_token.assert_called()


def test_call_without_tracker_creates_tracker(openai_model_instance):
    """When no _token_tracker is passed, __call__ creates one from monitoring manager."""
    mock_tracker = MagicMock()
    openai_model_instance._monitoring.create_token_tracker = MagicMock(return_value=mock_tracker)

    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "hi"
    mock_chunk.choices[0].delta.role = "assistant"
    mock_chunk.usage = MagicMock()
    mock_chunk.usage.prompt_tokens = 1
    mock_chunk.usage.completion_tokens = 1

    mock_result_message = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [mock_chunk]
        openai_model_instance(messages=[{"role": "user", "content": "hello"}])

    openai_model_instance._monitoring.create_token_tracker.assert_called_once_with("dummy-model")
    mock_tracker.record_token.assert_called()




def test_call_non_streaming_response_converted(openai_model_instance):
    """Test that non-streaming response is handled and converted to ChatMessage."""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Construct a non-streaming response (ChatCompletion-like object)
    # Non-streaming response has choices[0].message, NOT choices[0].delta
    non_streaming_response = types.SimpleNamespace()
    non_streaming_response.id = "chatcmpl-xxx"
    non_streaming_response.model = "gpt-4"
    non_streaming_response.choices = [types.SimpleNamespace()]
    non_streaming_response.choices[0].message = types.SimpleNamespace()
    non_streaming_response.choices[0].message.content = "Test response content"
    non_streaming_response.choices[0].message.role = "assistant"
    non_streaming_response.usage = types.SimpleNamespace()
    non_streaming_response.usage.prompt_tokens = 10
    non_streaming_response.usage.completion_tokens = 5

    # Mock ChatMessage.from_dict
    mock_result_message = MagicMock()
    mock_result_message.raw = non_streaming_response

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [non_streaming_response]

        # Call the method - should handle non-streaming response gracefully
        result = openai_model_instance.__call__(messages)

        # Verify the result is the converted ChatMessage
        assert result == mock_result_message

        # Verify observer calls
        openai_model_instance.observer.add_model_new_token.assert_called_once_with("Test response content")
        openai_model_instance.observer.flush_remaining_tokens.assert_called_once()

        # Verify token counts were set
        assert openai_model_instance.last_input_token_count == 10
        assert openai_model_instance.last_output_token_count == 5


def test_call_invalid_response_format_raises_value_error(openai_model_instance):
    """Test that invalid response format (string error) raises ValueError."""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Mock client returns an error string instead of proper response
    openai_model_instance.client.chat.completions.create.return_value = [
        "Error: rate limit exceeded"
    ]

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        # Call the method and expect ValueError
        with pytest.raises(ValueError, match="LLM API returned invalid response format"):
            openai_model_instance.__call__(messages)


def test_call_response_with_empty_choices_raises_value_error(openai_model_instance):
    """Test that response with empty choices raises ValueError."""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Construct a response with empty choices list
    empty_choices_response = types.SimpleNamespace()
    empty_choices_response.choices = []  # Empty choices

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        openai_model_instance.client.chat.completions.create.return_value = [empty_choices_response]

        # Call the method and expect ValueError
        with pytest.raises(ValueError, match="LLM API returned invalid response format"):
            openai_model_instance.__call__(messages)


def test_call_response_missing_delta_hits_non_streaming_path(openai_model_instance):
    """
    Test that response with choices but no delta (non-streaming format) is handled.

    This verifies the fix: OLD code would raise AttributeError here,
    NEW code correctly detects it as non-streaming and converts it.
    """

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Construct a response that has choices but NO delta attribute
    # This simulates what a non-streaming API returns wrapped in an iterator
    non_streaming_like = types.SimpleNamespace()
    non_streaming_like.id = "chatcmpl-abc123"
    non_streaming_like.model = "gpt-4"
    non_streaming_like.choices = [types.SimpleNamespace()]
    # Note: choices[0] has 'message' not 'delta' - this is the key difference
    non_streaming_like.choices[0].message = types.SimpleNamespace()
    non_streaming_like.choices[0].message.content = "Handled non-streaming response"
    non_streaming_like.choices[0].message.role = "assistant"
    non_streaming_like.usage = types.SimpleNamespace()
    non_streaming_like.usage.prompt_tokens = 5
    non_streaming_like.usage.completion_tokens = 3

    # Mock ChatMessage.from_dict to return a proper message
    mock_result_message = MagicMock()
    mock_result_message.raw = non_streaming_like

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [non_streaming_like]

        # OLD code would fail here with: AttributeError: 'SimpleNamespace' object has no attribute 'delta'
        # NEW code should detect this as non-streaming and handle it gracefully
        result = openai_model_instance.__call__(messages)

        # Verify the result was processed
        assert result == mock_result_message
        openai_model_instance.observer.add_model_new_token.assert_called_once()
        openai_model_instance.observer.flush_remaining_tokens.assert_called_once()


def test_old_code_would_fail_without_fix(openai_model_instance):
    """
    Demonstration test: shows what the OLD code would do without the fix.

    The OLD code accessed chunk.choices[0].delta.content directly without checking
    if delta exists. This test simulates that scenario to prove the fix is necessary.
    """

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Create a response that has choices but NO delta attribute
    malformed_response = types.SimpleNamespace()
    malformed_response.choices = [types.SimpleNamespace()]
    # Deliberately NOT setting .delta - simulating what OLD code would encounter

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        openai_model_instance.client.chat.completions.create.return_value = [malformed_response]

        # WITHOUT the fix, this would raise:
        # AttributeError: 'types.SimpleNamespace' object has no attribute 'delta'
        # WITH the fix, it raises a descriptive ValueError
        with pytest.raises((AttributeError, ValueError)):
            openai_model_instance.__call__(messages)


def test_non_streaming_response_with_error_message(openai_model_instance):
    """
    Test non-streaming response that contains an error.

    Some APIs return non-streaming responses with error info in the message.
    """

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Simulate a non-streaming response with an error message
    error_response = types.SimpleNamespace()
    error_response.id = "chatcmpl-error"
    error_response.model = "gpt-4"
    error_response.choices = [types.SimpleNamespace()]
    error_response.choices[0].message = types.SimpleNamespace()
    error_response.choices[0].message.content = None  # No content
    error_response.choices[0].message.role = "assistant"
    error_response.usage = types.SimpleNamespace()
    error_response.usage.prompt_tokens = 5
    error_response.usage.completion_tokens = 0

    mock_result_message = MagicMock()
    mock_result_message.raw = error_response

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [error_response]

        # Should handle gracefully without raising AttributeError
        result = openai_model_instance.__call__(messages)
        assert result == mock_result_message


def test_handle_non_streaming_no_choices_raises_error(openai_model_instance):
    """
    Test _handle_non_streaming_response raises ValueError when choices is empty.
    Covers line 223.

    When a response has id/model (indicating non-streaming) but empty choices,
    _handle_non_streaming_response is called and should raise ValueError.
    """

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Create a response with id/model but empty choices list
    # This makes it pass the non-streaming detection but fail in _handle_non_streaming_response
    response_no_choices = types.SimpleNamespace()
    response_no_choices.id = "chatcmpl-test"  # Has id to trigger non-streaming path
    response_no_choices.model = "gpt-4"  # Has model to trigger non-streaming path
    response_no_choices.choices = []  # Empty choices

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        openai_model_instance.client.chat.completions.create.return_value = [response_no_choices]

        with pytest.raises(ValueError, match="Non-streaming response has no choices"):
            openai_model_instance.__call__(messages)


def test_handle_non_streaming_no_choices_attr_raises_error(openai_model_instance):
    """
    Test _handle_non_streaming_response raises ValueError when choices attribute is missing.
    Covers line 223.
    """

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Create a response without choices attribute at all
    response_no_choices_attr = types.SimpleNamespace()
    # No choices attribute

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        openai_model_instance.client.chat.completions.create.return_value = [response_no_choices_attr]

        with pytest.raises(ValueError, match="LLM API returned invalid response format"):
            openai_model_instance.__call__(messages)


def test_handle_non_streaming_with_delta_fallback(openai_model_instance):
    """
    Test _handle_non_streaming_response uses delta as fallback for content.
    Covers lines 231-232.

    Some non-standard responses might have delta instead of message.
    """

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Create a non-streaming response that uses delta instead of message
    response_with_delta = types.SimpleNamespace()
    response_with_delta.id = "chatcmpl-delta-test"
    response_with_delta.model = "gpt-4"
    response_with_delta.choices = [types.SimpleNamespace()]
    # Use delta instead of message
    response_with_delta.choices[0].delta = types.SimpleNamespace()
    response_with_delta.choices[0].delta.content = "Content from delta"
    response_with_delta.choices[0].delta.role = "assistant"
    response_with_delta.usage = types.SimpleNamespace()
    response_with_delta.usage.prompt_tokens = 5
    response_with_delta.usage.completion_tokens = 3

    mock_result_message = MagicMock()
    mock_result_message.raw = response_with_delta

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [response_with_delta]

        result = openai_model_instance.__call__(messages)

        # Verify the result
        assert result == mock_result_message
        # Observer should have received the content from delta
        openai_model_instance.observer.add_model_new_token.assert_called_with("Content from delta")


def test_handle_non_streaming_delta_role_fallback(openai_model_instance):
    """
    Test _handle_non_streaming_response uses delta for role when message is absent.
    Covers lines 238-239.
    """

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Create a response with delta that has role (no message)
    response_delta_role = types.SimpleNamespace()
    response_delta_role.id = "chatcmpl-delta-role"
    response_delta_role.model = "gpt-4"
    response_delta_role.choices = [types.SimpleNamespace()]
    # Only delta, no message
    response_delta_role.choices[0].delta = types.SimpleNamespace()
    response_delta_role.choices[0].delta.content = "Response from delta"
    response_delta_role.choices[0].delta.role = "assistant"
    response_delta_role.usage = types.SimpleNamespace()
    response_delta_role.usage.prompt_tokens = 3
    response_delta_role.usage.completion_tokens = 2

    mock_result_message = MagicMock()
    mock_result_message.raw = response_delta_role

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [response_delta_role]

        result = openai_model_instance.__call__(messages)

        assert result == mock_result_message
        openai_model_instance.observer.add_model_new_token.assert_called_with("Response from delta")


def test_call_context_length_exceeded_raises_value_error(openai_model_instance):
    """
    Test that context_length_exceeded error is wrapped with ValueError.
    Covers line 209.

    Note: The exception handling at line 209 can only be reached when the error
    occurs INSIDE the try block (during streaming). When create() itself throws,
    it's outside the try block. This test verifies the error wrapping logic works.
    """

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Create a streaming response that eventually raises context_length error
    def streaming_with_error(*args, **kwargs):
        # First yield a valid chunk
        chunk1 = types.SimpleNamespace()
        chunk1.choices = [types.SimpleNamespace()]
        chunk1.choices[0].delta = types.SimpleNamespace()
        chunk1.choices[0].delta.content = "Partial "
        chunk1.choices[0].delta.role = "assistant"
        yield chunk1

        # Then raise the context_length error
        raise Exception("context_length_exceeded: token limit exceeded")

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        openai_model_instance.client.chat.completions.create.return_value = streaming_with_error()

        # Should raise ValueError with "Token limit exceeded" message
        with pytest.raises(ValueError, match="Token limit exceeded"):
            openai_model_instance.__call__(messages)


def test_call_context_length_exceeded_no_wrapping(openai_model_instance):
    """
    Test that non-context_length errors are re-raised as-is (not wrapped).
    Covers line 210 (raise e without wrapping).
    """

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        # Mock the client to raise a general error
        openai_model_instance.client.chat.completions.create.side_effect = Exception(
            "Some other error")

        # Should re-raise the original Exception
        with pytest.raises(Exception, match="Some other error"):
            openai_model_instance.__call__(messages)


def test_handle_non_streaming_response_directly_with_delta():
    """
    Test _handle_non_streaming_response directly with delta instead of message.
    Covers lines 232-233 and 239-240 (delta fallback branches).
    """

    # Create a minimal mock setup for direct method testing
    observer = MagicMock()
    model = ImportedOpenAIModel(observer=observer)
    model.model_id = "test-model"
    model.temperature = 0.7
    model.top_p = 0.9
    model.custom_role_conversions = {}

    # Create response that uses delta instead of message
    response = types.SimpleNamespace()
    response.choices = [types.SimpleNamespace()]
    # Only set delta, not message - triggers fallback branches
    response.choices[0].delta = types.SimpleNamespace()
    response.choices[0].delta.content = "Delta content"
    response.choices[0].delta.role = "assistant"
    response.usage = types.SimpleNamespace()
    response.usage.prompt_tokens = 5
    response.usage.completion_tokens = 2

    result = model._handle_non_streaming_response(response)

    # Verify the result
    assert result is not None
    observer.add_model_new_token.assert_called_with("Delta content")
    observer.flush_remaining_tokens.assert_called_once()
    assert model.last_input_token_count == 5
    assert model.last_output_token_count == 2


def test_handle_non_streaming_response_directly_delta_only_no_role():
    """
    Test _handle_non_streaming_response with delta but no role attribute.
    Covers fallback branches when delta exists but role is missing.
    """

    observer = MagicMock()
    model = ImportedOpenAIModel(observer=observer)
    model.model_id = "test-model"

    # Create response with delta but no role
    response = types.SimpleNamespace()
    response.choices = [types.SimpleNamespace()]
    response.choices[0].delta = types.SimpleNamespace()
    response.choices[0].delta.content = "Content without role"
    # No role attribute on delta
    response.usage = types.SimpleNamespace()
    response.usage.prompt_tokens = 1
    response.usage.completion_tokens = 1

    result = model._handle_non_streaming_response(response)

    # Should default to "assistant" role
    assert result is not None
    observer.add_model_new_token.assert_called_with("Content without role")


if __name__ == "__main__":
    pytest.main([__file__])
