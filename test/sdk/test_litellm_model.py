"""Tests for LiteLLMModel SDK integration."""

import os
import sys
import types as _types
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# Stub the heavy nexent import chain before importing LiteLLMModel
sdk_path = os.path.join(os.path.dirname(__file__), '..', '..', 'sdk')
sys.path.insert(0, sdk_path)


class _FakeObserver:
    current_mode = None
    @staticmethod
    def add_model_new_token(t): pass
    @staticmethod
    def add_model_reasoning_content(t): pass
    @staticmethod
    def flush_remaining_tokens(): pass


class _FakeProcessType:
    MODEL_OUTPUT_THINKING = "thinking"


# Stub observer module
_observer_mod = _types.ModuleType("nexent.core.utils.observer")
_observer_mod.MessageObserver = _FakeObserver
_observer_mod.ProcessType = _FakeProcessType

# Build nexent package hierarchy as stubs
_models_dir = os.path.join(sdk_path, "nexent", "core", "models")
for name in [
    "nexent", "nexent.core", "nexent.core.utils",
    "nexent.core.utils.observer", "nexent.core.models",
    "nexent.memory", "nexent.container", "nexent.monitor",
    "nexent.monitor.monitoring",
    "nexent.core.utils.token_estimation",
]:
    if name not in sys.modules:
        mod = _types.ModuleType(name)
        if name == "nexent.core.utils.observer":
            mod = _observer_mod
        # Mark packages so submodule imports work
        if not name.endswith((".observer", ".monitoring", ".token_estimation")):
            mod.__path__ = [os.path.join(sdk_path, *name.split("."))]
        sys.modules[name] = mod

# Now we can import the module (relative imports resolve against stubs)
from nexent.core.models.litellm_llm import LiteLLMModel


def _make_stream_chunks(content="hello", include_usage=True):
    """Create fake streaming chunks."""
    chunks = []
    for token in list(content):
        chunks.append(SimpleNamespace(
            choices=[SimpleNamespace(
                delta=SimpleNamespace(content=token, role="assistant", reasoning_content=None),
                finish_reason=None,
            )],
            usage=None,
        ))
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=len(content)) if include_usage else None
    chunks.append(SimpleNamespace(
        choices=[SimpleNamespace(
            delta=SimpleNamespace(content=None, role=None, reasoning_content=None),
            finish_reason="stop",
        )],
        usage=usage,
    ))
    return chunks


class TestInit:
    def test_basic(self):
        m = LiteLLMModel(model_id="anthropic/claude-sonnet-4-20250514")
        assert m.model_id == "anthropic/claude-sonnet-4-20250514"

    def test_with_credentials(self):
        m = LiteLLMModel(model_id="azure/gpt-4o", api_key="sk-test", api_base="https://x.com")
        assert m.api_key == "sk-test"
        assert m.api_base == "https://x.com"


class TestCall:
    def test_streaming_output(self):
        m = LiteLLMModel(model_id="gpt-4o-mini")
        with patch("litellm.completion", return_value=iter(_make_stream_chunks("OK"))):
            r = m([{"role": "user", "content": "hi"}])
        assert r.content == "OK"

    def test_api_key_forwarded(self):
        m = LiteLLMModel(model_id="gpt-4o-mini", api_key="sk-test")
        with patch("litellm.completion", return_value=iter(_make_stream_chunks("x"))) as mock:
            m([{"role": "user", "content": "hi"}])
        assert mock.call_args.kwargs["api_key"] == "sk-test"

    def test_api_key_omitted_when_none(self):
        m = LiteLLMModel(model_id="gpt-4o-mini")
        with patch("litellm.completion", return_value=iter(_make_stream_chunks("x"))) as mock:
            m([{"role": "user", "content": "hi"}])
        assert "api_key" not in mock.call_args.kwargs

    def test_api_base_forwarded(self):
        m = LiteLLMModel(model_id="azure/gpt-4o", api_base="https://x.com")
        with patch("litellm.completion", return_value=iter(_make_stream_chunks("x"))) as mock:
            m([{"role": "user", "content": "hi"}])
        assert mock.call_args.kwargs["api_base"] == "https://x.com"

    def test_drop_params_set(self):
        m = LiteLLMModel(model_id="gpt-4o-mini")
        with patch("litellm.completion", return_value=iter(_make_stream_chunks("x"))) as mock:
            m([{"role": "user", "content": "hi"}])
        assert mock.call_args.kwargs["drop_params"] is True

    def test_response_format(self):
        m = LiteLLMModel(model_id="gpt-4o-mini")
        with patch("litellm.completion", return_value=iter(_make_stream_chunks("{}"))) as mock:
            m([{"role": "user", "content": "json"}], response_format={"type": "json_object"})
        assert mock.call_args.kwargs["response_format"] == {"type": "json_object"}

    def test_stop_sequences(self):
        m = LiteLLMModel(model_id="gpt-4o-mini")
        with patch("litellm.completion", return_value=iter(_make_stream_chunks("x"))) as mock:
            m([{"role": "user", "content": "hi"}], stop_sequences=["END"])
        assert mock.call_args.kwargs["stop"] == ["END"]

    def test_token_tracking(self):
        m = LiteLLMModel(model_id="gpt-4o-mini")
        with patch("litellm.completion", return_value=iter(_make_stream_chunks("hello"))):
            m([{"role": "user", "content": "hi"}])
        assert m.last_input_token_count == 10
        assert m.last_output_token_count == 5


