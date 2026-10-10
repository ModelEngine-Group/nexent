"""D3 real-provider model, voice, and image integration scenarios."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from d3.assets import asset_path, model_request, get_test_asset
from shared.cases import case_params
from shared.audio import stt_transport_audio
from shared.config import controlled_asset_url, load_secret_env, load_yaml, service_url
from shared.http import MODEL_TIMEOUT, assert_status, client, redacted_response_body
from shared.factories.tenant import isolated_accounts


MODEL_CASES = [
    "API-048", "API-049", "API-050", "API-051", "API-052", "API-053",
    "CTR-006", "CTR-007", "CTR-008", "CTR-009", "CTR-010", "CTR-011",
    "CTR-012", "CTR-013", "CTR-014", "CTR-015", "CTR-016", "CTR-017",
]


def _configured_types() -> list[str]:
    models = load_yaml("models.yaml").get("models", [])
    return [str(item.get("capability") or item.get("type") or item.get("model_type")) for item in models]


async def _models(identity) -> list[dict]:
    async with client("config", token=identity.access_token) as api:
        response = await api.get("/model/list")
    assert_status(response, 200)
    return response.json().get("data") or []


def _saved_model(models: list[dict], capability: str | None = None) -> dict:
    candidates = models
    if capability:
        candidates = [item for item in models if str(item.get("model_type", "")).lower() == capability]
    if not candidates:
        pytest.skip(f"deployed tenant has no saved {capability or ''} model")
    return candidates[0]


@asynccontextmanager
async def _temporary_model(identity, capability: str = "llm"):
    display_name = f"d3-{capability}-{uuid.uuid4().hex[:10]}"
    payload = model_request(capability, display_name=display_name)
    async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        created = await api.post("/model/create", json=payload)
    assert_status(created, 200)
    try:
        yield display_name, payload
    finally:
        async with client("config", token=identity.access_token) as api:
            deleted = await api.post("/model/delete", params={"display_name": display_name})
        assert_status(deleted, (200, 404))


async def _provider_core(identity) -> None:
    payload = model_request("llm")
    provider_request = {
        "provider": payload["model_factory"],
        "model_type": "llm",
        "api_key": payload["api_key"],
        "base_url": payload["base_url"],
    }
    async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        discovered = await api.post("/model/provider/create", json=provider_request)
        assert_status(discovered, 200)
        persisted = await api.post("/model/provider/list", json=provider_request)
        assert_status(persisted, 200)
        current = persisted.json().get("data") or []
        if current:
            authoritative = await api.post("/model/provider/batch_create", json={
                "api_key": payload["api_key"],
                "provider": payload["model_factory"],
                "type": "llm",
                "models": current,
            })
            assert_status(authoritative, 200)


async def _provider_core_isolated() -> None:
    async with isolated_accounts(["tenant_a_admin"]) as accounts:
        await _provider_core(accounts["tenant_a_admin"])


async def _provider_negative(identity) -> None:
    async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        blank = await api.post("/model/provider/create", json={
            "provider": "", "model_type": "llm", "api_key": "", "base_url": "not-a-url",
        })
        malformed = await api.post("/model/provider/batch_create", json={
            "api_key": "", "provider": "", "type": "llm", "models": [{"display_name": ""}],
        })
    assert blank.status_code in {400, 422, 502, 503}, (
        f"provider/create returned {blank.status_code}: {redacted_response_body(blank)}"
    )
    assert malformed.status_code in {400, 422}, (
        f"provider/batch_create returned {malformed.status_code}: {redacted_response_body(malformed)}"
    )


async def _model_crud(identity) -> None:
    available = [kind for kind in _configured_types() if kind and kind != "None"]
    assert available, "models.yaml must define at least one model capability"
    for capability in available:
        async with _temporary_model(identity, capability) as (name, payload):
            async with client("config", token=identity.access_token) as api:
                updated = await api.post(
                    "/model/update", params={"display_name": name},
                    # The stored key is intentionally omitted. Editing a model
                    # with a blank credential must retain the existing secret.
                    json={
                        "display_name": name,
                        "max_tokens": payload.get("max_tokens") or 1024,
                    },
                )
                assert_status(updated, 200)

                # Prove the omitted key was preserved before adding arbitrary
                # provider parameters that a real provider may intentionally
                # reject during connectivity.
                health = await api.post(
                    "/model/healthcheck",
                    params={"display_name": name, "model_type": capability},
                )
                assert_status(health, 200)
                assert health.json().get("data", {}).get("connectivity") is True

                nested_update = await api.post(
                    "/model/update", params={"display_name": name},
                    json={
                        "extra_params": {
                            "__custom__": {
                                "routing": {"region": "cn-beijing", "fallbacks": ["a", "b"]},
                                "flags": [True, False, None, 3],
                            }
                        },
                    },
                )
                assert_status(nested_update, 200)
                listed = await api.get("/model/list")
                assert_status(listed, 200)
                records = listed.json().get("data", [])
                record = next(item for item in records if item.get("display_name") == name)
                assert "api_key" not in record
                assert record.get("extra_params", {}).get("__custom__", {}).get("routing") == {
                    "region": "cn-beijing", "fallbacks": ["a", "b"],
                }



async def _model_negative(identity) -> None:
    async with _temporary_model(identity) as (name, payload):
        async with client("config", token=identity.access_token) as api:
            duplicate = await api.post("/model/create", json=payload)
            missing = await api.post(
                "/model/update", params={"display_name": "missing-model"}, json={"max_tokens": 1}
            )
            bad_delete = await api.post("/model/delete", params={"display_name": "missing-model"})
        assert_status(duplicate, 409)
        assert_status(missing, 404)
        assert_status(bad_delete, 404)
        assert payload["api_key"] not in duplicate.text
        assert "api_key" not in duplicate.text.lower()


async def _model_lists(identity) -> None:
    models = await _models(identity)
    async with client("config", token=identity.access_token) as api:
        llms = await api.get("/model/llm_list")
        coverage = await api.get("/model/capacity-coverage")
    assert_status(llms, 200)
    assert_status(coverage, 200)
    assert all(str(item.get("model_type", "")).lower() == "llm" for item in llms.json().get("data", []))
    assert isinstance(models, list)


async def _model_list_boundaries(identity) -> None:
    async with client("config") as anonymous:
        denied = await anonymous.get("/model/list")
    assert_status(denied, 401)
    async with client("config", token=identity.access_token) as api:
        invalid = await api.post("/model/provider/list", json={"provider": "x", "model_type": "unknown"})
    assert invalid.status_code in {200, 400, 422}, (
        f"provider/list returned {invalid.status_code}: {redacted_response_body(invalid)}"
    )
    if invalid.status_code == 200:
        assert invalid.json().get("data") == []


async def _saved_health(identity) -> None:
    for model in await _models(identity):
        display = model.get("display_name")
        capability = model.get("model_type")
        if not display or not capability:
            continue
        async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            response = await api.post(
                "/model/healthcheck", params={"display_name": display, "model_type": capability}
            )
        assert_status(response, 200)
        assert "data" in response.json()
        assert "api_key" not in response.text.lower()


async def _saved_health_negative(identity) -> None:
    async with client("config", token=identity.access_token) as api:
        missing = await api.post(
            "/model/healthcheck", params={"display_name": "not-present", "model_type": "llm"}
        )
        invalid = await api.post(
            "/model/healthcheck", params={"display_name": "not-present", "model_type": "unknown"}
        )
    assert_status(missing, 404)
    assert invalid.status_code in {400, 404}


async def _temporary_health(identity, *, valid: bool, timeout_case: bool = False) -> None:
    if valid:
        payload = model_request("llm", display_name=f"probe-{uuid.uuid4().hex[:8]}")
    else:
        payload = {
            "model_factory": "OpenAI-API-Compatible", "model_name": "missing",
            "model_type": "llm", "api_key": "invalid", "display_name": "temporary-invalid",
            "base_url": "http://10.255.255.1:9" if timeout_case else "not-a-url",
        }
    async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        response = await api.post("/model/temporary_healthcheck", json=payload)
    if valid:
        assert_status(response, 200)
        assert response.json()["data"]["connectivity"] is True
        assert payload["api_key"] not in response.text
    else:
        if response.status_code == 200:
            assert response.json().get("data", {}).get("connectivity") is False
        else:
            assert response.status_code in ({502, 503, 504} if timeout_case else {400, 422})
        assert payload["api_key"] not in response.text


def _voice_ws_url(kind: str) -> str:
    base = service_url("runtime")
    websocket_base = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    return websocket_base + f"/voice/{kind}/ws"


def _ws_exchange(
    kind: str,
    config: dict,
    binary: bytes | None = None,
    expected_text_markers: list[str] | None = None,
) -> list[object]:
    import websocket

    deadline = time.monotonic() + 60
    ws = websocket.create_connection(_voice_ws_url(kind), timeout=10)
    events: list[object] = []
    try:
        ws.send(json.dumps(config))
        if binary is not None:
            while time.monotonic() < deadline:
                ws.settimeout(min(10, deadline - time.monotonic()))
                ready = ws.recv()
                events.append(ready)
                if "ready" in str(ready).lower():
                    break
                if "error" in str(ready).lower():
                    return events
            else:
                raise AssertionError(f"{kind} websocket did not become ready within 60 seconds")
            for offset in range(0, len(binary), 3200):
                ws.send_binary(binary[offset:offset + 3200])
                # 3,200 bytes is 100 ms at 16 kHz mono PCM16.  Send in real
                # time so provider VAD does not truncate the deterministic
                # utterance before its final numeric marker.
                time.sleep(0.10)
            if kind == "stt":
                # The Qwen-Audio realtime model uses server VAD. A finite PCM
                # fixture must include trailing silence so it can close the
                # utterance and emit the final transcription event.
                for _ in range(25):
                    ws.send_binary(bytes(3200))
                    time.sleep(0.10)
        # Realtime STT emits one interim frame per partial hypothesis.  A
        # short fixed utterance can legitimately exceed twenty frames before
        # the final marker, so bound by the deadline instead of frame count.
        for _ in range(200):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(f"{kind} websocket did not reach a terminal event within 60 seconds")
            ws.settimeout(min(10, remaining))
            try:
                value = ws.recv()
            except websocket.WebSocketTimeoutException:
                if time.monotonic() >= deadline:
                    # Browser STT consumes interim text and closes from the
                    # client side; the server does not guarantee a final
                    # frame.  Preserve received frames so the content oracle,
                    # rather than a missing terminal event, decides the case.
                    if kind == "stt" and len(events) > 1:
                        break
                    raise AssertionError(f"{kind} websocket did not reach a terminal event within 60 seconds")
                continue
            except websocket.WebSocketConnectionClosedException as exc:
                raise AssertionError(
                    f"{kind} websocket closed before a terminal transcription; "
                    f"received={events!r}"
                ) from exc
            events.append(value)
            lowered = str(value).lower()
            if isinstance(value, str) and (
                "completed" in lowered or "error" in lowered or '"is_final": true' in lowered
            ):
                break
            # Interim hypotheses can already contain every keyword before the
            # provider emits its final transcript. Keep reading through the
            # terminal frame so the oracle cannot pass on provisional text.
    finally:
        ws.close()
    return events


async def _stt_core() -> None:
    audio_path = asset_path("audio", "stt_wav")
    oracle = json.loads(asset_path("audio", "stt_expected").read_text(encoding="utf-8"))
    keywords = [str(value) for value in oracle.get("required_keywords") or []]
    assert keywords, "STT oracle must define required_keywords"
    config = model_request("stt")
    events = await asyncio.to_thread(
        _ws_exchange, "stt", config, stt_transport_audio(audio_path), keywords
    )
    assert events and not any("error" in str(item).lower() for item in events)
    final_texts = [
        str(event.get("text") or "")
        for raw in events
        if isinstance(raw, str)
        for event in [json.loads(raw)]
        if isinstance(event, dict) and event.get("is_final") is True
    ]
    assert final_texts, f"STT returned no final transcription: {events}"
    transcript = " ".join(final_texts)
    normalized = transcript.translate(str.maketrans("零一二三四五六七八九", "0123456789"))
    assert all(keyword in normalized for keyword in keywords), (
        f"STT final transcript did not contain required keywords {keywords}: {transcript}"
    )


async def _stt_error() -> None:
    events = await asyncio.to_thread(_ws_exchange, "stt", {"model_name": "missing"}, b"invalid-audio")
    assert any("error" in str(item).lower() for item in events)


async def _tts_core() -> None:
    config = model_request("tts")
    config["text"] = "D3 text to speech connectivity check."
    events = await asyncio.to_thread(_ws_exchange, "tts", config)
    assert any(isinstance(item, bytes) and item for item in events)
    assert any("completed" in str(item) for item in events)


async def _tts_error() -> None:
    events = await asyncio.to_thread(_ws_exchange, "tts", {"text": "test", "model_name": "missing"})
    assert any("error" in str(item).lower() for item in events)


async def _image_proxy(valid: bool) -> None:
    url = controlled_asset_url(str(get_test_asset("images", "remote_path"))) if valid else "http://127.0.0.1:9/unavailable.png"
    async with client("config", timeout=MODEL_TIMEOUT) as api:
        response = await api.get("/image", params={"url": url, "format": "json"})
        streamed = await api.get("/image", params={"url": url, "format": "stream"})
    if valid:
        assert_status(response, 200)
        assert response.json()["success"] is True and response.json().get("base64")
        assert_status(streamed, 200)
        assert streamed.headers["content-type"].startswith("image/")
    else:
        assert_status(response, 200)
        assert response.json()["success"] is False
        assert_status(streamed, 502)


@pytest.mark.asyncio
async def execute_model_and_multimodal_scenario(case: dict, tenant_a_admin, tenant_a_user) -> None:
    case_id = case["id"]
    handlers = {
        "API-048": _provider_core_isolated,
        "API-049": lambda: _provider_negative(tenant_a_admin),
        "API-050": lambda: _model_crud(tenant_a_admin),
        "API-051": lambda: _model_negative(tenant_a_admin),
        "API-052": lambda: _model_lists(tenant_a_admin),
        "API-053": lambda: _model_list_boundaries(tenant_a_admin),
        "CTR-006": lambda: _saved_health(tenant_a_admin),
        "CTR-007": lambda: _saved_health_negative(tenant_a_admin),
        "CTR-008": lambda: _temporary_health(tenant_a_user, valid=False, timeout_case=True),
        "CTR-009": lambda: _temporary_health(tenant_a_user, valid=True),
        "CTR-010": lambda: _temporary_health(tenant_a_user, valid=False),
        "CTR-011": lambda: _temporary_health(tenant_a_user, valid=False, timeout_case=True),
        "CTR-012": _stt_core,
        "CTR-013": _stt_error,
        "CTR-014": _tts_core,
        "CTR-015": _tts_error,
        "CTR-016": lambda: _image_proxy(True),
        "CTR-017": lambda: _image_proxy(False),
    }
    await handlers[case_id]()
