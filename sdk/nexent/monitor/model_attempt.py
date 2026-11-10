# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Local physical model attempts, independent of the existing remote logical span."""

from __future__ import annotations

import hashlib
import json
import re
import time
from functools import wraps
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .duration import duration_attributes
from .local_content import local_capture_enabled, safe_local_content


def _isolated(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        if not self.enabled:
            return None
        try:
            return method(self, *args, **kwargs)
        except Exception:
            # A telemetry failure must never resend or fail a business request.
            target = self.span or self.logical_span
            try:
                if target is not None:
                    target.set_attribute('nexent.trajectory.gap', True)
                    target.add_event('capture.error', {'reason_code': 'serialization_failed'})
            except Exception:
                pass
            return None
    return wrapped


def _safe(value, sensitive=()):
    # JSON encoding mirrors protocol enums/tuples without serializing arbitrary objects.
    dto = json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    value = json.loads(safe_local_content({'value': dto}))['value']

    def scrub(item):
        if isinstance(item, str):
            for secret in sorted({v for v in sensitive if isinstance(v, str) and v}, key=len, reverse=True):
                item = item.replace(secret, '[redacted]')
            item = re.sub(r'(?i)\bBearer\s+[^\s"\'<>]+', 'Bearer [redacted]', item)
            return re.sub(r'\bsk-[A-Za-z0-9_-]+', '[redacted]', item)
        if isinstance(item, list):
            return [scrub(v) for v in item]
        if isinstance(item, dict):
            return {k: scrub(v) for k, v in item.items()}
        return item

    return scrub(value)


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class ModelAttemptSession:
    """One local LLM span per physical send; only controlled JSON values are accepted."""

    def __init__(self, manager, model, logical_span, request_id, max_attempts):
        config = getattr(manager, '_config', None)
        self.enabled = local_capture_enabled(manager) and getattr(manager, 'tracer', None) is not None
        self.manager, self.model, self.logical_span = manager, model, logical_span
        self.request_id, self.max_attempts = str(request_id), max_attempts
        self.span = self.tracker = None
        self.attempt_id = self.previous_attempt_id = self.retry_reason = None
        self.attempt_no = 0
        self._raw = self._output = None
        self._terminal = False
        self._last_publish = 0
        self._started = 0
        self._sensitive = ()
        self._reasoning = []
        budget = getattr(getattr(config, 'local_span_processor', None), 'run_queue_max_bytes', None)
        self._budget = budget if type(budget) is int and budget > 0 else 16 * 1024 * 1024
        self._remaining = self._budget
        self._exhausted = False
        if self.enabled and logical_span is not None:
            try:
                logical_span.set_attribute('nexent.local.openinference.span.kind', 'CHAIN')
            except Exception:
                self.enabled = False

    @_isolated
    def begin(self, body, *, semantic=None, config=None, provider=None):
        self.end()
        self.attempt_no += 1
        self.attempt_id = str(uuid4())
        values = {
            'nexent.local_only': True, 'openinference.span.kind': 'LLM', 'llm.model_name': self.model,
            'nexent.logical_request_id': self.request_id, 'nexent.attempt_id': self.attempt_id,
            'nexent.attempt_no': self.attempt_no, 'nexent.max_attempts': self.max_attempts,
            'nexent.output_complete': False, 'nexent.business_status': 'running',
            'nexent.config_fingerprint_version': 1,
        }
        if provider:
            values['model.provider'] = provider
        if self.previous_attempt_id:
            values['nexent.previous_attempt_id'] = self.previous_attempt_id
        if self.retry_reason:
            values['nexent.retry_reason'] = self.retry_reason
        self.span = self.manager.tracer.start_span(
            'model.attempt', context=trace.set_span_in_context(self.logical_span), attributes=values,
        )
        self._started = time.perf_counter()
        self._raw, self._output = {'stream': []}, {'complete': False, 'deltas': []}
        self._terminal, self._last_publish, self._sensitive = False, 0, ()
        self._reasoning = []
        self._remaining, self._exhausted = self._budget, False
        # Local projection collapses this wrapper; the remote logical span stays unchanged.
        self.tracker = self.manager.create_token_tracker(self.model, self.span)
        safe_body = _safe(body)
        if self._take(safe_body, 'raw.request'):
            self._raw['request'] = safe_body
        safe_input = _safe(semantic) if semantic is not None else safe_body
        if self._take(safe_input, 'input'):
            self._put('input.value', safe_input)
        self.span.set_attribute('nexent.request_fingerprint', hashlib.sha256(_encoded(safe_body).encode()).hexdigest())
        if config is not None:
            safe_config = _safe(config)
            if self._take(safe_config, 'effective_config'):
                self._put('nexent.effective_config', safe_config)
            self.span.set_attribute('nexent.config_fingerprint', hashlib.sha256(
                _encoded(safe_config).encode()).hexdigest())
        self.span.add_event('model.requested', {'nexent.event_id': str(uuid4())})
        self._publish(force=True)
        return self.tracker

    def _put(self, key, value):
        self.span.set_attribute(key, _encoded(value))

    def _take(self, value, field):
        size = len(_encoded(value).encode('utf-8'))
        if self._exhausted or size > self._remaining:
            self._exhausted = True
            self.span.set_attribute('nexent.trajectory.gap', True)
            self.span.set_attribute(f'nexent.availability.{field}', 'not_captured')
            self.span.add_event('capture.gap', {'reason_code': 'capture_budget', 'field': field})
            return False
        self._remaining -= size
        return True

    def _publish(self, *, force=False):
        if self.span is not None and (force or time.perf_counter() - self._last_publish >= 0.2):
            self._put('nexent.raw.value', self._raw)
            self._put('output.value', self._output)
            self._last_publish = time.perf_counter()

    @_isolated
    def raw_response(self, response):
        self._sensitive = tuple(response.sensitive_values)
        try:
            body = json.loads(response.body)
        except (ValueError, UnicodeError):
            body = response.body.decode('utf-8', errors='replace')
        value = {'status_code': response.status_code, 'body': _safe(body, self._sensitive)}
        if self._take(value, 'raw.response'):
            self._raw['response'] = value
        self._publish(force=True)

    @_isolated
    def frame(self, frame):
        self._sensitive = tuple(frame.sensitive_values)
        try:
            body = json.loads(frame.data)
        except ValueError:
            body = frame.data
        value = _safe(
            {'data': body, 'event': frame.event, 'event_id': frame.event_id}, self._sensitive,
        )
        if self._take(value, 'raw.stream'):
            self._raw['stream'].append(value)
        self._publish()

    def frames(self, frames):
        for frame in frames:
            self.frame(frame)
            yield frame

    async def aframes(self, frames):
        async for frame in frames:
            self.frame(frame)
            yield frame

    @_isolated
    def event(self, event):
        if self.span is None:
            return
        if event.type == 'message_completed':
            self.complete(event.message.model_dump(mode='json'))
        else:
            if event.type == 'usage':
                self._usage(event.usage.model_dump(mode='json'))
            value = _safe(event.model_dump(mode='json', exclude_none=True), self._sensitive)
            admitted = self._take(value, 'output')
            if admitted:
                self._output['deltas'].append(value)
            if admitted and event.type == 'reasoning_delta' and event.delta:
                self._reasoning.append(_safe(event.delta, self._sensitive))
            self._publish()

    @_isolated
    def legacy_chunk(self, chunk):
        if self.span is None:
            return
        value = _safe(chunk.model_dump(mode='json'))
        if not self._take(value, 'raw.stream'):
            return
        self._raw['stream'].append(value)
        for choice in value.get('choices', []):
            self._output['deltas'].append({'index': choice.get('index'), 'delta': choice.get('delta'),
                                           'finish_reason': choice.get('finish_reason')})
            delta = choice.get('delta') or {}
            thought = delta.get('reasoning_content') or delta.get('reasoning')
            if thought:
                self._reasoning.append(thought)
        if value.get('usage') is not None:
            self._raw['usage'] = value['usage']
            self._usage(value['usage'])
        self._publish()

    @_isolated
    def legacy_complete(self, content, finish_reason):
        if self.span is None:
            return
        reasoning, calls = [], {}
        for item in self._output['deltas']:
            delta = item.get('delta') or {}
            thought = delta.get('reasoning_content') or delta.get('reasoning')
            if thought:
                reasoning.append({'type': 'text', 'text': thought})
            for call in delta.get('tool_calls') or []:
                index = call.get('index', 0)
                target = calls.setdefault(index, {'index': index, 'raw_arguments': ''})
                if call.get('id'):
                    target['provider_call_id'] = call['id']
                function = call.get('function') or {}
                if function.get('name'):
                    target['name'] = target.get('name', '') + function['name']
                target['raw_arguments'] += function.get('arguments') or ''
        for call in calls.values():
            try:
                call['parsed_arguments'] = json.loads(call['raw_arguments'])
            except ValueError:
                call['argument_error'] = 'invalid_json'
        usage = self._raw.get('usage')
        self.span.set_attribute('nexent.usage_origin', 'provider' if usage is not None else 'unknown')
        self.complete({'content_parts': [{'type': 'text', 'text': content}], 'reasoning_parts': reasoning or None,
                       'tool_calls': list(calls.values()), 'finish_reason': finish_reason, 'usage': usage})

    @_isolated
    def legacy_failure(self, error, *, category, retryable=False, will_retry=False):
        if self.span is None:
            return
        # Read transport DTOs only; never stringify a provider exception into storage.
        import httpx

        from nexent.core.model_service.http_contracts import RawHttpResponse

        response = getattr(error, 'response', None)
        status = getattr(error, 'status_code', None)
        if isinstance(response, httpx.Response) and response.is_closed:
            secrets = []
            for key, value in response.request.headers.items():
                if key.lower() in {'authorization', 'x-api-key', 'api-key', 'cookie'}:
                    secrets.extend([value, value.removeprefix('Bearer ')])
            self.raw_response(RawHttpResponse(response.status_code, {}, response.content, tuple(secrets)))
        self.fail({'category': category, 'http_status': status if type(status) is int else None,
                   'retryable': retryable, 'will_retry': will_retry})

    @_isolated
    def complete(self, message):
        if self.span is None:
            return
        output = _safe(message, self._sensitive)
        admitted = self._take(output, 'output')
        if admitted:
            self._output = output
            self._output['complete'] = True
            self._put('nexent.reasoning.value', self._output.get('reasoning_parts'))
        self._usage(output.get('usage') or {})
        values = {}
        if output.get('finish_reason') is not None:
            values['llm.response.finish_reason'] = output['finish_reason']
        self.span.set_attributes(values)
        self.span.set_attributes({'nexent.output_complete': admitted, 'nexent.business_status': 'completed'})
        self.span.add_event('model.finished', {'nexent.event_id': str(uuid4())})
        self._terminal = True
        self._publish(force=True)

    def _usage(self, usage):
        values = {}
        for field, alias, attribute in (
            ('input_tokens', 'prompt_tokens', 'llm.token_count.prompt'),
            ('output_tokens', 'completion_tokens', 'llm.token_count.completion'),
            ('total_tokens', 'total_tokens', 'llm.token_count.total'),
            ('cached_input_tokens', 'cached_input_tokens', 'llm.prompt_cache.cached_input_tokens'),
            ('reasoning_tokens', 'reasoning_tokens', 'llm.usage.reasoning_tokens'),
        ):
            value = usage.get(field, usage.get(alias))
            if type(value) is int and value >= 0:
                values[attribute] = value
        known = bool(values)
        values['nexent.usage_origin'] = usage.get('origin', 'provider' if known else 'unknown')
        if usage.get('semantics_id'):
            values['nexent.usage_semantics_id'] = usage['semantics_id']
        self.span.set_attributes(values)

    @_isolated
    def fail(self, error):
        if self.span is None:
            return
        self.retry_reason = error.get('category', 'MODEL_ERROR')
        self._put('nexent.error', _safe(error, self._sensitive))
        self.span.set_attributes({'nexent.business_status': 'failed', 'nexent.output_complete': False})
        self.span.set_status(Status(StatusCode.ERROR, self.retry_reason))
        self.span.add_event('model.failed', {'nexent.event_id': str(uuid4()), 'category': self.retry_reason})
        self._terminal = True
        self.end()

    @_isolated
    def end(self, *, cancelled=False):
        if self.span is None:
            return
        span, self.span = self.span, None
        try:
            if not self._terminal:
                span.set_attribute('nexent.business_status', 'cancelled' if cancelled else 'interrupted')
            span.set_attributes(duration_attributes(self._started, time.perf_counter()))
            span.set_attribute('nexent.raw.value', _encoded(self._raw))
            span.set_attribute('output.value', _encoded(self._output))
            if self._reasoning and 'nexent.reasoning.value' not in (span.attributes or {}):
                span.set_attribute('nexent.reasoning.value', _encoded(''.join(self._reasoning)))
            # Mirror observed metrics without recording a second histogram sample.
            for key, value in (getattr(span, 'attributes', None) or {}).items():
                if key.startswith('llm.'):
                    self.logical_span.set_attribute(key, value)
            for event in span.events:
                if event.name == 'first_token_received':
                    self.logical_span.add_event(event.name, event.attributes, timestamp=event.timestamp)
        finally:
            self.previous_attempt_id = self.attempt_id
            span.end()
