"""Shared MCP execution error types and classifiers."""

import asyncio
import json
import socket
import ssl
from collections.abc import Iterator


MCP_TOOL_TIMEOUT_TEXT = "MCP tool request timed out after"
MCP_CONNECTION_TIMEOUT_TEXT = "MCP connection timed out after"

# Cancellation/interruption signals are not service failures: they are never
# wrapped as MCP failures and never chosen as the representative leaf.
_CANCEL_EXCEPTION_TYPES = (KeyboardInterrupt, SystemExit, asyncio.CancelledError)


class MCPToolTimeoutError(TimeoutError):
    """Signal that an MCP tool request must terminate the current Agent run."""

    _nexent_mcp_timeout = True


class MCPConnectionTimeoutError(TimeoutError):
    """Signal that an MCP connection or initialization handshake timed out."""

    _nexent_mcp_connection_timeout = True


class MCPConnectionFailure(Exception):
    """Attribution carrier for one MCP server whose session setup failed.

    The original failure always travels on ``__cause__`` so classifiers and
    logs keep seeing the full exception tree.
    """

    def __init__(self, url: str, transport: str):
        self.url = url
        self.transport = transport
        super().__init__(f"MCP server {url} (transport={transport}) failed")


def _iter_exception_chain(error: BaseException) -> Iterator[BaseException]:
    """Yield the exception tree in pre-order: the error itself, then taskgroup
    members, then ``__cause__``/``__context__`` links, cycle-safe."""
    stack: list[BaseException] = [error]
    visited: set[int] = set()
    while stack:
        current = stack.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        yield current
        if current.__cause__ is not None:
            stack.append(current.__cause__)
        elif current.__context__ is not None:
            stack.append(current.__context__)
        if isinstance(current, BaseExceptionGroup):
            stack.extend(reversed(current.exceptions))


def iter_leaf_exceptions(error: BaseException) -> Iterator[BaseException]:
    """Expand the exception tree in pre-order, skipping cancellation signals
    so callers always see a real failure as the representative leaf."""
    for current in _iter_exception_chain(error):
        if not isinstance(current, _CANCEL_EXCEPTION_TYPES):
            yield current


def is_mcp_connection_timeout_error(error: BaseException) -> bool:
    """Identify timeouts raised while establishing an MCP session."""
    for current in _iter_exception_chain(error):
        if getattr(current, "_nexent_mcp_connection_timeout", False):
            return True
        message = str(current).lower()
        if MCP_CONNECTION_TIMEOUT_TEXT.lower() in message:
            return True
        if "mcp session startup timed out" in message:
            return True
        if (
            "timed out while waiting for response to clientrequest" in message
            and "calltoolrequest" not in message
        ):
            return True
    return False


def is_mcp_timeout_error(error: BaseException) -> bool:
    """Identify MCP tool timeouts, including errors wrapped by code execution."""
    for current in _iter_exception_chain(error):
        if getattr(current, "_nexent_mcp_timeout", False):
            return True
        message = str(current).lower()
        if MCP_TOOL_TIMEOUT_TEXT.lower() in message:
            return True
        if (
            "timed out while waiting for response to" in message
            and ("clientrequest" in message or "calltoolrequest" in message)
        ):
            return True
    return False


def propagate_mcp_timeout(error: BaseException) -> MCPToolTimeoutError:
    """Create a non-AgentError timeout that bypasses smolagents retry handling."""
    if isinstance(error, MCPToolTimeoutError):
        return error
    return MCPToolTimeoutError(str(error))


def _mcp_sdk_error_type() -> type | None:
    """Return the mcp SDK ``McpError`` type, or None when the SDK is absent."""
    try:
        from mcp.shared.exceptions import McpError
    except ImportError:
        return None
    return McpError


