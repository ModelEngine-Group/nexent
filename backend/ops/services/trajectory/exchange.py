# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exchange one native conversation archive without persistent import state."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import re
import stat
import tempfile
import zipfile
import zlib
from dataclasses import dataclass

from infrastructure.trace.trajectory_io import (
    TrajectoryConflict,
    TrajectoryCorrupt,
)
from infrastructure.trace.trajectory_reader import (
    JSONReader,
    Text,
    TrajectoryReadBudgetExceeded,
)
from infrastructure.trace.trajectory_store import (
    CaptureIdentity,
    TrajectoryFileStore,
    component,
)

from .archive import storage_error
from .nodes import attributes, build_nodes
from .primitives import Budget, QueryError
from .service import TrajectoryService

CHUNK = 64 * 1024


@dataclass(frozen=True)
class ExchangeLimits:
    compressed_bytes: int = 32 * 1024 * 1024
    unpacked_bytes: int = 128 * 1024 * 1024
    meta_bytes: int = 8 * 1024 * 1024
    response_bytes: int = 128 * 1024 * 1024
    files: int = 10000
    seconds: float = 30


def configured_limits():
    from contracts.constants import environment as config

    return ExchangeLimits(
        compressed_bytes=config.TRAJECTORY_EXCHANGE_MAX_ZIP_BYTES,
        unpacked_bytes=config.TRAJECTORY_EXCHANGE_MAX_BYTES,
        meta_bytes=config.TRAJECTORY_EXCHANGE_MAX_META_BYTES,
        response_bytes=config.TRAJECTORY_EXCHANGE_MAX_RESPONSE_BYTES,
        files=config.TRAJECTORY_EXCHANGE_MAX_FILES,
        seconds=config.TRAJECTORY_EXCHANGE_SECONDS,
    )


def _limit(value, maximum):
    if value > maximum:
        raise QueryError("archive_too_large", 413)


def _prefix(meta):
    return "/".join(
        (
            component(meta["tenant_id"]),
            component(meta["owner_user_id"]),
            meta.get("agent_id", meta.get("storage_agent_id")) or "_unknown",
            meta["conversation_id"],
        )
    )


