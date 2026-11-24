# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from contracts.errors.exceptions import AppException
from contracts.evolution import DevelopmentExperimentRequest, DevelopmentRunBudget


@pytest.mark.parametrize("limits", [{"max_replay_turns": 0}, {"max_elapsed_seconds": -1}, {"max_replay_turns": 1.5}])
def test_invalid_budget(limits):
    with pytest.raises(ValidationError):
        DevelopmentRunBudget(**limits)


@pytest.mark.asyncio
async def test_budget_includes_followups_and_fixed_tasks_in_every_arm(monkeypatch):
    from management.services.evaluation import experiments as service

    async def inline(label, fn, *args):
        return fn(*args)

    monkeypatch.setattr(service, "_io", inline)
    monkeypatch.setattr(service, "EVOLUTION_REPLAY_RUNTIME_URL", "http://replay")
    monkeypatch.setattr(service, "require_business_agent_edit", Mock())
    monkeypatch.setattr(service.jobs, "previous_submission", Mock(return_value=None))
    monkeypatch.setattr(service, "get_evaluator", Mock(return_value={"status":"PUBLISHED","evaluator_type":"code"}))
    monkeypatch.setattr(service, "_excluded_sources", AsyncMock(return_value=set()))
    monkeypatch.setattr(service, "freeze_regression_members", Mock(return_value={"2": {"digest":"2"}}))

    def task(tenant, user, agent, version, cid):
        return {"digest":str(cid), "task":{"attachments":[],"query":str(cid),"source_group":str(cid),
                                          "followups":[{"query":"next"}] if cid == 1 else []}}
    monkeypatch.setattr(service, "get_development_case", task)
    prepare = AsyncMock()
    monkeypatch.setattr(service, "_snapshot", prepare)
    monkeypatch.setattr(service, "snapshot_digest", Mock(return_value="digest"))
    save = Mock(return_value=7)
    monkeypatch.setattr(service.jobs, "submit", save)
    fields = dict(agent_id=1, version_no=1, candidate_id=3, candidate_type="prompt",
                  evaluator_id=2, case_ids=[1], request_id="budget-check")
    legacy = DevelopmentExperimentRequest(**fields)
    assert "budget" not in legacy.model_dump()
    with pytest.raises(AppException, match="requires 6 replay turns"):
        await service.create_experiment(DevelopmentExperimentRequest(**fields, budget={"max_replay_turns":5}), "t", "u")
    prepare.assert_not_awaited()
    save.assert_not_called()
    request = DevelopmentExperimentRequest(**fields, budget={"max_replay_turns":6, "max_elapsed_seconds":13})
    assert await service.create_experiment(request, "t", "u") == 7
    assert save.call_args.args[-1]["budget"] == {"max_replay_turns":6,"max_elapsed_seconds":13,"planned_replay_turns":6}


@pytest.mark.asyncio
async def test_worker_cancels_running_trial_on_experiment_deadline(monkeypatch):
    import asyncio
    import time

    from management.services.evaluation import experiments as service

    cancelled = asyncio.Event()

    async def wait_for_runtime(job):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    finish = Mock()
    async def inline(label, fn, *args):
        return fn(*args)

    monkeypatch.setattr(service, "_io", inline)
    monkeypatch.setattr(service, "execute_trial", wait_for_runtime)
    monkeypatch.setattr(service.jobs, "finish", finish)
    job = {"monotonic_deadline":time.monotonic()+0.03,"plan":{"request":dict(agent_id=1, version_no=1, candidate_type="baseline",
           evaluator_id=2, case_ids=[1], request_id="deadline")}}
    await service._work_one(job)
    assert cancelled.is_set()
    finish.assert_called_once_with(job, "error", {"error":"experiment_time_budget_exceeded"})
    finish.reset_mock()
    runner = AsyncMock()
    monkeypatch.setattr(service, "execute_trial", runner)
    await service._work_one(job)
    runner.assert_not_awaited()
    finish.assert_called_once_with(job, "error", {"error":"experiment_time_budget_exceeded"})
