# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Safe, call-scoped tracing at actual Jiuwen execution boundaries."""

import hashlib
import json
import sys
from contextlib import contextmanager
from contextvars import ContextVar

from nexent.monitor import get_agent_monitoring_context
from nexent.monitor.local_content import local_content_value
from nexent.monitor.run_capture import tool_capture_attributes


_active_span = ContextVar("jiuwen_active_tool_span", default=None)


@contextmanager
def tool_execution_trace(manager_factory, name, agent_name, attributes, *, tool_input=None, tool=None, observer=None):
    manager_context, span = None, None
    try:
        metadata = get_agent_monitoring_context()
        extra = getattr(metadata, "extra_metadata", None)
        run_id = extra.get("agentos_run_id") if isinstance(extra, dict) else None
        if isinstance(run_id, str) and run_id:
            attributes = {**attributes, "nexent.agentos.run_id": run_id}
        manager = manager_factory()
        if tool is not None:
            attributes = {**tool_capture_attributes(manager, tool, observer), **attributes}
        manager_context = manager.trace_tool_call(
            name, agent_name, safe_diagnostics=True,
            **{key: value for key, value in attributes.items() if value is not None},
        )
        span = manager_context.__enter__()
        _fingerprint(span, "input", tool_input)
    except Exception:
        manager_context = None
    token = _active_span.set(span)
    try:
        yield span
    except BaseException:
        error_info = sys.exc_info()
        if manager_context is not None:
            try:
                manager_context.__exit__(*error_info)
            except BaseException:
                pass
        raise
    else:
        if manager_context is not None:
            try:
                manager_context.__exit__(None, None, None)
            except Exception:
                pass
    finally:
        _active_span.reset(token)


def record_tool_result(is_error, result):
    """Structured result state is separate from normal call-return success."""
    span = _active_span.get()
    if span is not None:
        try:
            span.set_attributes({"nexent.tool.result.is_error": bool(is_error),
                                 "nexent.tool.execution_state": "returned"})
            _fingerprint(span, "output", result)
        except Exception:
            pass


def _fingerprint(span, field, value):
    """Identify the redacted runtime observation without exporting its body."""
    if span is None:
        return
    prefix = f"nexent.tool.{field}"
    try:
        cleaned = local_content_value(value)
        encoded = json.dumps(cleaned, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
        span.set_attributes({prefix + ".sha256": hashlib.sha256(encoded).hexdigest(),
                             prefix + ".size_bytes": len(encoded),
                             prefix + ".available": True,
                             prefix + ".representation": "redacted_runtime_value"})
    except Exception:
        try:
            span.set_attribute(prefix + ".available", False)
        except Exception:
            pass
