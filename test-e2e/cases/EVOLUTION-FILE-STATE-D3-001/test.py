# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI


@pytest.mark.case_id("EVOLUTION-FILE-STATE-D3-001")
@pytest.mark.stage("D3")
@pytest.mark.asyncio
async def test_file_receipts_over_agentos(monkeypatch):
    from contracts.agentos import EvaluationAgentResult, PreparedEvaluationRun, RunInput
    from contracts.constants import environment
    from contracts.replay_files import FileStateCheck
    from infrastructure.agentos_client import AgentOSClient
    from management.services.evaluation.replay_dialogue import judge_file_state, run_turns
    from nexent.core.agents.contracts.config import ToolConfig
    from nexent.core.agents.resources.tools import ToolResources
    from runtime.agentos import prepared_evaluation as runtime
    from runtime.agentos.evaluation import create_evaluation_router
    from runtime.agentos.middleware import AgentOSMiddleware

    monkeypatch.setattr(environment, "JWT_SECRET", "ephemeral-file-state-test-key")
    monkeypatch.setattr(environment, "EVOLUTION_REPLAY_RUNTIME", True)
    app = FastAPI(root_path="/api")
    app.add_middleware(AgentOSMiddleware)
    app.include_router(create_evaluation_router())
    client = AgentOSClient("http://offline", lambda **kw: httpx.AsyncClient(transport=httpx.ASGITransport(app), **kw))
    spec = PreparedEvaluationRun.model_validate({
        "mode":"nexent", "resource":{"agent_id":7,"version_no":1,"name":"files","description":"fixture",
            "model_alias":"local","prompt_templates":{"system_prompt":"Prepare files"}},
        "models":{"llm":{"model_id":1,"alias":"local","revision":"1"}}, "input":{"query":""}, "conversation_id":0})
    roots, snapshots = [], []
    async def materialize(payload, actor, _prepare):
        assert (actor.tenant_id, actor.user_id) == ("tenant","editor")
        snapshots.append(dict(payload.replay_files))
        config = ToolConfig(class_name="CreateFileTool", name="create_file", source="local", params={})
        observer = SimpleNamespace(lang="en", add_message=lambda *args: None)
        return SimpleNamespace(observer=observer, thread_future=None, attempt_outcome="completed",
            query=payload.input.query, history=payload.input.history,
            agent_config=SimpleNamespace(tools=[config],worker_agents=[],external_a2a_agents=[]))

    async def deliver(info, *_):
        fixture = info.observer.replay_file_directory
        roots.append(fixture.root)
        provider = ToolResources()
        provider.observer = info.observer
        writer = provider.create_tool(info.agent_config.tools[0])
        if info.query == "draft":
            writer.forward("actions.txt","draft")
        elif info.query == "finalize":
            assert info.history[-1].content == "done"
            writer.forward("actions.txt","final")
        elif info.query == "touch protected":
            writer.forward("frozen.txt","keep")
        return EvaluationAgentResult(answer="done",events=[{"type":"final_answer","content":"done"}])

    monkeypatch.setattr(runtime, "load_prepared_run", materialize)
    monkeypatch.setattr(runtime, "collect_observer_output", deliver)
    monkeypatch.setattr(runtime.agent_run_manager, "register_agent_run", lambda *args: None)
    monkeypatch.setattr(runtime, "release_prepared_run", lambda *args: None)
    start = {"frozen.txt":"keep"}
    rule = FileStateCheck(initial=start,expected={**start,"actions.txt":"final"},protected=["frozen.txt"]).model_dump()
    for index, (last, status) in enumerate((("report only","fail"),("finalize","pass"),("touch protected","fail")), 1):
        task = {"file_state":rule,"followups":[{"query":last}]}
        observed, turns, error = await run_turns(client,spec,task,
            AsyncMock(side_effect=[RunInput(query="draft"),RunInput(query=last)]),
            {"trial_id":index,"receipt_id":str(index)*32},"editor","tenant")
        assert not error and len(turns) == 2
        verdict = judge_file_state(rule,[o.replay_receipt for o in observed])
        assert verdict["status"] == status and observed[-1].answer == "done"
        if last == "touch protected":
            assert verdict["protected_writes"] == ["frozen.txt"]
    assert snapshots == [start,{**start,"actions.txt":"draft"}] * 3
    assert len(set(roots)) == 6 and all(not root.exists() for root in roots)
