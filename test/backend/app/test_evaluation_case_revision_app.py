"""Validate the case revision HTTP boundary without importing agent runtimes."""

import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def revision_client(monkeypatch):
    service = types.ModuleType("services.agent_evaluation_service")
    for name in (
        "create_agent_evaluation_run_impl", "delete_agent_evaluation_run_impl",
        "generate_agent_evaluation_report_impl", "get_agent_evaluation_run_impl",
        "list_agent_evaluation_cases_impl", "list_agent_evaluations_by_agent_impl",
        "revise_agent_evaluation_case_impl",
    ):
        setattr(service, name, MagicMock())
    auth = types.ModuleType("utils.auth_utils")
    auth.get_current_user_id = MagicMock(return_value=("user", "tenant"))
    monkeypatch.setitem(sys.modules, "services.agent_evaluation_service", service)
    monkeypatch.setitem(sys.modules, "utils.auth_utils", auth)
    source = Path(__file__).resolve().parents[3] / "backend/apps/agent_evaluation_app.py"
    spec = importlib.util.spec_from_file_location("evaluation_revision_api_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = FastAPI()
    app.include_router(module.router)
    return TestClient(app), service.revise_agent_evaluation_case_impl


def test_revision_uses_authenticated_tenant(revision_client):
    client, revise = revision_client
    response = client.patch("/agent-evaluations/1/cases/2", json={"pass_status": "pass", "tenant_id": "other"})
    assert response.status_code == 200
    revise.assert_called_once_with(
        agent_evaluation_id=1, agent_evaluation_case_id=2,
        tenant_id="tenant", user_id="user", pass_status="pass",
    )


@pytest.mark.parametrize("body", [{}, {"pass_status": "PASS"}, {"pass_status": "invalid"}])
def test_revision_validates_status(revision_client, body):
    client, revise = revision_client
    assert client.patch("/agent-evaluations/1/cases/2", json=body).status_code == 422
    revise.assert_not_called()


def test_revision_rejects_unavailable_case(revision_client):
    client, revise = revision_client
    revise.side_effect = ValueError("Evaluation case not found")
    assert client.patch("/agent-evaluations/1/cases/2", json={"pass_status": "fail"}).status_code == 400
