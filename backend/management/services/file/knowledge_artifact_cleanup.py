# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify the complete private inventory before issuing any one-shot deletes."""

from contracts.agentos_knowledge import CleanseArtifact
from nexent.storage.errors import Conflict, InvalidInput, OutcomeUnknown
from nexent.storage.models import PageRequest, WriteOutcome
from nexent.storage.objects import read_verified_object
from pydantic import ValidationError


def private_directory_absent(objects, prefix, *, context):
    cursor = None
    while True:
        page = objects.list(prefix, PageRequest(limit=100, cursor=cursor), context=context)
        if page.items:
            return False
        if page.next_cursor is None:
            return True
        cursor = page.next_cursor


def inspect_private_artifacts(objects, row, request, *, context, limit):
    prefix, cursor, inventory = row['artifact_prefix'], None, []
    while True:
        page = objects.list(prefix, PageRequest(limit=100, cursor=cursor), context=context)
        for item in page.items:
            metadata = objects.stat(item.ref, context=context)
            if metadata.ref.key != item.ref.key or metadata.etag != item.etag:
                raise Conflict()
            digest = item.ref.key.rsplit('/', 1)[1].split('.', 1)[0]
            try:
                body = read_verified_object(objects, metadata.ref, sha256=digest, limit=limit, context=context)
                if '/artifacts/' in item.ref.key:
                    manifest = CleanseArtifact.model_validate_json(body)
                    if manifest.source != request.source or manifest.parser_version != row['parser_version']:
                        raise Conflict()
            except (InvalidInput, ValidationError):
                raise Conflict() from None
            inventory.append(metadata.ref)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    return tuple(inventory)


def delete_private_artifacts(objects, inventory, prefix, *, context):
    # One closed writer and one reserved cleanup own every key in this directory.
    for ref in sorted(inventory, key=lambda ref: '/artifacts/' in ref.key):
        context.remaining()
        receipt = objects.delete(ref, context=context)
        if receipt.outcome is not WriteOutcome.CONFIRMED or receipt.deleted is not True:
            raise OutcomeUnknown(operation_id=context.operation_id)
    return private_directory_absent(objects, prefix, context=context)
