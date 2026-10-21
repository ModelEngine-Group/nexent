# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""MPN-D1-001: complete catalog publication through real internal collaborators."""

import hashlib
import os
import shutil
import socket
import tomllib
from pathlib import Path

import pytest
from nexent.core.model_service.profiles._models_dev.reader import SourceReadError
from nexent.core.model_service.profiles.resolver import (
    PARSER_REF,
    load_source_catalog,
)

from nexent.core.model_service.profiles.submission import check_source_catalog

ROOT = Path(__file__).resolve().parents[3] / "sdk/nexent/core/model_service/profiles"
pytestmark = [pytest.mark.case_id("MPN-D1-001"), pytest.mark.stage("D1")]


@pytest.fixture
def no_external_access(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError(
            "Catalog loading crossed an external service/credential boundary"
        )

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(os, "getenv", forbidden)


def copy_catalog(tmp_path, name):
    root = tmp_path / name
    shutil.copytree(ROOT, root)
    return root


def modify_source(root, path, transform):
    file = root / path
    old = file.read_bytes()
    updated = transform(old.decode("utf-8")).encode("utf-8")
    assert updated != old
    file.write_bytes(updated)
    manifest = root / "manifest.toml"
    old_hash = hashlib.sha256(old).hexdigest()
    new_hash = hashlib.sha256(updated).hexdigest()
    blocks = manifest.read_text().split("[[sources]]")
    matches = 0
    for index, block in enumerate(blocks[1:], 1):
        entry = tomllib.loads(block)
        if entry["path"] == path:
            assert entry["content_sha256"] == old_hash
            blocks[index] = block.replace(old_hash, new_hash)
            matches += 1
    assert matches == 1
    manifest.write_text("[[sources]]".join(blocks))


def test_complete_catalog_capabilities_origins_and_immutable_snapshots(
    no_external_access,
):
    before = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in ROOT.rglob("*.toml")
    }
    first = check_source_catalog(ROOT)
    second = load_source_catalog(ROOT)
    assert (len(first.models), len(first.providers), len(first.provider_models)) == (
        26,
        6,
        35,
    )
    assert first.revision == second.revision
    assert first.parser_ref == PARSER_REF
    assert set(first.providers) == {
        "alibaba-cn",
        "volcengine",
        "volcengine-coding-plan",
        "siliconflow-cn",
        "deepseek",
        "tokenpony",
    }
    assert "alibaba-cn/MiniMax/MiniMax-M2.7" in first.provider_models
    entry = first.provider_models["alibaba-cn/qwen3.8-max"]
    assert entry.capabilities["context"]["combined_window"] == 1_000_000
    assert entry.capabilities["tools"]["status"] == "supported"
    origin = entry.field_origins["/capabilities/tools/status"]
    assert origin.mapping.source.file_path == "models/alibaba/qwen3.8-max.toml"
    assert origin.mapping.source.source_path == "tool_call"
    assert origin.mapping.rule_id == "provider_model.tool_call"
    assert origin.mapping.rule_version == 1
    assert origin.normalization_ref == first.parser_ref
    assert {reference.key for reference in entry.source_refs} == {
        "alibaba/qwen3.8-max",
        "alibaba-cn/qwen3.8-max",
        "alibaba-cn",
    }
    assert all(
        reference.catalog_revision == first.revision for reference in entry.source_refs
    )
    plus = first.provider_models["alibaba-cn/qwen3.5-plus"]
    budget = plus.capabilities["reasoning"]["controls"][1]
    assert budget["min"] is None and budget["max"] == 81920
    assert (
        first.provider_models["alibaba-cn/glm-5.1"].capabilities["tools"]["status"]
        == "supported"
    )
    assert (
        first.provider_models["volcengine/deepseek-v4-flash-ga-260731"].capabilities[
            "reasoning"
        ]["status"]
        == "supported"
    )
    assert (
        first.provider_models["volcengine-coding-plan/minimax-m3"].capabilities[
            "context"
        ]["combined_window"]
        == 1048576
    )
    with pytest.raises(TypeError):
        first.models["new"] = entry
    with pytest.raises(TypeError):
        plus.capabilities["reasoning"]["controls"][0]["values"][0] = False
    after = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in ROOT.rglob("*.toml")
    }
    assert before == after


