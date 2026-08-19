"""Unit tests for the embedding modality adapters (base + OpenAI/DashScope/Jina/SiliconFlow)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import requests
from nexent.core.gateway.modality import (
    DashScopeEmbeddingAdapter,
    EmbeddingRequest,
    JinaEmbeddingAdapter,
    OpenAICompatibleEmbeddingAdapter,
    SiliconflowEmbeddingAdapter,
)
from nexent.core.gateway.modality.embedding.embedding_adapter import (
    DEFAULT_IMAGE_MIME_TYPE,
    _detect_image_mime,
    _is_multimodal,
)
from nexent.core.gateway.model_context import EmbeddingContext


def _ctx(**overrides):
    kwargs = {
        "model_name": "embed-model",
        "base_url": "https://emb.example.com/v1",
        "api_key": "key-1",
        "modality": "embedding",
        "factory": "openai",
    }
    kwargs.update(overrides)
    return EmbeddingContext(**kwargs)


def _mctx(**overrides):
    kwargs = {
        "model_name": "mm-model",
        "base_url": "https://mm.example.com/v1",
        "api_key": "key-1",
        "modality": "multi_embedding",
        "factory": "jina",
    }
    kwargs.update(overrides)
    return EmbeddingContext(**kwargs)


def _json_response(data):
    resp = MagicMock()
    resp.json.return_value = data
    return resp


# ---- MIME detection helpers ----


def test_detect_image_mime_png():
    assert _detect_image_mime(b"\x89PNG\r\n\x1a\nrest") == "image/png"


def test_detect_image_mime_jpeg():
    assert _detect_image_mime(b"\xff\xd8\xff\xe0rest") == DEFAULT_IMAGE_MIME_TYPE


def test_detect_image_mime_gif():
    assert _detect_image_mime(b"GIF89a rest") == "image/gif"
    assert _detect_image_mime(b"GIF87a rest") == "image/gif"


def test_detect_image_mime_webp():
    assert _detect_image_mime(b"RIFF\x00\x00\x00\x00WEBP") == "image/webp"


def test_detect_image_mime_bmp():
    assert _detect_image_mime(b"BMrest\x00") == "image/bmp"


def test_detect_image_mime_empty_and_unknown_fallback():
    assert _detect_image_mime(b"") == DEFAULT_IMAGE_MIME_TYPE
    assert _detect_image_mime(b"\x00\x01\x02\x03\x04\x05\x06\x07") == DEFAULT_IMAGE_MIME_TYPE


def test_is_multimodal_detects_dict_lists():
    assert _is_multimodal([{"text": "x"}]) is True
    assert _is_multimodal("text") is False
    assert _is_multimodal([]) is False
    assert _is_multimodal(["a"]) is False


def test_embedding_request_defaults():
    req = EmbeddingRequest(inputs="hi")
    assert req.with_metadata is False
    assert req.timeout is None
    assert req.retries == 3
    assert req.retry_timeout_step == 5.0


# ---- EmbeddingAdapter base ----


def test_embedding_adapter_init_sets_session_and_headers():
    adapter = OpenAICompatibleEmbeddingAdapter(_ctx(ssl_verify=False))
    assert adapter._session.trust_env is False
    assert adapter._headers["Content-Type"] == "application/json"
    assert adapter._headers["Authorization"] == "Bearer key-1"
    assert adapter._ssl_verify is False
    assert adapter._timeout == 30.0


def test_embedding_adapter_model_name():
    adapter = OpenAICompatibleEmbeddingAdapter(_ctx(model_name="m1"))
    assert adapter._model_name == "m1"


def test_make_request_posts_and_parses():
    adapter = OpenAICompatibleEmbeddingAdapter(_ctx())
    adapter._session.post = MagicMock(return_value=_json_response({"ok": True}))
    out = adapter._make_request({"a": 1}, timeout=1.5)
    assert out == {"ok": True}
    _, kwargs = adapter._session.post.call_args
    assert kwargs["json"] == {"a": 1}
    assert kwargs["timeout"] == 1.5
    assert kwargs["verify"] is True


def test_make_request_raises_on_http_error():
    adapter = OpenAICompatibleEmbeddingAdapter(_ctx())
    resp = MagicMock()
    resp.raise_for_status.side_effect = requests.exceptions.HTTPError("400")
    adapter._session.post = MagicMock(return_value=resp)
    with pytest.raises(requests.exceptions.HTTPError):
        adapter._make_request({})


def test_retry_returns_empty_for_zero_attempts():
    adapter = OpenAICompatibleEmbeddingAdapter(_ctx())
    assert adapter._retry(0, 1.0, 1.0, lambda t: 1, "X") == []


def test_retry_raises_after_all_attempts():
    adapter = OpenAICompatibleEmbeddingAdapter(_ctx())

    def boom(timeout):
        raise requests.exceptions.Timeout()

    with pytest.raises(requests.exceptions.Timeout):
        adapter._retry(2, 1.0, 1.0, boom, "X")


@pytest.mark.asyncio
async def test_embedding_health_check_true():
    adapter = OpenAICompatibleEmbeddingAdapter(_ctx())
    adapter.dimension_check = AsyncMock(return_value=[[1.0]])
    assert await adapter.health_check() is True


@pytest.mark.asyncio
async def test_embedding_health_check_false():
    adapter = OpenAICompatibleEmbeddingAdapter(_ctx())
    adapter.dimension_check = AsyncMock(side_effect=RuntimeError("boom"))
    assert await adapter.health_check() is False


# ---- OpenAI-compatible text embedding adapter ----


def test_openai_prepare_input_string_and_list():
    adapter = OpenAICompatibleEmbeddingAdapter(_ctx())
    assert adapter._prepare_input("hi") == {"model": "embed-model", "input": ["hi"]}
    assert adapter._prepare_input(["a", "b"]) == {"model": "embed-model", "input": ["a", "b"]}


def test_openai_get_embeddings_success():
    adapter = OpenAICompatibleEmbeddingAdapter(_ctx())
    adapter._make_request = MagicMock(return_value={"data": [{"embedding": [0.1, 0.2]}]})
    out = adapter.get_embeddings("hello")
    assert out == [[0.1, 0.2]]
    data = adapter._make_request.call_args[0][0]
    assert data["model"] == "embed-model"
    assert data["input"] == ["hello"]


def test_openai_get_embeddings_with_metadata():
    adapter = OpenAICompatibleEmbeddingAdapter(_ctx())
    adapter._make_request = MagicMock(return_value={"data": [{"embedding": [1.0]}]})
    out = adapter.get_embeddings("hello", with_metadata=True)
    assert out == {"data": [{"embedding": [1.0]}]}


def test_openai_get_embeddings_retries_on_timeout():
    adapter = OpenAICompatibleEmbeddingAdapter(_ctx())
    adapter._make_request = MagicMock(
        side_effect=[requests.exceptions.Timeout(), {"data": [{"embedding": [9.0]}]}]
    )
    out = adapter.get_embeddings("hello", retries=1, retry_timeout_step=1.0)
    assert out == [[9.0]]


def test_openai_get_embeddings_exhausts_retries():
    adapter = OpenAICompatibleEmbeddingAdapter(_ctx())
    adapter._make_request = MagicMock(side_effect=requests.exceptions.Timeout())
    with pytest.raises(requests.exceptions.Timeout):
        adapter.get_embeddings("hello", retries=1, retry_timeout_step=1.0)


@pytest.mark.asyncio
async def test_openai_dimension_check_success():
    adapter = OpenAICompatibleEmbeddingAdapter(_ctx())
    adapter.get_embeddings = MagicMock(return_value=[[0.25]])
    out = await adapter.dimension_check(timeout=2.0)
    assert out == [[0.25]]


@pytest.mark.asyncio
async def test_openai_dimension_check_timeout():
    adapter = OpenAICompatibleEmbeddingAdapter(_ctx())
    adapter.get_embeddings = MagicMock(side_effect=requests.exceptions.Timeout())
    assert await adapter.dimension_check(timeout=2.0) == []


@pytest.mark.asyncio
async def test_openai_dimension_check_connection_error():
    adapter = OpenAICompatibleEmbeddingAdapter(_ctx())
    adapter.get_embeddings = MagicMock(side_effect=requests.exceptions.ConnectionError())
    assert await adapter.dimension_check(timeout=2.0) == []


@pytest.mark.asyncio
async def test_openai_dimension_check_other_error():
    adapter = OpenAICompatibleEmbeddingAdapter(_ctx())
    adapter.get_embeddings = MagicMock(side_effect=RuntimeError("boom"))
    assert await adapter.dimension_check(timeout=2.0) == []


@pytest.mark.asyncio
async def test_openai_invoke():
    adapter = OpenAICompatibleEmbeddingAdapter(_ctx())
    adapter.get_embeddings = MagicMock(return_value=[[0.5]])
    out = await adapter.invoke(EmbeddingRequest(inputs=["a"]))
    assert out == [[0.5]]


def test_openai_get_model_info():
    info = OpenAICompatibleEmbeddingAdapter(_ctx(display_name="dn")).get_model_info()
    assert info.model_id == "embed-model"
    assert info.display_name == "dn"
    assert info.provider == "openai"
    assert info.capabilities == {"text": True, "multimodal": False}


# ---- multimodal embedding path (_MultimodalEmbeddingAdapter) ----


def test_multimodal_get_embeddings_string_delegates():
    adapter = JinaEmbeddingAdapter(_mctx())
    adapter.get_multimodal_embeddings = MagicMock(return_value=[[0.1]])
    assert adapter.get_embeddings("hello") == [[0.1]]
    adapter.get_multimodal_embeddings.assert_called_once_with(
        [{"text": "hello"}], False, None, 3, 5.0
    )


def test_multimodal_get_embeddings_list_delegates():
    adapter = JinaEmbeddingAdapter(_mctx())
    adapter.get_multimodal_embeddings = MagicMock(return_value=[[0.1]])
    adapter.get_embeddings(["a", "b"])
    adapter.get_multimodal_embeddings.assert_called_once_with(
        [{"text": "a"}, {"text": "b"}], False, None, 3, 5.0
    )


def test_multimodal_get_multimodal_embeddings_success():
    adapter = JinaEmbeddingAdapter(_mctx())
    adapter._prepare_multimodal_input = MagicMock(return_value={"model": "mm", "input": []})
    adapter._extract_embeddings = MagicMock(return_value=[[0.5]])
    adapter._make_request = MagicMock(return_value={"data": []})
    out = adapter.get_multimodal_embeddings([{"text": "x"}])
    assert out == [[0.5]]


def test_multimodal_with_metadata_returns_raw_response():
    adapter = JinaEmbeddingAdapter(_mctx())
    adapter._prepare_multimodal_input = MagicMock(return_value={})
    adapter._extract_embeddings = MagicMock(return_value=[])
    adapter._make_request = MagicMock(return_value={"raw": True})
    out = adapter.get_multimodal_embeddings([{"text": "x"}], with_metadata=True)
    assert out == {"raw": True}
    adapter._extract_embeddings.assert_not_called()


@pytest.mark.asyncio
async def test_multimodal_dimension_check_success():
    adapter = JinaEmbeddingAdapter(_mctx())
    adapter.get_multimodal_embeddings = MagicMock(return_value=[[0.1]])
    out = await adapter.dimension_check(timeout=1.0)
    assert out == [[0.1]]


@pytest.mark.asyncio
async def test_multimodal_dimension_check_timeout():
    adapter = DashScopeEmbeddingAdapter(_mctx(factory="dashscope"))
    adapter.get_multimodal_embeddings = MagicMock(side_effect=requests.exceptions.Timeout())
    assert await adapter.dimension_check(timeout=1.0) == []


@pytest.mark.asyncio
async def test_multimodal_dimension_check_connection_error():
    adapter = DashScopeEmbeddingAdapter(_mctx(factory="dashscope"))
    adapter.get_multimodal_embeddings = MagicMock(side_effect=requests.exceptions.ConnectionError())
    assert await adapter.dimension_check(timeout=1.0) == []


@pytest.mark.asyncio
async def test_multimodal_dimension_check_other_error():
    adapter = SiliconflowEmbeddingAdapter(_mctx(factory="siliconflow"))
    adapter.get_multimodal_embeddings = MagicMock(side_effect=RuntimeError("boom"))
    assert await adapter.dimension_check(timeout=1.0) == []


@pytest.mark.asyncio
async def test_multimodal_invoke_multimodal_inputs():
    adapter = JinaEmbeddingAdapter(_mctx())
    adapter.get_multimodal_embeddings = MagicMock(return_value=[[0.2]])
    out = await adapter.invoke(EmbeddingRequest(inputs=[{"text": "x"}], timeout=1.0))
    assert out == [[0.2]]


@pytest.mark.asyncio
async def test_multimodal_invoke_text_inputs():
    adapter = JinaEmbeddingAdapter(_mctx())
    adapter.get_embeddings = MagicMock(return_value=[[0.2]])
    out = await adapter.invoke(EmbeddingRequest(inputs="hi"))
    assert out == [[0.2]]


# ---- vendor-specific request building / extraction ----


def test_dashscope_prepare_multimodal_input():
    adapter = DashScopeEmbeddingAdapter(_mctx(factory="dashscope"))
    out = adapter._prepare_multimodal_input(
        [{"text": "hi"}, {"image": b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00IEND"}]
    )
    assert out["model"] == "mm-model"
    contents = out["input"]["contents"]
    assert contents[0] == {"text": "hi"}
    assert contents[1]["image"].startswith("data:image/png;base64,")


def test_dashscope_prepare_multimodal_input_passthrough_image_str():
    adapter = DashScopeEmbeddingAdapter(_mctx(factory="dashscope"))
    out = adapter._prepare_multimodal_input([{"image": "https://img/1.png"}])
    assert out["input"]["contents"] == [{"image": "https://img/1.png"}]


def test_dashscope_extract_embeddings():
    adapter = DashScopeEmbeddingAdapter(_mctx(factory="dashscope"))
    resp = {"output": {"embeddings": [{"embedding": [1.0, 2.0]}]}}
    assert adapter._extract_embeddings(resp) == [[1.0, 2.0]]


def test_dashscope_test_inputs():
    adapter = DashScopeEmbeddingAdapter(_mctx(factory="dashscope"))
    inputs = adapter._test_inputs()
    assert inputs[0] == {"text": "Hello, nexent!"}
    assert inputs[1]["image"].startswith("data:image/png;base64,")


def test_dashscope_get_model_info():
    info = DashScopeEmbeddingAdapter(_mctx(factory="dashscope")).get_model_info()
    assert info.provider == "dashscope"
    assert info.capabilities == {"text": True, "multimodal": True}


def test_jina_prepare_multimodal_input():
    adapter = JinaEmbeddingAdapter(_mctx())
    out = adapter._prepare_multimodal_input(
        [{"text": "hi"}, {"image": b"\xff\xd8\xff\xe0\x00\x00\x00"}]
    )
    assert out["model"] == "mm-model"
    assert out["truncate"] is True
    assert out["input"][0] == {"text": "hi"}
    assert out["input"][1]["image"].startswith("data:image/jpeg;base64,")


def test_jina_extract_embeddings():
    adapter = JinaEmbeddingAdapter(_mctx())
    resp = {"data": [{"embedding": [3.0]}, {"embedding": [4.0]}]}
    assert adapter._extract_embeddings(resp) == [[3.0], [4.0]]


def test_jina_test_inputs():
    adapter = JinaEmbeddingAdapter(_mctx())
    inputs = adapter._test_inputs()
    assert inputs[0] == {"text": "Hello, nexent!"}
    assert inputs[1]["image"].startswith("data:image/png;base64,")


def test_jina_get_model_info():
    info = JinaEmbeddingAdapter(_mctx()).get_model_info()
    assert info.provider == "jina"
    assert info.capabilities == {"text": True, "multimodal": True}


def test_siliconflow_prepare_multimodal_input():
    adapter = SiliconflowEmbeddingAdapter(_mctx(factory="siliconflow"))
    out = adapter._prepare_multimodal_input(
        [{"text": "hi"}, {"image": b"GIF89a\x00\x00\x00"}]
    )
    assert out["model"] == "mm-model"
    assert out["input"][0] == "hi"
    assert out["input"][1]["image"].startswith("data:image/gif;base64,")


def test_siliconflow_extract_embeddings():
    adapter = SiliconflowEmbeddingAdapter(_mctx(factory="siliconflow"))
    resp = {"data": [{"embedding": [7.0]}]}
    assert adapter._extract_embeddings(resp) == [[7.0]]


def test_siliconflow_test_inputs_are_raw_bytes():
    adapter = SiliconflowEmbeddingAdapter(_mctx(factory="siliconflow"))
    inputs = adapter._test_inputs()
    assert inputs[0] == {"text": "Hello, nexent!"}
    assert isinstance(inputs[1]["image"], bytes)


def test_siliconflow_get_model_info():
    info = SiliconflowEmbeddingAdapter(_mctx(factory="siliconflow")).get_model_info()
    assert info.provider == "siliconflow"
    assert info.capabilities == {"text": True, "multimodal": True}

def test_jina_prepare_multimodal_input_passthrough_unknown_item():
    adapter = JinaEmbeddingAdapter(_mctx())
    out = adapter._prepare_multimodal_input([{"text": "hi"}, {"other": "x"}])
    assert out["input"] == [{"text": "hi"}, {"other": "x"}]

def test_siliconflow_prepare_multimodal_input_passthrough_unknown_item():
    adapter = SiliconflowEmbeddingAdapter(_mctx(factory="siliconflow"))
    out = adapter._prepare_multimodal_input(
        [{"text": "hi"}, {"image": b"GIF89a\x00\x00\x00"}, {"other": "x"}]
    )
    assert out["input"][2] == {"other": "x"}


def test_jina_prepare_multimodal_input_passthrough_image_url():
    adapter = JinaEmbeddingAdapter(_mctx())
    out = adapter._prepare_multimodal_input(
        [{"text": "hi"}, {"image": "https://example.com/a.png"}]
    )
    assert out["input"][1] == {"image": "https://example.com/a.png"}


def test_siliconflow_prepare_multimodal_input_passthrough_image_url():
    adapter = SiliconflowEmbeddingAdapter(_mctx(factory="siliconflow"))
    out = adapter._prepare_multimodal_input(
        [{"text": "hi"}, {"image": "https://example.com/a.png"}]
    )
    assert out["input"][1] == {"image": "https://example.com/a.png"}
