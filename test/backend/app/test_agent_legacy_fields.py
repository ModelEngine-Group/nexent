"""Removed run controls must never become an ordinary query silently."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from consts.model import AgentRequest


@pytest.mark.parametrize("field,value", [
    ("enable_hitl", True), ("enable_hitl", False), ("hitl_run_id", None),
    ("hitl_run_id", "old-run"), ("hitl_after_event", 0),
])
def test_removed_fields_are_rejected_before_execution(field, value):
    calls = []
    app = FastAPI()

    @app.post("/agent/run")
    def run(request: AgentRequest):
        calls.append(request)
        return {"accepted": True}

    response = TestClient(app).post("/agent/run", json={"query": "Continue", field: value})
    assert response.status_code == 422
    assert not calls


def test_ordinary_query_contract_is_preserved():
    request = AgentRequest(query="Only East China", conversation_id=123, history=[])
    assert request.query == "Only East China"
    assert request.conversation_id == 123
    assert not {"enable_hitl", "hitl_run_id", "hitl_after_event"}.intersection(request.model_dump())
