# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Safe immutable input and lifecycle capture at the actual Agent worker boundary."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import fields, is_dataclass
from functools import wraps
from importlib.metadata import PackageNotFoundError, version

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel

from .duration import duration_attributes
from .local_content import local_capture_enabled, local_content_value, safe_local_content


def _gap(span, field):
    try:
        span.set_attributes({'nexent.trajectory.gap': True, f'nexent.availability.{field}': 'serialization_failed'})
    except Exception:
        pass


def _dto(value):
    return local_content_value(value)


def _configuration(value, availability, path='effective_config'):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode='python')
    elif is_dataclass(value) and not isinstance(value, type):
        value = {field.name: getattr(value, field.name) for field in fields(value)}
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if (key in {'url', 'base_url', 'api_base', 'endpoint', 'credential_ref', 'http_headers',
                        'auth_headers', 'api_key', 'connection_rules', 'connection', 'provenance'}
                    or key.endswith('_url')):
                availability[f'{path}.{key}'] = {'status': 'redacted', 'reason_code': 'connection_private'}
            else:
                result[key] = _configuration(item, availability, f'{path}.{key}')
        return result
    if isinstance(value, list):
        return [_configuration(item, availability, f'{path}.{i}') for i, item in enumerate(value)]
    try:
        return _dto(value)
    except ValueError:
        availability[path] = {'status': 'unsupported', 'reason_code': 'runtime_collaborator'}
        return None


def capture_run_input(manager, span, *, query, agent_config, model_configs, history=None,
                      context_items=None, attachments=None, app_version=None):
    """Capture only the authorized snapshots supplied by the worker's existing callers."""
    if not local_capture_enabled(manager) or span is None:
        return
    try:
        availability = {}
        configuration = _configuration({'agent_config': agent_config, 'model_configs': model_configs}, availability)
        safe_config = json.loads(safe_local_content(configuration))
        canonical = json.dumps(safe_config, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        body = {'query': _dto(query), 'effective_config': safe_config,
                'context': {'history': _dto(history), 'context_items': _dto(context_items)},
                'attachments': _dto(attachments)}
        body['availability'] = availability
        attributes = {
            'nexent.local.input.value': safe_local_content(body),
            'nexent.config_fingerprint_version': 1,
            'nexent.config_fingerprint': hashlib.sha256(canonical.encode()).hexdigest(),
            'nexent.core_type': 'smolagents',
            'nexent.core_adapter_version': 1,
            'nexent.trajectory.schema_version': 1,
            'nexent.availability.connection': 'redacted',
        }
        for package, field in (('nexent', 'sdk_version'), ('smolagents', 'core_version')):
            try:
                attributes[f'nexent.{field}'] = version(package)
            except PackageNotFoundError:
                attributes[f'nexent.availability.{field}'] = 'unsupported'
        if app_version is not None:
            attributes['nexent.app_version'] = str(app_version)
        else:
            attributes['nexent.availability.app_version'] = 'not_captured'
        span.set_attributes(attributes)
    except Exception:
        _gap(span, 'input')


def capture_run_result(manager, span, *, outcome):
    """Cancellation caught by the worker still has a cancelled business result."""
    if not local_capture_enabled(manager) or span is None:
        return
    status = {'stopped': 'cancelled', 'completed': 'completed', 'failed': 'failed'}.get(outcome, 'interrupted')
    try:
        span.set_attributes({'nexent.business_status': status, 'nexent.cancelled': status == 'cancelled'})
    except Exception:
        _gap(span, 'business_status')


def capture_context_values(manager, span, *, before=None, after=None, evidence=None):
    """Retain the actual before/after values; estimates are never provider usage."""
    if not local_capture_enabled(manager) or span is None:
        return
    try:
        attributes = {'nexent.token_measurement_origin': 'estimate'}
        if before is not None:
            attributes['input.value'] = safe_local_content(_dto(before))
        if after is not None:
            attributes['output.value'] = safe_local_content(_dto(after))
        if evidence is not None:
            attributes['nexent.context.evidence'] = safe_local_content(_dto(evidence))
        span.set_attributes(attributes)
    except Exception:
        _gap(span, 'context')


def capture_context_assembly(method):
    """Place compression model calls under a local context operation with safe errors."""
    @wraps(method)
    def captured(*args, **kwargs):
        from . import get_monitoring_manager

        manager = get_monitoring_manager()
        if not local_capture_enabled(manager):
            return method(*args, **kwargs)
        try:
            span = manager.tracer.start_span(
                'context.assemble', attributes={'nexent.local_only': True, 'openinference.span.kind': 'CHAIN'},
            )
        except Exception:
            _gap(trace.get_current_span(), 'context')
            return method(*args, **kwargs)
        started = time.perf_counter()
        try:
            with trace.use_span(span, record_exception=False, set_status_on_exception=False):
                try:
                    result = method(*args, **kwargs)
                except BaseException as error:
                    try:
                        span.set_status(Status(StatusCode.ERROR, type(error).__name__))
                        span.set_attribute('nexent.business_status', 'failed')
                    except Exception:
                        _gap(span, 'context')
                    raise
                capture_context_values(manager, span, after=result.messages, evidence=result.evidence)
                try:
                    span.add_event('context.compacted' if result.evidence.compression_attempted else 'context.updated')
                except Exception:
                    _gap(span, 'context')
                return result
        finally:
            try:
                span.set_attributes(duration_attributes(started, time.perf_counter()))
                span.end()
            except Exception:
                _gap(trace.get_current_span(), 'context')
    return captured


def capture_current_context_input(before):
    """Capture projected items before adaptive compaction mutates the selected representation."""
    from . import get_monitoring_manager

    manager = get_monitoring_manager()
    if local_capture_enabled(manager):
        capture_context_values(manager, trace.get_current_span(), before=before)


def tool_capture_attributes(manager, tool, observer=None):
    """Bind the executing implementation and observer identity to the local tool node."""
    if not local_capture_enabled(manager):
        return {}
    try:
        definition = {field: _dto(getattr(tool, field, None))
                      for field in ('name', 'description', 'inputs', 'output_type')}
        attributes = {
            'nexent.local.tool.definition': safe_local_content(definition),
            'nexent.local.tool.implementation': f'{type(tool).__module__}.{type(tool).__qualname__}',
            'nexent.availability.tool.implementation_version': 'unsupported',
        }
        call_id = getattr(observer, 'current_tool_call_id', None)
        if isinstance(call_id, str) and call_id:
            attributes['nexent.local.nexent.call_id'] = call_id
        return attributes
    except Exception:
        return {'nexent.trajectory.gap': True, 'nexent.availability.tool.definition': 'serialization_failed'}
