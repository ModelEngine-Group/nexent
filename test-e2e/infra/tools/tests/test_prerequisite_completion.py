# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Prevent missing preparation and late discovery of unconfigured mock services."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

import pytest
import yaml

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parents[2]
sys.path.insert(0, str(TOOLS))
import ext_attach
import prepare_ext_knowledge as deployment
from local_preflight import required_mock_services, static_config_problems
from validate_execution import inspect


SELF_CONTAINED = ["SEARCH-DEEPSEEK-D3-001", "AGENT-LIST-D4-002", "SEARCH-DEEPSEEK-D4-001",
                  "AGENT-PROMPT-D5-001", "EVAL-LEGACY-D5-001", "USER-MODEL-READ-D5-001"]


@pytest.mark.parametrize("case_id", SELF_CONTAINED)
def test_self_contained_cases_explicitly_avoid_unrelated_assets(case_id):
    data = yaml.safe_load((REPO / "test-e2e/cases" / case_id / "execution.yaml").read_text(encoding="utf-8"))
    assert data["preparation"].get("anchors", False) is False
    assert data["preparation"]["families"] == []
    assert not data["preparation"].get("special_assets")
    assert not data["preparation"].get("d4_groups")
    assert data["notes"]


def test_real_creator_requires_tenants_and_configured_model():
    data = yaml.safe_load((REPO / "test-e2e/cases/NL2AGENT-PROTOCOL-D4-001/execution.yaml").read_text())
    assert data["preparation"] == {"anchors": True, "families": [], "d4_groups": ["llm_model"]}


def test_implementation_gate_rejects_missing_preparation_before_execution(tmp_path):
    case = tmp_path / "test-e2e/cases/SEARCH-DEEPSEEK-D3-001"
    shutil.copytree(REPO / "test-e2e/cases/SEARCH-DEEPSEEK-D3-001", case)
    schema = tmp_path / "test-e2e/infra/schemas"
    schema.mkdir(parents=True)
    shutil.copyfile(REPO / "test-e2e/infra/schemas/preparation.schema.json", schema / "preparation.schema.json")
    assert inspect(tmp_path)[0] == []
    binding = yaml.safe_load((case / "execution.yaml").read_text())
    del binding["preparation"]
    (case / "execution.yaml").write_text(yaml.safe_dump(binding))
    issues, _ = inspect(tmp_path, require_preparation_cases=["SEARCH-DEEPSEEK-D3-001"])
    assert any("explicit preparation declaration" in str(issue) for issue in issues)
    assert not any("explicit preparation declaration" in str(issue) for issue in inspect(tmp_path, "design")[0])


def config(home, **changes):
    data = {"schema_version": 1, "runner_url": "http://127.0.0.1:30090",
            "product_url": "http://ext-knowledge:30090", "owner_run_id": "test-owner",
            "source_revision": "test-revision", "build_manifest_sha256": "a" * 64,
            "compose_project": "nexent-mock-ext-knowledge", "product_network": "nexent_network",
            "lock_directory": str(home.parent / "locks"), "logical_services": list(ext_attach.EXT_LOGICAL_SERVICES)}
    data.update(changes)
    deployment.atomic_yaml(home / "config/ext-knowledge.yaml", data)
    return data


def test_selected_dependency_is_required_but_unrelated_case_is_not(tmp_path):
    home = tmp_path / "home"
    assert ext_attach.config_problems(home, REPO) == []
    assert "required" in ext_attach.config_problems(home, REPO, ["knowledge-provider"])[0]
    assert ext_attach.config_problems(home, REPO, ["memory-provider", "a2a-agent"]) == []
    records = [{"status": "active", "execution": {"required_mock_services": ["knowledge-provider"]}},
               {"status": "blocked", "execution": {"required_mock_services": ["http-fixture"]}}]
    assert required_mock_services(records) == {"knowledge-provider"}


def test_live_preflight_checks_identity_and_every_route_without_reset(tmp_path):
    home = tmp_path / "home"
    data = config(home)
    identity = {"run_id": data["owner_run_id"], "source_revision": data["source_revision"],
                "build_manifest_sha256": data["build_manifest_sha256"]}
    health = {"status": "ok", "services": {name: "ok" for name in ext_attach.ALL_HEALTH_SERVICES}}
    with patch.object(ext_attach, "_request", side_effect=[(200, identity), (200, health)]) as request:
        assert ext_attach.config_problems(home, REPO, ["knowledge-provider"], live=True) == []
        assert all("/_reset" not in call.args[0] for call in request.call_args_list)
    health["services"]["aidp"] = "degraded"
    with patch.object(ext_attach, "_request", side_effect=[(200, identity), (200, health)]):
        assert "healthy" in ext_attach.config_problems(home, REPO, ["knowledge-provider"], live=True)[0]
    with patch.object(ext_attach, "_request", return_value=(200, {**identity, "run_id": "foreign"})):
        assert "identity mismatch" in ext_attach.config_problems(home, REPO, ["knowledge-provider"], live=True)[0]


