# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Uniform retrieval errors and retry logs at the upstream response boundary."""
import json
import logging
from unittest.mock import Mock

import httpx
import pytest
from nexent.core.ext_components.aidp import retrieval_client as client


def response(status=200, **kwargs):
    return httpx.Response(status, request=httpx.Request("POST", "https://aidp.invalid/retrieval"), **kwargs)


@pytest.mark.parametrize("statuses, waits", [
    ([200], []), ([503, 200], [0.5]), ([502, 504, 200], [0.5, 1.0]),
])
def test_retries_return_records_and_log_each_actual_retry(mocker, caplog, statuses, waits):
    transport = Mock()
    records = [{"text_id": "chunk", "score": 0}]
    transport.post.side_effect = [response(status, json={"result": records}) for status in statuses]
    sleep = mocker.patch.object(client.time, "sleep")
    with caplog.at_level(logging.WARNING, logger=client.__name__):
        assert client.post_retrieval(transport, "https://aidp.invalid/retrieval", "secret-key", {
            "query": "private question", "kds_list": ["kb"],
        }) == records
    assert transport.post.call_count == len(statuses)
    assert [call.args[0] for call in sleep.call_args_list] == waits
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == len(waits)
    for index, record in enumerate(warnings):
        assert f"HTTP {statuses[index]}" in record.message
        assert f"attempt {index + 1}/3" in record.message
        assert f"{waits[index]:.1f} seconds" in record.message
    assert "secret-key" not in caplog.text
    assert "private question" not in caplog.text


@pytest.mark.parametrize("status, attempts", [(400, 1), (401, 1), (403, 1), (500, 1), (502, 3), (503, 3), (504, 3)])
def test_http_failure_is_uniform_and_logged_once(mocker, caplog, status, attempts):
    transport = Mock()
    transport.post.return_value = response(status)
    sleep = mocker.patch.object(client.time, "sleep")
    with caplog.at_level(logging.WARNING, logger=client.__name__):
        with pytest.raises(client.AidpRetrievalError, match=f"HTTP {status} after {attempts} attempts"):
            client.post_retrieval(transport, "https://aidp.invalid/retrieval", "secret", {})
    assert transport.post.call_count == attempts
    assert sleep.call_count == attempts - 1
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == attempts - 1
    assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 1
    assert "upload" not in caplog.text
    assert "warming" not in caplog.text


@pytest.mark.parametrize("body", [{}, {"result": None}, {"result": {}}, [], None])
def test_missing_or_invalid_result_is_an_error_without_retry(mocker, caplog, body):
    transport = Mock()
    transport.post.return_value = response(content=json.dumps(body), headers={"content-type": "application/json"})
    sleep = mocker.patch.object(client.time, "sleep")
    with pytest.raises(client.AidpRetrievalError, match="result.*must be a list"):
        client.post_retrieval(transport, "https://aidp.invalid/retrieval", "secret", {})
    assert transport.post.call_count == 1
    sleep.assert_not_called()
    assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 1


def test_empty_results_are_valid():
    transport = Mock()
    transport.post.return_value = response(json={"result": []})
    assert client.post_retrieval(transport, "https://aidp.invalid/retrieval", "secret", {}) == []


def test_invalid_json_is_not_retried(mocker, caplog):
    transport = Mock()
    transport.post.return_value = response(content=b"not-json")
    sleep = mocker.patch.object(client.time, "sleep")
    with pytest.raises(client.AidpRetrievalError, match="invalid JSON"):
        client.post_retrieval(transport, "https://aidp.invalid/retrieval", "secret", {})
    assert transport.post.call_count == 1
    sleep.assert_not_called()
    assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 1


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("private question"), httpx.ConnectError("secret-key")])
def test_network_failure_is_not_retried_or_exposed(mocker, caplog, failure):
    transport = Mock()
    transport.post.side_effect = failure
    sleep = mocker.patch.object(client.time, "sleep")
    with pytest.raises(client.AidpRetrievalError, match="AIDP HTTP error") as error:
        client.post_retrieval(transport, "https://aidp.invalid/retrieval", "secret-key", {})
    assert error.value.__cause__ is failure
    assert transport.post.call_count == 1
    sleep.assert_not_called()
    assert "private question" not in str(error.value) + caplog.text
    assert "secret-key" not in str(error.value) + caplog.text
    assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 1


def test_wrappers_share_one_error_type_and_complete_parameter_descriptions():
    import inspect

    from nexent.core.ext_components.aidp.aidp_search_tool import (
        AidpSearchError,
        AidpSearchTool,
    )
    from nexent.core.tools.ind_aidp_search_tool import (
        IndependentAidpSearchError,
        IndependentAidpSearchTool,
    )

    assert AidpSearchError is IndependentAidpSearchError is client.AidpRetrievalError
    advanced = (
        "vector_candidates", "full_text_candidates", "hybrid_top_k", "graph_top_k",
        "vector_score_threshold", "full_text_score_threshold", "graph_score_threshold",
        "graph_reranking_enable", "query_expansion_enable",
    )
    for tool in (AidpSearchTool, IndependentAidpSearchTool):
        for field in advanced:
            description = tool.init_param_descriptions[field]["description_zh"]
            assert any("\u4e00" <= character <= "\u9fff" for character in description), field
        for field in ("vector_candidates", "full_text_candidates"):
            assert "跟随" in tool.init_param_descriptions[field]["description_zh"]
        for field in ("hybrid_top_k", "graph_top_k"):
            description = tool.init_param_descriptions[field]["description_zh"]
            assert "0" in description and "总返回上限" in description
        params = inspect.signature(tool.__init__).parameters
        assert "graph_search" in params["search_method"].default.description
        assert "jargon_coverage" in params["reranking_mode"].default.description
