# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Resolve versioned MCP services from the operator-managed deployment manifest."""

import json
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, field_validator

from contracts.agentos import MCPImplementation
from contracts.constants import environment
from contracts.evolution_sources import task_digest


class Deployment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    tenant_id: str
    server_id: int
    image: str
    production: str
    development: str
    confirmation: str

    @field_validator("production", "development", "confirmation")
    @classmethod
    def endpoint(cls, value):
        url = urlsplit(value)
        if (url.scheme not in {"http", "https"} or not url.hostname or url.username is not None
                or url.password is not None or url.fragment or url.query or not url.path
                or any(char.isspace() for char in value)):
            raise ValueError("Supply an explicit MCP endpoint without credentials or query parameters")
        # Accessing port also rejects invalid port values.
        if url.port == 0:
            raise ValueError("Supply a reachable port")
        return value

    def pin(self):
        return MCPImplementation(image=self.image, deployment_digest=task_digest(self.model_dump()))


@lru_cache(maxsize=1)
def deployment_manifest(raw):
    items = json.loads(raw)
    if not isinstance(items, list):
        raise ValueError("MCP deployment manifest must be a list")
    deployments = {}
    addresses = set()
    for item in items:
        record = Deployment.model_validate(item)
        record.pin()
        key = record.tenant_id, record.server_id, record.image
        if not record.tenant_id.strip() or record.server_id < 1 or key in deployments:
            raise ValueError("Duplicate or invalid MCP deployment identity")
        endpoints = {endpoint_identity(getattr(record, name)) for name in ("production", "development", "confirmation")}
        if len(endpoints) != 3 or addresses & endpoints:
            raise ValueError("MCP builds must use separate production, development and confirmation services")
        addresses.update(endpoints)
        deployments[key] = record
    return deployments


def endpoint_identity(endpoint):
    url = urlsplit(endpoint)
    hostname = (url.hostname or "").lower().rstrip(".")
    if hostname in {"localhost", "::1"}:
        hostname = "127.0.0.1"
    return hostname, url.port or (443 if url.scheme == "https" else 80)


def managed_deployment(tenant, server, image):
    result = deployment_manifest(environment.EVOLUTION_MCP_DEPLOYMENTS).get((tenant, server, image))
    if result is None:
        raise ValueError("No operator-managed deployment for the reviewed MCP image")
    return result


def implementation_host(tenant, server, pin, *, replay=False):
    deployment = managed_deployment(tenant, server, pin.image)
    if deployment.pin() != pin:
        raise ValueError("The configured MCP deployment differs from the pinned version")
    if replay:
        url = deployment.confirmation if environment.EVOLUTION_CONFIRMATION_BUCKET else deployment.development
    else:
        url = deployment.production
    return {"url": url, "transport": "sse" if url.endswith("/sse") else "streamable-http"}
