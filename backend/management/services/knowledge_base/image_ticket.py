# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Short-lived KB image URLs carry a sealed reference and require the issuing principal."""

import base64
import hmac
import json
from urllib.parse import urlencode

from contracts.agentos_knowledge import KnowledgeContentRequest
from contracts.constants import environment
from cryptography.fernet import Fernet, InvalidToken
from nexent.storage.errors import ScopeDenied
from pydantic import ValidationError

IMAGE_TICKET_PREFIX = "nxki1."
_TICKET_TTL = 600
_MAX_TICKET_LENGTH = 8192


def _cipher():
    if not environment.JWT_SECRET:
        raise ScopeDenied()
    key = hmac.digest(environment.JWT_SECRET.encode(), b"nexent/knowledge-image/v1", "sha256")
    return Fernet(base64.urlsafe_b64encode(key))


def issue_image_url(content, actor, *, northbound=False):
    if not isinstance(content, KnowledgeContentRequest) or content.image_ref is None:
        raise ScopeDenied()
    body = [actor.user_id, actor.tenant_id, northbound, content.model_dump(mode="json")]
    token = IMAGE_TICKET_PREFIX + _cipher().encrypt(json.dumps(body, separators=(",", ":")).encode()).decode()
    if len(token) > _MAX_TICKET_LENGTH:
        raise ScopeDenied()
    if northbound:
        query = urlencode({"presigned_url": token})
        return f"{environment.NORTHBOUND_EXTERNAL_URL}/nb/v1/file/fetch?{query}"
    return "/api/file/knowledge/content?" + urlencode({"ticket": token})


def open_image_ticket(ticket, actor, *, northbound=False):
    if not isinstance(ticket, str) or not ticket.startswith(IMAGE_TICKET_PREFIX) or len(ticket) > _MAX_TICKET_LENGTH:
        raise ScopeDenied()
    try:
        claims = json.loads(_cipher().decrypt(ticket[len(IMAGE_TICKET_PREFIX):].encode(), ttl=_TICKET_TTL))
        user, tenant, audience, payload = claims
        if (user, tenant) != (actor.user_id, actor.tenant_id) or audience is not northbound:
            raise ScopeDenied()
        request = KnowledgeContentRequest.model_validate(payload)
        if request.image_ref is None:
            raise ScopeDenied()
        return request
    except (InvalidToken, ValidationError, TypeError, ValueError):
        raise ScopeDenied() from None
