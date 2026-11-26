# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Owned voice protocol double and deterministic WebSocket relay for Runtime scaling."""

import asyncio
import base64
from ipaddress import ip_address
import sys
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from aiohttp import ClientSession, WSMsgType, web
from yarl import URL


VARIANTS = {"first": "producer", "second": "peer"}
KINDS = {"stt", "tts"}
HOP_HEADERS = {"connection", "host", "upgrade", "proxy-connection", "keep-alive", "transfer-encoding"}


def audio_markers(token, kind, turn):
    return [f"voice-{kind}:{token}:{turn}:{index}\0".encode() for index in (1, 2)]


def text_marker(token, kind, turn, index):
    return f"语音-{kind}:{token}:{turn}:{index}"


def direct_origin(origin):
    url = urlsplit(origin)
    if (url.scheme != "http" or url.username or url.password or url.path or url.query or url.fragment
            or not url.port or ip_address(url.hostname).is_unspecified):
        raise ValueError("Expected a direct HTTP address of an owned Runtime Pod")
    return origin.replace("http://", "ws://", 1)


async def receive_json(socket):
    return await socket.receive_json(timeout=12)


async def serve_stt(socket, token, turn, record):
    await socket.send_json({"type": "session.created", "session": {"id": record["session"]}})
    update = await receive_json(socket)
    assert update["type"] == "session.update" and update["session"]["input_audio_format"] == "pcm"
    assert update["session"]["sample_rate"] == 16000
    await socket.send_json({"type": "session.updated"})
    for index, audio in enumerate(audio_markers(token, "stt", turn), start=1):
        appended = await receive_json(socket)
        assert appended["type"] == "input_audio_buffer.append"
        assert base64.b64decode(appended["audio"], validate=True) == audio
        record["frames"] += 1
        kind = "text" if index == 1 else "completed"
        await socket.send_json({"type": f"conversation.item.input_audio_transcription.{kind}",
                                "text": text_marker(token, "stt", turn, index)})


async def serve_tts(socket, token, turn, record):
    started = await receive_json(socket)
    header = started["header"]
    assert header["action"] == "run-task" and started["payload"]["model"] == "cosyvoice-v2"
    task_id = UUID(hex=header["task_id"]).hex
    record["session"] = task_id
    await socket.send_json({"header": {"event": "task-started", "task_id": task_id}})
    continued = await receive_json(socket)
    assert continued["header"]["action"] == "continue-task" and continued["header"]["task_id"] == task_id
    assert continued["payload"]["input"]["text"] == text_marker(token, "tts", turn, 1)
    finished = await receive_json(socket)
    assert finished["header"]["action"] == "finish-task" and finished["header"]["task_id"] == task_id
    for audio in audio_markers(token, "tts", turn):
        await socket.send_bytes(audio)
        record["frames"] += 1
    await socket.send_json({"header": {"event": "task-finished", "task_id": task_id}})


async def pump(source, destination):
    while True:
        frame = await source.receive()
        if frame.type == WSMsgType.TEXT:
            await destination.send_str(frame.data)
        elif frame.type == WSMsgType.BINARY:
            await destination.send_bytes(frame.data)
        elif frame.type in {WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED}:
            return source.close_code
        elif frame.type == WSMsgType.ERROR:
            raise RuntimeError("Case-owned voice WebSocket transport failed")


def voice_app(token, first_origin, peer_origin):
    if UUID(hex=token).hex != token:
        raise ValueError("Expected the owned Runtime scaling run ID")
    origins = {"producer": direct_origin(first_origin), "peer": direct_origin(peer_origin)}
    if len(set(origins.values())) != 2:
        raise ValueError("The voice fixture requires distinct Runtime destinations")
    routes, providers = {}, {}
    client = None

    async def session(_app):
        nonlocal client
        async with ClientSession(trust_env=False) as session_client:
            client = session_client
            yield

    async def probe(request):
        if request.remote not in {"127.0.0.1", "::1"}:
            raise web.HTTPNotFound()
        return web.json_response({"routes": routes, "providers": providers})

    async def provider(request):
        kind, turn = request.match_info["kind"], request.match_info["turn"]
        if kind not in KINDS or turn not in VARIANTS or request.headers.get("Authorization") != f"Bearer {token}":
            raise web.HTTPNotFound()
        tag = f"{kind}-{turn}"
        record = providers.setdefault(tag, {"attempts": 0, "remote": request.remote, "frames": 0, "closed": False,
                                            "session": uuid4().hex})
        record["attempts"] += 1
        if record["attempts"] != 1:
            raise web.HTTPConflict()
        socket = web.WebSocketResponse(max_msg_size=8192)
        await socket.prepare(request)
        try:
            async with asyncio.timeout(25):
                if kind == "stt":
                    await serve_stt(socket, token, turn, record)
                else:
                    await serve_tts(socket, token, turn, record)
                frame = await socket.receive()
                assert frame.type == WSMsgType.CLOSE and frame.data == 1000
                record["closed"] = True
        finally:
            await socket.close()
        return socket

    async def relay(request):
        kind, marker = request.match_info["kind"], request.query.get("runtime_voice_probe", "")
        owner, _, turn = marker.partition(":")
        if kind not in KINDS or owner != token or turn not in VARIANTS:
            raise web.HTTPNotFound()
        tag = f"{kind}-{turn}"
        target = VARIANTS[turn]
        upstream_url = URL(origins[target] + request.raw_path, encoded=True)
        record = routes.setdefault(tag, {"attempts": 0, "target": target, "origin": origins[target], "closed": False})
        record["attempts"] += 1
        if record["attempts"] != 1:
            raise web.HTTPConflict()
        headers = [(name, value) for name, value in request.headers.items()
                   if name.lower() not in HOP_HEADERS and not name.lower().startswith("sec-websocket-")]
        async with client.ws_connect(upstream_url, headers=headers, max_msg_size=8192) as upstream:
            peer_ip, peer_port, *_ = upstream.get_extra_info("peername")
            assert ip_address(peer_ip) == ip_address(upstream_url.host) and peer_port == upstream_url.port
            record["runtime_peer"] = [str(ip_address(peer_ip)), peer_port]
            downstream = web.WebSocketResponse(max_msg_size=8192)
            await downstream.prepare(request)
            tasks = [asyncio.create_task(pump(*sockets)) for sockets in ((downstream, upstream), (upstream, downstream))]
            try:
                done, _ = await asyncio.wait(tasks, timeout=35, return_when=asyncio.FIRST_COMPLETED)
                assert done, "Case-owned voice connection did not close"
                codes = {task.result() for task in done}
                assert codes == {1000}, f"Unexpected voice close codes: {codes}"
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await upstream.close()
                await downstream.close()
            record["closed"] = True
        return downstream

    app = web.Application()
    app.cleanup_ctx.append(session)
    app.router.add_get("/test-relay/ready", ready)
    app.router.add_get("/test-relay/probe", probe)
    app.router.add_get("/test-voice/{kind}/{turn}", provider)
    app.router.add_get("/api/voice/{kind}/ws", relay)
    return app


async def ready(_request):
    return web.json_response({"ready": True})


if __name__ == "__main__":
    run_token, producer, peer, port, mode = sys.argv[1:]
    if mode != "voice":
        raise ValueError("Unsupported voice fixture mode")
    web.run_app(voice_app(run_token, producer, peer), port=int(port), access_log=None)
