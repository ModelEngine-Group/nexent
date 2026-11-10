# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authorize and reconstruct prepared evaluation attachment inputs."""

from functools import cache
from types import SimpleNamespace

from fastapi import HTTPException

from contracts.constants.environment import NORTHBOUND_EXTERNAL_URL
from infrastructure.agent_attachments import (
    _collect_run_minio_files, _convert_history_with_minio_files,
    render_query_with_attachments, validate_attachment_references,
)
from infrastructure.object_storage.read_access import build_attachment_proxy_url
from nexent.multi_modal.utils import parse_s3_url


def materialize_evaluation_input(run_input, actor, language):
    refs = [*run_input.attachment_refs, *(item for turn in run_input.history for item in turn.attachment_refs)]
    try:
        validate_attachment_references(list({file.url for file in refs}), actor.user_id, actor.tenant_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"code": "AGENTOS_ATTACHMENT_FORBIDDEN"}) from exc

    @cache
    def sign(url):
        from infrastructure.object_storage.client import minio_client

        bucket, key = parse_s3_url(url)
        success, presigned_url = minio_client.get_file_url(key, bucket)
        if not success or not presigned_url:
            raise HTTPException(status_code=503, detail={"code": "AGENTOS_ATTACHMENT_LINK_UNAVAILABLE"})
        return build_attachment_proxy_url(presigned_url, NORTHBOUND_EXTERNAL_URL)

    def rebuild(files):
        return [
            {"name": file.name, "url": file.url, "presigned_url": sign(file.url) if file.presign else ""}
            for file in files
        ]

    current = rebuild(run_input.attachment_refs)
    history = [
        SimpleNamespace(role=turn.role, content=turn.content, minio_files=rebuild(turn.attachment_refs))
        for turn in run_input.history
    ]
    effective = _collect_run_minio_files(current, history)
    return (
        render_query_with_attachments(current, run_input.query, history, language=language),
        _convert_history_with_minio_files(history, language=language),
        effective,
    )
