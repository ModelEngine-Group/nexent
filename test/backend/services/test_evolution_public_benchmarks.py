# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import pytest
from pydantic import ValidationError

from contracts.errors.exceptions import AppException
from contracts.evolution import PublicBenchmarkRequest
from management.services.evaluation import public_benchmarks as service


REPORT = dict(dataset="Instruction benchmark", revision="fixture-v1", subset="format",
              scoring_protocol="exact match v1", metric="accuracy ratio", sample_count=8,
              baseline_score=0.5, candidate_score=0.75)


@pytest.mark.parametrize("values", [
    {"dataset": "  "}, {"sample_count": 0}, {"sample_count": True},
    {"candidate_score": float("inf")}, {"baseline_score": "0.5"}, {"pairs": []},
])
def test_public_report_validates_provenance_and_finite_aggregate_scores(values):
    with pytest.raises(ValidationError):
        PublicBenchmarkRequest.model_validate({**REPORT, **values})


def test_recording_a_public_report_requires_agent_edit_scope(mocker):
    mocker.patch.object(service.experiments, "scope", return_value={"agent_id": 3})
    authorize = mocker.patch.object(service, "require_business_agent_edit")
    save = mocker.patch.object(service.public_benchmarks, "add_report", return_value={"report_id": 7})
    request = PublicBenchmarkRequest(**{**REPORT, "dataset": " Instruction benchmark "})
    assert service.record_report("tenant", "editor", 5, request) == {"report_id": 7}
    authorize.assert_called_once_with(3, "tenant", "editor")
    save.assert_called_once_with("tenant", "editor", 5, request.model_dump(mode="json"))
    assert save.call_args.args[3]["dataset"] == REPORT["dataset"]


def test_unknown_experiment_cannot_be_used_to_read_reports(mocker):
    mocker.patch.object(service.experiments, "scope", return_value=None)
    read = mocker.patch.object(service.public_benchmarks, "list_reports")
    with pytest.raises(AppException):
        service.read_reports("foreign", "editor", 5, None, 20)
    read.assert_not_called()
