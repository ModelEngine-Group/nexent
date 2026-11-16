# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Supplement declarations have exact ownership, digests and immutable snapshots."""

import hashlib
from pathlib import Path
from types import MappingProxyType

import pytest
from nexent.core.model_service.profiles.resolver import SourceCatalog
from nexent.core.model_service.profiles.supplements import (
    SupplementReadError,
    load_supplements,
)

MODEL_RULE = """schema_version = 1
rule_id = "test_model_v1"
version = 1
target_kind = "model"
target_key = "alibaba/qwen3.5-plus"
reason = "Declare traditional mapping separately"
evidence = "test-rule-v1"
aliases = ["qwen3.5-plus"]
[instruction_mapping]
ref = "system_only_v1"
version = 1
"""


@pytest.fixture
def sources():
    # Source normalization is a collaborator, covered separately by its owning UT/D1.
    return SourceCatalog(
        "a" * 64,
        "upstream",
        "parser",
        "mapping",
        1,
        MappingProxyType({"alibaba/qwen3.5-plus": None}),
        MappingProxyType({"alibaba-cn": None}),
        MappingProxyType({"alibaba-cn/qwen3.5-plus": None}),
    )


def write_manifest(root, entries):
    (root / "rules").mkdir(exist_ok=True)
    content = "schema_version = 1\n"
    for path, digest in entries:
        content += f'[[rules]]\npath = "{path}"\ncontent_sha256 = "{digest}"\n'
    (root / "rules/manifest.toml").write_text(content)


def write_rule(root, content=MODEL_RULE, path="rules/models/test.toml"):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content)
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    write_manifest(root, [(path, digest)])
    return file, digest


def test_valid_rule_is_frozen_and_revisions_include_source_and_rule_bytes(
    tmp_path, sources
):
    file, digest = write_rule(tmp_path)
    catalog = load_supplements(tmp_path, sources)
    assert catalog.source_revision == sources.revision
    entry = catalog.entries["test_model_v1"]
    assert entry.content_sha256 == digest
    assert entry.rule["aliases"] == ("qwen3.5-plus",)
    assert entry.rule["instruction_mapping"]["ref"] == "system_only_v1"
    assert load_supplements(tmp_path, sources).revision == catalog.revision
    with pytest.raises(TypeError):
        entry.rule["aliases"] = ()
    write_rule(tmp_path, MODEL_RULE.replace('"test-rule-v1"', '"changed-evidence"'))
    assert load_supplements(tmp_path, sources).revision != catalog.revision
    assert catalog.entries["test_model_v1"].rule["evidence"] == "test-rule-v1"
    assert file.exists()


def test_empty_explicit_manifest_is_valid(tmp_path, sources):
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules/manifest.toml").write_text("schema_version = 1\nrules = []\n")
    assert dict(load_supplements(tmp_path, sources).entries) == {}


@pytest.mark.parametrize(
    "replacement",
    [
        ("schema_version = 1", "schema_version = true"),
        ("schema_version = 1", "schema_version = 2"),
        ("version = 1\ntarget_kind", "version = true\ntarget_kind"),
        ("version = 1\ntarget_kind", "version = 0\ntarget_kind"),
        ('target_kind = "model"', 'target_kind = "unknown"'),
        ('aliases = ["qwen3.5-plus"]', 'aliases = ["same", "same"]'),
        ('aliases = ["qwen3.5-plus"]', 'endpoint_hints = ["url"]'),
        ('aliases = ["qwen3.5-plus"]', 'model_profile_key = "alibaba/qwen3.5-plus"'),
        ('ref = "system_only_v1"', 'ref = "unregistered"'),
        ('reason = "Declare traditional mapping separately"', 'reason = " "'),
    ],
)
def test_invalid_rule_contract_is_rejected_without_raw_contents(
    tmp_path, sources, replacement
):
    write_rule(tmp_path, MODEL_RULE.replace(*replacement))
    with pytest.raises(
        SupplementReadError, match="SUPPLEMENT_RULE_INVALID"
    ) as captured:
        load_supplements(tmp_path, sources)
    assert captured.value.file_path == "rules/models/test.toml"
    assert "Declare traditional" not in str(captured.value)


@pytest.mark.parametrize(
    "content,category",
    [
        (
            MODEL_RULE.replace('"alibaba/qwen3.5-plus"', '"missing"'),
            "SUPPLEMENT_TARGET_MISSING",
        ),
        (
            MODEL_RULE.replace(
                'target_kind = "model"', 'target_kind = "provider_model"'
            )
            .replace(
                'target_key = "alibaba/qwen3.5-plus"',
                'target_key = "alibaba-cn/qwen3.5-plus"',
            )
            .replace('aliases = ["qwen3.5-plus"]', 'model_profile_key = "missing"'),
            "SUPPLEMENT_PATH_OWNERSHIP",
        ),
    ],
)
def test_missing_target_and_wrong_directory_are_explicit(
    tmp_path, sources, content, category
):
    write_rule(tmp_path, content)
    with pytest.raises(SupplementReadError, match=category):
        load_supplements(tmp_path, sources)


