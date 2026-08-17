"""Runtime policy for Nexent's internal retrieval citation markers.

The model-facing citation protocol (for example ``[[a1]]``) is useful in a
chat response, but it is normally not desired in the body of a document sent
to an external writing tool.  Prompt instructions alone cannot guarantee that
boundary: a model can still copy the marker into a tool argument.

This module wraps the *actual* tool ``forward`` callable on the host.  It is
therefore shared by local, built-in and MCP tools, including tools invoked
through a sandbox bridge.
"""

from __future__ import annotations

import functools
import inspect
import logging
import re
from collections.abc import Mapping
from typing import Any, Iterable, Literal

from smolagents.utils import AgentExecutionError


CitationWriteMode = Literal["allow", "strip", "block"]

# Nexent's current citation protocol uses one tool sign plus a positive index:
# [[a1]], [[b12]], etc.  Do not match normal Markdown links or arbitrary
# double-bracket text written by the user.
_CITATION_MARKER_RE = re.compile(r"[ \t]*\[\[[a-z]\d+\]\]", re.IGNORECASE)

_DEFAULT_TEXT_FIELDS = frozenset({"content", "body", "text", "markdown"})
_DEFAULT_WRITE_TOOL_NAMES = frozenset(
    {
        "append_document",
        "create_document",
        "edit_document",
        "save_document",
        "update_document",
        "write_document",
        "append_file",
        "create_file",
        "edit_file",
        "save_file",
        "update_file",
    }
)
_WRITE_ACTIONS = ("append", "create", "edit", "save", "update", "write")


class _NoopAgentLogger:
    """Compatibility logger for direct tool calls outside a CoreAgent."""

    def log_error(self, _message: str) -> None:
        return None


class CitationWriteBlockedError(AgentExecutionError):
    """Raised when a configured write call contains internal citation markers."""

    def __init__(self, message: str, logger: logging.Logger | None = None):
        super().__init__(message, logger or _NoopAgentLogger())


def normalize_citation_write_mode(value: Any, default: CitationWriteMode = "strip") -> CitationWriteMode:
    """Return a safe citation-write mode.

    Invalid values intentionally fall back to ``default`` so a malformed tool
    metadata value cannot silently disable the host-side protection.
    """

    normalized = str(value or "").strip().lower()
    if normalized in {"allow", "strip", "block"}:
        return normalized  # type: ignore[return-value]
    return default


def _tool_guard_config(tool: Any) -> dict[str, Any]:
    config = getattr(tool, "_nexent_citation_write_guard_config", None)
    return dict(config) if isinstance(config, Mapping) else {}


def _is_write_tool(tool_name: str, config: Mapping[str, Any]) -> bool:
    """Whether the tool should have document-body citation policy applied."""

    if "enabled" in config:
        return bool(config["enabled"])

    name = (tool_name or "").lower()
    if name in _DEFAULT_WRITE_TOOL_NAMES:
        return True
    # Do not accidentally change skill code/files merely because its tool name
    # happens to include "write".  A skill author can opt in through metadata.
    if "skill" in name:
        return False
    return any(name.startswith(action) for action in _WRITE_ACTIONS) and any(
        token in name for token in ("document", "file", "note", "page", "markdown")
    )


def _text_fields(config: Mapping[str, Any]) -> frozenset[str]:
    configured_fields = config.get("text_fields")
    if not isinstance(configured_fields, (list, tuple, set)):
        return _DEFAULT_TEXT_FIELDS
    normalized = {str(field).strip().lower() for field in configured_fields if str(field).strip()}
    return frozenset(normalized) or _DEFAULT_TEXT_FIELDS


def _sanitize_value(value: Any, field_name: str, text_fields: frozenset[str], inherited_text_field: bool = False) -> tuple[Any, int]:
    """Remove markers recursively only inside configured document-body fields."""

    is_text_field = inherited_text_field or field_name.lower() in text_fields
    if isinstance(value, str):
        if not is_text_field:
            return value, 0
        sanitized, count = _CITATION_MARKER_RE.subn("", value)
        return sanitized, count
    if isinstance(value, Mapping):
        changed: dict[Any, Any] = {}
        total = 0
        for key, child in value.items():
            sanitized, count = _sanitize_value(
                child,
                str(key),
                text_fields,
                inherited_text_field=is_text_field,
            )
            changed[key] = sanitized
            total += count
        return changed, total
    if isinstance(value, list):
        changed_list = []
        total = 0
        for child in value:
            sanitized, count = _sanitize_value(
                child,
                field_name,
                text_fields,
                inherited_text_field=is_text_field,
            )
            changed_list.append(sanitized)
            total += count
        return changed_list, total
    if isinstance(value, tuple):
        changed_tuple = []
        total = 0
        for child in value:
            sanitized, count = _sanitize_value(
                child,
                field_name,
                text_fields,
                inherited_text_field=is_text_field,
            )
            changed_tuple.append(sanitized)
            total += count
        return tuple(changed_tuple), total
    return value, 0


