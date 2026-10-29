# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Logical model calls over registered adapters and the shared HTTP sender."""

import asyncio
import inspect
import json
import logging
import math
import random
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, replace

from nexent.core.concurrency.cancellation import RunCancellationScope, RunTerminated
from nexent.core.model_service.concurrency import ModelConcurrencyExceeded, model_concurrency_limiter
from nexent.core.model_service.contracts import ModelError, ModelEvent, ModelRequest
from nexent.core.model_service.errors import normalize_model_error
from nexent.core.model_service.http_contracts import ModelTransportError
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from nexent.core.model_service.registry import AdapterRegistry
from nexent.monitor import get_monitoring_manager


logger = logging.getLogger(__name__)


class ModelServiceError(Exception):
    """Only the public normalized error is exposed to callers."""

    def __init__(self, error):
        self.error = error
        super().__init__(error.category)


@dataclass(frozen=True)
class ModelRequestRetryPolicy:
    max_attempts: int = 3

    def __post_init__(self):
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("Retry attempts must be a positive integer")

    def calculate_backoff(self, attempt: int) -> float:
        return min(2 ** min(attempt - 1, 5), 30) + random.uniform(0, 0.25)


@dataclass
class _Call:
    request: ModelRequest
    profile: ResolvedModelProfile
    adapter: object
    sender: object
    prepared: object
    scope: RunCancellationScope
    deadline: float | None
    policy: object
    attempt: int = 1
    visible: bool = False
    sequence: int = 0
    monitoring: object = None
    token_tracker: object = None
    request_rebuild: object = None
    rebuilds: int = 0
    rebuild_pending: bool = False
    empty_response_retries: int = 0

    def check(self):
        if self.scope.cancelled:
            raise RunTerminated()
        if self.deadline is not None and time.monotonic() >= self.deadline:
            error = normalize_model_error(
                ModelTransportError("HTTP_RUN_DEADLINE"),
                request_id=self.request.request_id,
                attempt=self.attempt,
                max_attempts=self.policy.max_attempts,
            )
            raise ModelServiceError(error)

    def timeout(self):
        self.check()
        configured = self.profile.connection.timeout_seconds
        return configured if self.deadline is None else min(configured, self.deadline - time.monotonic())

    def wire_request(self):
        self.monitoring.add_span_event("model_attempt_begin", {
            "request_id": self.request.request_id, "attempt": self.attempt,
        })
        return replace(
            self.prepared,
            headers=dict(self.prepared.headers),
            json_body=json.loads(self.prepared.body_bytes),
            timeout_seconds=self.timeout(),
        )

    def event(self, event):
        self.check()
        if event.type in {"text_delta", "reasoning_delta", "tool_call_delta"}:
            self.token_tracker.record_first_token()
        elif event.type == "usage":
            self.monitoring.add_span_event("model_usage", {
                "attempt": self.attempt, **event.usage.model_dump(exclude_none=True),
            })
        elif event.type == "message_completed":
            self.observe_completion(event.message)
        self.sequence += 1
        self.visible |= event.type in {"text_delta", "reasoning_delta", "tool_call_delta", "message_completed"}
        return event.model_copy(update={"sequence": self.sequence, "attempt": self.attempt})

    def observe_completion(self, message):
        usage = message.usage
        if usage.input_tokens is not None and usage.output_tokens is not None:
            self.token_tracker.record_completion(usage.input_tokens, usage.output_tokens, total_tokens=usage.total_tokens)
        self.monitoring.set_span_attributes(**{
            "llm.usage." + key: value for key, value in usage.model_dump().items() if value is not None
        }, **{"llm.response.finish_reason": message.finish_reason, "llm.response.attempt": self.attempt})
        self.monitoring.set_openinference_output("".join(
            part.get("text", "") for part in message.content_parts if part.get("type") == "text"
        ))

    def failure(self, error):
        if self.scope.cancelled:
            raise RunTerminated()
        normalized = (
            error.error
            if isinstance(error, ModelServiceError)
            else self.adapter.normalize_error(
                error,
                request_id=self.request.request_id,
                attempt=self.attempt,
                max_attempts=self.policy.max_attempts,
            )
        )
        self.rebuild_pending = (
            normalized.category == "MODEL_CONTEXT_EXCEEDED" and self.request_rebuild is not None
            and not self.visible and self.attempt < self.policy.max_attempts and self.rebuilds < 2
        )
        if self.rebuild_pending:
            normalized = normalized.model_copy(update={"retryable": True})
        delay = None
        if normalized.retryable and not self.visible and self.attempt < self.policy.max_attempts:
            delay = 0 if self.rebuild_pending else self.policy.calculate_backoff(self.attempt)
            if not isinstance(delay, (int, float)) or not math.isfinite(delay) or delay < 0:
                raise ValueError("Retry backoff must be finite and nonnegative")
            response = getattr(error, "response", None)
            if response is not None:
                try:
                    retry_after = float(
                        next(value for key, value in response.headers.items() if key.lower() == "retry-after")
                    )
                    if math.isfinite(retry_after) and retry_after >= 0:
                        delay = max(delay, retry_after)
                except (ValueError, TypeError, StopIteration):
                    pass
            if self.deadline is not None and time.monotonic() + delay >= self.deadline:
                delay = None
        normalized = normalized.model_copy(update={"will_retry": delay is not None})
        self.monitoring.add_span_event("model_attempt_error", {
            "request_id": self.request.request_id, "attempt": self.attempt,
            "category": normalized.category, "will_retry": delay is not None,
        })
        if normalized.category in {"MODEL_TIMEOUT", "MODEL_CONCURRENCY_TIMEOUT", "MODEL_RUN_DEADLINE"}:
            logger.warning(
                "model_request_timeout",
                extra={
                    "request_id": self.request.request_id,
                    "outlet_id": self.profile.outlet_id,
                    "attempt": self.attempt,
                    "category": normalized.category,
                    "phase": "after_output" if self.visible else "before_output",
                    "timeout_seconds": self.profile.connection.timeout_seconds,
                    "exception_type": type(error).__name__,
                },
            )
        if delay is not None:
            logger.info(
                "model_request_retry",
                extra={
                    "request_id": self.request.request_id,
                    "attempt": self.attempt,
                    "category": normalized.category,
                    "will_retry": True,
                    "retry_delay_seconds": delay,
                },
            )
        return normalized, delay

    def apply_rebuild(self, request):
        self.check()
        if not isinstance(request, ModelRequest):
            raise TypeError("request_rebuild must return a ModelRequest")
        request = ModelRequest.model_validate(request.model_dump())
        if request.model_dump(exclude={"messages"}) != self.request.model_dump(exclude={"messages"}):
            raise ValueError("Context recovery may only replace messages")
        prepared = self.adapter.prepare_http_request(request, self.profile)
        self.request, self.prepared = request, prepared
        self.rebuilds += 1
        self.rebuild_pending = False
        self.monitoring.add_span_event("model_context_rebuild", {
            "request_id": request.request_id, "attempt": self.attempt,
            "recovery_dispatch": self.rebuilds, "message_count": len(request.messages),
        })
        self.check()

    def wait(self, delay):
        end = time.monotonic() + delay
        while time.monotonic() < end:
            self.check()
            self.scope.stop_event.wait(min(0.05, end - time.monotonic()))
        self.check()
        self.attempt += 1

    async def await_retry(self, delay):
        end = time.monotonic() + delay
        while time.monotonic() < end:
            self.check()
            await asyncio.sleep(min(0.05, end - time.monotonic()))
        self.check()
        self.attempt += 1


