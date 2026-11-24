# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from contracts.agentos import EvaluationAgentResult, ReplayReceipt, RunInput
from contracts.errors.exceptions import RuntimeUpstreamError
from contracts.replay_files import FileStateCheck
from contracts.evolution_sources import example_source_keys
from management.services.evaluation.replay_dialogue import judge_file_state, run_turns
from nexent.core.agents.resources.replay_files import files_digest


def test_file_material_keeps_its_source_when_question_and_filename_change():
    def sources(query, files):
        return example_source_keys({"query":query, "attachments":[], "file_state":{"initial":files}})
    assert sources("summarize", {"a":"meeting 14","b":"next task"}) & sources("assign", {"z":"next task","y":"meeting 14"})
    assert not sources("summarize", {"a":"meeting 14"}) & sources("assign", {"a":"meeting 15"})
    assert not sources("first", {"a":""}) & sources("second", {"b":""})


@pytest.mark.parametrize("enabled,attempt", [(True,None),(False,"a"*32)])
def test_writable_fixture_requires_a_synthetic_attempt_on_the_replay_runtime(monkeypatch, enabled, attempt):
    from contracts.constants import environment
    from runtime.agentos.prepared_evaluation import prepare_evaluation_run

    monkeypatch.setattr(environment, "EVOLUTION_REPLAY_RUNTIME", enabled)
    payload = SimpleNamespace(new_skill_trial=None, scoped_skill_trials=[], omit_root_skill_candidate_id=None, observe_root_skill_choices=False,
                              watch_mcp_replies=None, watch_skill_process=None, watch_tool_arguments=None, tool_set_check=None, replay_files={}, replay_trial_id=attempt)
    with pytest.raises(HTTPException) as caught:
        prepare_evaluation_run(payload,None)
    assert caught.value.detail["code"] == "AGENTOS_FILE_STATE_REQUIRES_REPLAY"


@pytest.mark.asyncio
async def test_unsupported_business_tool_fixture_is_an_invalid_trial_not_a_business_failure():
    spec = Mock()
    client = Mock(run_prepared_evaluation=AsyncMock(side_effect=RuntimeUpstreamError(
        422, b'{"detail":{"code":"AGENTOS_FILE_STATE_UNSUPPORTED_BINDINGS"}}', {})))
    obs, records, error = await run_turns(client,spec,{"file_state":{"initial":{}}},
        AsyncMock(return_value=RunInput(query="test")),{"trial_id":1,"receipt_id":"a"*32},"u","t")
    assert not obs and not records and error == {"turn":1, "error":"agentos_file_state_unsupported_bindings"}


@pytest.mark.asyncio
async def test_cancelled_file_trial_releases_its_directory_after_the_worker_exits(monkeypatch):
    from contracts.constants import environment
    from runtime.agentos import prepared_evaluation as runtime

    monkeypatch.setattr(environment, "EVOLUTION_REPLAY_RUNTIME", True)
    info = SimpleNamespace(thread_future=Future(), observer=SimpleNamespace(),
                           agent_config=SimpleNamespace(tools=[],worker_agents=[],external_a2a_agents=[]))
    monkeypatch.setattr(runtime, "load_prepared_run", AsyncMock(return_value=info))
    monkeypatch.setattr(runtime.agent_run_manager, "register_agent_run", Mock())
    release = Mock()
    monkeypatch.setattr(runtime, "release_prepared_run", release)
    monkeypatch.setattr(runtime, "collect_observer_output", AsyncMock(side_effect=asyncio.CancelledError()))
    payload = SimpleNamespace(new_skill_trial=None, scoped_skill_trials=[], confirmation_bucket=None, replay_trial_id="a"*32, replay_files={"a.txt":"draft"}, conversation_id=-1,
                              watch_mcp_replies=None, watch_skill_process=None, watch_tool_arguments=None, tool_set_check=None, resource=SimpleNamespace(skill_refs=[]),
                              observe_root_skill_choices=False)
    with pytest.raises(asyncio.CancelledError):
        await runtime.execute_prepared_evaluation(payload,SimpleNamespace(user_id="u",tenant_id="t"))
    folder = info.observer.replay_file_directory.root
    assert folder.is_dir() and release.call_args.args[-1] == "stopped"
    info.thread_future.set_result(None)
    assert not folder.exists()


@pytest.mark.parametrize("initial,expected,protected", [
    ({"A":"1","a":"2"}, {}, []), ({}, {"out":"ok"}, ["out"]),
    ({"../x":"1"}, {}, []), ({}, {"x":"a" * (256 * 1024 + 1)}, []),
    ({}, {"out":None}, []), ({"x":""}, {"X":""}, []),
])
def test_reject_invalid_or_unjudgeable_file_fixture(initial, expected, protected):
    with pytest.raises(ValidationError):
        FileStateCheck(initial=initial, expected=expected, protected=protected)


@pytest.mark.asyncio
@pytest.mark.parametrize("evidence", ["missing", "wrong_reset", "partial", "valid"])
async def test_only_verified_final_files_carry_to_next_turn(evidence):
    initial, expected = {"keep.txt":"private"}, {"keep.txt":"private", "out.txt":"hidden grading label"}
    rule = FileStateCheck(initial=initial, expected=expected, protected=["keep.txt"]).model_dump()
    spec = Mock(new_skill_trial=None, scoped_skill_trials=[], confirmation_bucket=None, resource=SimpleNamespace(skill_refs=[]),
                observe_root_skill_choices=False, tool_set_check=None)
    spec.model_copy.side_effect = lambda update: SimpleNamespace(**update)
    payloads = []
    async def respond(payload, *_):
        payloads.append(payload)
        first = len(payloads) == 1
        assert payload.replay_files == (initial if first else {**initial, "out.txt":"draft"})
        assert "hidden grading label" not in str(vars(payload)) and "protected" not in vars(payload)
        state = dict(initial_digest=files_digest(payload.replay_files), files={**initial, "out.txt":"draft"} if first else expected,
                     complete=True, bound=["CreateFileTool"], writes=["out.txt","keep.txt"] if first else [])
        if evidence == "wrong_reset":
            state["initial_digest"] = "0" * 64
        if evidence == "partial":
            state["complete"] = False
        receipt = ReplayReceipt(trial_id=payload.replay_trial_id, outcome="completed",
                                file_state=None if evidence == "missing" else state)
        return EvaluationAgentResult(replay_receipt=receipt, answer="done", events=[{"type":"final_answer"}])
    job = {"trial_id":1, "receipt_id":"a" * 32}
    obs, records, error = await run_turns(SimpleNamespace(run_prepared_evaluation=respond), spec,
        {"file_state":rule,"followups":[{"query":"finish"}]}, AsyncMock(return_value=RunInput(query="work")), job,"u","t")
    if evidence != "valid":
        assert error == {"error":"unverified_file_state"} and not obs and len(payloads) == 1
        return
    assert not error and len(records) == 2 and "hidden grading label" not in str(records)
    result = judge_file_state(rule, [o.replay_receipt for o in obs])
    assert result["status"] == "fail" and result["protected_writes"] == ["keep.txt"]
    assert result["expected_digest"] == result["final_digest"]
