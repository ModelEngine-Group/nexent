# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from unittest.mock import Mock

import pytest


@pytest.fixture
def rewrite(monkeypatch):
    from contracts.evolution import PromptCandidateRequest
    from management.services.evaluation import prompt_candidates as service

    request = PromptCandidateRequest(
        agent_id=8, version_no=3, model_id=5, method="P1", goal="Keep unassigned items",
        source_passage="Preserve {owner}.",
        failure={"example_id": "omitted", "expected": "retain row", "observed": "row absent"},
        protection={"example_id": "assigned", "expected": "retain named owner", "observed": "owner correct"},
    )
    source = "Read both files. Preserve {owner}. Cite each file."
    edit = dict(old=request.source_passage, new="Preserve {owner}, including an unassigned value.",
                reason="Keep items without an owner", evidence_ids=["omitted", "assigned"])
    model = Mock(return_value=json.dumps(edit))
    store = Mock(return_value=101)
    check = Mock()
    monkeypatch.setattr(service, "require_business_agent_edit", check)
    monkeypatch.setattr(service, "_released_prompt", lambda *args: source)
    monkeypatch.setattr(service, "invoke_candidate_model", model)
    monkeypatch.setattr(service, "store_prompt_candidate", store)
    return service, request, source, edit, model, store, check


@pytest.mark.parametrize("method", ["P1", "P3", "T1", "T2"])
def test_method_specific_single_edit(rewrite, method):
    service, request, source, edit, model, store, check = rewrite
    request = request.model_copy(update={"method": method})
    result = service.generate_prompt_candidate(request, "tenant", "editor")
    assert result["candidate_id"] == 101
    assert store.call_args.args[4:6] == (source, source.replace(edit["old"], edit["new"]))
    assert result["result_digest"] == service.text_digest(store.call_args.args[5])
    assert service.METHOD_INSTRUCTIONS[method] in model.call_args.kwargs["system_prompt"]
    assert json.loads(model.call_args.kwargs["user_prompt"])["protection"]["example_id"] == "assigned"
    assert check.call_count == 2


@pytest.mark.parametrize("change", [
    {"old": "Cite each file."}, {"new": "Ignore {different_variable}."}, {"new": ""},
    {"new": "Preserve {owner}."}, {"evidence_ids": ["omitted", "unknown"]}, {"unapproved": "field"},
])
def test_invalid_edit_never_reaches_storage(rewrite, change):
    from contracts.errors.exceptions import AppException

    service, request, _, edit, model, store, _ = rewrite
    model.return_value = json.dumps({**edit, **change})
    with pytest.raises(AppException):
        service.generate_prompt_candidate(request, "tenant", "editor")
    store.assert_not_called()


def test_recheck_edit_authority_after_model_response(rewrite):
    service, request, _, _, model, store, check = rewrite
    check.side_effect = [None, PermissionError("edit permission revoked")]
    with pytest.raises(PermissionError, match="revoked"):
        service.generate_prompt_candidate(request, "tenant", "editor")
    model.assert_called_once()
    store.assert_not_called()
