import json
from unittest.mock import MagicMock

import httpx
import pytest

import nexent.core.tools.ind_aidp_search_tool as ind_aidp_search_tool_module
from nexent.core.tools.ind_aidp_search_tool import (
    IndependentAidpSearchError,
    IndependentAidpSearchTool,
)


def make_tool(**overrides):
    params = {
        "server_url": "https://aidp.example.com",
        "api_key": "secret-key",
        "tenant_id": "aidp",
        "kds_list": ["kb-1"],
    }
    params.update(overrides)
    return IndependentAidpSearchTool(**params)


def test_query_and_optional_kds_list_are_exposed_to_the_model():
    assert set(IndependentAidpSearchTool.inputs) == {"query", "kds_list"}


def test_default_tenant_and_fixed_kds_payload():
    tool = make_tool()
    payload = tool._payload("question")

    assert tool.tenant_id == "aidp"
    assert payload["kds_list"] == ["kb-1"]
    assert payload["query"] == "question"


def test_rejects_invalid_configuration():
    with pytest.raises(ValueError, match="absolute HTTP"):
        make_tool(server_url="file:///tmp/aidp")
    with pytest.raises(ValueError, match="api_key"):
        make_tool(api_key="")
    with pytest.raises(ValueError, match="1-10"):
        make_tool(kds_list=[])


def test_retries_transient_status_and_uses_bearer(monkeypatch):
    tool = make_tool()
    request = httpx.Request("POST", tool._retrieve_url())
    responses = [
        httpx.Response(503, request=request),
        httpx.Response(200, request=request, json={"result": []}),
    ]
    tool._http_client = MagicMock()
    tool._http_client.post.side_effect = responses
    monkeypatch.setattr(ind_aidp_search_tool_module.time, "sleep", lambda _: None)

    assert tool._execute_request("question") == []
    assert tool._http_client.post.call_count == 2
    assert tool._http_client.post.call_args.kwargs["headers"]["Authorization"] == "Bearer secret-key"


def test_invalid_response_shape_is_rejected():
    tool = make_tool()
    request = httpx.Request("POST", tool._retrieve_url())
    tool._http_client = MagicMock()
    tool._http_client.post.return_value = httpx.Response(200, request=request, json={"result": {}})

    with pytest.raises(IndependentAidpSearchError, match="must be a list"):
        tool._execute_request("question")


def test_image_uses_proxy_builder_and_removes_html_image_tag():
    tool = make_tool(image_url_builder=lambda path: f"/api/ind-aidp/images/signed:{path}")
    ui_results, model_results, image_urls = tool._process_records(
        [{
            "id": "chunk-1",
            "chunk_type": "image",
            "title": "diagram",
            "text": "before <img src='hidden'> after",
            "file_url": "kb-1/images/a.png",
            "score": 0.9,
        }]
    )

    assert "<img" not in ui_results[0]["text"]
    assert "<img" not in model_results[0]["text"]
    assert ui_results[0]["image_key"] == "l1"
    assert "/__aidp_image__/l1" in model_results[0]["text"]
    assert image_urls == ["/api/ind-aidp/images/signed:kb-1/images/a.png"]


def test_forward_can_override_configured_kds_without_mutating_configuration():
    tool = make_tool(kds_list=["kb-fixed"])
    tool._execute_request = MagicMock(return_value=[])

    result = json.loads(tool.forward("question", kds_list=["kb-runtime"]))

    tool._execute_request.assert_called_once_with("question", ["kb-runtime"])
    assert tool.kds_list == ["kb-fixed"]
    assert "No relevant information" in result


def test_forward_uses_configured_kds_when_runtime_value_is_omitted():
    tool = make_tool(kds_list=["kb-fixed"])
    tool._execute_request = MagicMock(return_value=[])

    tool.forward("question")

    tool._execute_request.assert_called_once_with("question", ["kb-fixed"])


def test_parse_kds_list_json_string_and_validation():
    tool_module = ind_aidp_search_tool_module
    assert tool_module._parse_kds_list('["a", "a", "b"]') == ["a", "a", "b"]
    assert tool_module._parse_kds_list([1, 2]) == ["1", "2"]

    with pytest.raises(ValueError, match="JSON"):
        tool_module._parse_kds_list("{not-json")
    with pytest.raises(ValueError, match="JSON"):
        tool_module._parse_kds_list("not-a-list")
    with pytest.raises(ValueError, match="1-10"):
        tool_module._parse_kds_list(123)
    with pytest.raises(ValueError, match="1-10"):
        tool_module._parse_kds_list(list(range(11)))
    with pytest.raises(ValueError, match="empty"):
        tool_module._parse_kds_list(["kb", "  "])


