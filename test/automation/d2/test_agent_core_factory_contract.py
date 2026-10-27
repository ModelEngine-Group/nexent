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
from management.db.models import AgentInfo


def test_AGENT_CORE_D2_001_config_route_and_version(monkeypatch):
    # Load the actual route without initializing unrelated external services.
    # The handler and Pydantic schema remain production code at the HTTP boundary.
    root = Path(__file__).resolve().parents[3]
    source = ast.parse((root / "backend/apps/agent_app.py").read_text(encoding="utf-8"))
    handler = next(node for node in source.body if isinstance(node, ast.AsyncFunctionDef)
                   and node.name == "update_agent_info_api")
    update = AsyncMock(return_value={"agent_id": 1, "agent_core": "jiuwen"})
    namespace = {"AgentInfoRequest": AgentInfoRequest, "Request": Request, "Header": Header,
                 "Optional": __import__("typing").Optional, "agent_config_router": APIRouter(prefix="/agent"),
                 "get_current_user_id": lambda authorization: ("fixture-user", "fixture-tenant"),
                 "AUDIT_DETAIL_LIST_LIMIT": 30, "update_agent_info_impl": update,
                 "record_security_event": lambda *args, **kwargs: None, "ForbiddenError": ForbiddenError,
                 "TenantResourceLimitError": TenantResourceLimitError, "HTTPException": HTTPException,
                 "HTTPStatus": HTTPStatus, "JSONResponse": JSONResponse, "logger": logging.getLogger(__name__)}
    exec(compile(ast.Module(body=[handler], type_ignores=[]), "agent_app.py", "exec"), namespace)
    app = FastAPI()
    app.include_router(namespace["agent_config_router"])
    with TestClient(app) as client:
        response = client.post("/agent/update", json={"agent_id": 1, "agent_core": "jiuwen"})
        assert response.status_code == 200 and response.json()["agent_core"] == "jiuwen"
        request = update.call_args.args[0]
        assert request.agent_core == "jiuwen" and "agent_core" in request.model_fields_set
        update.reset_mock()
        assert client.post("/agent/update", json={"agent_id": 1, "agent_core": "unknown"}).status_code == 422
        update.assert_not_called()
        assert client.post("/agent/update", json={"agent_id": 1}).status_code == 200
        assert "agent_core" not in update.call_args.args[0].model_fields_set

    exported = ExportAndImportAgentInfo(agent_id=1, name="fixture", description="Fixture", max_steps=5,
                                       provide_run_summary=False, enabled=True, tools=[], managed_agents=[],
                                       agent_core="jiuwen")
    assert ExportAndImportAgentInfo.model_validate(exported.model_dump()).agent_core == "jiuwen"
    assert ExportAndImportAgentInfo.model_validate(exported.model_dump(exclude={"agent_core"})).agent_core == "smolagents"
    column = AgentInfo.__table__.c.agent_core
    assert column.type.length == 30 and not column.nullable and column.comment
    assert column.default.arg == "smolagents"

    # Execute the actual publish function with isolated persistence collaborators.
    source = ast.parse((root / "backend/services/agent_version_service.py").read_text(encoding="utf-8"))
    publish = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "publish_version_impl")
    snapshot = {}
    import database

    skill_db = SimpleNamespace(query_skill_instances_by_agent_id=lambda **kwargs: [])
    monkeypatch.setattr(database, "skill_db", skill_db, raising=False)
    monkeypatch.setitem(sys.modules, "management.db.skill.repository", skill_db)
    namespace = {"Optional": __import__("typing").Optional, "SOURCE_TYPE_NORMAL": "NORMAL",
                 "_ensure_system_agent_mutation_allowed": lambda *args: None,
                 "query_agent_draft": lambda *args: ({"agent_id": 1, "agent_core": "jiuwen", "version_no": 0}, [], []),
                 "get_next_version_no": lambda *args: 2, "_remove_audit_fields_for_insert": lambda data: None,
                 "insert_agent_snapshot": lambda data: snapshot.update(data),
                 "insert_version": lambda data: 1, "update_agent_current_version": lambda *args: None,
                 "STATUS_RELEASED": "RELEASED",
                 "logger": logging.getLogger(__name__)}
    exec(compile(ast.Module(body=[publish], type_ignores=[]), "agent_version_service.py", "exec"), namespace)
    namespace["publish_version_impl"](1, "fixture-tenant", "fixture-user")
    assert snapshot["agent_core"] == "jiuwen" and snapshot["version_no"] == 2
