# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import json
from hashlib import sha256

import pytest
from pydantic import ValidationError

from contracts.confirmation import ConfirmationManifest
from contracts.confirmation import ConfirmationPolicy
from contracts.evolution_sources import example_source_keys, task_digest
from management.cli.confirmation_manifest import compile_private_suite


def _case(**changes):
    return {"agent_id":1,"version_no":2,"query":"Private input","expected":"Private answer",
            "family":"Meeting","source_group":"Private source", **changes}


def test_private_results_distinguish_regression_missing_evidence_and_a_verified_gain():
    from management.services.evaluation.confirmation_results import arm_measurement, comparison_summary

    policy = ConfirmationPolicy(minimum_valid_pairs=2, minimum_valid_percent=100,
                                family_minimums={"private family": 2}, minimum_quality_gain_pp=1)
    def measure(status, reads=1):
        return arm_measurement(status, {"judgment":{"status":status}, "skill":{"guide_reads":reads},
                                        "execution_ms":20, "answer":"private answer"})
    base, better = measure("fail"), measure("pass")
    def compare(first, second):
        return comparison_summary(policy, [("private family", *first), ("private family", *second)], require_guide=True)
    passed = compare((base,better), (better,better))
    assert passed["decision"] == "passed" and passed["quality_gain_pp"] == 50
    assert "private" not in json.dumps(passed)
    missing = compare((base,measure("pass",0)), (better,better))
    assert missing["decision"] == "insufficient" and missing["valid_pairs"] == 1
    regressed = compare((better,base), (base,better))
    assert "regression_limit" in regressed["failures"]
    violation = arm_measurement("invalid", {"file_state":{"protected_writes":["private.txt"]}})
    failed = compare((measure("invalid"),violation), (better,better))
    assert failed["decision"] == "failed" and failed["forbidden_tasks"] == 1
    unknown = arm_measurement("invalid", {}, task={"tool_use":{"rules":[{"max_calls":0}]}})
    assert "unverified_protection" in compare((base,unknown),(better,better))["missing"]
    assert arm_measurement("pass",{"judgment":{"status":"pass"}},require_selection=True)["status"] == "invalid"


def test_usage_and_latency_need_complete_comparable_measurements():
    from management.services.evaluation.confirmation_results import comparison_summary

    policy = ConfirmationPolicy(minimum_valid_pairs=2, minimum_valid_percent=100, family_minimums={"x": 1},
                                minimum_quality_gain_pp=0, minimum_input_saving_percent=25, max_candidate_p95_ms=10)
    base = {"status":"pass", "forbidden":False, "tokens":100, "ms":5}
    pair = ("x",base,{**base,"tokens":75, "ms":10})
    def result(**changes):
        return comparison_summary(policy, [pair, ("x",base,{**pair[2],**changes})])
    assert result()["decision"] == "passed" and result()["input_saving_percent"] == 25
    assert result(tokens=76)["failures"] == ["usage_target"]
    assert result(ms=11)["failures"] == ["latency_limit"]
    assert result(ms=None,tokens=None)["decision"] == "insufficient"


def test_private_worker_requires_separate_state_and_reuses_only_first_measurement(tmp_path, monkeypatch):
    from contracts.constants import environment
    from management.services.evaluation.confirmation_runner import checkpoint, private_settings

    suite = tmp_path / "suite" / "tasks.json"
    for key, value in {"EVOLUTION_CONFIRMATION_BUCKET":"private","MINIO_DEFAULT_BUCKET":"private",
                       "EVOLUTION_CONFIRMATION_STATE_DIR":str(tmp_path/"state"),"ENABLE_TELEMETRY":False,
                       "EVOLUTION_CONFIRMATION_RUNTIME_URL":"http://private"}.items():
        monkeypatch.setattr(environment,key,value)
    _, ledger = private_settings(suite)
    assert checkpoint(ledger,"arm") is None
    assert checkpoint(ledger,"arm",{"status":"fail"}) == checkpoint(ledger,"arm",{"status":"pass"}) == {"status":"fail"}
    monkeypatch.setattr(environment,"EVOLUTION_CONFIRMATION_STATE_DIR",str(suite.parent/"state"))
    with pytest.raises(ValueError,match="state"):
        private_settings(suite)
    monkeypatch.setattr(environment,"ENABLE_TELEMETRY",True)
    with pytest.raises(ValueError,match="telemetry"):
        private_settings(suite)