def export_conversation(
    service, actor, conversation_id, tenant_id=None, target_user_id=None, *, limits=None
):
    limits = limits or ExchangeLimits()
    budget = Budget(max_bytes=limits.unpacked_bytes, seconds=limits.seconds)
    row = service.resolve(actor, conversation_id, tenant_id, target_user_id)
    meta = service.archive.manifest(row, persist_retention=False)
    if not meta:
        raise QueryError("nothing_to_export", 409)
    snapshot = copy.deepcopy(meta)
    prefix = _prefix(snapshot)
    selected = []
    for run in snapshot["runs"]:
        state = service.archive.available(run)
        if state in {"available", "partial"}:
            selected.append(run)
        elif state == "expired" and run["capture_state"] != "expired":
            run.update(
                capture_state="expired",
                cleanup_reason=run.get("cleanup_reason") or "retention",
            )
    if not selected:
        raise QueryError("nothing_to_export", 409)
    _limit(len(selected) + 1, limits.files)
    encoded = json.dumps(
        snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()
    _limit(len(encoded), limits.meta_bytes)
    _limit(
        len(encoded) + sum(run["confirmed_bytes"] for run in selected),
        limits.unpacked_bytes,
    )
    output = io.BytesIO()
    try:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{prefix}/meta.json", encoded)
            for run in selected:
                expected = {
                    "cleanup": meta["cleanup_version"],
                    "publication": meta["publication_no"],
                    "hash": run["confirmed_sha256"],
                }
                with (
                    service.archive.opened(
                        row, run["trajectory_id"], budget, expected
                    ) as (fd, _, current),
                    archive.open(
                        f"{prefix}/{run['trajectory_id']}.otlp.jsonl", "w"
                    ) as target,
                ):
                    offset = 0
                    while offset < current["confirmed_bytes"]:
                        budget.check()
                        data = os.pread(
                            fd,
                            min(CHUNK, current["confirmed_bytes"] - offset),
                            offset,
                        )
                        if not data:
                            raise QueryError("snapshot_reset", 409)
                        target.write(data)
                        offset += len(data)
                        _limit(output.tell(), limits.compressed_bytes)
        _limit(output.tell(), limits.compressed_bytes)
        current = service.archive.manifest(
            service.recheck(actor, row), persist_retention=False
        )
        if current is None or current["cleanup_version"] != meta["cleanup_version"]:
            raise QueryError("snapshot_reset", 409)
        for run in selected:
            service.archive.run(
                current,
                run["trajectory_id"],
                {
                    "cleanup": meta["cleanup_version"],
                    "publication": meta["publication_no"],
                    "hash": run["confirmed_sha256"],
                },
            )
        budget.check()
        return output.getvalue()
    except QueryError as error:
        if error.code == "content_expired":
            raise QueryError("snapshot_reset", 409) from error
        raise
    finally:
        output.close()


def _read_entry(archive, item, target, budget, remaining):
    digest, size = hashlib.sha256(), 0
    with archive.open(item) as source:
        while data := source.read(CHUNK):
            budget.check()
            size += len(data)
            _limit(size, remaining)
            target.write(data)
            digest.update(data)
    if size != item.file_size:
        raise ValueError("ZIP length differs")
    target.seek(0)
    return size, digest.hexdigest()


def _manifest(archive, item, prefix, limits, budget):
    with io.BytesIO() as stream:
        _read_entry(archive, item, stream, budget, limits.meta_bytes)

        # Bounded input, duplicate keys and non-finite numbers are rejected before validation.
        def pairs(values):
            result = {}
            for key, value in values:
                if key in result:
                    raise ValueError("Duplicate metadata key")
                result[key] = value
            return result

        meta = json.loads(
            stream.getvalue(),
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    pending, count = [(meta, 0)], 0
    while pending:
        value, depth = pending.pop()
        count += 1
        if depth > 64 or count > 500000:
            raise ValueError("Metadata complexity exceeded")
        if isinstance(value, dict):
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value)
    owner = CaptureIdentity(
        meta["tenant_id"],
        meta["owner_user_id"],
        meta["conversation_id"],
        meta.get("agent_id", meta.get("storage_agent_id")),
    )
    if type(meta.get("schema_version")) is not int:
        raise ValueError("Invalid schema version")
    TrajectoryFileStore._validate_manifest(meta, owner, prefix[0], prefix[2])
    if "/".join(prefix) != _prefix(meta):
        raise ValueError("Archive path differs from ownership")
    if any(
        type(meta.get(key)) is not int or meta[key] < 0
        for key in ("publication_no", "cleanup_version")
    ):
        raise ValueError("Invalid publication")
    seen, turns = set(), set()
    for run in meta["runs"]:
        if (
            run["trajectory_id"] in seen
            or type(run.get("turn_no")) is not int
            or run["turn_no"] < 1
            or run["turn_no"] in turns
        ):
            raise ValueError("Duplicate or invalid execution")
        seen.add(run["trajectory_id"])
        turns.add(run["turn_no"])
        publication = run.get("publication_no")
        if publication is not None and (
            type(publication) is not int
            or not 1 <= publication <= meta["publication_no"]
        ):
            raise ValueError("Invalid execution publication")
    return meta


def _availability(run):
    if run.get("cleanup_reason") or run["capture_state"] == "expired":
        return "expired"
    if run["capture_state"] == "corrupt":
        return "corrupt"
    if run.get("publication_no") is None:
        return "unarchived"
    if run["capture_state"] not in {"ready", "incomplete"}:
        raise ValueError("Invalid published execution")
    return "partial" if run["capture_state"] == "incomplete" else "available"


def _requests(reader, meta, run):
    for request in reader.requests():
        if not isinstance(request, dict) or not request.get("resourceSpans"):
            raise ValueError("Invalid OTLP request")
        for resource in request["resourceSpans"]:
            for scope in resource["scopeSpans"]:
                for span in scope["spans"]:
                    attrs = attributes(span.get("attributes", []))
                    for key, expected in (
                        ("tenant.id", meta["tenant_id"]),
                        ("nexent.owner_user_id", meta["owner_user_id"]),
                        ("conversation.id", meta["conversation_id"]),
                        ("session.id", meta["conversation_id"]),
                        ("nexent.trace_id", meta["conversation_id"]),
                        ("nexent.trajectory_id", run["trajectory_id"]),
                    ):
                        if attrs.get(key) != expected:
                            raise ValueError("OTLP ownership differs")
                    if not re.fullmatch(
                        r"[0-9a-f]{32}", span["traceId"]
                    ) or not re.fullmatch(r"[0-9a-f]{16}", span["spanId"]):
                        raise ValueError("Invalid OTLP identity")
        yield request


def _body(fd, value, availability, budget, response_size, limits):
    if value is None or not isinstance(value, Text):
        return {
            "availability": availability if value is None else "unsupported_encoding",
            "text": None,
            "complete": False,
            "content_id": None,
        }
    response_size[0] += value.byte_count
    _limit(response_size[0], limits.response_bytes)
    reader = JSONReader(fd, value.end, start=value.start, check=budget.check)
    text = "".join(reader.string_parts())
    return {
        "availability": "available",
        "type": "text",
        "text": text,
        "complete": True,
        "content_id": None,
        "byte_count": value.byte_count,
        "char_count": value.char_count,
    }


def import_archive(stream, *, limits=None):
    """Validate and parse entirely within this call; close every temporary file."""
    limits = limits or ExchangeLimits()
    budget = Budget(
        max_bytes=limits.unpacked_bytes,
        max_retained=limits.response_bytes,
        seconds=limits.seconds,
    )
    try:
        stream.seek(0, os.SEEK_END)
        _limit(stream.tell(), limits.compressed_bytes)
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            items = archive.infolist()
            _limit(len(items), limits.files)
            names, prefix, total = set(), None, 0
            for item in items:
                budget.check()
                parts = item.filename.split("/")
                mode = item.external_attr >> 16
                if (
                    len(parts) != 5
                    or any(part in {"", ".", ".."} for part in parts)
                    or "\\" in item.filename
                    or "\0" in item.orig_filename
                    or item.is_dir()
                    or item.filename in names
                    or item.flag_bits & 1
                    or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                    or item.compress_type
                    not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                ):
                    raise ValueError("Invalid ZIP entry")
                if prefix is not None and parts[:4] != prefix:
                    raise ValueError("Multiple conversations")
                prefix = parts[:4]
                names.add(item.filename)
                total += item.file_size
                _limit(total, limits.unpacked_bytes)
            if prefix is None:
                raise ValueError("Empty archive")
            base = "/".join(prefix)
            meta = _manifest(
                archive, archive.getinfo(f"{base}/meta.json"), prefix, limits, budget
            )
            expected = {f"{base}/meta.json"}
            pages, response_size = [], [0]
            for run in sorted(meta["runs"], key=lambda run: run["turn_no"]):
                budget.check()
                state = _availability(run)
                execution = {
                    key: run.get(key)
                    for key in (
                        "trajectory_id",
                        "turn_no",
                        "root_agent_id",
                        "root_agent_version_no",
                        "root_agent_version_name",
                        "business_status",
                        "cleanup_reason",
                    )
                } | {
                    "round_no": run["turn_no"],
                    "availability": state,
                    "matches_filters": True,
                }
                page = {"run": execution, "snapshot": None}
                if state in {"available", "partial"}:
                    name = f"{base}/{run['trajectory_id']}.otlp.jsonl"
                    expected.add(name)
                    with tempfile.TemporaryFile() as data:
                        size, digest = _read_entry(
                            archive,
                            archive.getinfo(name),
                            data,
                            budget,
                            limits.unpacked_bytes,
                        )
                        if (
                            size != run["confirmed_bytes"]
                            or digest != run["confirmed_sha256"]
                        ):
                            raise ValueError("Execution checksum differs")
                        nodes, root, coverage = build_nodes(
                            _requests(
                                JSONReader(data.fileno(), size, check=budget.check),
                                meta,
                                run,
                            ),
                            conversation_id=meta["conversation_id"],
                            complete=state == "available",
                            check=budget.check,
                        )
                        if not nodes:
                            raise ValueError("Empty published execution")
                        dtos = []
                        for node in nodes:
                            dto = {
                                key: value
                                for key, value in node.items()
                                if not key.startswith("_")
                            }
                            dto.update(
                                user=meta["owner_user_id"],
                                user_id=meta["owner_user_id"],
                            )
                            for slot in ("input", "output", "reasoning", "raw"):
                                dto[slot] = _body(
                                    data.fileno(),
                                    node["_bodies"].get(slot),
                                    node.get("_availability", {}).get(
                                        slot, "not_returned"
                                    ),
                                    budget,
                                    response_size,
                                    limits,
                                )
                            dtos.append(dto)
                        page["snapshot"] = {
                            "snapshot_id": "",
                            "conversation_id": meta["conversation_id"],
                            "trajectory_id": run["trajectory_id"],
                            "root_node_id": root,
                            "nodes": dtos,
                            "context_nodes": [],
                            "next_cursor": None,
                            "coverage": coverage,
                            "scope": {
                                "kind": "execution",
                                "complete": True,
                                "aggregates": "execution_subtree",
                            },
                        }
                pages.append(page)
            if expected != names or not any(page["snapshot"] for page in pages):
                raise ValueError("Unexpected files or no readable execution")
            result = {
                "row": _row(meta, pages),
                "pages": pages,
                "coverage": TrajectoryService.coverage(meta),
            }
            _limit(
                len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()),
                limits.response_bytes,
            )
            budget.check()
            return result
    except QueryError as error:
        if error.code == "query_budget_exceeded" and (
            budget.used_bytes > budget.max_bytes
            or budget.used_nodes > budget.max_nodes
            or budget.retained > budget.max_retained
        ):
            raise QueryError("archive_too_large", 413) from error
        raise
    except TrajectoryReadBudgetExceeded as error:
        raise QueryError("archive_too_large", 413) from error
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        UnicodeError,
        RecursionError,
        zipfile.BadZipFile,
        zlib.error,
        EOFError,
        NotImplementedError,
        RuntimeError,
        TrajectoryCorrupt,
        TrajectoryConflict,
    ) as error:
        raise QueryError("invalid_archive", 422) from error
    except OSError as error:
        raise storage_error(error) from error


