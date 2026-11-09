# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Casdoor environment settings, centralized per the project configuration contract."""

import os
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv(override=False)

CASDOOR_ENDPOINT = os.getenv("CASDOOR_ENDPOINT", "").strip().rstrip("/")
CASDOOR_BACKEND_ENDPOINT = os.getenv("CASDOOR_BACKEND_ENDPOINT", "").strip().rstrip("/")
CASDOOR_CLIENT_ID = os.getenv("CASDOOR_CLIENT_ID", "").strip()
CASDOOR_CLIENT_SECRET = os.getenv("CASDOOR_CLIENT_SECRET", "")
CASDOOR_ROLE_SYNC_ORGANIZATION = os.getenv("CASDOOR_ROLE_SYNC_ORGANIZATION", "").strip()
CASDOOR_ROLE_MAP_JSON = os.getenv("CASDOOR_ROLE_MAP_JSON", "").strip()
CASDOOR_PERMISSION_MODEL = os.getenv("CASDOOR_PERMISSION_MODEL", "").strip()


def is_casdoor_role_sync_configured() -> bool:
    return bool(CASDOOR_ROLE_SYNC_ORGANIZATION and CASDOOR_ROLE_MAP_JSON and is_casdoor_enabled())


def _valid_http_endpoint(value: str) -> bool:
    """Accept HTTP(S) origins or base paths without URL credentials or query data."""
    try:
        parsed = urlsplit(value)
        return bool(
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
            and (parsed.port is None or 0 < parsed.port <= 65535)
            and not any(character.isspace() for character in value)
        )
    except ValueError:
        return False


def is_casdoor_enabled() -> bool:
    """Hide incomplete or malformed provider configuration from login entry points."""
    return bool(
        CASDOOR_CLIENT_ID
        and CASDOOR_CLIENT_SECRET
        and _valid_http_endpoint(CASDOOR_ENDPOINT)
        and _valid_http_endpoint(CASDOOR_BACKEND_ENDPOINT or CASDOOR_ENDPOINT)
    )
