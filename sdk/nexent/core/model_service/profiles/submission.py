# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Submission checks for trusted packaged profiles; never called by the application."""

from pathlib import Path

from nexent.core.model_service.profiles._models_dev.inheritance import resolve_source_model
from nexent.core.model_service.profiles._models_dev.reader import SourceDocument, read_inventory
from nexent.core.model_service.profiles._models_dev.validation import validate_source_document
from nexent.core.model_service.profiles.resolver import load_profile_catalog, load_source_catalog


def check_source_catalog(root: Path | None = None):
    """Check consumed authored/inherited facts, then exercise the actual catalog composition."""
    root = (root or Path(__file__).parent).resolve()
    inventory = read_inventory(root)
    for document in inventory.documents:
        validate_source_document(document)
        if document.kind != "provider":
            source = resolve_source_model(document, inventory.documents)
            validate_source_document(SourceDocument(
                document.kind, document.key, document.file_path, document.content_sha256, source.data,
            ), effective=True)
    return load_source_catalog(root)



def check_profile_catalog(root: Path | None = None):
    """Check the complete packaged source and experience-profile composition."""
    check_source_catalog(root)
    return load_profile_catalog(root)