def test_default_suite_preflight_does_not_require_external_attach_yaml(tmp_path):
    records = [{"stage": "D3", "status": "active", "execution": {"required_mock_services": ["http-fixture"]}}]
    problems = static_config_problems(tmp_path, records, repo=REPO)
    assert not any("ext-knowledge.yaml" in row for row in problems)


def test_suite_owned_attach_never_reads_optional_external_configuration(tmp_path):
    home = tmp_path / "home"
    directory = tmp_path / "result"
    env = {"NEXENT_EXT_KNOWLEDGE_OWNED": "1",
           "NEXENT_EXT_KNOWLEDGE_RUNNER_URL": "http://127.0.0.1:30090",
           "NEXENT_EXT_KNOWLEDGE_PRODUCT_URL": "http://product-host:30090"}
    health = {"status": "ok", "services": {name: "ok" for name in ext_attach.ALL_HEALTH_SERVICES}}

    def request(url, **kwargs):
        return 200, health if url.endswith("/health") else {}

    attach = ext_attach.ExtKnowledgeAttach(REPO, home, directory, env, ["knowledge-provider"], "TEST-OWNED")
    with patch.object(ext_attach, "load_config", side_effect=AssertionError("external config must not be loaded")), \
            patch.object(ext_attach, "_request", side_effect=request):
        attach.attach()
        assert attach.owned and attach.attached
        assert attach.release() == 0
    evidence = json.loads((directory / "runtime/ext-knowledge-attach.json").read_text())
    assert evidence["config_fingerprint_source"] == "suite-controlled"
    assert not (home / "config/ext-knowledge.yaml").exists()


def test_default_preflight_ignores_stale_external_yaml(tmp_path):
    path = tmp_path / "config/ext-knowledge.yaml"
    path.parent.mkdir()
    path.write_text("deliberately: [invalid external configuration")
    records = [{"stage": "D3", "status": "active", "execution": {
        "required_mock_services": ["knowledge-provider"], "preparation": {"families": []}}}]
    problems = static_config_problems(tmp_path, records, repo=REPO)
    assert not any("ext-knowledge.yaml" in row for row in problems)


def test_source_match_ignores_unrelated_head_but_detects_byte_changes(tmp_path):
    source = tmp_path / "repo/mock/server.py"
    packed = tmp_path / "context/mock/server.py"
    for path in (source, packed):
        path.parent.mkdir(parents=True)
        path.write_text("source", encoding="utf-8")
    context = packed.parents[1]
    manifest = {"head": "older-product-head", "sources": {"mock": "mock", "aidp": "aidp"},
                "files": [{"path": "mock/server.py", "sha256": hashlib.sha256(b"source").hexdigest()}]}
    (context / "build-manifest.json").write_text(json.dumps(manifest))
    assert deployment.source_matches(tmp_path / "repo", context)
    source.write_text("changed")
    assert not deployment.source_matches(tmp_path / "repo", context)


def test_ensure_does_not_create_config_or_deploy_without_setup(tmp_path):
    home = tmp_path / "home"
    with patch.object(deployment, "deploy") as deploy:
        with pytest.raises(ext_attach.AttachError, match="before enabling"):
            deployment.prepare(REPO, home, "ensure", "nexent_network")
        deploy.assert_not_called()
    assert not (home / "config/ext-knowledge.yaml").exists()


def test_foreign_instance_cannot_be_replaced_by_ensure(tmp_path):
    home = tmp_path / "home"
    config(home)
    with patch.object(deployment, "_request", return_value=(200, {"run_id": "foreign"})), \
            patch.object(deployment, "deploy") as deploy:
        with pytest.raises(ext_attach.AttachError, match="foreign"):
            deployment.prepare(REPO, home, "ensure", "nexent_network")
        deploy.assert_not_called()


def test_ensure_reuses_image_and_keeps_batch_configuration_identical(tmp_path):
    home = tmp_path / "home"
    context = home / "runtime/ext-knowledge/owned/context"
    context.mkdir(parents=True)
    (context / "build-manifest.json").write_text("{}")
    manifest_hash = hashlib.sha256(b"{}").hexdigest()
    data = config(home, build_manifest_sha256=manifest_hash)
    (context.parents[1] / "deployment.json").write_text(json.dumps({"context": str(context)}))
    before = (home / "config/ext-knowledge.yaml").read_bytes()
    identity = {"run_id": data["owner_run_id"], "source_revision": data["source_revision"],
                "build_manifest_sha256": manifest_hash}
    with patch.object(deployment, "_request", return_value=(200, identity)), \
            patch.object(deployment, "source_matches", return_value=True), \
            patch.object(deployment, "product_probes"), \
            patch.object(deployment, "config_problems", return_value=[]), \
            patch.object(deployment, "deploy") as deploy:
        assert deployment.prepare(REPO, home, "ensure", "nexent_network")["status"] == "READY"
        assert deploy.call_args.kwargs == {"build": False}
    assert (home / "config/ext-knowledge.yaml").read_bytes() == before


def test_preview_has_no_side_effects(tmp_path):
    assert deployment.main(["up", "--test-home", str(tmp_path / "absent")]) == 0
    assert not (tmp_path / "absent").exists()
