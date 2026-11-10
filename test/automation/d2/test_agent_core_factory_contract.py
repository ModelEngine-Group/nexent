# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AGENT-CORE-D2-001: Actual Agent configuration route and version contracts."""

import ast
import logging
import sys
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from contracts.errors.exceptions import ForbiddenError, TenantResourceLimitError
from contracts.agent import AgentInfoRequest, ExportAndImportAgentInfo
from contracts.authentication import AuthenticatedIdentity
from management.db.models import AgentInfo


def test_AGENT_CORE_D2_001_config_route_and_version(monkeypatch):
    # Load the actual route without initializing unrelated external services.
    # The handler and Pydantic schema remain production code at the HTTP boundary.
    root = Path(__file__).resolve().parents[3]
    source = ast.parse((root / "backend/management/api/agent/agent.py").read_text(encoding="utf-8"))
    handler = next(node for node in source.body if isinstance(node, ast.AsyncFunctionDef)
                   and node.name == "update_agent_info_api")
    update = AsyncMock(return_value={"agent_id": 1})
    namespace = {"AgentInfoRequest": AgentInfoRequest, "Request": Request, "Header": Header,
                 "Optional": __import__("typing").Optional, "agent_config_router": APIRouter(prefix="/agent"),
                 "get_current_user_id": lambda authorization: ("fixture-user", "fixture-tenant"),
                 "AUDIT_DETAIL_LIST_LIMIT": 30, "update_agent_info_impl": update,
                 "AuthenticatedIdentity": AuthenticatedIdentity,
                 "record_security_event": lambda *args, **kwargs: None, "ForbiddenError": ForbiddenError,
                 "TenantResourceLimitError": TenantResourceLimitError, "HTTPException": HTTPException,
                 "HTTPStatus": HTTPStatus, "JSONResponse": JSONResponse, "logger": logging.getLogger(__name__)}
    exec(compile(ast.Module(body=[handler], type_ignores=[]), "agent_app.py", "exec"), namespace)
    app = FastAPI()
    app.include_router(namespace["agent_config_router"])
    with TestClient(app) as client:
        # Retired per-Agent Core input cannot override deployment policy or persist.
        for legacy_core in ("jiuwen", "smolagents", "unknown"):
            response = client.post("/agent/update", json={"agent_id": 1, "agent_core": legacy_core})
            assert response.status_code == 200 and response.json() == {"agent_id": 1}
            request = update.call_args.args[0]
            assert "agent_core" not in request.model_dump()
            assert "agent_core" not in request.model_fields_set
            assert update.call_args.args[1] == AuthenticatedIdentity("fixture-user", "fixture-tenant")
        assert client.post("/agent/update", json={"agent_id": 1}).status_code == 200
        assert "agent_core" not in update.call_args.args[0].model_dump()

    exported = ExportAndImportAgentInfo(agent_id=1, name="fixture", description="Fixture", max_steps=5,
                                       provide_run_summary=False, enabled=True, tools=[], managed_agents=[],
                                       agent_core="jiuwen")
    assert "agent_core" not in exported.model_dump()
    assert "agent_core" not in ExportAndImportAgentInfo.model_validate(exported.model_dump()).model_dump()
    assert "agent_core" not in AgentInfo.__table__.c

    # Execute the actual publish function with isolated persistence collaborators.
    source = ast.parse((root / "backend/management/services/agent/versions.py").read_text(encoding="utf-8"))
    publish = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "publish_version_impl")
    snapshot = {}
    from management.db import skill

    skill_db = SimpleNamespace(query_skill_instances_by_agent_id=lambda **kwargs: [])
    monkeypatch.setattr(skill, "repository", skill_db, raising=False)
    monkeypatch.setitem(sys.modules, "management.db.skill.repository", skill_db)
    namespace = {"Optional": __import__("typing").Optional, "SOURCE_TYPE_NORMAL": "NORMAL",
                 "_ensure_system_agent_mutation_allowed": lambda *args: None,
                 "query_agent_draft": lambda *args: ({"agent_id": 1, "name": "fixture", "version_no": 0}, [], []),
                 "get_next_version_no": lambda *args: 2, "_remove_audit_fields_for_insert": lambda data: None,
                 "insert_agent_snapshot": lambda data: snapshot.update(data),
                 "insert_version": lambda data: 1, "update_agent_current_version": lambda *args: None,
                 "STATUS_RELEASED": "RELEASED",
                 "logger": logging.getLogger(__name__)}
    exec(compile(ast.Module(body=[publish], type_ignores=[]), "agent_version_service.py", "exec"), namespace)
    namespace["publish_version_impl"](1, "fixture-tenant", "fixture-user")
    assert "agent_core" not in snapshot and snapshot["version_no"] == 2