def _classify_leaf_exception(leaf: BaseException) -> str | None:
    """Map one exception node to an MCP failure category (leaf type first, message fallback)."""
    message = str(leaf).lower()
    if (
        getattr(leaf, "_nexent_mcp_timeout", False)
        or getattr(leaf, "_nexent_mcp_connection_timeout", False)
        or MCP_TOOL_TIMEOUT_TEXT.lower() in message
        or MCP_CONNECTION_TIMEOUT_TEXT.lower() in message
        or "mcp session startup timed out" in message
        or "timed out while waiting for response to" in message
    ):
        return "timeout"

    try:
        import httpx
    except ImportError:
        httpx = None

    if httpx is not None:
        if isinstance(leaf, (httpx.ConnectError, ConnectionRefusedError)):
            return "connection_refused"
        if isinstance(leaf, socket.gaierror):
            return "dns_failure"
        if isinstance(leaf, httpx.HTTPStatusError):
            status = getattr(getattr(leaf, "response", None), "status_code", None)
            if status in (401, 403):
                return "auth_failed"
            if status == 404:
                return "bad_url"
            if status in (405, 406):
                return "transport_mismatch"
        if isinstance(leaf, (httpx.ReadError, httpx.RemoteProtocolError)):
            return "connection_dropped"

    if isinstance(leaf, ssl.SSLError):
        return "tls_error"

    mcp_error_type = _mcp_sdk_error_type()
    if mcp_error_type is not None and isinstance(leaf, mcp_error_type):
        return "protocol_error"
    if isinstance(leaf, json.JSONDecodeError):
        return "not_mcp_endpoint"

    if "getaddrinfo failed" in message or "name or service not known" in message:
        return "dns_failure"
    if "connection refused" in message:
        return "connection_refused"
    if "401 unauthorized" in message or "403 forbidden" in message:
        return "auth_failed"
    if "404 not found" in message:
        return "bad_url"
    if "405 method not allowed" in message or "406 not acceptable" in message:
        return "transport_mismatch"
    if (
        "peer closed connection" in message
        or "incomplete message body" in message
        or "server disconnected" in message
        or "connection reset" in message
    ):
        return "connection_dropped"
    if "certificate verify failed" in message or ("ssl" in message and "certificate" in message):
        return "tls_error"
    if (
        "expecting value" in message
        or "invalid json" in message
        or "text/html" in message
        or "unexpected content-type" in message
    ):
        return "not_mcp_endpoint"
    if "protocol version" in message:
        return "protocol_error"
    return None


def classify_mcp_failure(error: BaseException) -> tuple[str | None, BaseException | None]:
    """Classify the root cause of a failed MCP interaction.

    Walks the whole exception tree (taskgroup members, ``__cause__`` and
    ``__context__``) and returns ``(category, representative_leaf)`` where
    category is one of connection_refused / dns_failure / auth_failed /
    bad_url / transport_mismatch / connection_dropped / tls_error /
    not_mcp_endpoint / protocol_error / timeout. When no category matches but
    a real (non-cancellation) leaf exists, returns ``(None, leaf)`` so callers
    can still surface the underlying cause; ``(None, None)`` means no usable
    leaf was found, e.g. a taskgroup that only carries a cancellation.
    """
    representative: BaseException | None = None
    true_leaf: BaseException | None = None
    for leaf in iter_leaf_exceptions(error):
        category = _classify_leaf_exception(leaf)
        if category is not None:
            return category, leaf
        if isinstance(leaf, BaseExceptionGroup):
            continue
        if leaf.__cause__ is None and leaf.__context__ is None:
            if true_leaf is None:
                true_leaf = leaf
        elif representative is None:
            # Wrapping node: only used when the tree has no true leaf at all.
            representative = leaf
    return None, true_leaf or representative


def find_mcp_server_url(error: BaseException) -> str | None:
    """Return the server URL attributed by :class:`MCPConnectionFailure`, if present."""
    for current in _iter_exception_chain(error):
        if isinstance(current, MCPConnectionFailure) and current.url:
            return current.url
    return None


def describe_exception_leaf(leaf: BaseException, limit: int = 300) -> str:
    """One-line ``Type: message`` description used when no category matches."""
    message = " ".join(str(leaf).split())
    if len(message) > limit:
        message = message[: limit - 3] + "..."
    return f"{type(leaf).__name__}: {message}"


