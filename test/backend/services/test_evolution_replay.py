# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import copy
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError


@pytest.fixture
def replay(monkeypatch):
    from contracts.evolution import ReplayCaseRequest
    from management.db.evaluation.replay_cases import task_digest
    from management.services.evaluation import replay_cases as service

    objects = {"attachments/editor/file": b"\x00test\xff"}
    saved = []
    monkeypatch.setattr(service, "require_business_agent_edit", lambda *args: None)
    monkeypatch.setattr(service, "published_business_agent", lambda *args: {})
    monkeypatch.setattr(service.minio_client, "get_file_stream",
                        lambda key: (True, io.BytesIO(objects[key])) if key in objects else (False, None))
    def upload(stream, key):
        objects[key] = stream.read()
        return True, ""
    def remove(key):
        objects.pop(key, None)
        return True, ""
    def save(tenant, agent, version, user, task):
        saved.append({"case_id": 1, "digest": task_digest(task), "task": task})
        return saved[-1]
    monkeypatch.setattr(service.minio_client, "upload_fileobj", upload)
    monkeypatch.setattr(service.minio_client, "delete_file", remove)
    monkeypatch.setattr(service, "save_replay_case", save)
    monkeypatch.setattr(service, "read_replay_case", lambda *args: saved[-1])
    request = ReplayCaseRequest(agent_id=3, version_no=2, family="attachments", query="read both files",
                                expected="private scoring label", attachments=[{"name":"document.bin",
                                "object_name":"attachments/editor/file"}])
    return service, request, objects, saved


def test_arms_get_independent_approved_bytes_and_labels_are_withheld(replay):
    service, request, objects, saved = replay
    service.freeze_development_case(request, "editor", "tenant")
    objects["attachments/editor/file"] = b"changed after confirmation"
    args = ("tenant", "editor", 3, 2, 1)
    with service.stage_case_input(*args) as base, service.stage_case_input(*args) as candidate:
        first, second = [spec.attachment_refs[0].url.split("/", 3)[3] for spec in (base, candidate)]
        assert first != second
        assert objects[first] == objects[second] == b"\x00test\xff"
        assert base.query == candidate.query == request.query
        assert request.expected not in base.model_dump_json()
        objects[first] = b"side effect"
        assert objects[second] == b"\x00test\xff"
    assert first not in objects and second not in objects
    archived = next(key for key in objects if key.startswith("evolution/"))
    objects[archived] = b"broken"
    with pytest.raises(Exception, match="changed"):
        with service.stage_case_input(*args):
            pytest.fail("corrupt input reached the runtime")


def test_foreign_input_rejected_before_storage_access(replay, monkeypatch):
    service, request, objects, saved = replay
    request.attachments[0].object_name = "attachments/other/file"
    read = Mock()
    monkeypatch.setattr(service, "_read_bounded", read)
    with pytest.raises(Exception):
        service.freeze_development_case(request, "editor", "tenant")
    read.assert_not_called()
    assert not saved


def test_followup_attachment_created_only_when_turn_starts(replay):
    from contracts.evolution import ReplayFollowup

    service, request, objects, _ = replay
    request.followups = [ReplayFollowup(query="use the file", attachment_names=["document.bin"])]
    service.freeze_development_case(request, "editor", "tenant")
    args = ("tenant", "editor", 3, 2, 1, "2" * 32)
    with service.stage_case_input(*args, 0) as first:
        assert not first.attachment_refs and not any("evolution-replay/" in key for key in objects)
        with service.stage_case_input(*args, 1) as second:
            assert second.query == "use the file" and second.attachment_refs[0].name == "document.bin"
            assert sum("evolution-replay/" in key for key in objects) == 1
    assert not any("evolution-replay/" in key for key in objects)


@pytest.mark.parametrize("name", ["../a", "a/b", "C:x", "NUL", "a\x00b"])
def test_replay_paths_are_portable(name):
    from contracts.evolution import ReplayAttachmentSource

    with pytest.raises(ValidationError):
        ReplayAttachmentSource(name=name, object_name="attachments/editor/object")


