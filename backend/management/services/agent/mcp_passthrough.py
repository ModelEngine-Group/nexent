# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Northbound MCP header passthrough — Phase 1 helpers.

This module owns every piece of logic that bridges a northbound ``metadata``
reserved field (``_mcp_headers`` / ``_mcp_headers_by_server``) into the MCP
HTTP session, plus the ``${HeaderName}`` placeholder resolution engine that
lets admin-authored MCP static headers defer identity fields to the request.

Design contract in ``nexent-doc/nexent/northbound-mcp-header-passthrough/``.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException


logger = logging.getLogger("northbound-mcp-passthrough")


# ---------------------------------------------------------------------------
# 1. Reserved-field extraction
# ---------------------------------------------------------------------------

def _lowercase_keys(d: Dict[str, Any]) -> Dict[str, Any]:
    return {str(k).lower(): v for k, v in d.items()}


def extract_passthrough_headers(
    metadata: Optional[Dict[str, Any]],
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Return ``(mode, headers_map)`` from ``metadata`` reserved fields.

    ``mode`` is one of ``"by_server"`` (URL-routed) / ``"global"`` (one
    header block for every MCP server) / ``None`` (no reserved fields).
    ``by_server`` always wins when both forms are present — ``_mcp_headers``
    is silently ignored so callers do not get surprise double-injection.
    All key names in the returned map are lowercased; values are kept as-is.
    """
    if not metadata:
        return None, {}

    by_server = metadata.get("_mcp_headers_by_server")
    if isinstance(by_server, dict):
        return "by_server", {
            str(url): _lowercase_keys(block)
            for url, block in by_server.items()
            if isinstance(block, dict)
        }

    global_headers = metadata.get("_mcp_headers")
    if isinstance(global_headers, dict):
        return "global", _lowercase_keys(global_headers)

    return None, {}


# ---------------------------------------------------------------------------
# 2. Routing + static-priority merge
# ---------------------------------------------------------------------------

def route_passthrough_headers(
    mode: Optional[str],
    headers_map: Dict[str, Any],
    url: str,
) -> Dict[str, str]:
    """Resolve per-server passthrough headers from the extracted map."""
    if not mode:
        return {}
    if mode == "by_server":
        block = headers_map.get(url) or {}
        return dict(block)  # shallow copy so callers may mutate
    return dict(headers_map)


def merge_static_priority(
    existing: Optional[Dict[str, Any]],
    dynamic: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Merge dynamic headers into the static preset with STATIC priority.

    Any key already present in ``existing`` is preserved; dynamic values
    only fill gaps.  Comparison is **case-insensitive** because HTTP header
    names are case-insensitive — otherwise a static ``Cookie`` and a dynamic
    ``cookie`` would both be emitted as duplicate headers.

    This keeps MCP-server-level auth tokens (e.g. the
    ``X-Nexent-Internal-Token`` header injected for the local tenant MCP)
    from being overwritten by a caller-supplied ``Authorization``.
    """
    result: Dict[str, Any] = dict(existing or {})
    occupied = {str(k).lower() for k in result}
    for k, v in (dynamic or {}).items():
        if str(k).lower() not in occupied:
            result[k] = v
            occupied.add(str(k).lower())
    return result


# ---------------------------------------------------------------------------
# 3. Placeholder engine (${Name} with $${ escape + fail-closed semantics)
# ---------------------------------------------------------------------------

# Matches either $${Name} (escape → literal ${Name}) or ${Name} (resolve).
_PLACEHOLDER_RE = re.compile(r"\$\$\{([A-Za-z0-9_-]+)\}|\$\{([A-Za-z0-9_-]+)\}")


def resolve_placeholders(
    static_headers: Optional[Dict[str, Any]],
    context_headers: Dict[str, str],
    *,
    passthrough_allowed: bool,
    run_id: str,
    agent_id: int,
    server_url: str,
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """Substitute ``${Name}`` placeholders inside ``static_headers`` values.

    Returns a 3-tuple:
        (resolved_headers, resolved_names, unresolved_names)

    Rules baked in here (never compromised by callers):

    * **Switch-gated.** ``passthrough_allowed=False`` discards every header
      whose value contains a real ``${...}`` placeholder — we never ship a
      literal ``${Cookie}`` to an MCP server, even when the admin config got
      pasted in by accident.  ``$${Name}`` escapes survive as literal text.
    * **Case-insensitive.** Context headers are matched after lowercasing
      the placeholder name, matching HTTP header semantics.
    * **Fail-closed.** Any placeholder that cannot be resolved causes the
      whole header entry to be dropped (we log which names were missing so
      ops can fix the admin config), not just unset.
    * **No placeholders → no-op.**  Plain literal values are returned as-is.
    """
    if not static_headers:
        return {}, [], []

    resolved: Dict[str, Any] = {}
    resolved_names: List[str] = []
    unresolved_names: List[str] = []

    for name, raw_value in static_headers.items():
        if not isinstance(raw_value, str) or "${" not in raw_value:
            # No placeholder at all — keep as-is (includes non-string values).
            resolved[name] = raw_value
            continue

        if not passthrough_allowed:
            # Agent switch is OFF: drop every header that still contains a
            # REAL ${...} placeholder.  Fully-escaped $${...} entries are
            # converted to literal ${...} and KEPT — the admin explicitly
            # typed them as literals and we must not interpret them.
            has_real_placeholder = False
            for m in _PLACEHOLDER_RE.finditer(raw_value):
                if m.group(2) is not None:
                    has_real_placeholder = True
                    break

            if has_real_placeholder:
                logger.warning(
                    "agent_id=%s run_id=%s server_url=%s "
                    "event=placeholder_dropped_switch_off header=%s",
                    agent_id, run_id, server_url, name,
                )
                continue

            processed = _PLACEHOLDER_RE.sub(
                lambda m: "${" + m.group(1) + "}" if m.group(1) is not None else m.group(0),
                raw_value,
            )
            resolved[name] = processed
            continue

        # Switch ON — attempt real resolution.
        seen_placeholders: List[str] = []

        def _sub(match: "re.Match[str]") -> str:
            escaped = match.group(1)   # $${Name} case
            real = match.group(2)      # ${Name} case
            if escaped is not None:
                return "${" + escaped + "}"
            # Real placeholder — remember for resolution tracking.
            key = real.lower()
            seen_placeholders.append(key)
            return context_headers.get(key, match.group(0))

        processed = _PLACEHOLDER_RE.sub(_sub, raw_value)

        if seen_placeholders:
            missing = [n for n in seen_placeholders if context_headers.get(n) is None]
            if missing:
                # Fail-closed: drop the whole header entry.
                unresolved_names.extend(missing)
                logger.warning(
                    "agent_id=%s run_id=%s server_url=%s "
                    "event=placeholder_unresolved header=%s unresolved=%s",
                    agent_id, run_id, server_url, name, sorted(set(missing)),
                )
                continue
            resolved_names.extend(seen_placeholders)

        resolved[name] = processed

    return resolved, sorted(set(resolved_names)), sorted(set(unresolved_names))


# ---------------------------------------------------------------------------
# 4. Pure pre-validation — raises AppException BEFORE any SSE is committed
# ---------------------------------------------------------------------------


def validate_mcp_header_passthrough(
    metadata: Optional[Dict[str, Any]],
    agent_record: Dict[str, Any],
    mcp_host: Sequence[Any],
) -> None:
    """Raise :class:`AppException` when the caller-supplied passthrough
    headers would violate the contract documented in the Phase-1 spec.

    This function is **non-mutating** — it never touches ``mcp_host``.  It
    exists so callers that need to fail **before** opening an SSE stream
    (to surface HTTP 400 + business code 010111 at the northbound entry
    point) can check early without triggering the full run machinery.
    """
    if not isinstance(mcp_host, list) or not mcp_host:
        return

    mode, passthrough_headers = extract_passthrough_headers(metadata)

    # by_server routing: every URL key must match a configured MCP server.
    if mode == "by_server" and passthrough_headers:
        configured_urls = {
            str(item["url"])
            for item in mcp_host
            if isinstance(item, dict) and "url" in item
        }
        unmatched = sorted(set(passthrough_headers) - configured_urls)
        if unmatched:
            raise AppException(
                ErrorCode.CHAT_MCP_HEADER_ROUTE_NOT_FOUND,
                details={"unmatched_server_urls": unmatched},
            )


# ---------------------------------------------------------------------------
# 5. Top-level orchestration — modifies mcp_host in place
# ---------------------------------------------------------------------------


def apply_mcp_header_passthrough(
    mcp_host: List[Any],
    metadata: Optional[Dict[str, Any]],
    *,
    agent_id: int,
    tenant_id: str,
    version_no: int,
    run_id: str,
) -> None:
    """Run every Phase 1 step against ``mcp_host`` in place.

    Call this AFTER the MCP host list has been assembled (static auth +
    custom headers from DB are already present) but BEFORE the list is
    handed to ``build_run_info``.  The function is deliberately defensive:
    a malformed ``mcp_host`` list leaves no trace, and a missing agent
    record is treated as "passthrough disabled" — never open the flood
    gate on a failed lookup.
    """
    if not isinstance(mcp_host, list) or not mcp_host:
        return

    from management.db.agent.repository import search_agent_info_by_agent_id

    try:
        agent_record = search_agent_info_by_agent_id(
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no,
        ) or {}
    except Exception:
        # Never open the flood gate on a failed lookup.
        logger.warning(
            "agent_id=%s run_id=%s event=agent_lookup_failed passthrough_disabled",
            agent_id, run_id,
        )
        agent_record = {}

    # Pre-check: raise AppException before any mutation happens.  Callers that
    # want HTTP 400 instead of SSE error must run the same check BEFORE the
    # StreamingResponse is returned — this guard keeps the error semantics
    # identical everywhere apply() is called from.
    try:
        validate_mcp_header_passthrough(metadata, agent_record, mcp_host)
    except AppException:
        raise
    except Exception:
        # validate never raises non-AppException in happy-path failures, but
        # a malformed mcp_host or metadata dict should be treated exactly
        # like the rest of apply — never let a tool-side issue crash the run.
        logger.warning(
            "agent_id=%s run_id=%s event=passthrough_precheck_failed",
            agent_id, run_id,
            exc_info=True,
        )

    passthrough_allowed = bool(
        agent_record.get("allow_mcp_header_passthrough", False)
    )

    mode, passthrough_headers = extract_passthrough_headers(metadata)

    # -----------------------------------------------------------------------
    # Mutation phase — only starts now.  All validation errors above raised
    # before any call to mcp_host item["headers"] = ... happens.
    # -----------------------------------------------------------------------

    for item in mcp_host:
        if not isinstance(item, dict) or "url" not in item:
            # Fallback string URLs carry no headers — skip silently.
            continue

        server_url = str(item["url"])
        current_headers = item.get("headers") or {}

        # ---- Placeholder resolution (uses metadata headers as context) ----
        context_block = (
            passthrough_headers.get(server_url)
            if mode == "by_server"
            else passthrough_headers
        ) or {}

        resolved, resolved_names, _unresolved = resolve_placeholders(
            current_headers,
            context_block,
            passthrough_allowed=passthrough_allowed,
            run_id=run_id,
            agent_id=agent_id,
            server_url=server_url,
        )

        # ---- Dynamic injection (static priority merge) ----
        if passthrough_allowed and mode is not None:
            dynamic = route_passthrough_headers(mode, passthrough_headers, server_url)
            effective_headers = merge_static_priority(resolved, dynamic)
            if dynamic:
                logger.info(
                    "agent_id=%s run_id=%s server_url=%s "
                    "event=passthrough_injected keys=%s",
                    agent_id, run_id, server_url, sorted(dynamic.keys()),
                )
        else:
            effective_headers = resolved

        # Keep the original mcp_host shape: entries that had no headers must
        # stay header-less, otherwise every agent payload grows an empty dict.
        if effective_headers or "headers" in item:
            item["headers"] = effective_headers

        if resolved_names:
            logger.info(
                "agent_id=%s run_id=%s server_url=%s "
                "event=placeholder_resolved placeholders=%s",
                agent_id, run_id, server_url, sorted(set(resolved_names)),
            )

    # Audit: caller supplied reserved fields but the agent switch is OFF.
    if not passthrough_allowed and mode is not None:
        raw_keys: List[str]
        if mode == "global":
            raw_keys = sorted(passthrough_headers.keys())
        else:
            raw_keys = sorted({
                k for block in passthrough_headers.values()
                for k in block.keys()
            })
        logger.warning(
            "agent_id=%s run_id=%s reason=agent_switch_off "
            "mode=%s raw_keys=%s",
            agent_id, run_id, mode, raw_keys,
        )