def _positional_parameter_names(forward: Any) -> list[str]:
    """Best-effort mapping of positional tool arguments to parameter names."""

    try:
        return [
            parameter.name
            for parameter in inspect.signature(forward).parameters.values()
            if parameter.name not in {"self", "cls"}
            and parameter.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
    except (TypeError, ValueError):
        return []


def sanitize_citation_write_arguments(
    forward: Any,
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
    text_fields: Iterable[str] | None = None,
) -> tuple[tuple[Any, ...], dict[str, Any], int]:
    """Return copied arguments with internal citations removed from text fields."""

    normalized_fields = frozenset(str(field).strip().lower() for field in (text_fields or _DEFAULT_TEXT_FIELDS))
    parameter_names = _positional_parameter_names(forward)
    sanitized_args: list[Any] = []
    marker_count = 0
    for index, value in enumerate(args):
        field_name = parameter_names[index] if index < len(parameter_names) else ""
        # Many MCP tools expose a single positional document body without
        # introspectable parameter metadata.  Treat that specific shape as
        # content, while leaving multi-argument unknown calls untouched.
        if not field_name and len(args) == 1 and isinstance(value, (str, Mapping, list, tuple)):
            field_name = "content"
        sanitized, count = _sanitize_value(value, field_name, normalized_fields)
        sanitized_args.append(sanitized)
        marker_count += count

    sanitized_kwargs: dict[str, Any] = {}
    for field_name, value in kwargs.items():
        sanitized, count = _sanitize_value(value, str(field_name), normalized_fields)
        sanitized_kwargs[field_name] = sanitized
        marker_count += count
    return tuple(sanitized_args), sanitized_kwargs, marker_count


def wrap_tool_with_citation_write_guard(
    tool: Any,
    agent_mode: CitationWriteMode | str = "strip",
    logger: logging.Logger | None = None,
) -> bool:
    """Install the document-write policy on one actual tool callable.

    ``metadata.citation_write_guard`` may opt a tool in/out or override the
    mode and content fields.  Example configuration for a remote MCP tool::

        {"citation_write_guard": {"enabled": True, "mode": "strip",
          "text_fields": ["content", "markdown"]}}

    Returns whether a wrapper was installed.  The operation is idempotent.
    """

    if tool is None or getattr(tool, "_nexent_citation_write_guard_wrapped", False):
        return False
    original_forward = getattr(tool, "forward", None)
    if not callable(original_forward):
        return False

    config = _tool_guard_config(tool)
    tool_name = str(getattr(tool, "name", "") or "")
    if not _is_write_tool(tool_name, config):
        return False

    mode = normalize_citation_write_mode(config.get("mode"), normalize_citation_write_mode(agent_mode))
    if mode == "allow":
        return False
    fields = _text_fields(config)

    def prepare_call(args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
        sanitized_args, sanitized_kwargs, marker_count = sanitize_citation_write_arguments(
            original_forward,
            args,
            kwargs,
            fields,
        )
        if not marker_count:
            return args, dict(kwargs)
        if mode == "block":
            raise CitationWriteBlockedError(
                f"CitationWriteGuard blocked '{tool_name}': document text contains internal citation markers.",
                logger,
            )
        if logger:
            message = (
                "CitationWriteGuard stripped "
                f"{marker_count} internal citation marker(s) from tool '{tool_name}'."
            )
            # Standard Python loggers expose ``info``; smolagents' AgentLogger
            # exposes ``log`` instead.  Supporting both keeps sanitisation from
            # becoming a new failure point at the execution boundary.
            if hasattr(logger, "info"):
                logger.info(message)
            elif hasattr(logger, "log"):
                logger.log(message)
        return sanitized_args, sanitized_kwargs

    if inspect.iscoroutinefunction(original_forward):
        @functools.wraps(original_forward)
        async def guarded_forward(*args: Any, **kwargs: Any) -> Any:
            clean_args, clean_kwargs = prepare_call(args, kwargs)
            return await original_forward(*clean_args, **clean_kwargs)
    else:
        @functools.wraps(original_forward)
        def guarded_forward(*args: Any, **kwargs: Any) -> Any:
            clean_args, clean_kwargs = prepare_call(args, kwargs)
            return original_forward(*clean_args, **clean_kwargs)

    tool.forward = guarded_forward
    try:
        tool._nexent_citation_write_guard_wrapped = True
    except Exception:
        # Some remote tool proxies reject custom attributes.  The assigned
        # callable is still valid; a repeated wrap is safe but less efficient.
        pass
    return True