def test_fixed_regression_report_accounts_for_missing_trials_and_unresolved_failures(monkeypatch):
    from management.services.evaluation import experiments as service

    frozen = {str(i): {"source_case_id": i, "digest": str(i)} for i in range(1, 6)}
    monkeypatch.setattr(service.jobs, "scope", lambda *args: {"agent_id": 12, "version_no": 1, "regression_cases": frozen})
    monkeypatch.setattr(service, "require_business_agent_edit", lambda *args: None)
    rows = [{"case_id": i, "variant": arm, "status": status, "result": {}}
            for i, statuses in enumerate([("pass", "fail"), ("fail", "fail"), ("fail", "pass"),
                                          ("pass", None), (None, None)], 1)
            for arm, status in zip(("base", "result"), statuses) if status is not None]
    monkeypatch.setattr(service.jobs, "trials", lambda *args: rows)
    report = service.experiment_report("tenant", "editor", 1)
    assert report["fixed_regression"] == {"case_ids": [1, 2, 3, 4, 5], "failed": [1, 2], "incomplete": [4, 5]}
    assert report["total_pairs"] == 5 and report["valid_pairs"] == 3
    assert report["pairs"][5]["comparison"] == "inconclusive"


def test_same_answer_uses_the_rubric_frozen_for_its_task():
    from contracts.agentos import EvaluationAgentResult
    from management.services.evaluation.experiments import _grade

    def rule(eid, version, score):
        return {"evaluator_id": eid, "version_no": version, "name": "rule", "evaluator_type": "code",
                "pass_threshold": 1.0, "code": f"def evaluate(query, expected, actual, runtime_events):\n    return {{'score': {score}}}"}

    request = SimpleNamespace(evaluator_id=1, judge_model_id=None, language="en")
    observed = EvaluationAgentResult(answer="[]", events=[{"type": "final_answer"}])
    task = {"query": "list rows", "expected": "[]"}
    frozen = {"evaluator": rule(3, 7, 0), "judge_model_id": None, "language": "zh"}
    job = {"plan": {"evaluator": rule(1, 4, 1), "regression_cases": {"2": {"scoring": frozen}}},
           "tenant_id": "tenant", "created_by": "editor"}
    general = _grade(request, {**job, "case_id": 1}, task, observed)
    fixed = _grade(request, {**job, "case_id": 2}, task, observed)
    assert (general["status"], general["evaluator_id"], general["evaluator_version"]) == ("pass", 1, 4)
    assert (fixed["status"], fixed["evaluator_id"], fixed["evaluator_version"]) == ("fail", 3, 7)


def test_snapshot_digest_normalizes_only_generated_binding_names():
    from management.services.evaluation.experiments import snapshot_digest

    def spec(alias, revision, instruction="baseline"):
        data = {"resource": {"model_alias":alias, "subagents":[], "instructions":instruction},
                "models":{"llm":{"alias":alias, "revision":revision}, "additional_llms":[]}}
        return SimpleNamespace(model_dump=lambda **kwargs: copy.deepcopy(data))
    a, b = "agent_model_" + "a"*32, "agent_model_" + "b"*32
    assert snapshot_digest(spec(a, "1")) == snapshot_digest(spec(b, "1"))
    assert snapshot_digest(spec(a, "1")) != snapshot_digest(spec(a, "2"))
    assert snapshot_digest(spec(a, "1")) != snapshot_digest(spec(b, "1", "candidate"))


def test_normal_runtime_declines_replay_before_materialization(monkeypatch):
    from contracts.constants import environment
    from fastapi import HTTPException
    from runtime.agentos import prepared_evaluation as runtime
    monkeypatch.setattr(environment, "EVOLUTION_REPLAY_RUNTIME", False)
    prepare = AsyncMock()
    monkeypatch.setattr(runtime, "load_prepared_run", prepare)
    with pytest.raises(HTTPException) as error:
        asyncio.run(runtime.execute_prepared_evaluation(SimpleNamespace(replay_trial_id="a"*32, confirmation_bucket=None), None))
    assert error.value.status_code == 503
    prepare.assert_not_awaited()


@pytest.mark.parametrize("pool,requested,telemetry", [("", "private", False), ("private", None, False),
                                                       ("private", "other", False), ("private", "private", True)])
def test_private_trials_reject_an_unmatched_runtime_before_loading(pool, requested, telemetry, monkeypatch):
    from contracts.constants import environment
    from fastapi import HTTPException
    from runtime.agentos import prepared_evaluation as runtime

    monkeypatch.setattr(environment, "EVOLUTION_REPLAY_RUNTIME", True)
    monkeypatch.setattr(environment, "EVOLUTION_CONFIRMATION_BUCKET", pool)
    monkeypatch.setattr(environment, "MINIO_DEFAULT_BUCKET", "private")
    monkeypatch.setattr(environment, "ENABLE_TELEMETRY", telemetry)
    prepare = AsyncMock()
    monkeypatch.setattr(runtime, "load_prepared_run", prepare)
    with pytest.raises(HTTPException) as error:
        asyncio.run(runtime.execute_prepared_evaluation(SimpleNamespace(replay_trial_id="a"*32, confirmation_bucket=requested), None))
    assert error.value.status_code == 403
    prepare.assert_not_awaited()
