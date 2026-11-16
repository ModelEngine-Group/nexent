# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Repository profiles must pass submission checks through the ordinary UT runner."""

import hashlib
import shutil
import tomllib
from pathlib import Path

import pytest

from nexent.core.model_service import profiles
from nexent.core.model_service.profiles._models_dev.inheritance import resolve_source_model
from nexent.core.model_service.profiles._models_dev.reader import SourceDocument, SourceReadError, read_inventory
from nexent.core.model_service.profiles._models_dev.validation import validate_source_document
from nexent.core.model_service.profiles.resolver import load_profile_catalog
from nexent.core.model_service.profiles.supplements import SupplementReadError


PROFILE_ROOT = Path(profiles.__file__).resolve().parent


def _check_catalog(root):
    inventory = read_inventory(root)
    for document in inventory.documents:
        validate_source_document(document)
        if document.kind != "provider":
            effective = resolve_source_model(document, inventory.documents)
            validate_source_document(SourceDocument(
                document.kind, document.key, document.file_path, document.content_sha256, effective.data,
            ), effective=True)
    return load_profile_catalog(root)


@pytest.fixture
def catalog_copy(tmp_path):
    return Path(shutil.copytree(PROFILE_ROOT, tmp_path / "profiles", ignore=shutil.ignore_patterns("__pycache__")))


def test_packaged_profiles_pass_source_inheritance_and_experience_checks():
    catalog = _check_catalog(PROFILE_ROOT)
    assert catalog.revision
    assert catalog.models
    assert catalog.providers
    assert catalog.provider_models


@pytest.mark.parametrize("manifest, key, error_type, category", [
    ("manifest.toml", "sources", SourceReadError, "SOURCE_DIGEST_MISMATCH"),
    ("rules/manifest.toml", "rules", SupplementReadError, "SUPPLEMENT_HASH_MISMATCH"),
])
def test_submission_rejects_changed_source_or_rule(catalog_copy, manifest, key, error_type, category):
    entry = tomllib.loads((catalog_copy / manifest).read_text())[key][0]
    source = catalog_copy / entry["path"]
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(error_type) as error:
        _check_catalog(catalog_copy)
    assert error.value.category == category


def test_submission_checks_consumed_values_even_when_digest_matches(catalog_copy):
    manifest = catalog_copy / "manifest.toml"
    entry = next(item for item in tomllib.loads(manifest.read_text())["sources"]
                 if item["path"] == "models/alibaba/qwen3.5-27b.toml")
    source = catalog_copy / entry["path"]
    content = source.read_text()
    assert "reasoning = true" in content
    source.write_text(content.replace("reasoning = true", 'reasoning = "invalid"', 1))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest.write_text(manifest.read_text().replace(entry["content_sha256"], digest, 1))
    with pytest.raises(SourceReadError) as error:
        _check_catalog(catalog_copy)
    assert error.value.category == "SOURCE_VALUE_INVALID"
    assert error.value.source_path == "reasoning"
