"""Unit tests for the LLM modality adapters (base + OpenAI standard/long-context)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from nexent.core.gateway.modality import OpenAILLMAdapter, OpenAILongContextLLMAdapter
from nexent.core.gateway.modality.llm.llm_adapter import LLMAdapter, LLMRequest
from nexent.core.gateway.model_context import LLMContext, LongContextLLMContext


def _ctx(**overrides):
    kwargs = {
        "model_name": "llm-x",
        "base_url": "https://llm.example.com/v1",
        "api_key": "key-1",
        "modality": "llm",
        "factory": "openai",
    }
    kwargs.update(overrides)
    return LLMContext(**kwargs)


class _ConcreteLLMAdapter(LLMAdapter):
    async def invoke(self, request):
        return "ok"

    async def health_check(self):
        return True

    def get_model_info(self):
        from nexent.core.gateway.multimodal_adapter import ModelInfo

        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={"text": True},
        )


def test_llm_request_defaults():
    req = LLMRequest(messages=[{"role": "user", "content": "hi"}])
    assert req.messages == [{"role": "user", "content": "hi"}]
    assert req.kwargs == {}


def test_llm_adapter_attribute_modality():
    assert _ConcreteLLMAdapter.modality == "llm"
    adapter = _ConcreteLLMAdapter(_ctx())
    assert adapter._context.model_name == "llm-x"
    assert adapter._model is None


def test_llm_adapter_call_forwards_to_model():
    adapter = _ConcreteLLMAdapter(_ctx())
    model = MagicMock(return_value="resp")
    adapter._model = model
    assert adapter([{"role": "user", "content": "hi"}], temperature=0.1) == "resp"
    model.assert_called_once_with(
        [{"role": "user", "content": "hi"}], temperature=0.1
    )


def test_llm_adapter_call_builds_model_when_missing():
    adapter = _ConcreteLLMAdapter(_ctx())
    model = MagicMock(return_value="resp")
    adapter._build_model = MagicMock(side_effect=lambda: setattr(adapter, "_model", model))
    adapter._model = None
    assert adapter("hi") == "resp"
    adapter._build_model.assert_called_once()


def test_llm_adapter_getattr_forwards_to_model():
    adapter = _ConcreteLLMAdapter(_ctx())
    model = MagicMock()
    model.model_id = "m42"
    adapter._model = model
    assert adapter.model_id == "m42"
    assert adapter.client is model.client


def test_llm_adapter_getattr_missing_raises():
    adapter = _ConcreteLLMAdapter(_ctx())
    adapter._model = None
    with pytest.raises(AttributeError, match="nope"):
        _ = adapter.nope


def test_llm_adapter_getattr_dunder_raises():
    adapter = _ConcreteLLMAdapter(_ctx())
    with pytest.raises(AttributeError, match="__wrapped__"):
        _ = adapter.__wrapped__


@pytest.mark.asyncio
async def test_llm_adapter_stream_not_implemented():
    adapter = _ConcreteLLMAdapter(_ctx())
    with pytest.raises(NotImplementedError):
        await adapter.stream(LLMRequest(messages=[]))


def test_llm_adapter_build_model_not_implemented():
    adapter = _ConcreteLLMAdapter(_ctx())
    with pytest.raises(NotImplementedError):
        adapter._build_model()


# ---- OpenAILLMAdapter ----


def test_openai_llm_init():
    adapter = OpenAILLMAdapter(_ctx(timeout_seconds=12.0, ssl_verify=False))
    assert adapter._base_url == "https://llm.example.com/v1"
    assert adapter._api_key == "key-1"
    assert adapter._ssl_verify is False
    assert adapter._timeout == 12.0


def test_openai_llm_init_default_timeout():
    adapter = OpenAILLMAdapter(_ctx(timeout_seconds=None))
    assert adapter._timeout == 30.0


def test_openai_llm_build_model(monkeypatch):
    adapter = OpenAILLMAdapter(
        _ctx(
            temperature=0.3,
            top_p=0.9,
            stream=True,
            max_output_tokens=64,
            display_name="dn",
            observer="obs",
            timeout_seconds=5.0,
        )
    )
    fake = MagicMock()
    monkeypatch.setattr("nexent.core.gateway.modality.llm.openai.OpenAIModel", fake)
    adapter._build_model()
    fake.assert_called_once()
    kwargs = fake.call_args[1]
    assert kwargs["observer"] == "obs"
    assert kwargs["model_id"] == "llm-x"
    assert kwargs["api_base"] == "https://llm.example.com/v1"
    assert kwargs["api_key"] == "key-1"
    assert kwargs["model_factory"] == "openai"
    assert kwargs["display_name"] == "dn"
    assert kwargs["temperature"] == 0.3
    assert kwargs["top_p"] == 0.9
    assert kwargs["stream"] is True
    assert kwargs["max_output_tokens"] == 64
    assert adapter._model is fake.return_value


def test_openai_llm_build_model_omits_unset_tunables(monkeypatch):
    adapter = OpenAILLMAdapter(_ctx())
    fake = MagicMock()
    monkeypatch.setattr("nexent.core.gateway.modality.llm.openai.OpenAIModel", fake)
    adapter._build_model()
    kwargs = fake.call_args[1]
    assert "temperature" not in kwargs
    assert "top_p" not in kwargs
    assert "stream" not in kwargs


@pytest.mark.asyncio
async def test_openai_llm_invoke(monkeypatch):
    adapter = OpenAILLMAdapter(_ctx())
    model = MagicMock(return_value="chatmsg")
    adapter._model = model
    out = await adapter.invoke(
        LLMRequest(messages=[{"role": "user", "content": "x"}], kwargs={"k": 1})
    )
    assert out == "chatmsg"
    model.assert_called_once_with([{"role": "user", "content": "x"}], k=1)


@pytest.mark.asyncio
async def test_openai_llm_invoke_builds_model(monkeypatch):
    adapter = OpenAILLMAdapter(_ctx())
    monkeypatch.setattr("nexent.core.gateway.modality.llm.openai.OpenAIModel", MagicMock())
    await adapter.invoke(LLMRequest(messages=[]))
    assert adapter._model is not None


@pytest.mark.asyncio
async def test_openai_llm_stream(monkeypatch):
    adapter = OpenAILLMAdapter(_ctx())
    model = MagicMock()
    model.model_id = "llm-x"
    model.client.chat.completions.create = AsyncMock(return_value="iterator")
    adapter._model = model
    out = await adapter.stream(
        LLMRequest(messages=[{"role": "user", "content": "x"}], kwargs={"extra": 2})
    )
    assert out == "iterator"
    model.client.chat.completions.create.assert_called_once_with(
        model="llm-x",
        messages=[{"role": "user", "content": "x"}],
        stream=True,
        extra=2,
    )


@pytest.mark.asyncio
async def test_openai_llm_health_check(monkeypatch):
    adapter = OpenAILLMAdapter(_ctx())
    model = MagicMock()
    model.check_connectivity = AsyncMock(return_value=True)
    adapter._model = model
    assert await adapter.health_check() is True


def test_openai_llm_get_model_info():
    info = OpenAILLMAdapter(_ctx(display_name="dn")).get_model_info()
    assert info.model_id == "llm-x"
    assert info.display_name == "dn"
    assert info.provider == "openai"
    assert info.capabilities == {"text": True, "tool_calling": True, "long_context": False}


# ---- OpenAILongContextLLMAdapter ----


def _lctx(**overrides):
    kwargs = {
        "model_name": "llm-x",
        "base_url": "https://llm.example.com/v1",
        "api_key": "key-1",
        "modality": "llm_long_context",
        "factory": "openai",
    }
    kwargs.update(overrides)
    return LongContextLLMContext(**kwargs)


def test_long_context_build_model_defaults(monkeypatch):
    adapter = OpenAILongContextLLMAdapter(_lctx())
    fake = MagicMock()
    monkeypatch.setattr(
        "nexent.core.gateway.modality.llm.openai.OpenAILongContextModel", fake
    )
    adapter._build_model()
    kwargs = fake.call_args[1]
    assert kwargs["max_context_tokens"] == 128000
    assert kwargs["truncation_strategy"] == "start"
    assert kwargs["model_factory"] == "openai"
    assert kwargs["model_id"] == "llm-x"
    assert adapter._model is fake.return_value


def test_long_context_build_model_explicit(monkeypatch):
    adapter = OpenAILongContextLLMAdapter(
        _lctx(max_tokens=8192, truncation_strategy="end", display_name="dn")
    )
    fake = MagicMock()
    monkeypatch.setattr(
        "nexent.core.gateway.modality.llm.openai.OpenAILongContextModel", fake
    )
    adapter._build_model()
    kwargs = fake.call_args[1]
    assert kwargs["max_context_tokens"] == 8192
    assert kwargs["truncation_strategy"] == "end"


def test_long_context_get_model_info():
    info = OpenAILongContextLLMAdapter(_ctx()).get_model_info()
    assert info.capabilities["long_context"] is True
    assert info.capabilities["text"] is True
    assert info.capabilities["tool_calling"] is True


def test_long_context_analyze_long_text_reuses_built_model(monkeypatch):
    adapter = OpenAILongContextLLMAdapter(_lctx())
    prebuilt = MagicMock()
    prebuilt.analyze_long_text.return_value = ("R2", "0%")
    adapter._model = prebuilt
    monkeypatch.setattr(
        "nexent.core.gateway.modality.llm.openai.OpenAILongContextModel", MagicMock()
    )
    result, pct = adapter.analyze_long_text(
        text_content="t",
        system_prompt="s",
        user_prompt="u",
    )
    assert adapter._model is prebuilt
    prebuilt.analyze_long_text.assert_called_once_with(
        text_content="t", system_prompt="s", user_prompt="u"
    )
    assert result == "R2"
    assert pct == "0%"


def test_long_context_analyze_long_text_builds_and_delegates(monkeypatch):
    adapter = OpenAILongContextLLMAdapter(_lctx())
    fake_model = MagicMock()
    fake_model.analyze_long_text.return_value = ("RESULT", "100%")
    monkeypatch.setattr(
        "nexent.core.gateway.modality.llm.openai.OpenAILongContextModel",
        MagicMock(return_value=fake_model),
    )
    result, pct = adapter.analyze_long_text(
        text_content="文档内容",
        system_prompt="sys",
        user_prompt="usr",
    )
    assert adapter._model is fake_model
    fake_model.analyze_long_text.assert_called_once_with(
        text_content="文档内容", system_prompt="sys", user_prompt="usr"
    )
    assert result == "RESULT"
    assert pct == "100%"

@pytest.mark.asyncio
async def test_openai_stream_builds_model_when_missing():
    adapter = OpenAILLMAdapter(_ctx())
    model = MagicMock()
    model.model_id = "llm-x"
    model.client.chat.completions.create = AsyncMock(return_value="iterator")
    adapter._build_model = MagicMock(
        side_effect=lambda: setattr(adapter, "_model", model)
    )
    out = await adapter.stream(LLMRequest(messages=[{"role": "user", "content": "x"}]))
    assert out == "iterator"


@pytest.mark.asyncio
async def test_openai_health_check_builds_model_when_missing():
    adapter = OpenAILLMAdapter(_ctx())
    model = MagicMock()
    model.check_connectivity = AsyncMock(return_value=True)
    adapter._build_model = MagicMock(
        side_effect=lambda: setattr(adapter, "_model", model)
    )
    assert await adapter.health_check() is True