def compile_at(path, *cases):
    path.write_text(json.dumps(list(cases)), encoding="utf-8")
    return compile_private_suite(path)


def test_private_suite_serializes_only_digests_and_binds_input_answer_and_attachment(tmp_path):
    pack = tmp_path / "tasks.json"
    file = tmp_path / "local.txt"
    file.write_bytes(b"Private evidence")
    task = _case(attachments=[{"name":"agenda.txt","object_name":file.name}], followups=[{"query":"Private follow-up"}])
    first = compile_at(pack, task)
    encoded = json.dumps(first.canonical())
    assert "Private" not in encoded and "agenda.txt" not in encoded and "local.txt" not in encoded
    assert set(first.cases[0].sources) == example_source_keys({"query":task["query"], "source_group":task["source_group"],
        "attachments":[{"sha256":sha256(file.read_bytes()).hexdigest()}]})
    revised = compile_at(pack, {**task,"expected":"changed"})
    assert revised.cases[0].digest != first.cases[0].digest and revised.cases[0].sources == first.cases[0].sources
    file.write_bytes(b"changed material")
    assert compile_at(pack, task).cases[0].digest != first.cases[0].digest
    other = _case(query="Another question", source_group="Independent document")
    assert task_digest(compile_at(pack, task, other).canonical()) == task_digest(compile_at(pack, other, task).canonical())


def test_compiler_rejects_mixed_scope_duplicate_tasks_and_paths_outside_the_suite(tmp_path):
    pack = tmp_path / "tasks.json"
    with pytest.raises(ValueError):
        compile_at(pack, _case(), _case(version_no=1))
    with pytest.raises(ValueError):
        compile_at(pack, _case(), _case())
    with pytest.raises(ValueError):
        compile_at(pack, _case(attachments=[{"name":"input.txt","object_name":"../input.txt"}]))
    with pytest.raises(ValidationError):
        compile_at(pack, _case(source_group="   "))
    public = compile_at(pack, _case()).canonical()
    public["cases"][0]["expected"] = "private"
    with pytest.raises(ValidationError):
        ConfirmationManifest.model_validate(public)


def test_confirm_requires_positive_quality_or_usage_and_named_coverage():
    raw = {"minimum_valid_pairs":3,"minimum_valid_percent":90,"family_minimums":{"meeting":2},
           "minimum_quality_gain_pp":0}
    with pytest.raises(ValidationError):
        ConfirmationPolicy(**raw)
    assert ConfirmationPolicy(**raw,minimum_input_saving_percent=10).minimum_quality_gain_pp == 0
    for bad in ({"family_minimums":{}},{"family_minimums":{" ":1}},{"minimum_valid_percent":0},
                {"minimum_valid_pairs":0},{"max_candidate_p95_ms":0}):
        with pytest.raises(ValidationError):
            ConfirmationPolicy(**{**raw,"minimum_quality_gain_pp":5,**bad})


def test_private_preflight_binds_materials_coverage_recipe_and_policy(tmp_path):
    from management.cli.confirmation_manifest import inspect_private_suite, verify_private_protocol
    path = tmp_path / "tasks.json"
    compile_at(path, _case())
    manifest, families = inspect_private_suite(path)
    policy = ConfirmationPolicy(minimum_valid_pairs=1,minimum_valid_percent=100,family_minimums={"Meeting":1},
                                minimum_quality_gain_pp=1).model_dump()
    recipe = {"tenant_id":"tenant","agent_id":1,"version_no":2,"experiment_id":10}
    protocol = {"lock_id":3,"suite_id":4,"suite_digest":task_digest(manifest.canonical()),"experiment_id":10,
                "candidate_digest":task_digest(recipe),"recipe":recipe,"policy":policy}
    protocol["digest"] = task_digest(["tenant",4,protocol["suite_digest"],10,protocol["candidate_digest"],policy])
    assert verify_private_protocol(manifest, families, protocol)["verified_tasks"] == 1
    changed = compile_at(path, _case(expected="different acceptance rule"))
    with pytest.raises(ValueError,match="locked comparison"):
        verify_private_protocol(changed, families, protocol)
    with pytest.raises(ValueError,match="declared scope"):
        verify_private_protocol(manifest, {}, protocol)
    with pytest.raises(ValueError,match="locked comparison"):
        verify_private_protocol(manifest, families, {**protocol,"policy":{**policy,"minimum_quality_gain_pp":2}})


