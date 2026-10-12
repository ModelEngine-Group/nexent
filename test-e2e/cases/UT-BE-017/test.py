"""D1 backend policy tests for repository, sharing, runtime and memory."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


STAGE = pytest.mark.stage("D1")










@STAGE
@pytest.mark.case_id("UT-BE-017")
def test_a2a_security_requirement_maps_credentials_to_wire_parts() -> None:
    from services.a2a_client_service import A2AClientService, AgentCallError

    service = object.__new__(A2AClientService)
    agent = {
        "security_schemes": {
            "jwt": {"httpAuthSecurityScheme": {"scheme": "bearer", "bearerFormat": "JWT"}},
            "tenant": {"apiKeySecurityScheme": {"location": "header", "name": "X-Tenant"}},
        },
        "security_requirements": [{"schemes": {"jwt": [], "tenant": []}}],
        "security_credentials": {"jwt": "signed-token", "tenant": "t1"},
        "selected_security_requirement_index": 0,
    }
    headers, params, cookies = service._build_security_request_parts(agent)
    assert headers == {"Authorization": "Bearer signed-token", "X-Tenant": "t1"}
    assert params == {} and cookies == {}
    agent["security_credentials"] = {"jwt": "signed-token"}
    with pytest.raises(AgentCallError, match="do not satisfy"):
        service._build_security_request_parts(agent)
















