# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise the existing STT and TTS WebSocket contracts through the stable Web entrance."""

import json
from ipaddress import ip_address
from urllib.parse import urlsplit

import httpx
from websockets.exceptions import ConnectionClosedOK, InvalidStatus
from websockets.sync.client import connect

from shared.runtime_scaling_admission import wait_for
from shared.runtime_scaling_attachments import sign_in
from shared.runtime_scaling_voice_fixture import VARIANTS, audio_markers, text_marker


def voice_path(web_url, token, kind, turn):
    return f"{web_url.replace('http://', 'ws://', 1)}/api/voice/{kind}/ws?runtime_voice_probe={token}:{turn}"


def receive_text_event(socket, timeout):
    message = socket.recv(timeout)
    assert isinstance(message, str), "The voice status or transcript must be a WebSocket text frame"
    return json.loads(message)


def exchange_stt(socket, token, turn, timeout):
    assert receive_text_event(socket, timeout) == {"status": "ready"}
    for index, audio in enumerate(audio_markers(token, "stt", turn), start=1):
        socket.send(audio)
        assert receive_text_event(socket, timeout) == {
            "text": text_marker(token, "stt", turn, index), "is_final": index == 2,
        }
    socket.close(code=1000)


def exchange_tts(socket, token, turn, timeout):
    for audio in audio_markers(token, "tts", turn):
        assert socket.recv(timeout) == audio
    assert receive_text_event(socket, timeout) == {"status": "completed"}
    try:
        socket.recv(timeout)
    except ConnectionClosedOK:
        assert socket.close_code == 1000
    else:
        raise AssertionError("TTS emitted another frame instead of closing normally")


def exercise_public_voice(web_url, gateway_url, provider_url, identity, token, *, transport, origins,
                          wait_seconds, assert_pod_ips=False):
    with httpx.Client(base_url=gateway_url, timeout=10, trust_env=False) as gateway:
        authorization = sign_in(gateway, identity)["Authorization"]
    headers = {"Cookie": f"nexent_access_token={authorization.removeprefix('Bearer ')}"}
    settings = {"proxy": None, "open_timeout": 10, "close_timeout": 5, "max_size": 8192}
    assert transport("probe") == {"routes": {}, "providers": {}}
    try:
        with connect(voice_path(web_url, token, "stt", "first"), **settings):
            raise AssertionError("Anonymous voice request received a WebSocket upgrade")
    except InvalidStatus as rejected:
        assert rejected.response.status_code == 403
    assert transport("probe") == {"routes": {}, "providers": {}}, "Denied upgrade reached a Runtime or provider"

    evidence = {}
    for kind, exchange in (("stt", exchange_stt), ("tts", exchange_tts)):
        for turn, target in VARIANTS.items():
            tag = f"{kind}-{turn}"
            config = {"model_factory": "dashscope", "api_key": token,
                      "base_url": f"{provider_url}/test-voice/{kind}/{turn}"}
            if kind == "tts":
                config.update(model_name="cosyvoice-v2", text=text_marker(token, kind, turn, 1))
            with connect(voice_path(web_url, token, kind, turn), additional_headers=headers, **settings) as socket:
                assert socket.response.status_code == 101
                socket.send(json.dumps(config))
                exchange(socket, token, turn, min(wait_seconds, 12))
                assert socket.close_code == 1000

            def closed():
                trace = transport("probe")
                return trace["routes"].get(tag, {}).get("closed") and trace["providers"].get(tag, {}).get("closed")

            wait_for(closed, wait_seconds, f"The {tag} upstream and provider sessions did not both close")
            trace = transport("probe")
            origin = origins[target]
            address = urlsplit(origin)
            assert trace["routes"][tag] == {"attempts": 1, "target": target, "origin": origin.replace("http://", "ws://", 1),
                                           "runtime_peer": [str(ip_address(address.hostname)), address.port], "closed": True}
            provider = trace["providers"][tag]
            assert (provider["attempts"], provider["frames"], provider["closed"]) == (1, 2, True)
            if assert_pod_ips:
                assert ip_address(provider["remote"]) == ip_address(address.hostname)
            assert provider["session"] and provider["session"] not in {item["session"] for item in evidence.values()}
            evidence[tag] = {"session": provider["session"], "runtime": origin, "provider_peer": provider["remote"],
                             "frames": provider["frames"], "closed": True}
    final = transport("probe")
    assert set(final["routes"]) == set(final["providers"]) == set(evidence)
    assert all(record["attempts"] == 1 and record["closed"] for records in final.values() for record in records.values())
    return {"anonymous_upgrade_rejected": True, "sessions": evidence}