def test_validate_base_url_rejects_bad_inputs():
    tool_module = ind_aidp_search_tool_module
    with pytest.raises(ValueError, match="non-empty"):
        tool_module._validate_base_url("   ")
    with pytest.raises(ValueError, match="credentials"):
        tool_module._validate_base_url("https://u:p@host/x?y=1#f")
    assert tool_module._validate_base_url("  https://aidp.example.com/  ") == (
        "https://aidp.example.com"
    )


def test_init_rejects_invalid_search_method_and_rerank_mode():
    with pytest.raises(ValueError, match="search_method"):
        make_tool(search_method="magic")
    with pytest.raises(ValueError, match="reranking_mode"):
        make_tool(reranking_mode="magic")
    with pytest.raises(ValueError, match="tenant_id"):
        make_tool(tenant_id="")


def test_payload_embeds_rerank_mode_when_reranking_enabled():
    tool = make_tool()
    payload = tool._payload("q", kds_list=["kb-2"])
    assert payload["kds_list"] == ["kb-2"]
    assert payload["reranking_mode"] == "performance"
    assert payload["multi_modal"] is True
    assert 0.0 <= payload["score_threshold"] <= 1.0


def test_exhausts_retries_then_raises(monkeypatch):
    tool = make_tool()
    request = httpx.Request("POST", tool._retrieve_url())
    tool._http_client = MagicMock()
    tool._http_client.post.return_value = httpx.Response(503, request=request)
    monkeypatch.setattr(ind_aidp_search_tool_module.time, "sleep", lambda _: None)

    with pytest.raises(IndependentAidpSearchError, match="HTTP 503"):
        tool._execute_request("question")
    assert tool._http_client.post.call_count == 3


def test_http_status_error_is_wrapped():
    tool = make_tool()
    request = httpx.Request("POST", tool._retrieve_url())
    tool._http_client = MagicMock()
    tool._http_client.post.return_value = httpx.Response(500, request=request)

    with pytest.raises(IndependentAidpSearchError, match="HTTP 500"):
        tool._execute_request("question")


def test_invalid_json_response_is_rejected():
    tool = make_tool()
    request = httpx.Request("POST", tool._retrieve_url())
    tool._http_client = MagicMock()
    tool._http_client.post.return_value = httpx.Response(
        200, request=request, content=b"not-json"
    )

    with pytest.raises(IndependentAidpSearchError, match="invalid JSON"):
        tool._execute_request("question")


def test_forward_rejects_empty_query_and_wraps_http_errors():
    tool = make_tool()
    with pytest.raises(ValueError, match="query"):
        tool.forward("   ")

    tool._execute_request = MagicMock(side_effect=httpx.HTTPError("boom"))
    with pytest.raises(IndependentAidpSearchError, match="HTTP error"):
        tool.forward("question")


def test_process_records_text_chunk_and_failed_builder():
    tool = make_tool(image_url_builder=lambda _: "")
    ui, model, image_urls = tool._process_records(
        [{"chunk_type": "text", "title": "t", "text": "body", "score": 0.5}]
    )
    assert ui[0]["score_details"]["chunk_type"] == "text"
    assert "body" in model[0]["text"]
    assert image_urls == []

    broken = make_tool(image_url_builder=lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
    ui, model, image_urls = broken._process_records(
        [{
            "chunk_type": "image",
            "title": "t",
            "text": "x",
            "file_url": "kb-1/i.png",
            "score": 0.5,
        }]
    )
    assert image_urls == []
    assert ui[0].get("image_key") is None


def test_forward_emits_messages_with_observer():
    tool = make_tool(observer=MagicMock())
    tool._execute_request = MagicMock(
        return_value=[{"chunk_type": "text", "text": "content", "score": 0.8}]
    )

    result = json.loads(tool.forward("question"))

    assert result[0]["text"] == "content"
    assert tool.record_ops == 2
    tool.observer.add_message.call_count >= 2


def test_forward_emits_picture_messages_for_images():
    tool = make_tool(
        observer=MagicMock(),
        image_url_builder=lambda path: f"/proxy/{path}",
    )
    tool._execute_request = MagicMock(
        return_value=[{
            "chunk_type": "image",
            "title": "d",
            "text": "x",
            "file_url": "kb-1/p.png",
            "score": 0.5,
        }]
    )

    tool.forward("question")

    tool.observer.add_message.assert_any_call(
        "",
        ind_aidp_search_tool_module.ProcessType.PICTURE_WEB,
        json.dumps({"images_url": ["/proxy/kb-1/p.png"]}, ensure_ascii=False),
    )
