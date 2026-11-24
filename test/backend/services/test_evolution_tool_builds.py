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



def test_managed_endpoints_are_distinct_and_pins_reject_changed_registry(monkeypatch):
    import json
    from infrastructure import mcp_implementations as deployments

    config = dict(tenant_id="tenant", server_id=1, image="sha256:" + "a" * 64,
                  production="http://127.0.0.1:6001/mcp", development="http://localhost:6002/mcp",
                  confirmation="http://127.0.0.1:6003/mcp")
    monkeypatch.setattr(deployments.environment, "EVOLUTION_MCP_DEPLOYMENTS", json.dumps([config]))
    monkeypatch.setattr(deployments.environment, "EVOLUTION_CONFIRMATION_BUCKET", "")
    pin = deployments.managed_deployment("tenant", 1, config["image"]).pin()
    assert deployments.implementation_host("tenant", 1, pin)["url"] == config["production"]
    assert deployments.implementation_host("tenant", 1, pin, replay=True)["url"] == config["development"]
    monkeypatch.setattr(deployments.environment, "EVOLUTION_CONFIRMATION_BUCKET", "private")
    assert deployments.implementation_host("tenant", 1, pin, replay=True)["url"] == config["confirmation"]
    with pytest.raises(ValueError, match="No operator-managed deployment"):
        deployments.implementation_host("other-tenant", 1, pin)
    with pytest.raises(ValueError, match="separate"):
        deployments.deployment_manifest(json.dumps([{**config, "confirmation": "http://localhost:6001/sse"}]))
    monkeypatch.setattr(deployments.environment, "EVOLUTION_MCP_DEPLOYMENTS", json.dumps([
        {**config, "confirmation": "http://127.0.0.1:6004/mcp"}
    ]))
    with pytest.raises(ValueError, match="differs from"):
        deployments.implementation_host("tenant", 1, pin)


def test_tool_repair_requires_equal_tool_input_and_business_initial_state():
    from management.services.evaluation.tool_use import build_effect, observed_build_call

    def observe(**changes):
        raw = dict(tool="ledger", remote="ledger", kind="text", inputs="approved", before="initial",
                   input_matches=True, reply_matches=True, state_matches=True, error=False)
        return observed_build_call({"tool_use": {"mcp_evidence": [{**raw, **changes}], "issues": []}},
                                   {"tool": "ledger"})

    old = observe(state_matches=False)
    assert build_effect(old, observe()) == "corrected"
    assert build_effect(observe(), observe()) == "protected"
    assert build_effect(old, observe(before="new initial")) is None
    assert build_effect(old, observe(inputs="different input")) is None
    assert build_effect(old, observe(input_matches=False)) is None
    assert build_effect(old, observe(state_matches=None)) is None
