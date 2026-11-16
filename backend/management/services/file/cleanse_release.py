# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Validate a reserved completed run's immutable manifest before any cleanup writes."""

from contracts.agentos_knowledge import (
    CleanseArtifact,
    ObjectReference,
    cleanse_output_prefix,
)
from contracts.knowledge_cleanse import parse_cleanse_request
from nexent.storage.errors import InvalidInput, OutcomeUnknown
from nexent.storage.models import ObjectRef, Revision, WriteOutcome
from nexent.storage.objects import read_verified_object
from pydantic import ValidationError


def release_artifacts(objects, row, lookup, *, limit, context):
    request = parse_cleanse_request(row)
    reference = ObjectReference.model_validate(row["artifact"])
    prefix = cleanse_output_prefix(lookup)

    def read(reference, kind):
        expected = f"{prefix}{kind}/{request.source.sha256}/{reference.sha256}"
        if reference.space != request.source.space or not reference.key.startswith(
            expected + "."
        ):
            raise InvalidInput()
        if kind == "artifacts" and reference.key != expected + ".json":
            raise InvalidInput()
        if kind == "images" and reference.key.removeprefix(expected + ".") not in {
            "png",
            "jpg",
            "jpeg",
            "gif",
            "webp",
            "bmp",
            "tiff",
        }:
            raise InvalidInput()
        ref = ObjectRef(reference.space, reference.key, Revision(reference.version))
        data = read_verified_object(
            objects, ref, sha256=reference.sha256, limit=limit, context=context
        )
        return ref, data

    manifest_ref, body = read(reference, "artifacts")
    try:
        manifest = CleanseArtifact.model_validate_json(body)
    except ValidationError as error:
        raise InvalidInput() from error
    if (
        manifest.source != request.source
        or manifest.parser_version != row["parser_version"]
    ):
        raise InvalidInput()
    images = []
    for block in manifest.blocks:
        if block.kind == "image":
            ref, _ = read(block.object_ref, "images")
            if ref not in images:
                images.append(ref)
    # All reads finish before the first delete; the manifest remains until images are gone.
    for ref in [*images, manifest_ref]:
        context.remaining()
        receipt = objects.delete(ref, context=context)
        if receipt.outcome is not WriteOutcome.CONFIRMED or not receipt.deleted:
            raise OutcomeUnknown(operation_id=context.operation_id)