def test_judge_version_and_template_are_frozen_and_checked_after_grading(monkeypatch):
    from types import SimpleNamespace
    from management.services.evaluation import experiments as service, judge_binding as bindings
    from contracts.agentos import EvaluationAgentResult

    revisions = iter(["v1","v1","v2"])
    monkeypatch.setattr(bindings, "get_model_by_model_id", lambda model, tenant: {"update_time":next(revisions)})
    monkeypatch.setattr(bindings, "model_record_revision", lambda row: row["update_time"])
    rule = {"evaluator_type":"llm","version_no":1}
    req = SimpleNamespace(judge_model_id=4,language="en",evaluator_id=2)
    frozen = bindings.judges_for_plan("tenant",rule,req,{})
    stamped = []
    monkeypatch.setattr(service, "grade_observed_case", lambda *args,**kwargs: stamped.append(True) or {2:{"status":"pass"}})
    job = {"plan":{"judges":frozen,"evaluator":rule},"tenant_id":"tenant","created_by":"editor"}
    grade = service._grade(req,job,{"query":"query","expected":"result"},EvaluationAgentResult(answer="result",events=[]))
    assert stamped == [True] and grade["status"] == "invalid" and grade["reason"] == "judge_binding_changed"


@pytest.mark.asyncio
async def test_confirmation_recipe_rejects_drift_and_omits_private_fields(monkeypatch):
    from types import SimpleNamespace
    from contracts.errors.exceptions import AppException
    from management.services.evaluation import confirmation as service
    raw = dict(agent_id=1,version_no=2,request_id="test",candidate_type="prompt",candidate_id=5,case_ids=[8],
               evaluator_id=7,screening={"target_case_ids":[8],"minimum":1})
    rubric = {"evaluator_type":"code","code":"private scoring code","version_no":1}
    plan = {"request":raw,"evaluator":rubric,"regression_cases":{},"snapshots":{"base":"old","result":"new"}}
    async def direct(name, fn, *args):
        return fn(*args)
    async def snapshot(request, tenant, editor, arm):
        return SimpleNamespace(digest=("old" if arm == "base" else "new"))
    monkeypatch.setattr(service,"_io",direct)
    monkeypatch.setattr(service,"require_business_agent_edit",lambda *args:None)
    monkeypatch.setattr(service,"get_evaluator",lambda *args:rubric)
    monkeypatch.setattr(service,"regression_members",lambda *args:[])
    monkeypatch.setattr(service.experiments,"_snapshot",snapshot)
    monkeypatch.setattr(service.experiments,"snapshot_digest",lambda spec:spec.digest)
    receipt = await service.verified_recipe("tenant","editor",44,plan)
    assert receipt["snapshots"] == plan["snapshots"] and "case_ids" not in receipt and "private scoring code" not in str(receipt)
    monkeypatch.setattr(service,"get_evaluator",lambda *args:{**rubric,"is_current":False,"update_time":"later"})
    assert await service.verified_recipe("tenant","editor",44,plan) == receipt
    plan["snapshots"]["result"] = "other"
    with pytest.raises(AppException,match="compiled resources"):
        await service.verified_recipe("tenant","editor",44,plan)
    monkeypatch.setattr(service,"regression_members",lambda *args:[{"digest":"later","scoring":{}}])
    with pytest.raises(AppException,match="current fixed regression"):
        await service.verified_recipe("tenant","editor",44,plan)


def test_private_combination_needs_observed_reads_for_each_confirmed_step():
    from management.services.evaluation.confirmation_results import arm_measurement, comparison_summary
    policy = ConfirmationPolicy(minimum_valid_pairs=1, minimum_valid_percent=100,
                                family_minimums={"heldout":1}, minimum_quality_gain_pp=1)
    def measure(status, ids):
        skills = [{"candidate_id": cid, "guide_reads": 2} for cid in ids]
        return arm_measurement(status, {"judgment":{"status":status}, "skills":skills}, step_ids={41, 42})
    old = measure("fail", [41, 42])
    def compare(new):
        return comparison_summary(policy, [("heldout", old, new)], required_step_ids={41,42})
    assert compare(measure("pass",[41,42]))["decision"] == "passed"
    decision = compare(measure("pass",[41,99]))
    assert decision["decision"] == "insufficient" and decision["missing"] == ["combined_step_not_read"]
