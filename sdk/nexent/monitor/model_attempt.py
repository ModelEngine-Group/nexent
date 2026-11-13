# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Local physical model attempts, independent of the existing remote logical span."""

from __future__ import annotations

import hashlib
import json
import re
import time
from functools import wraps
from io import StringIO
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
        self._started = 0
        self._sensitive = ()
        self._reset_buffer()
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
        self._raw, self._output = {}, {'complete': False}
        self._terminal, self._sensitive = False, ()
        self._reset_buffer()
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

    def _reset_buffer(self):
        self._text = {key: StringIO() for key in ('content', 'reasoning', 'refusal')}
        self._calls = {}
        self._buffered_bytes = 0
        self._usage_value = None

    def _reserve_buffer(self, size):
        if self._exhausted:
            return False
        if size > self._remaining:
            self._exhausted = True
            self.span.set_attribute('nexent.trajectory.gap', True)
            self.span.set_attribute('nexent.availability.output', 'not_captured')
            self.span.add_event('capture.gap', {'reason_code': 'capture_budget', 'field': 'output'})
            return False
        self._remaining -= size
        self._buffered_bytes += size
        return True

    def _append_text(self, target, value):
        if isinstance(value, str) and value:
            # Charge encoded content, independently of the provider's chunk boundaries.
            if self._reserve_buffer(len(_encoded(value).encode('utf-8')) - 2):
                target.write(value)

    def _call_delta(self, index, *, call_id=None, name=None, arguments=None, local_id=None):
        if index not in self._calls:
            identity = {'index': index, 'provider_call_id': call_id, 'local_call_id': local_id}
            if not self._reserve_buffer(len(_encoded(identity).encode('utf-8'))):
                return
            self._calls[index] = {**identity, 'name': StringIO(), 'raw_arguments': StringIO()}
        call = self._calls[index]
        if call_id:
            call['provider_call_id'] = call_id
        self._append_text(call['name'], name)
        self._append_text(call['raw_arguments'], arguments)

    def _merged_output(self):
        calls = []
        for _, call in sorted(self._calls.items()):
            value = {key: item.getvalue() if isinstance(item, StringIO) else item for key, item in call.items()}
            try:
                value['parsed_arguments'] = json.loads(value['raw_arguments'])
            except ValueError:
                value['argument_error'] = 'invalid_json'
            calls.append(value)
        text = {key: value.getvalue() for key, value in self._text.items()}
        return {
            'content_parts': [{'type': 'text', 'text': text['content']}] if text['content'] else [],
            'reasoning_parts': [{'type': 'text', 'text': text['reasoning']}] if text['reasoning'] else [],
            'refusal': text['refusal'] or None, 'tool_calls': calls, 'usage': self._usage_value,
        }

    def _save_output(self, message, *, complete):
        # The final message replaces, rather than adds to, the bounded stream buffer.
        output = _safe(message, self._sensitive)
        metadata = output.get('provider_metadata')
        if isinstance(metadata, dict):
            metadata.pop('unmapped_delta_fields', None)
        self._remaining += self._buffered_bytes
        self._reset_buffer()
        output['complete'] = complete
        admitted = self._take(output, 'output')
        if admitted:
            self._output = output
        return admitted

    @_isolated
    def raw_response(self, response):
        self._sensitive = tuple(dict.fromkeys((*self._sensitive, *response.sensitive_values)))
        try:
            body = json.loads(response.body)
        except (ValueError, UnicodeError):
            body = response.body.decode('utf-8', errors='replace')
        value = {'status_code': response.status_code, 'body': _safe(body, self._sensitive)}
        if self._take(value, 'raw.response'):
            self._raw['response'] = value

    @_isolated
    def frame(self, frame):
        # Frames remain transport data; retain credentials only for final redaction.
        self._sensitive = tuple(dict.fromkeys((*self._sensitive, *frame.sensitive_values)))

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
        if self.span is None or self._terminal:
            return
        if event.type == 'message_completed':
            self.complete(event.message.model_dump(mode='json'))
        elif event.type == 'usage':
            self._usage_value = event.usage.model_dump(mode='json')
            self._usage(self._usage_value)
        elif event.type in {'text_delta', 'reasoning_delta'}:
            key = 'reasoning' if event.type == 'reasoning_delta' else (
                'refusal' if event.content_kind == 'refusal' else 'content'
            )
            self._append_text(self._text[key], event.delta)
        elif event.type == 'tool_call_delta':
            call = event.tool_call_delta
            self._call_delta(call.index, call_id=call.provider_call_id, local_id=str(call.local_call_id),
                             name=call.name_delta, arguments=call.arguments_delta)

    @_isolated
    def legacy_chunk(self, chunk):
        if self.span is None or self._terminal:
            return
        value = chunk.model_dump(mode='json')
        for choice in value.get('choices', []):
            delta = choice.get('delta') or {}
            self._append_text(self._text['content'], delta.get('content'))
            self._append_text(self._text['reasoning'], delta.get('reasoning_content') or delta.get('reasoning'))
            self._append_text(self._text['refusal'], delta.get('refusal'))
            for call in delta.get('tool_calls') or []:
                function = call.get('function') or {}
                self._call_delta(call.get('index', 0), call_id=call.get('id'),
                                 name=function.get('name'), arguments=function.get('arguments'))
        if value.get('usage') is not None:
            self._usage_value = value['usage']
            self._usage(value['usage'])

    @_isolated
    def legacy_complete(self, content, finish_reason):
        if self.span is None:
            return
        message = self._merged_output()
        message['content_parts'] = [{'type': 'text', 'text': content}]
        message['finish_reason'] = finish_reason
        self.complete(message)

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
        admitted = self._save_output(output, complete=True)
        self._usage(output.get('usage') or {})
        values = {}
        if output.get('finish_reason') is not None:
            values['llm.response.finish_reason'] = output['finish_reason']
        self.span.set_attributes(values)
        self.span.set_attributes({'nexent.output_complete': admitted, 'nexent.business_status': 'completed'})
        self.span.add_event('model.finished', {'nexent.event_id': str(uuid4())})
        self._terminal = True

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
        if not self._output.get('complete'):
            self._save_output(self._merged_output(), complete=False)
        span, self.span = self.span, None
        try:
            if not self._terminal:
                span.set_attribute('nexent.business_status', 'cancelled' if cancelled else 'interrupted')
            span.set_attributes(duration_attributes(self._started, time.perf_counter()))
            span.set_attribute('nexent.raw.value', _encoded(self._raw))
            span.set_attribute('output.value', _encoded(self._output))
            if self._output.get('reasoning_parts'):
                span.set_attribute('nexent.reasoning.value', _encoded(self._output['reasoning_parts']))
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