def test_provider_model_link_requires_known_atom(tmp_path, sources):
    content = MODEL_RULE.replace(
        'target_kind = "model"', 'target_kind = "provider_model"'
    )
    content = content.replace(
        'target_key = "alibaba/qwen3.5-plus"', 'target_key = "alibaba-cn/qwen3.5-plus"'
    )
    content = content.replace(
        'aliases = ["qwen3.5-plus"]', 'model_profile_key = "missing"'
    )
    write_rule(tmp_path, content, "rules/providers/test.toml")
    with pytest.raises(SupplementReadError, match="SUPPLEMENT_MODEL_MISSING"):
        load_supplements(tmp_path, sources)


@pytest.mark.parametrize(
    "path",
    [
        "../outside.toml",
        "rules/models/../test.toml",
        "models/test.toml",
        "rules/models/test.json",
    ],
)
def test_manifest_paths_are_canonical_and_controlled(tmp_path, sources, path):
    write_manifest(tmp_path, [(path, "a" * 64)])
    with pytest.raises(SupplementReadError, match="SUPPLEMENT_PATH_INVALID"):
        load_supplements(tmp_path, sources)


def test_content_digest_mismatch_and_missing_file(tmp_path, sources):
    file, _ = write_rule(tmp_path)
    file.write_text(file.read_text() + "\n# different bytes\n")
    with pytest.raises(SupplementReadError, match="SUPPLEMENT_HASH_MISMATCH"):
        load_supplements(tmp_path, sources)
    file.unlink()
    with pytest.raises(SupplementReadError, match="SUPPLEMENT_FILE_INVALID"):
        load_supplements(tmp_path, sources)


def test_invalid_utf8_toml_and_external_symlink_are_sanitized(tmp_path, sources):
    path = "rules/models/test.toml"
    file, _ = write_rule(tmp_path)
    for data in [b"\xff", b"not toml = ["]:
        file.write_bytes(data)
        write_manifest(tmp_path, [(path, hashlib.sha256(data).hexdigest())])
        with pytest.raises(SupplementReadError, match="SUPPLEMENT_FILE_INVALID"):
            load_supplements(tmp_path, sources)
    file.unlink()
    file.symlink_to(Path(__file__))
    with pytest.raises(SupplementReadError, match="SUPPLEMENT_FILE_INVALID"):
        load_supplements(tmp_path, sources)


def test_duplicate_files_and_rules_never_publish_partial_catalog(tmp_path, sources):
    file, digest = write_rule(tmp_path)
    catalog = load_supplements(tmp_path, sources)
    write_manifest(
        tmp_path,
        [("rules/models/test.toml", digest), ("rules/models/test.toml", digest)],
    )
    with pytest.raises(SupplementReadError, match="SUPPLEMENT_PATH_INVALID"):
        load_supplements(tmp_path, sources)
    other = file.parent / "other.toml"
    other.write_text(file.read_text())
    write_manifest(
        tmp_path,
        [("rules/models/test.toml", digest), ("rules/models/other.toml", digest)],
    )
    with pytest.raises(SupplementReadError, match="SUPPLEMENT_DUPLICATE"):
        load_supplements(tmp_path, sources)
    assert catalog.entries["test_model_v1"].rule["target_key"] == "alibaba/qwen3.5-plus"


def test_parameter_contracts_checked_but_cross_atom_conditions_wait_for_composition(
    tmp_path, sources
):
    parameters = """\n[[parameters]]
key = "temperature"
visible = true
editable = true
required = false
allowed_scopes = ["outlet"]
ui_group = "common"
owner = "model"
default_value = 0
[parameters.source]
rule_id = "test"
[parameters.schema]
type = "number"
minimum = 0
[parameters.condition]
key = "provider_switch"
op = "eq"
value = true
"""
    write_rule(tmp_path, MODEL_RULE + parameters)
    loaded = load_supplements(tmp_path, sources)
    assert loaded.entries["test_model_v1"].rule["parameters"][0]["default_value"] == 0
    write_rule(
        tmp_path,
        MODEL_RULE + parameters.replace("default_value = 0", "default_value = false"),
    )
    with pytest.raises(SupplementReadError, match="SUPPLEMENT_RULE_INVALID"):
        load_supplements(tmp_path, sources)


