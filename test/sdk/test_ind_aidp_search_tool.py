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
