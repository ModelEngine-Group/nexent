# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import httpx
import pytest
from nexent.core.tools import deepseek_search_tool as module
from nexent.core.tools.deepseek_search_tool import DeepSeekSearchTool
from nexent.core.utils.observer import ProcessType


def result(score=2, url="https://example.com/article", **extra):
    return {"title": "Title", "url": url, "summary": "Summary", "snippet": "Snippet", "content": "Body",
            "rerank_score": score, "authority": 3, "date": None, **extra}


@pytest.fixture
def wire(mocker):
    client = mocker.patch.object(module.httpx, "Client").return_value.__enter__.return_value
    client.post.return_value = httpx.Response(200, json={"results": [result()]})
    mocker.patch.object(module.time, "sleep")
    return client


def tool(**kwargs):
    return DeepSeekSearchTool(deepseek_api_key="synthetic-key", **kwargs)


def test_default_request_and_observer_mapping(wire):
    observer = Mock()
    search = tool(observer=observer)
    data = json.loads(search.forward(" DeepSeek site:github.com after:2025 "))
    assert wire.post.call_args.kwargs["json"] == {
        "query": "DeepSeek site:github.com after:2025 lang:zh", "count": 10, "need_content": False,
    }
    assert wire.post.call_args.kwargs["headers"]["Authorization"] == "Bearer synthetic-key"
    assert data == [{"title": "Title", "text": "Summary", "index": "o1", "reference_mark": "[[o1]]"}]
    events = observer.add_message.call_args_list
    sources = json.loads(next(c.args[2] for c in events if c.args[1] == ProcessType.SEARCH_CONTENT))
    assert sources[0]["url"] == "https://example.com/article"
    assert sources[0]["score_details"]["deepseek"]["rerank_score"] == 2
    assert sources[0]["published_date"] is None
    assert sources[0]["cite_index"] == 1
    assert {c.args[1] for c in events} == {ProcessType.CARD, ProcessType.SEARCH_CONTENT}


@pytest.mark.parametrize("language,expected", [("zh", "zh"), ("zh-CN", "zh"), ("en", "en"), ("en-US", "en")])
def test_language_normalization_and_existing_operator(wire, language, expected):
    query = 'topic "lang:en literal" site:example.com lang:zh,en'
    tool(language=language).forward(query)
    actual = wire.post.call_args.kwargs["json"]["query"]
    assert actual == f'topic "lang:en literal" site:example.com lang:{expected}'


@pytest.mark.parametrize("query", ["x" * 120, "中" * 120, "😀" * 120])
def test_query_boundary_success(wire, query):
    tool().forward(query)
    assert len(wire.post.call_args.kwargs["json"]["query"]) == 128


@pytest.mark.parametrize("query", ["", "   ", "x" * 121, "😀" * 121, None, 42, "lang:en"])
def test_invalid_query_never_requests(wire, query):
    with pytest.raises(ValueError):
        tool().forward(query)
    wire.post.assert_not_called()


@pytest.mark.parametrize("config", [
    {"max_results": 0}, {"max_results": 51}, {"max_results": True}, {"max_results": 1.5},
    {"only_high_quality": "true"}, {"need_content": 1}, {"max_retries": 3},
    {"timeout_seconds": 0}, {"language": "fr"},
])
def test_invalid_configuration(config):
    with pytest.raises(ValueError):
        tool(**config)


@pytest.mark.parametrize("key", ["", " ", None, 42])
def test_invalid_key(key):
    with pytest.raises(ValueError):
        DeepSeekSearchTool(deepseek_api_key=key)


@pytest.mark.parametrize("enabled,expected", [(False, 3), (True, 2)])
def test_quality_threshold_is_inclusive(wire, enabled, expected):
    wire.post.return_value = httpx.Response(200, json={"results": [
        result(score, f"https://example.com/{i}") for i, score in enumerate([1.49, 1.5, 3])
    ]})
    data = json.loads(tool(only_high_quality=enabled).forward("topic"))
    assert len(data) == expected
    assert data[0]["index"] == "o1"
    assert wire.post.call_count == 1
    assert "only_high_quality" not in wire.post.call_args.kwargs["json"]