@pytest.mark.parametrize(
    "manifest",
    [
        "schema_version = 2\nrules = []",
        "schema_version = true\nrules = []",
        'schema_version = 1\nunknown = "secret"\nrules = []',
    ],
)
def test_manifest_schema_version_and_unknown_fields_fail(tmp_path, sources, manifest):
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules/manifest.toml").write_text(manifest)
    with pytest.raises(SupplementReadError, match="SUPPLEMENT_MANIFEST_INVALID"):
        load_supplements(tmp_path, sources)


def test_diagnostics_identify_fields_without_echoing_values(tmp_path, sources):
    write_rule(
        tmp_path,
        MODEL_RULE.replace(
            "version = 1\ntarget_kind", 'version = "secret"\ntarget_kind'
        ),
    )
    with pytest.raises(SupplementReadError) as captured:
        load_supplements(tmp_path, sources)
    assert captured.value.field_path == "version"
    assert "secret" not in str(captured.value)
    write_rule(tmp_path, MODEL_RULE.replace('ref = "system_only_v1"', 'ref = "secret"'))
    with pytest.raises(SupplementReadError) as captured:
        load_supplements(tmp_path, sources)
    assert captured.value.field_path == "instruction_mapping"
    assert "secret" not in str(captured.value)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_capability_override_values_must_be_finite_json(tmp_path, sources, value):
    override = f"""\n[[capability_overrides]]
path = "/context/combined_window"
value = {value}
reason = "test"
evidence = "test"
"""
    write_rule(tmp_path, MODEL_RULE + override)
    with pytest.raises(
        SupplementReadError, match="SUPPLEMENT_RULE_INVALID"
    ) as captured:
        load_supplements(tmp_path, sources)
    assert captured.value.field_path == "/capability_overrides/0/value"


JSON_PARAMETER = """
[[parameters]]
key = "reasoning_effort"
visible = true
editable = true
required = false
allowed_scopes = ["outlet"]
ui_group = "reasoning"
owner = "model"
[parameters.source]
rule_id = "test"
[json_fields]
"/parameters/0/schema" = '{"enum": [null, "low"]}'
"/parameters/0/default_value" = 'null'
"""


def test_explicit_json_fields_preserve_null_without_string_aliases(tmp_path, sources):
    write_rule(tmp_path, MODEL_RULE + JSON_PARAMETER)
    parameters = (
        load_supplements(tmp_path, sources).entries["test_model_v1"].rule["parameters"]
    )
    assert parameters[0]["default_value"] is None
    assert parameters[0]["schema"]["enum"] == (None, "low")
    content = JSON_PARAMETER.replace(
        '\'{"enum": [null, "low"]}\'', '\'{"type": "string"}\''
    )
    content = content.replace("= 'null'", "= '\"null\"'")
    write_rule(tmp_path, MODEL_RULE + content)
    assert (
        load_supplements(tmp_path, sources)
        .entries["test_model_v1"]
        .rule["parameters"][0]["default_value"]
        == "null"
    )


@pytest.mark.parametrize(
    "encoded", ["NaN", "Infinity", "1e9999", '{"key": 0, "key": 1}', "invalid"]
)
def test_embedded_json_is_strict_and_sanitized(tmp_path, sources, encoded):
    write_rule(
        tmp_path, MODEL_RULE + JSON_PARAMETER.replace("= 'null'", f"= '{encoded}'")
    )
    with pytest.raises(SupplementReadError, match="SUPPLEMENT_JSON_FIELD_INVALID"):
        load_supplements(tmp_path, sources)


@pytest.mark.parametrize(
    "pointer",
    [
        "/parameters/00/default_value",
        "/parameters/1/default_value",
        "/parameters/0/key",
        "/capability_overrides/0/schema",
    ],
)
def test_json_fields_cannot_patch_arbitrary_paths(tmp_path, sources, pointer):
    write_rule(
        tmp_path,
        MODEL_RULE + JSON_PARAMETER.replace("/parameters/0/default_value", pointer),
    )
    with pytest.raises(SupplementReadError, match="SUPPLEMENT_JSON_FIELD_INVALID"):
        load_supplements(tmp_path, sources)


def test_json_and_toml_cannot_both_define_the_same_field(tmp_path, sources):
    content = JSON_PARAMETER.replace(
        'key = "reasoning_effort"', 'key = "reasoning_effort"\ndefault_value = "low"'
    )
    write_rule(tmp_path, MODEL_RULE + content)
    with pytest.raises(SupplementReadError, match="SUPPLEMENT_JSON_FIELD_CONFLICT"):
        load_supplements(tmp_path, sources)
