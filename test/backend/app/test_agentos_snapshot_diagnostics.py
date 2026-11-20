# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Locate snapshot failures without exposing secrets or hiding service errors."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from management.services.agent.preparation import evaluation_snapshot as subject


def compile_args():
    return dict(agent=SimpleNamespace(agent_id=7, version_no=3, model_name="fixture"), models=[],
                query="private prompt", history=None, tenant_id="tenant-a", conversation_id=0, language="zh")


@pytest.mark.parametrize("error,category", [
    (LookupError("private catalog"), "unresolved"),
    (OSError("private endpoint"), "dependency_io"),
    (TypeError("private setting"), "compiler"),
    (ValueError("private setting"), "contract"),
])
def test_strict_export_preserves_cause_and_safe_stage(mocker, caplog, error, category):
    mocker.patch.object(subject, "_export_resource", side_effect=error)
    with pytest.raises(subject.SnapshotCompilationError) as result:
        subject.compile_snapshot(**compile_args())
    assert result.value.stage == "resource"
    assert result.value.category == category
    assert result.value.error_type == type(error).__name__
    assert result.value.__cause__ is error
    assert "private" not in str(result.value)
    assert subject.export_snapshot(**compile_args()) is None
    assert "agentos_snapshot_not_exported" in caplog.text
    assert "private" not in caplog.text


def test_strict_export_locates_model_failure(mocker):
    def resource(_agent, aliases, *args, **kwargs):
        aliases["fixture"] = None
        return SimpleNamespace()
    mocker.patch.object(subject, "_export_resource", side_effect=resource)
    error = ValueError("private model config")
    mocker.patch.object(subject, "_export_model", side_effect=error)
    with pytest.raises(subject.SnapshotCompilationError) as result:
        subject.compile_snapshot(**compile_args())
    assert result.value.stage == "model" and result.value.__cause__ is error


def test_http_permission_and_version_errors_are_not_compatibility_failures(mocker):
    error = HTTPException(status_code=403, detail={"code": "DENIED"})
    mocker.patch.object(subject, "_export_resource", side_effect=error)
    with pytest.raises(HTTPException) as result:
        subject.export_snapshot(**compile_args())
    assert result.value is error
