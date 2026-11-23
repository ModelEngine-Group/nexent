# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
from unittest.mock import AsyncMock, Mock

import pytest


def test_selection_is_order_independent_and_prefers_complementary_sources():
    from contracts.errors.exceptions import AppException
    from management.services.evaluation.example_candidates import select_examples

    pool = [dict(case_id=i, input="x" * n, output="ok", behavior=b, source_keys=[s])
            for i, n, b, s in [(3, 9, "target", "a"), (1, 2, "TARGET", "b"), (2, 3, "edge", "b"),
                               (4, 7, "edge", "c"), (5, 8, "protected", "d"), (6, 9, "other", "e")]]
    for samples in (pool, list(reversed(pool))):
        assert [e["case_id"] for e in select_examples(samples, "target")] == [1, 4, 5]
    with pytest.raises(AppException, match="target behavior"):
        select_examples(pool, "different")
    # When the shortest target shares the only edge source, use the alternative target.
    assert [e["case_id"] for e in select_examples(pool[:3], "target")] == [3, 2]


def test_filename_and_case_wording_do_not_separate_shared_material():
    from management.services.evaluation.example_candidates import example_source_keys

    def keys(q, group=None, files=()):
        return example_source_keys(dict(query=q, source_group=group, attachments=files))
    assert keys("List   actions") == keys("ＬＩＳＴ actions")
    assert keys("a", "Group A") & keys("b", "group a")
    assert keys("a", files=[{"name":"a", "sha256":"x"}]) == keys("b", files=[{"name":"b", "sha256":"x"}])
    assert not keys("same query", files=[{"sha256":"x"}]) & keys("same query", files=[{"sha256":"y"}])


def test_graded_receipt_and_selected_text_are_verified_before_write(monkeypatch):
    from contracts.errors.exceptions import AppException
    from contracts.evolution import ExampleCandidateRequest
    from management.services.evaluation import example_candidates as service

    req = ExampleCandidateRequest(target_case_id=4, target_behavior="a", examples=[
        dict(case_id=4, variant="result", behavior="a", input_excerpt="example", output_excerpt="correct")])
    trials = [dict(case_id=4, variant=v, status=s, receipt_id=v, result={"case_digest":"x", "answer":a})
              for v, s, a in [("base","fail","bad"), ("result","pass","correct response")]]
    monkeypatch.setattr(service, "require_business_agent_edit", lambda *a: None)
    monkeypatch.setattr(service.jobs, "trials", lambda *a: trials)
    monkeypatch.setattr(service, "get_development_case", lambda *a: dict(case_id=4, digest="x", task={
        "query":"example query", "attachments":[], "expected":"private grader rubric"}))
    monkeypatch.setattr(service, "published_business_agent", lambda *a: {"prompt":"original"})
    store = Mock(return_value=[12])
    monkeypatch.setattr(service, "store_prompt_candidates", store)
    def generate():
        return service.generate_example_candidates("t", "u", 5, req, "original", 1, 1, "en")
    assert [v["candidate_id"] for v in generate()["variants"]] == [None, 12]
    assert "private grader rubric" not in store.call_args.args[-1][0][0]
    store.reset_mock()
    for field, invalid in (("status","error"), ("receipt_id",None), ("result",{"case_digest":"wrong", "answer":"correct"})):
        old = trials[1][field]
        trials[1][field] = invalid
        with pytest.raises(AppException, match="receipt"):
            generate()
        trials[1][field] = old
    req.examples[0].input_excerpt = "fabricated"
    with pytest.raises(AppException, match="input"):
        generate()
    req.examples[0].input_excerpt = "example"
    req.examples[0].output_excerpt = "fabricated"
    with pytest.raises(AppException, match="output"):
        generate()
    store.assert_not_called()


def test_input_usage_includes_zero_and_rejects_missing_or_ambiguous_steps():
    from management.services.evaluation.experiments import reported_step_input_tokens

    a = {"type":"token_count", "content":'{"step_number":1,"step_input_tokens":0,"total_output_tokens":9}'}
    b = {**a, "invocation_id":"child", "content":{"step_number":1, "step_input_tokens":14}}
    assert reported_step_input_tokens([a]) == 0
    assert reported_step_input_tokens([a, b]) == 14
    for events in ([], [a, a], [a, {**b, "content":{"step_number":2}}], [{**a, "content":"broken"}]):
        assert reported_step_input_tokens(events) is None


def test_worker_rechecks_newly_linked_example_sources_before_materializing(monkeypatch):
    from management.services.evaluation import experiments as service
    from management.services.evaluation.example_candidates import example_source_keys

    task = {"query":"already shown", "attachments":[]}
    job = {"tenant_id":"tenant", "created_by":"owner", "case_id":3, "plan":{"request":{
        "agent_id":1, "version_no":1, "case_ids":[3], "request_id":"pending", "candidate_type":"prompt",
        "candidate_id":2, "evaluator_id":1}}}
    monkeypatch.setattr(service, "_io", AsyncMock(return_value={"task":task}))
    monkeypatch.setattr(service, "_excluded_sources", AsyncMock(return_value=example_source_keys(task)))
    snapshot = AsyncMock()
    monkeypatch.setattr(service, "_snapshot", snapshot)
    assert asyncio.run(service.execute_trial(job)) == ("invalid", {"error":"example_source_overlap"})
    snapshot.assert_not_called()