def test_source_and_rule_changes_affect_revision_and_preserve_original(
    tmp_path, no_external_access, monkeypatch
):
    original = load_source_catalog(ROOT)
    changed_source = copy_catalog(tmp_path, "source")
    modify_source(
        changed_source,
        "models/alibaba/qwen3.8-max.toml",
        lambda text: text.replace("tool_call = true", "tool_call = false", 1),
    )
    changed = load_source_catalog(changed_source)
    key = "alibaba-cn/qwen3.8-max"
    assert changed.revision != original.revision
    assert (
        changed.provider_models[key].profile_revision
        != original.provider_models[key].profile_revision
    )
    assert changed.provider_models[key].capabilities["tools"]["status"] == "unsupported"
    assert original.provider_models[key].capabilities["tools"]["status"] == "supported"
    assert (
        changed.provider_models["alibaba-cn/qwen3.5-plus"].profile_revision
        == original.provider_models["alibaba-cn/qwen3.5-plus"].profile_revision
    )
    from dataclasses import replace
    from nexent.core.model_service.profiles import resolver
    with monkeypatch.context() as patch:
        patch.setattr(resolver, "SOURCE_MAPPING", replace(resolver.SOURCE_MAPPING, mapping_version=2))
        remapped = load_source_catalog(ROOT)
        assert remapped.revision != original.revision
        assert remapped.provider_models[key].profile_revision != original.provider_models[key].profile_revision
        assert remapped.mapping_version == 2
        assert load_source_catalog(ROOT).revision == remapped.revision
    assert original.mapping_version == 1
    assert load_source_catalog(ROOT).revision == original.revision


@pytest.mark.parametrize(
    "variant,category,source_path",
    [
        ("unhandled", "SOURCE_FIELD_UNHANDLED", "reasoning_effort"),
        ("base", "SOURCE_BASE_MODEL_MISSING", "base_model"),
        ("type", "SOURCE_VALUE_INVALID", "tool_call"),
        ("upstream", "SOURCE_SCHEMA_UNSUPPORTED", "upstream_revision"),
    ],
)
def test_invalid_catalog_never_publishes_partial_results(
    tmp_path, no_external_access, variant, category, source_path
):
    original = load_source_catalog(ROOT)
    root = copy_catalog(tmp_path, variant)
    if variant == "unhandled":
        modify_source(
            root,
            "models/alibaba/qwen3.8-max.toml",
            lambda text: 'reasoning_effort = "sensitive-marker"\n' + text,
        )
    elif variant == "base":
        modify_source(
            root,
            "providers/alibaba-cn/models/qwen3.8-max.toml",
            lambda text: text.replace("alibaba/qwen3.8-max", "missing/model", 1),
        )
    elif variant == "upstream":
        path = root / "manifest.toml"
        path.write_text(path.read_text().replace(original.upstream_revision, "a" * 40))
    else:
        modify_source(root, "models/alibaba/qwen3.8-max.toml",
                      lambda text: text.replace("tool_call = true", 'tool_call = "invalid"', 1))
    with pytest.raises(SourceReadError) as error:
        check_source_catalog(root)
    assert error.value.category == category
    assert error.value.source_path == source_path
    assert "sensitive-marker" not in str(error.value)
    assert str(tmp_path) not in str(error.value)
    assert (
        original.provider_models["alibaba-cn/qwen3.8-max"].capabilities["tools"][
            "status"
        ]
        == "supported"
    )
    assert load_source_catalog(ROOT).revision == original.revision



def test_runtime_does_not_execute_submission_checks_and_reference_metadata_is_unrestricted(tmp_path, monkeypatch):
    from nexent.core.model_service.profiles import submission
    root = copy_catalog(tmp_path, "reference")
    modify_source(root, "models/alibaba/qwen3.8-max.toml",
                  lambda text: text + '\n[[benchmarks]]\nfuture_score = "free-form"\n')
    checked = check_source_catalog(root)
    def forbidden(*args, **kwargs):
        raise AssertionError("Runtime invoked submission schema validation")
    monkeypatch.setattr(submission, "validate_source_document", forbidden)
    runtime = load_source_catalog(root)
    assert runtime.revision == checked.revision
    assert runtime.models["alibaba/qwen3.8-max"].reference_metadata["benchmarks"][-1]["future_score"] == "free-form"
    assert runtime.models["alibaba/qwen3.8-max"].capabilities == load_source_catalog(ROOT).models["alibaba/qwen3.8-max"].capabilities
