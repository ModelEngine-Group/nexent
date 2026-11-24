# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI


@pytest.mark.case_id("EVOLUTION-FILE-STATE-D3-001")
@pytest.mark.stage("D3")
@pytest.mark.asyncio
async def test_file_receipts_over_agentos(monkeypatch, tmp_path):
    from contracts.agentos import EvaluationAgentResult, PreparedEvaluationRun, RunInput
    from contracts.constants import environment
    from contracts.replay_files import FileStateCheck
    from infrastructure.agentos_client import AgentOSClient
    from management.services.evaluation.replay_dialogue import judge_file_state, run_turns
    from nexent.core.agents.contracts.config import ToolConfig
    from nexent.core.agents.resources.tools import ToolResources
    from nexent.core.agents.resources.workspace import WorkspaceResources
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
    roots, snapshots, transfers = [], [], []

    def download(key, path, bucket):
        transfers.append((key, bucket))
        Path(path).write_text("draft", encoding="utf-8")
        return True, ""

    storage = SimpleNamespace(default_bucket="pilot", get_file_size=lambda *_: 5, download_file=download)
    class TrialResources(ToolResources, WorkspaceResources):
        pass

    async def materialize(payload, actor, _prepare):
        assert (actor.tenant_id, actor.user_id) == ("tenant","editor")
        snapshots.append(dict(payload.replay_files))
        workspace = tmp_path / payload.replay_trial_id
        configs = [ToolConfig(class_name="CreateFileTool", name="create_file", source="local", params={}),
                   ToolConfig(class_name="ReadFileTool", name="read_file", source="local", params={}),
                   ToolConfig(class_name="DownloadFromS3Tool", name="download_from_s3", source="builtin", params={},
                              metadata={"minio_client": storage, "user_id": "editor", "tenant_id": "tenant"})]
        observer = SimpleNamespace(lang="en", add_message=lambda *args: None)
        return SimpleNamespace(observer=observer, thread_future=None, attempt_outcome="completed",
            query=payload.input.query, history=payload.input.history, workspace=str(workspace),
            attachments=[{"name": item.name, "url": item.url} for item in payload.input.attachment_refs],
            agent_config=SimpleNamespace(tools=configs,worker_agents=[],external_a2a_agents=[]))

    async def deliver(info, *_):
        fixture = info.observer.replay_file_directory
        roots.append(fixture.root)
        provider = TrialResources()
        provider.observer = info.observer
        provider.workspace_path = info.workspace
        provider.user_id, provider.tenant_id = "editor", "tenant"
        provider.minio_files = info.attachments
        provider._push_file_workspace_to_sandbox = lambda: None
        provider._initialize_sandbox_workspaces = lambda: None
        tools = {config.name: provider.create_tool(config) for config in info.agent_config.tools}
        provider.agent = SimpleNamespace(tools=tools)
        query = provider._prepare_file_workspace(info.query)
        assert ("- inputs/000_approved.txt" in query) == bool(info.attachments)
        assert "s3://pilot/" not in query
        writer = tools["create_file"]
        if info.query == "draft":
            content = json.loads(tools["read_file"].forward("inputs/000_approved.txt"))["content"]
            writer.forward("actions.txt", content)
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
        material = {"name": "approved.txt", "url": f"s3://pilot/attachments/editor/approved-{index}"}
        observed, turns, error = await run_turns(client,spec,task,
            AsyncMock(side_effect=[RunInput(query="draft", attachment_refs=[material]), RunInput(query=last)]),
            {"trial_id":index,"receipt_id":str(index)*32},"editor","tenant")
        assert not error and len(turns) == 2
        verdict = judge_file_state(rule,[o.replay_receipt for o in observed])
        assert verdict["status"] == status and observed[-1].answer == "done"
        if last == "touch protected":
            assert verdict["protected_writes"] == ["frozen.txt"]
    assert snapshots == [start,{**start,"actions.txt":"draft"}] * 3
    assert transfers == [(f"attachments/editor/approved-{index}", "pilot") for index in range(1, 4)]
    assert len(set(roots)) == 6 and all(not root.exists() for root in roots)