class TestEdgeCases:
    def test_empty_stream(self):
        m = LiteLLMModel(model_id="gpt-4o-mini")
        chunks = [SimpleNamespace(
            choices=[SimpleNamespace(
                delta=SimpleNamespace(content=None, role="assistant", reasoning_content=None),
                finish_reason="stop",
            )], usage=SimpleNamespace(prompt_tokens=5, completion_tokens=0),
        )]
        with patch("litellm.completion", return_value=iter(chunks)):
            r = m([{"role": "user", "content": "hi"}])
        assert r.content == ""

    def test_chunk_without_choices(self):
        m = LiteLLMModel(model_id="gpt-4o-mini")
        chunks = [SimpleNamespace(usage=None), *_make_stream_chunks("OK")]
        with patch("litellm.completion", return_value=iter(chunks)):
            r = m([{"role": "user", "content": "hi"}])
        assert r.content == "OK"

    def test_context_length_exceeded(self):
        """context_length_exceeded during streaming is converted to ValueError."""
        m = LiteLLMModel(model_id="gpt-4o-mini")

        def _exploding_stream(**kwargs):
            yield SimpleNamespace(
                choices=[SimpleNamespace(
                    delta=SimpleNamespace(content="x", role="assistant", reasoning_content=None),
                    finish_reason=None,
                )], usage=None,
            )
            raise Exception("context_length_exceeded")

        with patch("litellm.completion", side_effect=lambda **kw: _exploding_stream(**kw)):
            with pytest.raises(ValueError, match="Token limit exceeded"):
                m([{"role": "user", "content": "hi"}])

    def test_auth_error_propagates(self):
        m = LiteLLMModel(model_id="gpt-4o-mini")
        with patch("litellm.completion", side_effect=ValueError("invalid api key")):
            with pytest.raises(ValueError, match="invalid api key"):
                m([{"role": "user", "content": "hi"}])

    def test_import_error(self):
        m = LiteLLMModel(model_id="gpt-4o-mini")
        with patch.dict("sys.modules", {"litellm": None}):
            with pytest.raises(ImportError, match="litellm is required"):
                m([{"role": "user", "content": "hi"}])

    def test_stop_event_interrupts(self):
        m = LiteLLMModel(model_id="gpt-4o-mini")
        m.stop_event.set()
        with patch("litellm.completion", return_value=iter(_make_stream_chunks("long text"))):
            with pytest.raises(RuntimeError, match="interrupted"):
                m([{"role": "user", "content": "hi"}])


@pytest.mark.skipif(
    "ANTHROPIC_FOUNDRY_API_KEY" not in os.environ,
    reason="Live E2E requires ANTHROPIC_FOUNDRY_API_KEY",
)
class TestLiveE2E:
    def test_live_streaming(self):
        m = LiteLLMModel(
            model_id="anthropic/" + os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-20250514"),
            api_key=os.environ["ANTHROPIC_FOUNDRY_API_KEY"],
            api_base=os.environ.get("ANTHROPIC_FOUNDRY_BASE_URL"),
            temperature=0.7,
        )
        r = m([{"role": "user", "content": "Say OK and nothing else."}])
        assert isinstance(r.content, str)
        assert len(r.content) > 0
        print(f"Live E2E response: {r.content!r}")
