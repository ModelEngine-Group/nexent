# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Expiring, exact-key read grants shared by the independent service roles."""

import base64
import hmac
import json
from time import time
from urllib.parse import urlencode

TICKET_PREFIX = 'nxo1.'
_SIGNING_DOMAIN = b'nexent/object-download/v1'
_MAX_TICKET_LENGTH = 10_000
_MAX_TTL = 7 * 24 * 60 * 60


class InvalidObjectTicket(ValueError):
    """An invalid, expired, or unissuable download ticket."""


def _validate_key(key):
    try:
        valid = isinstance(key, str) and 0 < len(key.encode('utf-8')) <= 1024 and '\x00' not in key
    except UnicodeError:
        valid = False
    if not valid:
        raise InvalidObjectTicket()


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('ascii').rstrip('=')


def _signature(encoded: str, secret: str) -> str:
    if not secret:
        raise InvalidObjectTicket()
    key = hmac.digest(secret.encode('utf-8'), _SIGNING_DOMAIN, 'sha256')
    return _encode(hmac.digest(key, encoded.encode('ascii'), 'sha256'))


def issue_object_ticket(key: str, ttl: int, *, secret: str, now: int | None = None) -> str:
    _validate_key(key)
    if type(ttl) is not int or not 1 <= ttl <= _MAX_TTL:
        raise InvalidObjectTicket()
    issued = int(time()) if now is None else now
    encoded = _encode(json.dumps([key, issued + ttl], ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    return f'{TICKET_PREFIX}{encoded}.{_signature(encoded, secret)}'


def open_object_ticket(ticket: str, *, secret: str, now: int | None = None) -> str:
    if not isinstance(ticket, str) or len(ticket) > _MAX_TICKET_LENGTH or not ticket.startswith(TICKET_PREFIX):
        raise InvalidObjectTicket()
    try:
        encoded, signature = ticket[len(TICKET_PREFIX):].split('.')
        if not hmac.compare_digest(signature, _signature(encoded, secret)):
            raise InvalidObjectTicket()
        raw = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True)
        claims = json.loads(raw)
        if not isinstance(claims, list) or len(claims) != 2:
            raise InvalidObjectTicket()
        key, expires = claims
        _validate_key(key)
        current = int(time()) if now is None else now
        if type(expires) is not int or not current < expires <= current + _MAX_TTL:
            raise InvalidObjectTicket()
        return key
    except (ValueError, TypeError):
        raise InvalidObjectTicket() from None


def object_ticket_url(base_url: str, ticket: str) -> str:
    return f"{base_url}/nb/v1/file/fetch?{urlencode({'presigned_url': ticket})}"


def issue_download_url(key: str, ttl: int = 86400, *, bucket: str | None = None) -> str:
    """Issue a link for an object already authorized by the caller."""
    from contracts.constants import environment

    if bucket and bucket != environment.MINIO_DEFAULT_BUCKET:
        raise InvalidObjectTicket()
    ticket = issue_object_ticket(key, ttl, secret=environment.JWT_SECRET)
    return object_ticket_url(environment.NORTHBOUND_EXTERNAL_URL, ticket)