class ModelService:
    """No environment reads, resource execution, AgentMode selection or semantic repair."""

    def __init__(self, sender_factory, *, registry=None, limiter=None, retry_policy=None, monitoring=None, outlet_reader=None):
        if outlet_reader is not None and (
            not callable(outlet_reader) or inspect.iscoroutinefunction(outlet_reader)
            or inspect.iscoroutinefunction(getattr(outlet_reader, "__call__", None))
        ):
            raise TypeError("Outlet reader must be a synchronous snapshot reader")
        self._outlet_reader = outlet_reader
        self._sender_factory = sender_factory
        self._registry = registry if registry is not None else AdapterRegistry()
        self._limiter = limiter if limiter is not None else model_concurrency_limiter
        self._policy = retry_policy if retry_policy is not None else ModelRequestRetryPolicy()
        self._monitoring = monitoring if monitoring is not None else get_monitoring_manager()
        if type(self._policy.max_attempts) is not int or self._policy.max_attempts < 1:
            raise ValueError("Retry attempts must be a positive integer")

    def bind_outlet(self, model_id, run_context):
        """Select one tenant-owned saved snapshot without storing active run state on the service."""
        tenant_id = getattr(run_context, "tenant_id", None)
        if (type(model_id) is not int or not 0 < model_id < 2**31
                or not isinstance(tenant_id, str) or not tenant_id.strip()):
            raise ValueError("MODEL_OUTLET_SELECTION_INVALID")
        if self._outlet_reader is None:
            raise ValueError("MODEL_OUTLET_READER_UNCONFIGURED")
        try:
            profile = self._outlet_reader(model_id, run_context)
        except Exception:
            raise ValueError("MODEL_OUTLET_RESOLUTION_FAILED") from None
        if profile is None:
            raise ValueError("MODEL_OUTLET_NOT_FOUND")
        try:
            if not isinstance(profile, ResolvedModelProfile):
                raise TypeError("Invalid snapshot")
            profile = ResolvedModelProfile.model_validate(profile.model_dump())
        except Exception:
            raise ValueError("MODEL_OUTLET_SNAPSHOT_INVALID") from None
        if profile.outlet_id != model_id or profile.identity.tenant_id != tenant_id:
            raise ValueError("MODEL_OUTLET_SNAPSHOT_MISMATCH")
        self._registry.resolve(profile.bindings.adapter)
        return profile

    def _call(self, request, profile, scope, deadline, request_rebuild=None):
        if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
            raise ValueError("Run deadline must be a finite monotonic timestamp")
        request = ModelRequest.model_validate(request.model_dump())
        profile = ResolvedModelProfile.model_validate(profile.model_dump())
        scope = scope if scope is not None else RunCancellationScope()
        if scope.cancelled:
            raise RunTerminated()
        try:
            adapter = self._registry.resolve(profile.bindings.adapter)
            prepared = adapter.prepare_http_request(request, profile)
            sender = self._sender_factory(profile).freeze_credentials(prepared)
        except Exception as error:
            raise ModelServiceError(
                normalize_model_error(
                    error,
                    request_id=request.request_id,
                    max_attempts=self._policy.max_attempts,
                )
            ) from None
        call = _Call(request, profile, adapter, sender, prepared, scope, deadline, self._policy,
                     monitoring=self._monitoring, request_rebuild=request_rebuild)
        call.check()
        return call

    @staticmethod
    def _validate_rebuild(callback, *, asynchronous=False):
        if callback is None:
            return
        is_async = inspect.iscoroutinefunction(callback) or inspect.iscoroutinefunction(getattr(callback, "__call__", None))
        if not callable(callback) or is_async != asynchronous:
            raise TypeError("Request rebuild callback must match the synchronous or asynchronous API")

    @staticmethod
    async def _arebuild(call, error):
        call.check()
        budget = asyncio.timeout_at(call.deadline)
        loop, task = asyncio.get_running_loop(), asyncio.current_task()
        active = True

        def cancel_if_active():
            if active:
                task.cancel()

        token = call.scope.register_closer(lambda: loop.call_soon_threadsafe(cancel_if_active))
        try:
            async with budget:
                request = await call.request_rebuild(error)
        except asyncio.CancelledError:
            call.check()
            raise
        except TimeoutError:
            if budget.expired():
                call.check()
            raise
        finally:
            active = False
            call.scope.unregister_closer(token)
        call.apply_rebuild(request)

    @contextmanager
    def _trace(self, call):
        with self._monitoring.trace_llm_request(
            f"{call.profile.identity.display_name or call.profile.identity.request_model_id}.generate",
            call.profile.identity.request_model_id,
            **{
                "input.value": [message.model_dump(mode="json") for message in call.request.messages],
                "model.request_id": call.request.request_id,
                **({"model.outlet_id": call.profile.outlet_id} if call.profile.outlet_id is not None else {}),
                "model.config_revision": call.profile.config_revision,
                "model.provider": call.profile.identity.provider_id,
            },
        ) as span:
            call.token_tracker = self._monitoring.create_token_tracker(call.profile.identity.request_model_id, span)
            yield

    def _admission_args(self, call):
        profile = call.profile
        return {
            "key": (profile.identity.tenant_id, profile.identity.provider_id, profile.identity.request_model_id),
            "limit": profile.connection.concurrency_limit,
            "timeout_seconds": call.timeout(),
            "stop_event": call.scope.stop_event,
        }

    @contextmanager
    def _permit(self, call):
        call.check()
        permit = None
        try:
            if call.profile.connection.concurrency_limit is not None:
                try:
                    permit = self._limiter.acquire(**self._admission_args(call))
                except ModelConcurrencyExceeded:
                    raise ModelTransportError("HTTP_CONCURRENCY_TIMEOUT") from None
            call.check()
            yield
        finally:
            if permit is not None:
                permit.release()

    @asynccontextmanager
    async def _apermit(self, call):
        call.check()
        permit = None
        try:
            if call.profile.connection.concurrency_limit is not None:
                try:
                    permit = await self._limiter.acquire_async(**self._admission_args(call))
                except ModelConcurrencyExceeded:
                    raise ModelTransportError("HTTP_CONCURRENCY_TIMEOUT") from None
            call.check()
            budget = asyncio.timeout_at(call.deadline)
            try:
                async with budget:
                    yield
            except TimeoutError:
                if budget.expired():
                    raise ModelTransportError("HTTP_RUN_DEADLINE") from None
                raise
        finally:
            if permit is not None:
                permit.release()

    def invoke(self, request, profile, *, scope=None, deadline=None, request_rebuild=None):
        self._validate_rebuild(request_rebuild, asynchronous=False)
        if request.stream:
            raise ValueError("Invoke requires a non-streaming request")
        call = self._call(request, profile, scope, deadline, request_rebuild)
        with self._trace(call):
            while True:
                try:
                    with self._permit(call):
                        raw = call.sender.invoke(call.wire_request(), scope=call.scope)
                        result = call.adapter.decode_response(raw, call.request, call.profile)
                        call.check()
                        call.observe_completion(result)
                    return result
                except Exception as error:
                    normalized, delay = call.failure(error)
                    if delay is None:
                        raise ModelServiceError(normalized) from None
                if call.rebuild_pending:
                    call.check()
                    call.apply_rebuild(call.request_rebuild(normalized))
                call.wait(delay)

    async def ainvoke(self, request, profile, *, scope=None, deadline=None, request_rebuild=None):
        self._validate_rebuild(request_rebuild, asynchronous=True)
        if request.stream:
            raise ValueError("Invoke requires a non-streaming request")
        call = self._call(request, profile, scope, deadline, request_rebuild)
        with self._trace(call):
            while True:
                try:
                    async with self._apermit(call):
                        raw = await call.sender.ainvoke(call.wire_request(), scope=call.scope)
                        result = call.adapter.decode_response(raw, call.request, call.profile)
                        call.check()
                        call.observe_completion(result)
                    return result
                except Exception as error:
                    normalized, delay = call.failure(error)
                    if delay is None:
                        raise ModelServiceError(normalized) from None
                if call.rebuild_pending:
                    call.check()
                    await self._arebuild(call, normalized)
                await call.await_retry(delay)

    @staticmethod
    def _error_event(call, error, message_id):
        call.sequence += 1
        return ModelEvent(
            request_id=call.request.request_id,
            message_id=message_id,
            sequence=call.sequence,
            attempt=call.attempt,
            type="error",
            error=error,
        )

    @staticmethod
    def _check_empty_response(call, event, policy):
        if policy == "accept" or event.type != "message_completed":
            return
        message = event.message
        if message.tool_calls or message.refusal or any(
            part.get("type") == "text" and part.get("text", "").strip() for part in message.content_parts
        ):
            return
        retryable = policy == "retry" and message.finish_reason == "stop" and call.empty_response_retries < 1
        if retryable:
            call.empty_response_retries += 1
        raise ModelServiceError(ModelError(
            category="MODEL_EMPTY_RESPONSE", scope="protocol",
            retryable=retryable,
            attempt=call.attempt, max_attempts=call.policy.max_attempts,
            safe_message="The model returned an empty response.", request_id=call.request.request_id,
            finish_reason=message.finish_reason,
        ))

    @staticmethod
    def _validate_empty_policy(policy):
        if policy not in ("accept", "fail", "retry"):
            raise ValueError("Unknown empty response policy")

    def _events(self, call, empty_response_policy):
        message_id = uuid.uuid4()
        pending_delay = None
        while True:
            try:
                if pending_delay is not None:
                    call.wait(pending_delay)
                with self._permit(call), call.sender.stream(call.wire_request(), scope=call.scope) as frames:
                    for event in call.adapter.decode_stream(frames, call.request, call.profile):
                        message_id = event.message_id
                        self._check_empty_response(call, event, empty_response_policy)
                        yield call.event(event)
                        if event.type == "message_completed":
                            return
                return
            except Exception as error:
                normalized, delay = call.failure(error)
                if delay is None:
                    yield self._error_event(call, normalized, message_id)
                    return
            if call.rebuild_pending:
                call.check()
                call.apply_rebuild(call.request_rebuild(normalized))
            pending_delay = delay

    async def _aevents(self, call, empty_response_policy):
        message_id = uuid.uuid4()
        pending_delay = None
        while True:
            try:
                if pending_delay is not None:
                    await call.await_retry(pending_delay)
                async with self._apermit(call), call.sender.astream(call.wire_request(), scope=call.scope) as frames:
                    async for event in call.adapter.adecode_stream(frames, call.request, call.profile):
                        message_id = event.message_id
                        self._check_empty_response(call, event, empty_response_policy)
                        yield call.event(event)
                        if event.type == "message_completed":
                            return
                return
            except Exception as error:
                normalized, delay = call.failure(error)
                if delay is None:
                    yield self._error_event(call, normalized, message_id)
                    return
            if call.rebuild_pending:
                call.check()
                await self._arebuild(call, normalized)
            pending_delay = delay

    @contextmanager
    def stream(
        self, request, profile, *, scope=None, deadline=None, empty_response_policy="accept", request_rebuild=None,
    ):
        self._validate_rebuild(request_rebuild, asynchronous=False)
        self._validate_empty_policy(empty_response_policy)
        if not request.stream:
            raise ValueError("Stream requires a streaming request")
        call = self._call(request, profile, scope, deadline, request_rebuild)
        events = self._events(call, empty_response_policy)
        with self._trace(call):
            try:
                yield events
            finally:
                events.close()

    @asynccontextmanager
    async def astream(
        self, request, profile, *, scope=None, deadline=None, empty_response_policy="accept", request_rebuild=None,
    ):
        self._validate_rebuild(request_rebuild, asynchronous=True)
        self._validate_empty_policy(empty_response_policy)
        if not request.stream:
            raise ValueError("Stream requires a streaming request")
        call = self._call(request, profile, scope, deadline, request_rebuild)
        events = self._aevents(call, empty_response_policy)
        with self._trace(call):
            try:
                yield events
            finally:
                await events.aclose()
