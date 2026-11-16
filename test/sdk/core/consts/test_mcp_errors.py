# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import json
import socket
import ssl
import sys
from unittest.mock import patch

import httpx
import pytest
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from nexent.consts.mcp_errors import (
    MCPConnectionFailure,
    MCPConnectionTimeoutError,
    MCPToolTimeoutError,
    _mcp_sdk_error_type,
    classify_mcp_failure,
    describe_exception_leaf,
    find_mcp_server_url,
    is_mcp_connection_timeout_error,
    is_mcp_timeout_error,
    iter_leaf_exceptions,
    mcp_failure_message,
)


def _task_group(*leaves):
    return BaseExceptionGroup("unhandled errors in a taskgroup", list(leaves))


def _step_wrapped(error):
    """Wrap like the step-level handler: raise ValueError while handling."""
    try:
        raise error
    except BaseException:
        try:
            raise ValueError("Error in interaction: unhandled errors in a taskgroup")
        except ValueError as wrapped:
            return wrapped


def _http_status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "http://mcp.invalid:5011/mcp")
    response = httpx.Response(status_code=status, request=request)
    return httpx.HTTPStatusError(f"Client error '{status}'", request=request, response=response)


LEAF_CASES = [
    (httpx.ConnectError("[Errno 111] Connection refused"), "connection_refused"),
    (ConnectionRefusedError(), "connection_refused"),
    (socket.gaierror("[Errno -2] Name or service not known"), "dns_failure"),
    (_http_status_error(401), "auth_failed"),
    (_http_status_error(403), "auth_failed"),
    (_http_status_error(404), "bad_url"),
    (_http_status_error(405), "transport_mismatch"),
    (_http_status_error(406), "transport_mismatch"),
    (httpx.ReadError("peer closed connection"), "connection_dropped"),
    (
        httpx.RemoteProtocolError("server disconnected without sending a response"),
        "connection_dropped",
    ),
    (ssl.SSLError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"), "tls_error"),
    (json.JSONDecodeError("Expecting value", "<html>", 0), "not_mcp_endpoint"),
    (McpError(ErrorData(code=-32601, message="protocol error", data=None)), "protocol_error"),
    (MCPToolTimeoutError("MCP tool request timed out after 10 seconds"), "timeout"),
    (RuntimeError("Timed out while waiting for response to CallToolRequest"), "timeout"),
]


@pytest.mark.parametrize(("leaf", "category"), LEAF_CASES)
def test_classify_sees_leaf_through_group_and_value_wrapping(leaf, category):
    """Leaf → taskgroup → ValueError: every category is still recognized."""
    classified_category, representative = classify_mcp_failure(_step_wrapped(_task_group(leaf)))

    assert classified_category == category
    assert representative is leaf


def test_cancelled_only_group_classifies_to_nothing():
    error = _task_group(asyncio.CancelledError())

    assert classify_mcp_failure(error) == (None, None)
    assert all(
        not isinstance(node, asyncio.CancelledError) for node in iter_leaf_exceptions(error)
    )


def test_mixed_group_skips_cancellation_leaf():
    leaf = ConnectionRefusedError()
    error = _task_group(asyncio.CancelledError(), leaf)

    category, representative = classify_mcp_failure(error)

    assert category == "connection_refused"
    assert representative is leaf


def test_unclassified_group_returns_representative_leaf():
    leaf = RuntimeError("disk on fire")
    error = _task_group(leaf)

    assert classify_mcp_failure(error) == (None, leaf)
    # Even behind a step-level ValueError wrapper the true leaf wins.
    assert classify_mcp_failure(_step_wrapped(error)) == (None, leaf)


def test_nested_groups_are_reached():
    leaf = _http_status_error(404)
    error = _task_group(_task_group(leaf))

    category, representative = classify_mcp_failure(error)

    assert category == "bad_url"
    assert representative is leaf


def test_self_referencing_chain_is_cycle_safe():
    error = RuntimeError("loop")
    error.__cause__ = error

    assert classify_mcp_failure(error) == (None, error)
    assert not is_mcp_timeout_error(error)


def test_grouped_timeout_is_recognized_by_existing_classifier():
    """Regression: a timeout inside a taskgroup must classify as an MCP timeout."""
    leaf = RuntimeError("Timed out while waiting for response to ClientRequest")
    error = _step_wrapped(_task_group(leaf))

    assert is_mcp_timeout_error(error)
    assert classify_mcp_failure(error)[0] == "timeout"


def test_connection_timeout_classifier_matches_marker_and_client_request():
    """Connection-timeout signals: native marker, ClientRequest text, CallToolRequest exclusion."""
    assert is_mcp_connection_timeout_error(MCPConnectionTimeoutError("native marker"))
    assert is_mcp_connection_timeout_error(
        RuntimeError("Timed out while waiting for response to ClientRequest")
    )
    assert not is_mcp_connection_timeout_error(
        RuntimeError("Timed out while waiting for response to CallToolRequest")
    )


def test_mcp_connection_failure_carries_attribution():
    error = MCPConnectionFailure(url="http://mcp.invalid:5011/mcp", transport="streamable-http")

    assert error.url == "http://mcp.invalid:5011/mcp"
    assert error.transport == "streamable-http"
    assert "http://mcp.invalid:5011/mcp" in str(error)


def test_find_mcp_server_url_digs_through_wrapping():
    leaf = ConnectionRefusedError()
    attributed = MCPConnectionFailure(url="http://a/mcp", transport="sse")
    attributed.__cause__ = leaf
    error = _step_wrapped(_task_group(attributed))

    assert find_mcp_server_url(error) == "http://a/mcp"
    assert find_mcp_server_url(_step_wrapped(_task_group(leaf))) is None


def test_describe_exception_leaf_truncates_long_messages():
    text = describe_exception_leaf(RuntimeError("x" * 500), limit=300)

    assert text.startswith("RuntimeError: ")
    assert len(text.split(": ", 1)[1]) == 300
    assert text.endswith("...")


@pytest.mark.parametrize(
    "category",
    [
        "auth_failed",
        "bad_url",
        "transport_mismatch",
        "connection_dropped",
        "tls_error",
        "not_mcp_endpoint",
        "protocol_error",
        "timeout",
    ],
)
def test_message_table_covers_both_languages(category):
    zh = mcp_failure_message(category, "zh")
    en = mcp_failure_message(category, "en")

    assert zh and en
    assert zh != en


def test_connection_refused_message_includes_server():
    zh = mcp_failure_message("connection_refused", "zh", server="http://a:5011/mcp")
    en = mcp_failure_message("connection_refused", "en", server="http://a:5011/mcp")

    assert zh == (
        "MCP 工具服务连接失败（http://a:5011/mcp 连接被拒绝）。"
        "请确认服务已启动、地址端口正确、防火墙已放行。"
    )
    assert "http://a:5011/mcp refused the connection" in en


def test_connection_refused_message_without_server():
    zh = mcp_failure_message("connection_refused", "zh")

    assert zh == "MCP 工具服务连接失败（连接被拒绝）。请确认服务已启动、地址端口正确、防火墙已放行。"


def test_bad_url_message_is_exact():
    assert mcp_failure_message("bad_url", "zh") == (
        "MCP 服务地址无效（HTTP 404）。请确认 URL 正确，且以 /mcp（streamable-http）或 /sse（SSE）结尾。"
    )


@pytest.mark.parametrize(
    ("category", "zh_fragment", "en_fragment"),
    [
        ("auth_failed", "MCP 服务鉴权失败（HTTP 401/403，http://a）", "(HTTP 401/403, http://a)"),
        ("bad_url", "MCP 服务地址无效（HTTP 404，http://a）", "(HTTP 404, http://a)"),
        ("transport_mismatch", "MCP 传输类型不匹配（HTTP 406，http://a）", "(HTTP 406, http://a)"),
        ("not_mcp_endpoint", "目标地址不是 MCP 服务端点（http://a）", "endpoint (http://a)"),
    ],
)
def test_status_messages_name_server_when_attributed(category, zh_fragment, en_fragment):
    zh = mcp_failure_message(category, "zh", server="http://a")
    en = mcp_failure_message(category, "en", server="http://a")

    assert zh_fragment in zh
    assert en_fragment in en


def test_unclassified_fallback_exposes_leaf():
    zh = mcp_failure_message("unknown-category", "zh", leaf=RuntimeError("boom"))
    en = mcp_failure_message("unknown-category", "en")
    empty = mcp_failure_message("unknown-category", "en", leaf=None)

    assert "RuntimeError: boom" in zh
    assert en.startswith("MCP tool service call failed (")
    assert "unknown failure" in empty


# ---------------------------------------------------------------------------
# Import-failure fallbacks inside the classifier
# ---------------------------------------------------------------------------


def test_mcp_sdk_error_type_returns_none_when_sdk_missing():
    """The mcp SDK type lookup degrades gracefully when the import fails."""
    with patch.dict(sys.modules, {"mcp.shared.exceptions": None}):
        assert _mcp_sdk_error_type() is None


def test_classify_without_httpx_falls_back_to_messages():
    """httpx absence degrades type matching to message matching."""
    with patch.dict(sys.modules, {"httpx": None}):
        category, _ = classify_mcp_failure(RuntimeError("[Errno 111] Connection refused"))

    assert category == "connection_refused"


# ---------------------------------------------------------------------------
# Message-text fallback classification (no special leaf types)
# ---------------------------------------------------------------------------


MESSAGE_CASES = [
    ("getaddrinfo failed", "dns_failure"),
    ("Name or service not known", "dns_failure"),
    ("401 Unauthorized", "auth_failed"),
    ("403 Forbidden", "auth_failed"),
    ("404 Not Found", "bad_url"),
    ("405 Method Not Allowed", "transport_mismatch"),
    ("406 Not Acceptable", "transport_mismatch"),
    ("peer closed connection", "connection_dropped"),
    ("incomplete message body", "connection_dropped"),
    ("server disconnected", "connection_dropped"),
    ("connection reset", "connection_dropped"),
    ("certificate verify failed", "tls_error"),
    ("ssl certificate rejected", "tls_error"),
    ("Expecting value", "not_mcp_endpoint"),
    ("invalid json body", "not_mcp_endpoint"),
    ("served text/html instead", "not_mcp_endpoint"),
    ("unexpected content-type", "not_mcp_endpoint"),
    ("protocol version mismatch", "protocol_error"),
]


@pytest.mark.parametrize(("message", "category"), MESSAGE_CASES)
def test_message_fallback_classifies_without_special_types(message, category):
    """Plain RuntimeError leaves are classified by message text alone."""
    assert classify_mcp_failure(RuntimeError(message))[0] == category


# ---------------------------------------------------------------------------
# Representative-leaf selection branches
# ---------------------------------------------------------------------------


def test_first_true_leaf_wins_over_later_leaves():
    first = RuntimeError("first failure")
    second = RuntimeError("second failure")
    error = _task_group(first, second)

    assert classify_mcp_failure(error) == (None, first)


def test_wrapping_node_serves_as_representative_without_true_leaf():
    """A wrapper whose context carries only a cancellation becomes the leaf."""
    wrap = ValueError("interaction failed")
    wrap.__context__ = _task_group(asyncio.CancelledError())

    assert classify_mcp_failure(wrap) == (None, wrap)


def test_second_wrapper_does_not_replace_existing_representative():
    """Only the first wrapping node is kept as the fallback representative."""
    outer = ValueError("outer interaction failure")
    inner = ValueError("inner interaction failure")
    outer.__context__ = inner
    inner.__context__ = _task_group(asyncio.CancelledError())

    assert classify_mcp_failure(outer) == (None, outer)


def test_unrecognized_http_status_falls_through_classification():
    """A non-40x HTTP status matches no category and becomes the leaf."""
    leaf = _http_status_error(500)
    error = _task_group(leaf)

    assert classify_mcp_failure(error) == (None, leaf)


# ---------------------------------------------------------------------------
# Localized dns / connection-refused message variants
# ---------------------------------------------------------------------------


def test_dns_failure_message_bilingual_with_and_without_server():
    assert mcp_failure_message("dns_failure", "zh", server="http://a:5011/mcp") == (
        "MCP 服务地址无法解析（http://a:5011/mcp）。请检查地址拼写与 DNS 配置。"
    )
    assert mcp_failure_message("dns_failure", "zh") == (
        "MCP 服务地址无法解析。请检查地址拼写与 DNS 配置。"
    )
    assert mcp_failure_message("dns_failure", "en", server="http://a:5011/mcp") == (
        "MCP service address could not be resolved (http://a:5011/mcp). "
        "Please check the address spelling and DNS configuration."
    )
    assert mcp_failure_message("dns_failure", "en") == (
        "MCP service address could not be resolved. "
        "Please check the address spelling and DNS configuration."
    )


def test_connection_refused_message_without_server_english():
    assert mcp_failure_message("connection_refused", "en") == (
        "MCP tool service connection failed (the connection was refused). "
        "Please verify the service is running, the address and port are correct, "
        "and the firewall allows access."
    )
