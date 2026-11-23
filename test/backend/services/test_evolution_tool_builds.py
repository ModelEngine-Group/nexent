# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError


def test_bindings_keep_the_physical_owner_and_version():
    from management.services.evaluation.tool_builds import _binding_names, _key

    direct = {"agent_id": 9, "version_no": 1, "owner_agent": 9, "owner_version": 1, "name": "receipt"}
    child = {**direct, "owner_agent": 8}
    assert _binding_names([direct, child]) - {_key(9, 1, "receipt")} == {(9, 1, 8, 1, "receipt")}


def test_review_rejects_mutable_images_and_nonlocal_paths():
    from contracts.tool_repair import ReviewedToolBuild

    valid = {"base_image": "sha256:" + "a" * 64, "result_image": "sha256:" + "b" * 64, "review": "contract fix"}
    assert ReviewedToolBuild(**valid).path == "/mcp"
    for edit in (
        {"base_image": "tool:latest"},
        {"result_image": valid["base_image"]},
        {"path": "//external.example/mcp"},
        {"path": "/../prod"},
        {"port": 65536},
    ):
        with pytest.raises(ValidationError):
            ReviewedToolBuild(**{**valid, **edit})


def test_orphan_recovery_only_removes_expired_owned_containers(monkeypatch):
    from management.cli import verify_tool_build as verifier

    client = Mock()

    def fixture(deadline, network):
        return SimpleNamespace(
            labels={verifier._EXPIRES: deadline}, attrs={"HostConfig": {"NetworkMode": network}}, remove=Mock()
        )

    live, old, judge, unknown = (
        fixture("2000", "none"),
        fixture("100", "none"),
        fixture("100", "container:old"),
        fixture("", "none"),
    )
    client.containers.list.return_value = [old, live, judge, unknown]
    monkeypatch.setattr(verifier, "time", lambda: 1000)
    verifier._clear_expired(client)
    client.containers.list.assert_called_once_with(
        all=True, filters={"label": "nexent.evolution.tool-check=isolated-v1"}
    )
    for container in (old, judge):
        container.remove.assert_called_once_with(force=True, v=True)
    for container in (live, unknown):
        container.remove.assert_not_called()


def test_coverage_is_invalidated_after_caller_editor_loses_access(monkeypatch):
    from contracts.errors.codes import ErrorCode
    from contracts.errors.exceptions import AppException
    from management.services.evaluation import tool_builds as builds
    from nexent.core.agents.resources.replay_tools import argument_digest

    old = {k: "x" for k in ("remote", "kind", "inputs", "content", "before", "after", "error")}
    source = {
        "test_suite": {"failure": {}, "protection": {}},
        **{k: {"observation": old} for k in ("failure", "protection")},
    }
    manifest = {
        "suite_digest": argument_digest(source["test_suite"]),
        "server_id": 44,
        "binding_revision": "revision",
    }
    monkeypatch.setattr(
        builds,
        "_record",
        lambda *args: {"manifest": manifest, "created_by": "owner", "feedback_id": 2, "digest": "pinned"},
    )
    monkeypatch.setattr(builds, "maintainer_brief", lambda *args: source)
    monkeypatch.setattr(
        builds.jobs,
        "read_handoff",
        lambda *args: {"agent_id": 8, "version_no": 1, "tool_name": "ledger", "repeat_experiment_id": 32},
    )
    monkeypatch.setattr(
        builds.db, "source_approval", lambda *args: {"experiment_id": 31, "created_by": "original"}
    )
    monkeypatch.setattr(builds.jobs, "read_plan", lambda *args: {"snapshots": {"base": "original"}})
    monkeypatch.setattr(builds, "read_mcp_execution_servers", lambda *args: [])
    monkeypatch.setattr(builds, "_current_revision", lambda *args: "revision")
    inventory = [
        {"agent_id": agent, "version_no": 1, "owner_agent": agent, "owner_version": 1, "name": "ledger"}
        for agent in (8, 9)
    ]
    monkeypatch.setattr(builds.db, "published_callers", lambda *args: inventory)
    monkeypatch.setattr(
        builds.db,
        "guard_records",
        lambda *args: [
            {
                "agent_id": 9,
                "version_no": 1,
                "tool_name": "ledger",
                "approved_by": "caller",
                "experiment_id": 61,
                "case_id": 95,
                "data": {
                    "baseline": "original",
                    "rule": {},
                    "observation": old,
                    "case_digest": "case",
                    "binding_revision": "revision",
                },
            }
        ],
    )
    monkeypatch.setattr(builds, "require_development_sources", lambda *args: None)
    monkeypatch.setattr(builds, "require_business_agent_edit", lambda *args: None)
    _, plan, digest = builds.verification_plan("tenant", 30)
    assert not plan["uncovered"] and len(plan["checks"]) == 3

    def revoked(agent, tenant, user):
        if user == "caller":
            raise AppException(ErrorCode.COMMON_FORBIDDEN)

    monkeypatch.setattr(builds, "require_business_agent_edit", revoked)
    _, changed, fresh = builds.verification_plan("tenant", 30)
    assert changed["uncovered"] == [[9, 1, 9, 1, "ledger"]] and len(changed["checks"]) == 2 and fresh != digest