def test_quality_precedes_deduplication(wire):
    wire.post.return_value = httpx.Response(200, json={"results": [result(1), result(2, summary="Retained")]})
    assert json.loads(tool(only_high_quality=True).forward("topic"))[0]["text"] == "Retained"


@pytest.mark.parametrize("only_high_quality", [False, True])
def test_stable_score_order_precedes_citation_assignment(wire, only_high_quality):
    rows = [result(score, f"https://example.com/{title}", title=title) for title, score in (
        ("low", 1), ("tie-first", 2), ("highest", 3), ("tie-second", 2), ("boundary", 1.5),
    )]
    rows.insert(2, result(score="invalid", url="https://example.com/invalid"))
    wire.post.return_value = httpx.Response(200, json={"results": rows})
    observer = Mock()
    search = tool(only_high_quality=only_high_quality, observer=observer)
    titles = ["highest", "tie-first", "tie-second", "boundary"]
    if not only_high_quality:
        titles.append("low")
    for start in (1, len(titles) + 1):
        model = json.loads(search.forward("topic"))
        sources = json.loads(observer.add_message.call_args.args[2])
        indices = list(range(start, start + len(titles)))
        assert [item["title"] for item in model] == titles
        assert [item["title"] for item in sources] == titles
        assert [item["url"] for item in sources] == [f"https://example.com/{title}" for title in titles]
        assert [item["cite_index"] for item in sources] == indices
        assert [item["index"] for item in model] == [f"o{index}" for index in indices]
        assert [item["reference_mark"] for item in model] == [f"[[o{index}]]" for index in indices]


def test_score_sort_precedes_result_limit(wire):
    wire.post.return_value = httpx.Response(200, json={"results": [
        result(score, f"https://example.com/{score}", title=str(score)) for score in (1, 2, 3)
    ]})
    assert [item["title"] for item in json.loads(tool(max_results=2).forward("topic"))] == ["3", "2"]


@pytest.mark.parametrize("results", [[], [result(1.49)]])
def test_empty_results_do_not_retry_or_consume_indices(wire, results):
    wire.post.return_value = httpx.Response(200, json={"results": results})
    search = tool(only_high_quality=True)
    assert search.forward("topic") == "[]"
    assert search.record_ops == 1
    wire.post.assert_called_once()


@pytest.mark.parametrize("need_content,extra,expected", [
    (False, {}, "Summary"), (True, {}, "Body"), (True, {"content": ""}, "Summary"),
    (False, {"summary": ""}, "Snippet"), (False, {"summary": "", "snippet": ""}, "Body"),
])
def test_content_fallback(wire, need_content, extra, expected):
    wire.post.return_value = httpx.Response(200, json={"results": [result(**extra)]})
    assert json.loads(tool(need_content=need_content).forward("topic"))[0]["text"] == expected


@pytest.mark.parametrize("need_content,field", [(True, "content"), (False, "summary")])
def test_full_text_and_sequential_indices(wire, need_content, field):
    text = "中😀" * 15000
    wire.post.return_value = httpx.Response(200, json={"results": [result(**{field: text})]})
    observer = Mock()
    search = tool(need_content=need_content, observer=observer)
    assert json.loads(search.forward("topic"))[0]["text"] == text
    sources = json.loads(observer.add_message.call_args.args[2])
    assert sources[0]["text"] == text
    assert "text_truncated" not in sources[0]["score_details"]["deepseek"]
    assert json.loads(search.forward("topic"))[0]["index"] == "o2"


@pytest.mark.parametrize("body", [{}, {"results": None}, {"results": {}}, {"results": [None]},
                                       {"results": [result(score="2")]}, {"results": [result(url="javascript:alert(1)")]}])
def test_invalid_protocol_is_not_empty_success(wire, body):
    wire.post.return_value = httpx.Response(200, json=body)
    search = tool()
    with pytest.raises(RuntimeError, match="response"):
        search.forward("topic")
    assert search.record_ops == 1
    wire.post.assert_called_once()


