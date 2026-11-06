# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Gateway's sole environment reader, independent of backend business settings."""

import math
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
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "nexent"
    db_user: str = "root"
    db_password: str = field(default="", repr=False)
    db_pool_size: int = 8
    db_timeout: float = 5.0

    def __post_init__(self):
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("GATEWAY_PORT must be an integer between 1 and 65535")
        if not self.host.strip() or not self.jwt_issuer.strip():
            raise ValueError("Gateway host and JWT issuer must be nonempty")
        if type(self.auth_enabled) is not bool:
            raise ValueError("GATEWAY_AUTH_ENABLED must be true or false")
        if self.deployment_version not in {"full", "speed"}:
            raise ValueError("DEPLOYMENT_VERSION must be full or speed")
        if type(self.db_port) is not int or not 1 <= self.db_port <= 65535:
            raise ValueError("POSTGRES_PORT must be between 1 and 65535")
        if type(self.db_pool_size) is not int or not 1 <= self.db_pool_size <= 64:
            raise ValueError("Gateway database pool size must be between 1 and 64")
        if type(self.db_timeout) not in (int, float) or not math.isfinite(self.db_timeout) or not 0 < self.db_timeout <= 60:
            raise ValueError("Gateway database timeout must be finite and between 0 and 60 seconds")

    def database_options(self):
        if not all(isinstance(value, str) and value.strip() for value in
                   (self.db_host, self.db_name, self.db_user, self.db_password)):
            raise ValueError("Gateway database host, name, user and password are required")
        return dict(host=self.db_host, port=self.db_port, database=self.db_name, user=self.db_user,
                    password=self.db_password, max_size=self.db_pool_size, timeout=self.db_timeout)

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
        db_host=(values.get("POSTGRES_HOST") or "localhost"),
        db_port=int((values.get("POSTGRES_PORT") or "5432")),
        db_name=(values.get("POSTGRES_DB") or "nexent"),
        db_user=(values.get("POSTGRES_USER") or "root"),
        db_password=values.get("NEXENT_POSTGRES_PASSWORD", ""),
    )
