"""Opaque, Agent-scoped Tokens for login-gated share links."""

import base64
import binascii
import hashlib
import hmac
import uuid
from dataclasses import dataclass

_TOKEN_DOMAIN = b"nexent.agent-share.v1"


@dataclass(frozen=True)
class AgentShareTokenPayload:
    public_share_id: str
    generation: int


def _signature_payload(public_share_id: str, generation: int, nonce: str) -> bytes:
    return b"\x00".join(
        (
            _TOKEN_DOMAIN,
            public_share_id.encode("ascii"),
            str(generation).encode("ascii"),
            nonce.encode("utf-8"),
        )
    )


def _encode_signature(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def build_agent_share_token(
    *,
    public_share_id: str,
    generation: int,
    nonce: str,
    secret: str,
) -> str:
    """Build a stable Token for the current share generation."""
    if not secret:
        raise ValueError("Agent share Token secret is not configured")
    if generation <= 0:
        raise ValueError("Agent share Token generation must be positive")

    canonical_public_share_id = str(uuid.UUID(public_share_id))
    signature = _encode_signature(
        _signature_payload(canonical_public_share_id, generation, nonce), secret
    )
    return f"{canonical_public_share_id}.{generation}.{signature}"


def parse_agent_share_token(
    token: str,
    *,
    nonce: str,
    secret: str,
) -> AgentShareTokenPayload | None:
    """Return a verified Token payload, or ``None`` for any invalid Token."""
    if not secret:
        return None

    parts = token.split(".")
    if len(parts) != 3:
        return None

    public_share_id, generation_text, supplied_signature = parts
    try:
        canonical_public_share_id = str(uuid.UUID(public_share_id))
        generation = int(generation_text)
        base64.urlsafe_b64decode(
            supplied_signature + "=" * (-len(supplied_signature) % 4)
        )
    except (ValueError, AttributeError, binascii.Error):
        return None

    if generation <= 0 or canonical_public_share_id != public_share_id:
        return None

    expected_signature = _encode_signature(
        _signature_payload(canonical_public_share_id, generation, nonce), secret
    )
    if not hmac.compare_digest(supplied_signature, expected_signature):
        return None

    return AgentShareTokenPayload(
        public_share_id=canonical_public_share_id,
        generation=generation,
    )
