# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from unittest.mock import Mock

import httpx
import pytest

from nexent.core.tools import outcrawl_search_tool as module
from nexent.core.tools.outcrawl_search_tool import OutcrawlSearchTool
from nexent.core.utils.observer import ProcessType


def hit(rank=1, **extra):
    return {"url": f"https://example.com/{rank}", "title": f"Title {rank}", "snippet": f"Snippet {rank}",
            "rank": rank, **extra}


@pytest.fixture
def wire(mocker):
    post = mocker.patch.object(module.httpx, "post")
    post.return_value = httpx.Response(200, json={"hits": [hit(1), hit(2)], "usage": {"credits": "1"}})
    return post


def tool(**kwargs):
    return OutcrawlSearchTool(outcrawl_api_key="synthetic-key", **kwargs)


def test_default_request_and_observer_mapping(wire):
    observer = Mock()
    data = json.loads(tool(observer=observer).forward(" outcrawl docs "))
    assert wire.call_args.args == ("https://api.outcrawl.ai/v1/search",)
    assert wire.call_args.kwargs["json"] == {"query": "outcrawl docs", "limit": 5}
    assert wire.call_args.kwargs["headers"]["Authorization"] == "Bearer synthetic-key"
    assert data == [
        {"title": "Title 1", "text": "Snippet 1", "index": "q1", "reference_mark": "[[q1]]"},
        {"title": "Title 2", "text": "Snippet 2", "index": "q2", "reference_mark": "[[q2]]"},
    ]
    events = observer.add_message.call_args_list
    assert events[0].args == ("", ProcessType.CARD, json.dumps([{"icon": "search", "text": "outcrawl docs"}]))
    sources = json.loads(next(c.args[2] for c in events if c.args[1] == ProcessType.SEARCH_CONTENT))
    assert sources[0]["url"] == "https://example.com/1"
    assert sources[0]["search_type"] == "outcrawl_search"
    assert sources[0]["tool_sign"] == "q"
    assert [s["cite_index"] for s in sources] == [1, 2]


def test_scrape_content_requests_markdown_and_falls_back_to_snippet(wire):
    wire.return_value = httpx.Response(200, json={"hits": [hit(1, markdown="# Page 1"), hit(2, markdown=" ")]})
    data = json.loads(tool(scrape_content=True).forward("query"))
    assert wire.call_args.kwargs["json"] == {"query": "query", "limit": 5, "scrape": True, "formats": ["markdown"]}
    assert [item["text"] for item in data] == ["# Page 1", "Snippet 2"]


def test_markdown_ignored_when_scrape_disabled(wire):
    wire.return_value = httpx.Response(200, json={"hits": [hit(1, markdown="# Page 1")]})
    assert json.loads(tool().forward("query"))[0]["text"] == "Snippet 1"


def test_cite_index_continues_across_calls_without_observer(wire):
    search = tool()
    search.forward("first")
    data = json.loads(search.forward("second"))
    assert [item["index"] for item in data] == ["q3", "q4"]


def test_hits_without_url_are_dropped_and_title_falls_back_to_url(wire):
    wire.return_value = httpx.Response(200, json={"hits": [{"title": "No URL"}, "bad", hit(3, title="")]})
    data = json.loads(tool().forward("query"))
    assert data == [{"title": "https://example.com/3", "text": "Snippet 3", "index": "q1", "reference_mark": "[[q1]]"}]


@pytest.mark.parametrize("max_results", [1, 20])
def test_max_results_boundaries(wire, max_results):
    wire.return_value = httpx.Response(200, json={"hits": [hit(i) for i in range(1, 25)]})
    data = json.loads(tool(max_results=max_results).forward("query"))
    assert wire.call_args.kwargs["json"]["limit"] == max_results
    assert len(data) == max_results


@pytest.mark.parametrize("config", [
    {"max_results": 0}, {"max_results": 21}, {"max_results": True}, {"max_results": "5"},
    {"scrape_content": "true"}, {"scrape_content": 1},
])
def test_invalid_configuration(config):
    with pytest.raises(ValueError):
        tool(**config)


@pytest.mark.parametrize("key", ["", "  ", None, 42])
def test_missing_api_key(key):
    with pytest.raises(ValueError, match="API key"):
        OutcrawlSearchTool(outcrawl_api_key=key)


@pytest.mark.parametrize("query", ["", "   ", None, 42])
def test_invalid_query_never_requests(wire, query):
    with pytest.raises(ValueError):
        tool().forward(query)
    wire.assert_not_called()


def test_no_results_raises(wire):
    wire.return_value = httpx.Response(200, json={"hits": []})
    with pytest.raises(Exception, match="No results found"):
        tool().forward("query")


def test_http_error_reports_api_message(wire):
    wire.return_value = httpx.Response(401, json={"code": "unauthorized", "message": "authentication failed"})
    with pytest.raises(RuntimeError, match=r"HTTP 401\): authentication failed"):
        tool().forward("query")


def test_http_error_without_json_body(wire):
    wire.return_value = httpx.Response(502, text="Bad Gateway")
    with pytest.raises(RuntimeError, match=r"^Outcrawl search failed \(HTTP 502\)$"):
        tool().forward("query")


def test_transport_error_does_not_leak_key(wire):
    wire.side_effect = httpx.ConnectTimeout("timed out")
    with pytest.raises(RuntimeError, match="ConnectTimeout") as error:
        tool().forward("query")
    assert "synthetic-key" not in str(error.value)


@pytest.mark.parametrize("response", [
    httpx.Response(200, text="not json"), httpx.Response(200, json=[]), httpx.Response(200, json={"hits": None}),
])
def test_invalid_response_raises(wire, response):
    wire.return_value = response
    with pytest.raises(RuntimeError, match="Invalid Outcrawl search response"):
        tool().forward("query")
