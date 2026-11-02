# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Gateway's sole environment reader, independent of backend business settings."""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GatewaySettings:
    host: str = "0.0.0.0"
    port: int = 5013
    management_url: str = "http://localhost:5010"
    runtime_url: str = "http://localhost:5014"
    northbound_url: str = "http://localhost:5010"
    auth_enabled: bool = True
    jwt_secret: str = field(default="", repr=False)
    jwt_issuer: str = "nexent"
    signing_secret: str = field(default="", repr=False)
    deployment_version: str = "full"
    default_user_id: str = "user_id"
    default_tenant_id: str = "tenant_id"

    def __post_init__(self):
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("GATEWAY_PORT must be an integer between 1 and 65535")
        if not self.host.strip() or not self.jwt_issuer.strip():
            raise ValueError("Gateway host and JWT issuer must be nonempty")
        if type(self.auth_enabled) is not bool:
            raise ValueError("GATEWAY_AUTH_ENABLED must be true or false")
        if self.deployment_version not in {"full", "speed"}:
            raise ValueError("DEPLOYMENT_VERSION must be full or speed")

    @property
    def is_speed_mode(self):
        return self.deployment_version == "speed"

    def signing_key(self):
        from gateway.security.identity import derive_signing_key

        return derive_signing_key(self.jwt_secret, self.signing_secret)


def load_settings(environ=None):
    """Read injected environment only; local callers may provide a mapping."""
    values = os.environ if environ is None else environ
    flag = values.get("GATEWAY_AUTH_ENABLED", "true").lower()
    if flag not in {"true", "false"}:
        raise ValueError("GATEWAY_AUTH_ENABLED must be true or false")
    try:
        port = int(values.get("GATEWAY_PORT", "5013"))
    except (TypeError, ValueError) as exc:
        raise ValueError("GATEWAY_PORT must be an integer between 1 and 65535") from exc
    management = values.get("GATEWAY_MANAGEMENT_URL", "http://localhost:5010").rstrip("/")
    return GatewaySettings(
        host=values.get("GATEWAY_HOST", "0.0.0.0"), port=port,
        management_url=management,
        runtime_url=values.get("GATEWAY_RUNTIME_URL", "http://localhost:5014").rstrip("/"),
        northbound_url=values.get("GATEWAY_NORTHBOUND_URL", management).rstrip("/"),
        auth_enabled=flag == "true", jwt_secret=values.get("JWT_SECRET", ""),
        jwt_issuer=values.get("JWT_ISSUER", "nexent"),
        signing_secret=values.get("GATEWAY_SIGNING_SECRET", ""),
        deployment_version=values.get("DEPLOYMENT_VERSION", "full"),
    )
