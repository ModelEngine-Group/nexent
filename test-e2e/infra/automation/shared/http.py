from __future__ import annotations

import json
import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from .config import service_url


DEFAULT_TIMEOUT = httpx.Timeout(30, connect=10)
MODEL_TIMEOUT = httpx.Timeout(300, connect=15)

_SENSITIVE_KEY_PARTS = ("password", "token", "apikey", "accesskey", "authorization", "secret")


def _redact(value: Any, key: str = "") -> Any:
    normalized_key = re.sub(r"[^a-z0-9]", "", key.lower())
    if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
        return "***"
    if isinstance(value, dict):
        return {str(child_key): _redact(child, str(child_key)) for child_key, child in value.items()}
    if isinstance(value, list):
        return [_redact(child) for child in value]
    return value


def redacted_response_body(response: httpx.Response, limit: int = 1000) -> str:
    if not response.is_closed:
        return "<streaming response body not read>"
    try:
        return json.dumps(_redact(response.json()), ensure_ascii=False)[:limit]
    except Exception:
        text = response.text
        text = re.sub(r"(?i)bearer\s+[a-z0-9._~+/=-]+", "Bearer ***", text)
        text = re.sub(r"nexent-[a-z0-9]+", "nexent-***", text, flags=re.IGNORECASE)
        return text[:limit]


def client(service: str, token: str | None = None, api_key: str | None = None, **kwargs: Any) -> httpx.AsyncClient:
    from .deployment_guard import assert_service_available
    assert_service_available(service)
    headers = dict(kwargs.pop("headers", {}))
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if api_key:
        # The Northbound API authenticates access keys with the standard
        # Bearer scheme (see northbound_app._get_northbound_context).
        headers["Authorization"] = f"Bearer {api_key}"
    base_url = service_url(service)
    host = urlsplit(base_url).hostname or ""
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower().rstrip(".") == "localhost"
    return httpx.AsyncClient(
        base_url=base_url,
        headers=headers,
        timeout=kwargs.pop("timeout", DEFAULT_TIMEOUT),
        follow_redirects=kwargs.pop("follow_redirects", False),
        trust_env=kwargs.pop("trust_env", not loopback),
        **kwargs,
    )


def assert_status(response: httpx.Response, expected: int | tuple[int, ...]) -> None:
    allowed = (expected,) if isinstance(expected, int) else expected
    assert response.status_code in allowed, (
        f"{response.request.method} {response.request.url}: expected {allowed}, "
        f"got {response.status_code}; body={redacted_response_body(response)!r}"
    )


def assert_no_server_error(response: httpx.Response) -> None:
    assert response.status_code < 500, (
        f"unexpected server error {response.status_code} for "
        f"{response.request.method} {response.request.url}: {redacted_response_body(response)!r}"
    )


def response_message(response: httpx.Response) -> str:
    """Return the semantic error across the service response wrappers."""
    try:
        body = response.json()
    except Exception:
        return response.text
    if not isinstance(body, dict):
        return str(body)
    value = body.get("detail")
    if isinstance(value, dict):
        value = value.get("message") or value.get("detail") or value
    if value in (None, ""):
        value = body.get("message")
    return value if isinstance(value, str) else str(value or "")


def config_save_payload(loaded: dict[str, Any]) -> dict[str, Any]:
    """Translate load_config's UI shape into the current GlobalConfig request."""
    config = loaded.get("config") if isinstance(loaded.get("config"), dict) else loaded
    app = config.get("app") or {}
    icon = app.get("icon") if isinstance(app.get("icon"), dict) else {}
    def model_payload(value: Any, *, speech: bool = False) -> dict[str, Any]:
        source = value if isinstance(value, dict) else {}
        api = source.get("apiConfig") if isinstance(source.get("apiConfig"), dict) else {}
        result = {
            "modelName": source.get("modelName") or source.get("name") or "",
            "displayName": source.get("displayName") or source.get("display_name") or source.get("name") or "",
            "apiConfig": {
                "apiKey": api.get("apiKey") or api.get("api_key") or "",
                "modelUrl": api.get("modelUrl") or api.get("model_url") or "",
            },
        }
        if source.get("dimension") is not None:
            result["dimension"] = source["dimension"]
        if speech:
            result.update({
                "modelFactory": source.get("modelFactory") or source.get("model_factory"),
                "modelAppid": source.get("modelAppid") or source.get("model_appid"),
                "accessToken": source.get("accessToken") or source.get("access_token"),
            })
        return result

    models = config.get("models") if isinstance(config.get("models"), dict) else {}
    return {
        "app": {
            "appName": app.get("appName") or app.get("name") or "Nexent",
            "appDescription": app.get("appDescription") or app.get("description") or "",
            "iconType": app.get("iconType") or icon.get("type") or "preset",
            "iconKey": app.get("iconKey") or icon.get("iconKey") or "search",
            "customIconUrl": app.get("customIconUrl") or icon.get("customUrl"),
            "avatarUri": app.get("avatarUri") or icon.get("avatarUri"),
            "modelEngineEnabled": bool(app.get("modelEngineEnabled", False)),
            "datamateUrl": app.get("datamateUrl") or "",
        },
        "models": {
            "llm": model_payload(models.get("llm")),
            "embedding": model_payload(models.get("embedding")),
            "multiEmbedding": model_payload(models.get("multiEmbedding")),
            "rerank": model_payload(models.get("rerank")),
            "vlm": model_payload(models.get("vlm")),
            "vlm2": model_payload(models.get("vlm2")),
            "vlm3": model_payload(models.get("vlm3")),
            "vlm4": model_payload(models.get("vlm4")),
            "stt": model_payload(models.get("stt"), speech=True),
            "tts": model_payload(models.get("tts"), speech=True),
        },
    }