@pytest.mark.parametrize("score", [None, True, -1, 3.01, float("nan"), float("inf")])
def test_invalid_scores_are_protocol_errors(wire, score):
    wire.post.return_value.json = Mock(return_value={"results": [result(score)]})
    with pytest.raises(RuntimeError, match="response"):
        tool().forward("topic")


@pytest.mark.parametrize("status,retry", [(400, False), (401, False), (402, False), (413, False),
                                         (302, False), (408, True), (429, True), (500, True), (504, True)])
def test_http_error_policy_and_redaction(wire, status, retry, caplog):
    wire.post.return_value = httpx.Response(status, text="synthetic-key PRIVATE RESPONSE")
    observer = Mock()
    search = tool(observer=observer)
    with pytest.raises(RuntimeError) as exc:
        search.forward("topic")
    assert wire.post.call_count == (3 if retry else 1)
    assert "synthetic-key" not in str(exc.value) + caplog.text
    assert "PRIVATE RESPONSE" not in str(exc.value) + caplog.text
    assert search.record_ops == 1
    assert not any(c.args[1] == ProcessType.SEARCH_CONTENT for c in observer.add_message.call_args_list)


def test_retry_then_success_reuses_query(wire):
    wire.post.side_effect = [httpx.ConnectError("synthetic-key"), httpx.Response(200, json={"results": [result()]})]
    assert json.loads(tool().forward("topic"))[0]["index"] == "o1"
    assert len({c.kwargs["json"]["query"] for c in wire.post.call_args_list}) == 1


def test_retry_after_budget(wire):
    wire.post.return_value = httpx.Response(429, headers={"Retry-After": "11"})
    with pytest.raises(RuntimeError):
        tool().forward("topic")
    wire.post.assert_called_once()


def test_parallel_indices_do_not_collide(wire):
    search = tool()
    with ThreadPoolExecutor(max_workers=4) as pool:
        data = list(pool.map(search.forward, ["topic"] * 8))
    assert {json.loads(item)[0]["index"] for item in data} == {f"o{i}" for i in range(1, 9)}


def test_metadata_excludes_runtime_context():
    import inspect

    from management.services.tool.catalog import (
        get_local_tools_classes,
        get_local_tools_description_zh,
    )

    assert DeepSeekSearchTool in get_local_tools_classes()
    metadata = get_local_tools_description_zh()["deepseek_search"]
    names = {param["name"] for param in metadata["params"]}
    assert "only_high_quality" in names
    assert "observer" not in names
    assert "language" not in names
    assert names.isdisjoint({"localization", "max_content_chars"})
    quality = next(param for param in metadata["params"] if param["name"] == "only_high_quality")
    assert not quality["description_zh"].startswith("仅优质内容")
    assert inspect.signature(DeepSeekSearchTool.__init__).parameters["max_results"].default.default == 10
    for key in ("description", "description_zh"):
        description = metadata["inputs"]["query"][key]
        for syntax in ("site:", "-site:", "after:", "before:", "lang:"):
            assert syntax in description


def test_instance_keys_stay_separate_without_localization(wire):
    first = DeepSeekSearchTool(deepseek_api_key="first", max_results=50)
    second = DeepSeekSearchTool(deepseek_api_key="second", language="en")
    first.forward("topic")
    second.forward("topic")
    assert "localization" not in wire.post.call_args_list[0].kwargs["json"]
    assert wire.post.call_args_list[0].kwargs["json"]["count"] == 50
    assert "localization" not in wire.post.call_args_list[1].kwargs["json"]
    assert wire.post.call_args_list[0].kwargs["headers"]["Authorization"] == "Bearer first"
    assert wire.post.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer second"


def test_invalid_json_is_redacted_and_not_retried(wire):
    wire.post.return_value = httpx.Response(200, text="synthetic-key")
    with pytest.raises(RuntimeError, match="response JSON") as error:
        tool().forward("topic")
    assert "synthetic-key" not in str(error.value)
    wire.post.assert_called_once()
