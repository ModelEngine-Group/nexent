"""Tests for _build_security_headers and _find_text_in_artifacts."""
import pytest


def test_build_security_headers_apikey():
    """X-HW-ID + X-HW-APPKEY (two apiKey-header schemes)."""
    from backend.agents.create_agent_info import _build_security_headers
    agent = {
        "security_schemes": {
            "hwIdAuth": {"apiKeySecurityScheme": {"name": "X-HW-ID", "location": "header"}},
            "hwAppKeyAuth": {"apiKeySecurityScheme": {"name": "X-HW-APPKEY", "location": "header"}},
        },
        "security_requirements": [{"schemes": {"hwIdAuth": {}, "hwAppKeyAuth": {}}}],
        "security_credentials": {"hwIdAuth": "id-val", "hwAppKeyAuth": "key-val"},
    }
    headers = _build_security_headers(agent)
    assert headers == {"X-HW-ID": "id-val", "X-HW-APPKEY": "key-val"}


def test_build_security_headers_http_bearer():
    """HTTP Bearer JWT scheme."""
    from backend.agents.create_agent_info import _build_security_headers
    agent = {
        "security_schemes": {"jwt": {"httpAuthSecurityScheme": {"scheme": "bearer", "bearerFormat": "JWT"}}},
        "security_requirements": [{"schemes": {"jwt": {}}}],
        "security_credentials": {"jwt": "token123"},
    }
    headers = _build_security_headers(agent)
    assert headers == {"Authorization": "Bearer token123"}


def test_build_security_headers_no_credentials():
    """No credentials configured -> empty headers."""
    from backend.agents.create_agent_info import _build_security_headers
    agent = {
        "security_schemes": {"k": {"apiKeySecurityScheme": {"name": "X-Key", "location": "header"}}},
        "security_requirements": [{"schemes": {"k": {}}}],
        "security_credentials": {},
    }
    assert _build_security_headers(agent) == {}
