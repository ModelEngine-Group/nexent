# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Provider-independent identifiers used by tag adapters and display projections."""

import base64
import json

KNOWLEDGE_CONTENT_LIBRARY_CODE = "knowledge_content"
LOCAL_DOCUMENT_PROVIDER = "local"


def _encode_document_resource_id(
    provider: str,
    knowledge_base_id: str,
    provider_document_id: str,
) -> str:
    """Encode the provider document tuple as a stable, reversible resource ID."""

    payload = json.dumps(
        [provider, knowledge_base_id, provider_document_id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")
