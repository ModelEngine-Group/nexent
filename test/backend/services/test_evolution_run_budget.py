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


@pytest.mark.parametrize("authority", ["editor", "revoked", "missing", "no_runtime"])
def test_retry_authorizes_before_queueing(monkeypatch, authority):
    from management.services.evaluation import experiments as service

    monkeypatch.setattr(service, "EVOLUTION_REPLAY_RUNTIME_URL", "" if authority == "no_runtime" else "http://replay")
    monkeypatch.setattr(service.jobs, "scope", Mock(return_value=None if authority == "missing" else {"agent_id": 1}))
    check = Mock(side_effect=AppException(service.ErrorCode.COMMON_FORBIDDEN) if authority == "revoked" else None)
    monkeypatch.setattr(service, "require_business_agent_edit", check)
    schedule = Mock()
    monkeypatch.setattr(service.jobs, "retry_inconclusive", schedule)
    report = Mock(return_value={"experiment_id": 7, "status": "running"})
    monkeypatch.setattr(service, "experiment_report", report)
    if authority == "editor":
        assert service.retry_experiment("tenant", "editor", 7) == report.return_value
        schedule.assert_called_once_with("tenant", "editor", 7)
        report.assert_called_once_with("tenant", "editor", 7)
    else:
        with pytest.raises(AppException):
            service.retry_experiment("tenant", "editor", 7)
        schedule.assert_not_called()
        report.assert_not_called()
    if authority == "missing":
        check.assert_not_called()
    else:
        check.assert_called_once_with(1, "tenant", "editor")


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
@pytest.mark.parametrize("authority", ["active", "lost_lease", "revoked"])
async def test_development_trial_checks_authority_at_dispatch(monkeypatch, authority):
    from management.services.evaluation import experiments as service

    async def inline(_label, fn, *args):
        return fn(*args)

    req = DevelopmentExperimentRequest(
        agent_id=1, version_no=1, evaluator_id=2, case_ids=[1], candidate_type="baseline",
        request_id="dispatch-authority",
    )
    job = dict(
        tenant_id="t", created_by="u", case_id=1, variant="base", receipt_id="a" * 32,
        plan={"request": req.model_dump(), "cases": {"1": "frozen"}, "snapshots": {"base": "snapshot"}},
    )
    sent = Mock()
    mark = Mock(return_value=authority == "active")
    permission = Mock(side_effect=ValueError("revoked") if authority == "revoked" else None)

    async def run_arm(_req, _job, _case, _spec, _client, _stage, *, before_dispatch):
        await before_dispatch(0)
        sent()
        return "pass", {}

    monkeypatch.setattr(service, "_io", inline)
    monkeypatch.setattr(service, "_snapshot", AsyncMock())
    monkeypatch.setattr(service, "snapshot_digest", lambda _: "snapshot")
    monkeypatch.setattr(service, "_excluded_sources", AsyncMock(return_value=set()))
    monkeypatch.setattr(service, "get_development_case", lambda *_: {
        "digest": "frozen", "task": {"query": "Original work", "source_group": "independent", "attachments": []},
    })
    monkeypatch.setattr(service, "run_verified_arm", run_arm)
    monkeypatch.setattr(service, "require_business_agent_edit", permission)
    monkeypatch.setattr(service.jobs, "authorize_dispatch", mark)

    if authority == "active":
        assert await service.execute_trial(job) == ("pass", {})
        sent.assert_called_once()
    elif authority == "lost_lease":
        with pytest.raises(AppException, match="no longer authorized to dispatch"):
            await service.execute_trial(job)
        sent.assert_not_called()
    else:
        with pytest.raises(ValueError, match="revoked"):
            await service.execute_trial(job)
        sent.assert_not_called()
    permission.assert_called_once_with(1, "t", "u")
    if authority == "revoked":
        mark.assert_not_called()
    else:
        mark.assert_called_once_with(job, 0)


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
