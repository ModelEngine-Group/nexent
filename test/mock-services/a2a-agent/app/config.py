"""Environment-backed configuration for the standalone A2A mock service."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _as_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    advertised_base_url: str
    control_token: str
    jwt_secret: str
    jwt_issuer: str
    jwt_ttl_seconds: int
    scenario_catalog: str
    default_scenario: str
    observation_limit: int
    nacos_enabled: bool
    nacos_required: bool
    nacos_server_url: str
    nacos_namespace: str
    nacos_agent_name: str
    nacos_registration_type: str
    nacos_auth_enabled: bool
    nacos_username: str
    nacos_password: str
    nacos_login_path: str
    nacos_admin_init_path: str
    nacos_register_path: str
    nacos_retry_count: int
    nacos_retry_seconds: float

    @classmethod
    def from_env(cls) -> "Settings":
        port = int(os.getenv("A2A_MOCK_PORT", "8888"))
        return cls(
            host=os.getenv("A2A_MOCK_HOST", "0.0.0.0"),
            port=port,
            advertised_base_url=os.getenv(
                "A2A_ADVERTISED_BASE_URL", f"http://127.0.0.1:{port}"
            ).rstrip("/"),
            control_token=os.getenv("A2A_CONTROL_TOKEN", "local-test-control"),
            jwt_secret=os.getenv("A2A_JWT_SECRET", "local-a2a-mock-secret"),
            jwt_issuer=os.getenv("A2A_JWT_ISSUER", "nexent-a2a-mock"),
            jwt_ttl_seconds=int(os.getenv("A2A_JWT_TTL_SECONDS", "300")),
            scenario_catalog=os.getenv("A2A_SCENARIO_CATALOG", "scenarios/catalog.yaml"),
            default_scenario=os.getenv("A2A_DEFAULT_SCENARIO", "happy-jsonrpc"),
            observation_limit=int(os.getenv("A2A_OBSERVATION_LIMIT", "1000")),
            nacos_enabled=_as_bool("NACOS_ENABLED"),
            nacos_required=_as_bool("NACOS_REQUIRED"),
            nacos_server_url=os.getenv("NACOS_SERVER_URL", "http://nacos-a2a-test:8848").rstrip("/"),
            nacos_namespace=os.getenv("NACOS_NAMESPACE_ID", "public"),
            nacos_agent_name=os.getenv("NACOS_AGENT_NAME", "nexent-a2a-mock"),
            nacos_registration_type=os.getenv("NACOS_REGISTRATION_TYPE", "URL").upper(),
            nacos_auth_enabled=_as_bool("NACOS_AUTH_ENABLED"),
            nacos_username=os.getenv("NACOS_USERNAME", "nacos"),
            nacos_password=os.getenv("NACOS_PASSWORD", "nacos"),
            nacos_login_path=os.getenv("NACOS_LOGIN_PATH", "/nacos/v3/auth/user/login"),
            nacos_admin_init_path=os.getenv(
                "NACOS_ADMIN_INIT_PATH", "/nacos/v3/auth/user/admin"
            ),
            nacos_register_path=os.getenv("NACOS_REGISTER_PATH", "/nacos/v3/admin/ai/a2a"),
            nacos_retry_count=int(os.getenv("NACOS_RETRY_COUNT", "30")),
            nacos_retry_seconds=float(os.getenv("NACOS_RETRY_SECONDS", "2")),
        )