def _row(meta, pages):
    runs = sorted(meta["runs"], key=lambda run: run["turn_no"])
    latest = runs[-1]
    roots = [
        next(
            (
                node
                for node in page["snapshot"]["nodes"]
                if node["id"] == page["snapshot"]["root_node_id"]
            ),
            None,
        )
        for page in pages
        if page["snapshot"]
    ]
    root = next((node for node in reversed(roots) if node), None)
    complete = len(roots) == len(pages) and all(
        node and (node.get("usage") or {}).get("complete") for node in roots
    )
    usage = {
        key: sum(node["usage"][key] for node in roots) if complete else None
        for key in ("input", "output", "total")
    } | {"complete": complete}
    return {
        "tenant_id": meta["tenant_id"],
        "tenant_name": meta["tenant_id"],
        "user_id": meta["owner_user_id"],
        "user_name": meta["owner_user_id"],
        "conversation_id": meta["conversation_id"],
        "conversation_title": None,
        "trajectory_id": latest["trajectory_id"],
        "root_agent_id": latest.get("root_agent_id"),
        "root_agent_name": latest.get("root_agent_name")
        or (root["name"] if root else None),
        "root_agent_version_no": latest.get("root_agent_version_no"),
        "root_agent_version_name": latest.get("root_agent_version_name"),
        "round_count": len(runs),
        "execution_count": len(runs),
        "models": sorted(
            {
                node["model"]
                for page in pages
                if page["snapshot"]
                for node in page["snapshot"]["nodes"]
                if node["model"]
            }
        ),
        "status": {
            "completed": "success",
            "failed": "error",
            "cancelled": "cancelled",
        }.get(latest["business_status"]),
        "business_status": latest["business_status"],
        "availability": "available",
        "started_at": runs[0].get("started_at"),
        "finished_at": latest.get("finished_at"),
        "duration_ms": sum(node["duration_ms"] for node in roots)
        if len(roots) == len(pages)
        and all(node and node["duration_ms"] is not None for node in roots)
        else None,
        "usage": usage,
        "coverage": TrajectoryService.coverage(meta),
    }
