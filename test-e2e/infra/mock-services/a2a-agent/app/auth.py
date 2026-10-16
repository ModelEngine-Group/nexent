"""Deterministic API-key and JWT authentication used by the A2A mock."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True)
class AuthProfile:
    key: str
    modes: tuple[str, ...]
    hardware_id: str
    app_key: str | None = None


AUTH_PROFILES = {
    "basic": AuthProfile("basic", (), ""),
    "idkey": AuthProfile("idkey", ("appkey",), "hw-id-001", "hw-key-001"),
    "jwt": AuthProfile("jwt", ("jwt",), "hw-id-002"),
    "both": AuthProfile("both", ("appkey", "jwt"), "hw-id-003", "hw-key-003"),
}


class JwtService:
    def __init__(self, secret: str, issuer: str, ttl_seconds: int) -> None:
        self.secret = secret
        self.issuer = issuer
        self.ttl_seconds = ttl_seconds

    def issue(self, agent_key: str, hardware_id: str, ttl_seconds: int | None = None) -> str:
        now = int(time.time())
        ttl = self.ttl_seconds if ttl_seconds is None else ttl_seconds
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "sub": hardware_id,
            "aud": agent_key,
            "agent_key": agent_key,
            "iss": self.issuer,
            "iat": now,
            "nbf": now,
            "exp": now + ttl,
        }
        encoded_header = _encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        encoded_payload = _encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = hmac.new(
            self.secret.encode("utf-8"),
            f"{encoded_header}.{encoded_payload}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"{encoded_header}.{encoded_payload}.{_encode(signature)}"

    def verify(self, token: str, agent_key: str, hardware_id: str) -> bool:
        try:
            encoded_header, encoded_payload, encoded_signature = token.split(".")
            signed = f"{encoded_header}.{encoded_payload}".encode("ascii")
            expected = hmac.new(self.secret.encode("utf-8"), signed, hashlib.sha256).digest()
            if not hmac.compare_digest(_decode(encoded_signature), expected):
                return False
            header = json.loads(_decode(encoded_header))
            payload: dict[str, Any] = json.loads(_decode(encoded_payload))
            now = int(time.time())
            return (
                header.get("alg") == "HS256"
                and payload.get("iss") == self.issuer
                and payload.get("aud") == agent_key
                and payload.get("agent_key") == agent_key
                and payload.get("sub") == hardware_id
                and int(payload.get("nbf", now + 1)) <= now
                and int(payload.get("exp", 0)) > now
            )
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return False


def authenticate(profile: AuthProfile, headers: dict[str, str], jwt_service: JwtService) -> bool:
    if not profile.modes:
        return True
    hardware_id = headers.get("x-hw-id", "")
    if hardware_id != profile.hardware_id:
        return False
    if "appkey" in profile.modes and hmac.compare_digest(
        headers.get("x-hw-appkey", ""), profile.app_key or ""
    ):
        return True
    authorization = headers.get("authorization", "")
    if "jwt" in profile.modes and authorization.startswith("Bearer "):
        return jwt_service.verify(authorization[7:].strip(), profile.key, profile.hardware_id)
    return False


def security_contract(profile: AuthProfile) -> tuple[dict[str, object], list[dict[str, object]]]:
    if not profile.modes:
        return {}, []
    schemes: dict[str, object] = {
        "hwId": {
            "apiKeySecurityScheme": {
                "description": "Hardware identity required by every authentication mode.",
                "location": "header",
                "name": "X-HW-ID",
            }
        }
    }
    requirements: list[dict[str, object]] = []
    if "appkey" in profile.modes:
        schemes["hwAppKey"] = {
            "apiKeySecurityScheme": {
                "description": "Application key paired with X-HW-ID.",
                "location": "header",
                "name": "X-HW-APPKEY",
            }
        }
        requirements.append({"schemes": {"hwId": {"list": []}, "hwAppKey": {"list": []}}})
    if "jwt" in profile.modes:
        schemes["hwBearerJwt"] = {
            "httpAuthSecurityScheme": {
                "description": "Bearer JWT paired with X-HW-ID.",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            }
        }
        requirements.append({"schemes": {"hwId": {"list": []}, "hwBearerJwt": {"list": []}}})
    return schemes, requirements

