"""Unit tests for the rerank modality adapters (base + OpenAI/Jina/Cohere)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import requests
from nexent.core.gateway.modality import (
    CohereRerankAdapter,
    JinaRerankAdapter,
    OpenAICompatibleRerankAdapter,
    RerankRequest,
)
from nexent.core.gateway.modality.rerank.rerank_adapter import _apply_defaults
from nexent.core.gateway.model_context import ModelContext


def _ctx(**overrides):
    kwargs = {
        "model_name": "rr-model",
        "base_url": "https://rr.example.com/v1",
        "api_key": "key-1",
        "modality": "rerank",
        "factory": "openai",
    }
    kwargs.update(overrides)
    return ModelContext(**kwargs)


def test_rerank_request_defaults():
    req = RerankRequest(query="q", documents=["a"])
    assert req.query == "q"
    assert req.documents == ["a"]
    assert req.top_n is None


def test_apply_defaults_returns_same_context_when_fully_set():
    ctx = _ctx()
    out = _apply_defaults(ctx, "https://default/", "default-model")
    assert out is ctx
    assert ctx.base_url == "https://rr.example.com/v1"


def test_apply_defaults_fills_missing_without_mutating():
    ctx = _ctx(base_url="", model_name="")
    out = _apply_defaults(ctx, "https://default/", "default-model")
    assert out is not ctx
    assert out.base_url == "https://default/"
    assert out.model_name == "default-model"
    assert ctx.base_url == ""
    assert ctx.model_name == ""


def test_apply_defaults_fills_partial():
    ctx = _ctx(base_url="")
    out = _apply_defaults(ctx, "https://default/", "default-model")
    assert out.base_url == "https://default/"
    assert out.model_name == "rr-model"


def test_jina_defaults_applied():
    adapter = JinaRerankAdapter(_ctx(base_url="", model_name=""))
    assert adapter._base_url == "https://api.jina.ai/v1/rerank"
    assert adapter._model_name == "jina-rerank-v2-base"
    assert adapter.factory == "jina"


def test_cohere_defaults_applied():
    adapter = CohereRerankAdapter(_ctx(base_url="", model_name=""))
    assert adapter._base_url == "https://api.cohere.ai/v1/rerank"
    assert adapter._model_name == "rerank-multilingual-v3.0"
    assert adapter.factory == "cohere"


def test_prepare_request_flat_format():
    adapter = OpenAICompatibleRerankAdapter(_ctx())
    data = adapter._prepare_request("q", ["a", "b"], top_n=1)
    assert data == {
        "model": "rr-model",
        "query": "q",
        "documents": ["a", "b"],
        "top_n": 1,
    }


def test_prepare_request_flat_default_top_n_is_doc_count():
    adapter = OpenAICompatibleRerankAdapter(_ctx())
    data = adapter._prepare_request("q", ["a", "b"])
    assert data["top_n"] == 2


def test_prepare_request_dashscope_wrapper():
    adapter = OpenAICompatibleRerankAdapter(
        _ctx(base_url="https://dashscope.example.com/v1")
    )
    data = adapter._prepare_request("q", ["a", "b"])
    assert data["input"] == {"query": "q", "documents": ["a", "b"]}
    assert data["parameters"] == {"top_n": 2}


def test_make_request_posts_and_parses(monkeypatch):
    adapter = OpenAICompatibleRerankAdapter(_ctx())
    resp = MagicMock()
    resp.json.return_value = {"ok": True}
    monkeypatch.setattr("requests.post", MagicMock(return_value=resp))
    out = adapter._make_request({"a": 1}, timeout=1.0)
    assert out == {"ok": True}


def test_make_request_raises_on_http_error(monkeypatch):
    adapter = OpenAICompatibleRerankAdapter(_ctx())
    resp = MagicMock()
    resp.raise_for_status.side_effect = requests.exceptions.HTTPError("400")
    monkeypatch.setattr("requests.post", MagicMock(return_value=resp))
    with pytest.raises(requests.exceptions.HTTPError):
        adapter._make_request({})


def test_rerank_empty_documents_short_circuits():
    adapter = OpenAICompatibleRerankAdapter(_ctx())
    assert adapter.rerank("q", []) == []


def test_rerank_success():
    adapter = OpenAICompatibleRerankAdapter(_ctx())
    adapter._make_request = MagicMock(
        return_value={
            "results": [
                {"index": 1, "relevance_score": 0.9, "document": "doc"}
            ]
        }
    )
    out = adapter.rerank("q", ["doc"])
    assert out == [{"index": 1, "relevance_score": 0.9, "document": "doc"}]


def test_rerank_retries_on_timeout_then_succeeds():
    adapter = OpenAICompatibleRerankAdapter(_ctx())
    adapter._make_request = MagicMock(
        side_effect=[
            requests.exceptions.Timeout(),
            {"results": [{"index": 0, "relevance_score": 1.0, "document": "a"}]},
        ]
    )
    out = adapter.rerank("q", ["a"])
    assert out[0]["document"] == "a"
    assert adapter._make_request.call_count == 2


def test_rerank_exhausts_timeout_retries():
    adapter = OpenAICompatibleRerankAdapter(_ctx())
    adapter._make_request = MagicMock(side_effect=requests.exceptions.Timeout())
    with pytest.raises(requests.exceptions.Timeout):
        adapter.rerank("q", ["a"])


def test_rerank_request_error_raises_immediately():
    adapter = OpenAICompatibleRerankAdapter(_ctx())
    adapter._make_request = MagicMock(
        side_effect=requests.exceptions.RequestException("bad")
    )
    with pytest.raises(requests.exceptions.RequestException):
        adapter.rerank("q", ["a"])


def test_normalize_results_flat_with_dict_document():
    adapter = OpenAICompatibleRerankAdapter(_ctx())
    out = adapter._normalize_results(
        {
            "results": [
                {"index": 0, "relevance_score": 0.5, "document": {"text": "d1"}}
            ]
        }
    )
    assert out == [{"index": 0, "relevance_score": 0.5, "document": "d1"}]


def test_normalize_results_nested_output_with_scalar_document():
    adapter = OpenAICompatibleRerankAdapter(_ctx())
    out = adapter._normalize_results(
        {
            "output": {
                "results": [{"index": 2, "relevance_score": 0.1, "document": "plain"}]
            }
        }
    )
    assert out == [{"index": 2, "relevance_score": 0.1, "document": "plain"}]


@pytest.mark.asyncio
async def test_rerank_async():
    adapter = OpenAICompatibleRerankAdapter(_ctx())
    adapter.rerank = MagicMock(return_value=[{"index": 0, "relevance_score": 1.0, "document": "a"}])
    out = await adapter.rerank_async("q", ["a"], top_n=1)
    assert out == [{"index": 0, "relevance_score": 1.0, "document": "a"}]
    adapter.rerank.assert_called_once_with("q", ["a"], 1)


@pytest.mark.asyncio
async def test_connectivity_check_success():
    adapter = OpenAICompatibleRerankAdapter(_ctx())
    adapter.rerank = MagicMock(return_value=[])
    assert await adapter.connectivity_check() is True


@pytest.mark.asyncio
async def test_connectivity_check_timeout():
    adapter = OpenAICompatibleRerankAdapter(_ctx())
    adapter.rerank = MagicMock(side_effect=requests.exceptions.Timeout())
    assert await adapter.connectivity_check() is False


@pytest.mark.asyncio
async def test_connectivity_check_connection_error():
    adapter = OpenAICompatibleRerankAdapter(_ctx())
    adapter.rerank = MagicMock(side_effect=requests.exceptions.ConnectionError())
    assert await adapter.connectivity_check() is False


@pytest.mark.asyncio
async def test_connectivity_check_other_error():
    adapter = OpenAICompatibleRerankAdapter(_ctx())
    adapter.rerank = MagicMock(side_effect=RuntimeError("boom"))
    assert await adapter.connectivity_check() is False


@pytest.mark.asyncio
async def test_rerank_invoke():
    adapter = OpenAICompatibleRerankAdapter(_ctx())
    adapter.rerank = MagicMock(return_value=[])
    out = await adapter.invoke(RerankRequest(query="q", documents=["a"], top_n=1))
    assert out == []
    adapter.rerank.assert_called_once_with("q", ["a"], 1)


@pytest.mark.asyncio
async def test_rerank_health_check():
    adapter = OpenAICompatibleRerankAdapter(_ctx())
    adapter.connectivity_check = AsyncMock(return_value=True)
    assert await adapter.health_check() is True


def test_rerank_get_model_info():
    info = OpenAICompatibleRerankAdapter(_ctx(display_name="dn")).get_model_info()
    assert info.model_id == "rr-model"
    assert info.display_name == "dn"
    assert info.provider == "openai"
    assert info.capabilities == {"rerank": True}
