# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from contracts.errors.exceptions import AppException
from contracts.evolution import ToolMappingProposal
from management.services.evaluation import tool_mapping_candidates as service
from nexent.core.agents.resources.replay_tools import argument_digest


def test_generation_requires_approved_values_and_physical_evidence(monkeypatch):
    from management.services.evaluation import experiments, feedback_handoff
    proposal = ToolMappingProposal(tool_name="lookup",field="day",failure_case_id=1,protection_case_id=2,
                                   supplied_value="2026/09/01")
    spec = Mock(resource=SimpleNamespace(agent_id=7,version_no=1))
    ref = SimpleNamespace(instance_id=19,revision="abc",argument_formats=None)
    plan = {"request":{"candidate_type":"baseline"},"cases":{"1":"failure","2":"protection"},"snapshots":{"base":"baseline"}}
    rows, cases = [], {}
    for cid, source, expected, status in [(1,"2026/09/01","2026-09-01","fail"), (2,"2025-07-01","2025-07-01","pass")]:
        digest = plan["cases"][str(cid)]
        cases[cid] = {"digest":digest, "task":{"query":str(cid),"attachments":[],"tool_use":{"rules":[
            {"name":"lookup","arguments":{"day":expected}}]}}}
        evidence = {"tool":"lookup","field":"day","requested":argument_digest(source),
                    "effective":argument_digest(source),"expected":argument_digest(expected)}
        rows.append({"receipt_id":str(cid),"case_id":cid,"status":status,"variant":"base","result":{
            "tool_use":{"status":status,"argument_evidence":[evidence]}, "snapshot_digest":"baseline","case_digest":digest}})
    access = Mock()
    store = Mock(return_value=[123])
    monkeypatch.setattr(service,"require_business_agent_edit",access)
    monkeypatch.setattr(experiments,"snapshot_digest",lambda *_:"baseline")
    monkeypatch.setattr(feedback_handoff,"require_development_sources",lambda *_:None)
    monkeypatch.setattr(service,"_binding",lambda *_:(None,ref,{"kind":"iso_date"}))
    monkeypatch.setattr(service.jobs,"trials",lambda *_:rows)
    monkeypatch.setattr(service,"get_development_case",lambda *args:cases[args[-1]])
    monkeypatch.setattr(service,"store_prompt_candidates",store)
    assert service.generate_mapping("tenant","editor",8,proposal,plan,spec)["candidate_id"]==123
    assert access.call_count==2 and "2026/09/01" not in str(store.call_args)
    with pytest.raises(AppException):
        service.generate_mapping("tenant","editor",8,proposal.model_copy(update={"supplied_value":"2026/09/02"}),plan,spec)
    rows[0]["result"]["tool_use"]["argument_evidence"][0]["effective"] = argument_digest("2026-09-02")
    with pytest.raises(AppException):
        service.generate_mapping("tenant","editor",8,proposal,plan,spec)
    assert store.call_count==1


def test_private_gate_requires_proven_conversion_and_preservation():
    from contracts.confirmation import ConfirmationPolicy
    from management.services.evaluation.confirmation_results import arm_measurement, comparison_summary
    mapping = {"tool":"lookup","field":"day"}
    def measure(status, requested, effective, expected):
        event = {**mapping,"requested":requested,"effective":effective,"expected":expected}
        return arm_measurement(status, {"judgment":{"status":status},"tool_use":{"status":status,"argument_evidence":[event]}},
                               mapping=mapping)
    policy = ConfirmationPolicy(minimum_valid_pairs=2, minimum_valid_percent=100, family_minimums={"day":2}, minimum_quality_gain_pp=1)
    old, new = measure("fail","raw","raw","iso"), measure("pass","raw","iso","iso")
    guard = measure("pass","ok","ok","ok")
    def decide():
        return comparison_summary(policy,[("day",old,new),("day",guard,guard)],require_mapping=True)
    assert decide()["decision"]=="passed"
    new["mapping_observation"]["requested"]="different"
    assert "mapping_unproven_gain" in decide()["missing"]
    new["mapping_observation"]["requested"]="raw"
    guard["mapping_observation"]=None
    assert decide()["missing"]==["mapping_scope_coverage"]
