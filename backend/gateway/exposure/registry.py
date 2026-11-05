# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Immutable public exposure snapshot; downstream declarations never open routes."""

from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

from starlette.convertors import CONVERTOR_TYPES
from starlette.routing import compile_path

from gateway.security.policy import is_public_request


def valid_path(path, raw_path=None):
    if not isinstance(path, str) or not path.startswith("/"):
        return False
    if any(c in path for c in ("\\", "\x00", "?", "#")) or "//" in path:
        return False
    if any(part.lower() in {".", "..", "internal"} for part in path.split("/")):
        return False
    raw = raw_path.lower() if raw_path is not None else path.encode("utf-8").lower()
    return not any(value in raw for value in (b"%2f", b"%5c", b"%25", b"%00"))


@dataclass(frozen=True)
class Exposure:
    route_id: str
    method: str
    path: str
    transport: str
    target: str
    credential_kinds: tuple[str, ...]
    pattern: object = field(repr=False, compare=False)


class ExposureRegistry:
    def __init__(self, document):
        if (not isinstance(document, dict) or type(document.get("version")) is not int or document.get("version") != 1
                or not isinstance(document.get("revision"), str)
                or not document["revision"].strip()
                or not isinstance(document.get("routes"), list) or not document["routes"]):
            raise ValueError("Invalid Gateway exposure document")
        routes, seen, ids = [], set(), set()
        for row in document["routes"]:
            if not isinstance(row, dict):
                raise ValueError("Invalid Gateway exposure entry")
            required = {"route_id", "method", "path", "transport", "target", "credential_kinds"}
            if not required <= row.keys() or row.keys() - required - {"source"}:
                raise ValueError("Invalid Gateway exposure fields")
            if any(not isinstance(row[key], str) for key in required - {"credential_kinds"}):
                raise ValueError("Invalid Gateway exposure field type")
            method, path, transport = row["method"], row["path"], row["transport"]
            if (method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}
                    or transport not in {"http", "websocket"}
                    or transport == "websocket" and method != "GET"
                    or row["target"] not in {"management", "runtime", "northbound"}
                    or not valid_path(path) or "*" in path):
                raise ValueError("Invalid Gateway exposure route")
            if not isinstance(row["route_id"], str) or not row["route_id"] or row["route_id"] in ids:
                raise ValueError("Duplicate or invalid Gateway route ID")
            kinds = row["credential_kinds"]
            if (not isinstance(kinds, list) or not kinds or any(not isinstance(k, str) or k not in {"anonymous", "session", "api_key"} for k in kinds)
                    or len(set(kinds)) != len(kinds)):
                raise ValueError("Invalid Gateway credential policy")
            expected = "api_key" if path.startswith(("/nb/", "/api/nb/")) else "session"
            if "anonymous" in kinds and not is_public_request(method, path):
                raise ValueError("Anonymous exposure requires an explicit public-entry policy")
            if any(kind not in {"anonymous", expected} for kind in kinds) and not is_public_request(method, path):
                raise ValueError("Exposure credential policy conflicts with the service identity protocol")
            # Reject equivalent templates even if parameter names differ.
            shape = re.sub(r"\{[^}:]+", "{parameter", path.rstrip("/"))
            key = method, shape, transport
            if key in seen:
                raise ValueError("Ambiguous Gateway exposure route")
            pattern, _, converters = compile_path(path.rstrip("/") or "/")
            if any(converter not in CONVERTOR_TYPES.values() for converter in converters.values()):
                raise ValueError("Unsupported path converter")
            if ":path}" in path and len(path.split("{", 1)[0].strip("/").split("/")) < 2:
                raise ValueError("Unbounded Gateway exposure template")
            seen.add(key)
            ids.add(row["route_id"])
            routes.append(Exposure(row["route_id"], method, path, transport, row["target"], tuple(kinds), pattern))
        # Literal routes take precedence over parameter routes.
        self.routes = tuple(sorted(routes, key=lambda r: (r.path.count("{"), ":path}" in r.path,
                                                         -r.path.count(":int}"), -len(r.path))))
        self.revision = document["revision"]
        self.digest = hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def match(self, method, path, *, transport="http", raw_path=None):
        if not valid_path(path, raw_path):
            return None
        path = path.rstrip("/") or "/"
        return next((r for r in self.routes if r.method == method and r.transport == transport
                     and r.pattern.fullmatch(path)), None)


@lru_cache(maxsize=1)
def default_registry():
    return ExposureRegistry(json.loads(Path(__file__).with_name("registry.json").read_text(encoding="utf-8")))
