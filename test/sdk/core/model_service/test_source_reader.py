# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit proof for controlled local sources; normalization is a separate contract."""

import hashlib
from pathlib import Path

import pytest
from nexent.core.model_service.profiles._models_dev.reader import (
    SourceReadError,
    read_sources,
)

CATALOG_ROOT = (
    Path(__file__).resolve().parents[4] / "sdk/nexent/core/model_service/profiles"
)


def write_inventory(
    root,
    *,
    data=b'name = "Test"\n[limit]\ncontext = 100\n',
    path="models/test/model.toml",
    kind="model",
    digest=None,
    version="1",
    extra="",
    copies=1,
):
    digest = digest or hashlib.sha256(data).hexdigest()
    (root / "manifest.toml").write_text(
        f'schema_version = {version}\nsource_schema_ref = "models_dev_authored_v1"\n'
        'upstream_url = "https://github.com/anomalyco/models.dev"\n'
        f'upstream_revision = "{"a" * 40}"\n{extra}\n'
        + (
            f'[[sources]]\nkind = "{kind}"\npath = "{path}"\ncontent_sha256 = "{digest}"\n'
            * copies
        )
    )
    if not path.startswith("/") and ".." not in path.split("/"):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def test_loads_pinned_inventory_with_exact_nested_model_identity():
    documents = read_sources(CATALOG_ROOT)
    assert len(documents) == 67
    assert any(
        document.key == "alibaba-cn/MiniMax/MiniMax-M2.7" for document in documents
    )
    assert {document.key for document in documents if document.kind == "provider"} == {
        "alibaba-cn",
        "volcengine",
        "volcengine-coding-plan",
        "siliconflow-cn",
        "deepseek",
        "tokenpony",
    }


def test_authored_documents_are_deeply_immutable(tmp_path):
    write_inventory(
        tmp_path,
        data=b'name = "Test"\nvalues = ["low", "high"]\n[limit]\ncontext = 100\n',
    )
    documents = read_sources(tmp_path)
    assert isinstance(documents, tuple)
    doc = documents[0]
    assert doc.data["values"] == ("low", "high")
    with pytest.raises(TypeError):
        doc.data["limit"]["context"] = 0
    with pytest.raises(TypeError):
        doc.data["name"] = "Changed"


@pytest.mark.parametrize(
    "changes,category",
    [
        ({"path": "../outside.toml"}, "SOURCE_REFERENCE_INVALID"),
        ({"path": "/tmp/outside.toml"}, "SOURCE_REFERENCE_INVALID"),
        ({"path": "models/./test.toml"}, "SOURCE_REFERENCE_INVALID"),
        (
            {"path": "providers/test/provider.toml", "kind": "model"},
            "SOURCE_KIND_PATH_MISMATCH",
        ),
        ({"digest": "a" * 64}, "SOURCE_DIGEST_MISMATCH"),
        ({"digest": "wrong"}, "SOURCE_REFERENCE_INVALID"),
        ({"data": b"name = ["}, "SOURCE_TOML_INVALID"),
        ({"data": b"\xff"}, "SOURCE_TOML_INVALID"),
        ({"copies": 2}, "SOURCE_DUPLICATE"),
        ({"copies": 0}, "SOURCE_MANIFEST_INVALID"),
        ({"version": "2"}, "SOURCE_MANIFEST_INVALID"),
        ({"version": "1.0"}, "SOURCE_MANIFEST_INVALID"),
        ({"path": "models/test/model.json"}, "SOURCE_KIND_PATH_MISMATCH"),
        ({"path": "models/test/.toml"}, "SOURCE_KIND_PATH_MISMATCH"),
        ({"version": "true"}, "SOURCE_MANIFEST_INVALID"),
        ({"extra": "unexpected = 1"}, "SOURCE_MANIFEST_INVALID"),
    ],
)
def test_rejects_invalid_inventory_before_returning_partial_data(
    tmp_path, changes, category
):
    write_inventory(tmp_path, **changes)
    with pytest.raises(SourceReadError) as caught:
        read_sources(tmp_path)
    assert caught.value.category == category
    assert "name =" not in str(caught.value)
    assert caught.value.rule_id == "source_inventory_v1"


def test_missing_manifest_and_source_are_explicit_errors(tmp_path):
    with pytest.raises(SourceReadError, match="SOURCE_FILE_UNAVAILABLE"):
        read_sources(tmp_path)
    write_inventory(tmp_path)
    (tmp_path / "models/test/model.toml").unlink()
    with pytest.raises(SourceReadError, match="SOURCE_FILE_UNAVAILABLE"):
        read_sources(tmp_path)


def test_symlink_to_outside_root_is_rejected(tmp_path):
    root = tmp_path / "catalog"
    root.mkdir()
    write_inventory(root)
    target = root / "models/test/model.toml"
    target.unlink()
    outside = tmp_path / "outside.toml"
    outside.write_text('name = "Outside"')
    target.symlink_to(outside)
    with pytest.raises(SourceReadError, match="SOURCE_PATH_OUTSIDE_ROOT"):
        read_sources(root)


def test_invalid_upstream_commit_is_rejected(tmp_path):
    write_inventory(tmp_path)
    manifest = tmp_path / "manifest.toml"
    manifest.write_text(manifest.read_text().replace("a" * 40, "not-a-commit"))
    with pytest.raises(SourceReadError, match="SOURCE_MANIFEST_INVALID"):
        read_sources(tmp_path)


@pytest.mark.parametrize("declarations", [
    'origin = "nexent"\n',
    'origin = "nexent"\nsource_revision = "local-v1"\n',
    'origin = "nexent"\nsource_url = "https://docs.example.com/"\n',
    'origin = "nexent"\nsource_revision = "local-v1"\nsource_url = "file:///tmp/doc"\n',
    'source_revision = "pretend-upstream"\nsource_url = "https://docs.example.com/"\n',
])
def test_local_sources_reject_incomplete_or_misrepresented_origin(tmp_path, declarations):
    write_inventory(tmp_path)
    manifest = tmp_path / "manifest.toml"
    manifest.write_text(manifest.read_text() + declarations)
    with pytest.raises(SourceReadError, match="SOURCE_MANIFEST_INVALID"):
        read_sources(tmp_path)


def test_local_source_keeps_origin_separate_from_upstream_commit():
    local = next(document for document in read_sources(CATALOG_ROOT) if document.key == "tokenpony")
    assert local.origin == "nexent"
    assert local.source_revision == "nexent_tokenpony_provider_v1"
    assert local.source_url == "https://docs.tokenpony.cn/"
