# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""One-attempt sync/async HTTP sender with owned resource lifetime."""

import asyncio
import socket
import ssl
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace

import httpx

from nexent.core.concurrency.cancellation import RunCancellationScope, RunTerminated
from nexent.core.model_service.http_contracts import (
    ModelTransportError,
    PreparedHttpRequest,
    RawHttpResponse,
    validate_headers,
)
from nexent.core.model_service.profiles.resolved_profile import CredentialReference
from nexent.core.model_service.sse import SSEByteDecoder, SSEDecodeError, SSEEvent


CredentialResolver = Callable[[CredentialReference], dict[str, str]]


def _check_cancelled(scope: RunCancellationScope | None) -> None:
    if scope is not None and scope.cancelled:
        raise RunTerminated()


class HttpRequestSender:
    """No retries, provider policy, environment reads or tool execution here."""

    def __init__(
        self,
        resolve_credentials: CredentialResolver,
        *,
        max_response_bytes: int = 32 * 1024 * 1024,
        max_error_bytes: int = 1024 * 1024,
        max_event_bytes: int = 1024 * 1024,
    ):
        if any(
            type(limit) is not int or limit <= 0 for limit in (max_response_bytes, max_error_bytes, max_event_bytes)
        ):
            raise ValueError("HTTP response limits must be positive integers")
        self._resolve_credentials = resolve_credentials
        self._response_limit = max_response_bytes
        self._error_limit = max_error_bytes
        self._event_limit = max_event_bytes

    def _headers(self, request: PreparedHttpRequest) -> dict[str, str]:
        try:
            credentials = validate_headers(self._resolve_credentials(request.credential_ref), credentials=True)
        except Exception:
            raise ModelTransportError("CREDENTIAL_RESOLUTION_FAILED") from None
        if credentials.keys() & request.headers.keys():
            raise ModelTransportError("CREDENTIAL_HEADER_CONFLICT")
        return {"content-type": "application/json", **request.headers, **credentials}

    def freeze_credentials(self, request: PreparedHttpRequest) -> "HttpRequestSender":
        """Resolve once for a logical call; retries retain the same credential headers."""
        try:
            headers = validate_headers(self._resolve_credentials(request.credential_ref), credentials=True)
        except Exception:
            raise ModelTransportError("CREDENTIAL_RESOLUTION_FAILED") from None
        if headers.keys() & request.headers.keys():
            raise ModelTransportError("CREDENTIAL_HEADER_CONFLICT")

        def resolve(reference):
            if reference != request.credential_ref:
                raise ValueError("Credential reference does not match the frozen request")
            return dict(headers)

        return HttpRequestSender(
            resolve,
            max_response_bytes=self._response_limit,
            max_error_bytes=self._error_limit,
            max_event_bytes=self._event_limit,
        )

    @staticmethod
    def _failure(error: httpx.HTTPError) -> ModelTransportError:
        cause = error
        for _ in range(8):
            if isinstance(cause, ssl.SSLError):
                return ModelTransportError("HTTP_TLS_ERROR")
            cause = cause.__cause__ or cause.__context__
            if cause is None:
                break
        category = "HTTP_TIMEOUT" if isinstance(error, httpx.TimeoutException) else "HTTP_NETWORK_ERROR"
        return ModelTransportError(category)

    @staticmethod
    def _metadata(response: httpx.Response, body: bytes) -> RawHttpResponse:
        try:
            headers = response.request.headers
        except RuntimeError:
            headers = {}
        public_headers = {"host", "accept", "accept-encoding", "connection", "content-length", "content-type", "user-agent"}
        secrets = []
        for name, value in headers.items():
            if name.lower() not in public_headers:
                secrets.append(value)
                if name.lower() == "authorization" and " " in value:
                    secrets.append(value.split(" ", 1)[1])
        return RawHttpResponse(response.status_code, dict(response.headers), body, tuple(secrets))

    def _read(self, response: httpx.Response, limit: int) -> bytes:
        parts, size = [], 0
        for part in response.iter_bytes():
            size += len(part)
            if size > limit:
                raise ModelTransportError("HTTP_RESPONSE_TOO_LARGE")
            parts.append(part)
        return b"".join(parts)

    async def _aread(self, response: httpx.Response, limit: int) -> bytes:
        parts, size = [], 0
        async for part in response.aiter_bytes():
            size += len(part)
            if size > limit:
                raise ModelTransportError("HTTP_RESPONSE_TOO_LARGE")
            parts.append(part)
        return b"".join(parts)

    @contextmanager
    def _response(self, request: PreparedHttpRequest, scope: RunCancellationScope | None):
        _check_cancelled(scope)
        headers = self._headers(request)
        client = httpx.Client(verify=request.ssl_verify, timeout=request.timeout_seconds, trust_env=False)
        lock = threading.Lock()
        closed = False
        aborted = False
        streams = []

        def shutdown_stream(stream):
            try:
                connection = stream.get_extra_info("socket")
                if isinstance(connection, socket.socket):
                    connection.shutdown(socket.SHUT_RDWR)
            except (AttributeError, OSError):
                pass

        def trace(event, info):
            if event not in {"connection.connect_tcp.complete", "connection.start_tls.complete"}:
                return
            stream = info.get("return_value")
            if stream is None:
                return
            with lock:
                already_closed = aborted
                if not already_closed:
                    streams.append(stream)
            if already_closed:
                shutdown_stream(stream)
                stream.close()
                _check_cancelled(scope)

        def abort_once():
            nonlocal aborted
            with lock:
                if aborted:
                    return
                aborted = True
                owned_streams = tuple(streams)
            for stream in owned_streams:
                shutdown_stream(stream)

        def close_once():
            nonlocal closed
            abort_once()
            with lock:
                if closed:
                    return
                closed = True
            # Only the reader closes the client after its socket read unwinds.
            client.close()

        token = scope.register_closer(abort_once) if scope else None
        try:
            _check_cancelled(scope)
            with client.stream(
                request.method,
                request.url,
                headers=headers,
                content=request.body_bytes,
                extensions={"trace": trace},
            ) as response:
                _check_cancelled(scope)
                yield response
        except httpx.HTTPError as error:
            _check_cancelled(scope)
            raise self._failure(error) from None
        finally:
            if scope and token:
                scope.unregister_closer(token)
            close_once()

    @asynccontextmanager
    async def _aresponse(self, request: PreparedHttpRequest, scope: RunCancellationScope | None):
        _check_cancelled(scope)
        headers = self._headers(request)
        loop, task = asyncio.get_running_loop(), asyncio.current_task()

        active = True

        def cancel_if_active():
            if active:
                task.cancel()

        def cancel_task():
            loop.call_soon_threadsafe(cancel_if_active)

        token = scope.register_closer(cancel_task) if scope else None
        try:
            _check_cancelled(scope)
            async with httpx.AsyncClient(
                verify=request.ssl_verify, timeout=request.timeout_seconds, trust_env=False
            ) as client:
                async with client.stream(
                    request.method, request.url, headers=headers, content=request.body_bytes
                ) as response:
                    _check_cancelled(scope)
                    yield response
        except asyncio.CancelledError:
            _check_cancelled(scope)
            raise
        except httpx.HTTPError as error:
            _check_cancelled(scope)
            raise self._failure(error) from None
        finally:
            active = False
            if scope and token:
                scope.unregister_closer(token)

    def invoke(self, request: PreparedHttpRequest, *, scope: RunCancellationScope | None = None) -> RawHttpResponse:
        with self._response(request, scope) as response:
            body = self._read(response, self._response_limit if response.is_success else self._error_limit)
            _check_cancelled(scope)
            raw = self._metadata(response, body)
            if not response.is_success:
                raise ModelTransportError("HTTP_STATUS_ERROR", response=raw)
            return raw

    async def ainvoke(
        self, request: PreparedHttpRequest, *, scope: RunCancellationScope | None = None
    ) -> RawHttpResponse:
        async with self._aresponse(request, scope) as response:
            body = await self._aread(response, self._response_limit if response.is_success else self._error_limit)
            _check_cancelled(scope)
            raw = self._metadata(response, body)
            if not response.is_success:
                raise ModelTransportError("HTTP_STATUS_ERROR", response=raw)
            return raw

    def _stream_decoder(self, response: httpx.Response, request: PreparedHttpRequest) -> SSEByteDecoder:
        if (
            request.stream_protocol != "sse"
            or response.headers.get("content-type", "").split(";")[0].strip() != "text/event-stream"
        ):
            raise ModelTransportError("HTTP_STREAM_FORMAT_INVALID")
        return SSEByteDecoder(max_event_bytes=self._event_limit)

    @contextmanager
    def stream(
        self, request: PreparedHttpRequest, *, scope: RunCancellationScope | None = None
    ) -> Iterator[Iterator[SSEEvent]]:
        with self._response(request, scope) as response:
            if not response.is_success:
                raise ModelTransportError(
                    "HTTP_STATUS_ERROR", response=self._metadata(response, self._read(response, self._error_limit))
                )
            decoder = self._stream_decoder(response, request)
            secrets = self._metadata(response, b"").sensitive_values

            def events():
                try:
                    for text in response.iter_bytes():
                        _check_cancelled(scope)
                        for event in decoder.feed(text):
                            _check_cancelled(scope)
                            yield replace(event, sensitive_values=secrets)
                    decoder.finish()
                except SSEDecodeError as error:
                    raise ModelTransportError(error.category) from None

            iterator = events()
            try:
                yield iterator
            finally:
                iterator.close()

    @asynccontextmanager
    async def astream(
        self, request: PreparedHttpRequest, *, scope: RunCancellationScope | None = None
    ) -> AsyncIterator[AsyncIterator[SSEEvent]]:
        async with self._aresponse(request, scope) as response:
            if not response.is_success:
                body = await self._aread(response, self._error_limit)
                raise ModelTransportError("HTTP_STATUS_ERROR", response=self._metadata(response, body))
            decoder = self._stream_decoder(response, request)
            secrets = self._metadata(response, b"").sensitive_values

            async def events():
                try:
                    async for text in response.aiter_bytes():
                        _check_cancelled(scope)
                        for event in decoder.feed(text):
                            _check_cancelled(scope)
                            yield replace(event, sensitive_values=secrets)
                    decoder.finish()
                except SSEDecodeError as error:
                    raise ModelTransportError(error.category) from None

            iterator = events()
            try:
                yield iterator
            finally:
                await iterator.aclose()