_MCP_FAILURE_MESSAGES: dict[str, dict[str, str]] = {
    "connection_dropped": {
        "zh": "MCP 服务连接中断。请检查服务运行状态与网络稳定性后重试。",
        "en": "MCP service connection was interrupted. Please check the service "
        "status and network stability, then try again.",
    },
    "tls_error": {
        "zh": "MCP 服务证书校验失败。请检查 TLS 证书配置。",
        "en": "MCP service certificate verification failed. Please check the TLS "
        "certificate configuration.",
    },
    "protocol_error": {
        "zh": "MCP 服务协议交互异常。请联系管理员核对服务端版本兼容性。",
        "en": "MCP service protocol interaction failed. Please contact the "
        "administrator to check server version compatibility.",
    },
    "timeout": {
        "zh": "MCP 工具服务调用超时。请确认服务响应状态后重试。",
        "en": "MCP tool service call timed out. Please check the service response "
        "status and try again.",
    },
}


def _status_detail(zh: bool, status: str, server: str | None) -> str:
    """Parenthesized HTTP status, optionally naming the failing server."""
    if zh:
        return f"（{status}，{server}）" if server else f"（{status}）"
    return f"({status}, {server})" if server else f"({status})"


def _server_detail(zh: bool, server: str | None) -> str:
    """Parenthesized server reference, or an empty string when unattributed."""
    if not server:
        return ""
    return f"（{server}）" if zh else f" ({server})"


def mcp_failure_message(
    category: str,
    lang: str = "en",
    *,
    server: str | None = None,
    leaf: BaseException | None = None,
) -> str:
    """Return the localized friendly message for a classified MCP failure.

    ``server`` is an optional attributed server URL; ``leaf`` feeds the
    unclassified fallback so the user still sees the real cause.
    """
    zh = lang == "zh"
    if category == "connection_refused":
        if zh:
            detail = f"{server} 连接被拒绝" if server else "连接被拒绝"
            return f"MCP 工具服务连接失败（{detail}）。请确认服务已启动、地址端口正确、防火墙已放行。"
        detail = f"{server} refused the connection" if server else "the connection was refused"
        return (
            "MCP tool service connection failed "
            f"({detail}). Please verify the service is running, the address and port "
            "are correct, and the firewall allows access."
        )
    if category == "dns_failure":
        if zh:
            return f"MCP 服务地址无法解析{_server_detail(True, server)}。请检查地址拼写与 DNS 配置。"
        return f"MCP service address could not be resolved{_server_detail(False, server)}. Please check the address spelling and DNS configuration."
    if category == "auth_failed":
        if zh:
            return f"MCP 服务鉴权失败{_status_detail(True, 'HTTP 401/403', server)}。请检查该服务的 Authorization/API Key 配置。"
        return f"MCP service authentication failed {_status_detail(False, 'HTTP 401/403', server)}. Please check the service's Authorization/API Key configuration."
    if category == "bad_url":
        if zh:
            return f"MCP 服务地址无效{_status_detail(True, 'HTTP 404', server)}。请确认 URL 正确，且以 /mcp（streamable-http）或 /sse（SSE）结尾。"
        return f"MCP service address is invalid {_status_detail(False, 'HTTP 404', server)}. Please confirm the URL is correct and ends with /mcp (streamable-http) or /sse (SSE)."
    if category == "transport_mismatch":
        if zh:
            return f"MCP 传输类型不匹配{_status_detail(True, 'HTTP 406', server)}。请核对 URL 结尾与服务端支持的传输类型。"
        return f"MCP transport type mismatch {_status_detail(False, 'HTTP 406', server)}. Please check the URL ending against the transports the server supports."
    if category == "not_mcp_endpoint":
        if zh:
            return f"目标地址不是 MCP 服务端点{_server_detail(True, server)}。请核对服务地址与路径。"
        return f"The target address is not an MCP service endpoint{_server_detail(False, server)}. Please verify the service address and path."
    message = _MCP_FAILURE_MESSAGES.get(category, {}).get("zh" if zh else "en")
    if message is not None:
        return message
    leaf_text = describe_exception_leaf(leaf) if leaf is not None else "unknown failure"
    if zh:
        return f"MCP 工具服务调用失败（{leaf_text}）。请联系管理员并提供报错时间点。"
    return f"MCP tool service call failed ({leaf_text}). Please contact the administrator and provide the time of the error."
