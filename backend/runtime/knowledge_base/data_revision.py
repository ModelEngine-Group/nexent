# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Stable revision of confirmed chunk changes and current published manifests."""

import hashlib
import json

from runtime.knowledge_base.chunk_view import ChunkReadView
from runtime.knowledge_base.publication import published_files


def knowledge_data_revision(records, knowledge_id, *, context):
    view = ChunkReadView(records, knowledge_id, context=context)
    digest = hashlib.sha256(json.dumps([knowledge_id, view.version], separators=(",", ":")).encode())
    for row in published_files(records, knowledge_id, context=context):
        digest.update(json.dumps([row["file_id"], row["visible_version"], row["visible_generation"],
                                  row["visible_job_id"]], separators=(",", ":")).encode())
    view.stable(context=context)
    return digest.hexdigest()
