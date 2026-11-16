# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Actual HTTP source, Management route and ObjectStore against owned MinIO."""

import asyncio
import base64
import io
import json
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

root = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(root), str(root / "backend"), str(root / "sdk")]

import aiohttp
import boto3
import httpx
from aiohttp import web
from botocore.config import Config
from contracts.constants import environment
from fastapi import FastAPI
from management.api.file import image as image_api
from management.services.file import image_proxy
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    set_default_thread_manager,
)
from PIL import Image


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, stderr=subprocess.PIPE, timeout=20).strip()


def png(mode):
    with Image.new(mode, (8, 8)) as image, io.BytesIO() as output:
        image.save(output, format="PNG")
        return output.getvalue()


async def scenario(endpoint):
    environment.MINIO_ENDPOINT = endpoint
    environment.MINIO_ACCESS_KEY = "fixture-user"
    environment.MINIO_SECRET_KEY = "fixture-password"
    environment.MINIO_DEFAULT_BUCKET = "image-probe"
    environment.MINIO_REGION = "us-east-1"
    environment.AIDP_SERVER_URL = ""
    client = boto3.client(
        "s3", endpoint_url=endpoint, aws_access_key_id="fixture-user",
        aws_secret_access_key="fixture-password", region_name="us-east-1",
        config=Config(retries={"total_max_attempts": 1}, proxies={"http": None, "https": None}),
    )
    rgb, rgba = png("RGB"), png("RGBA")
    own, foreign = "attachments/owner/a.png", "attachments/foreign/a.png"
    try:
        client.create_bucket(Bucket="image-probe")
        client.put_bucket_versioning(Bucket="image-probe", VersioningConfiguration={"Status": "Enabled"})
        for key in (own, foreign):
            client.put_object(Bucket="image-probe", Key=key, Body=rgb, ContentType="image/png")
    finally:
        client.close()

    manager = ThreadManager(service_name="image-proof", lane_policies={
        "control-io": LanePolicy(name="control-io", max_workers=2, max_queue_size=2,
                                 queue_timeout_seconds=0, cancel_grace_seconds=1, shutdown_grace_seconds=3),
    })
    manager.start()
    set_default_thread_manager(manager)
    queries = []

    async def source(request):
        queries.append(dict(request.query))
        return web.Response(body={"rgb": rgb, "rgba": rgba}.get(request.match_info["kind"], b"invalid"))

    source_app = web.Application()
    source_app.router.add_get("/{kind}", source)
    runner = web.AppRunner(source_app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    app = FastAPI()
    app.include_router(image_api.router)
    network = []
    original_request = aiohttp.ClientSession._request

    async def observed_request(session, method, url, **kwargs):
        network.append(str(url))
        assert not urlsplit(str(url)).path.startswith("/tasks/"), "Retired data-process request"
        return await original_request(session, method, url, **kwargs)

    try:
        # The controlled source is loopback; select the external-source branch only.
        # Actual source HTTP and object operations remain production implementations.
        with patch.object(image_proxy, "_validate_loopback_url", return_value=None), patch.object(
            image_api, "get_current_user_id", return_value=("owner", "tenant"),
        ), patch.object(aiohttp.ClientSession, "_request", observed_request):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://management") as api:
                for kind, expected in (("rgb", "PNG"), ("rgba", "JPEG")):
                    url = f"http://127.0.0.1:{port}/{kind}?first=one&second=two"
                    response = await api.get("/image", params={"url": url})
                    payload = response.json()
                    assert response.status_code == 200 and payload["success"], payload
                    raw = base64.b64decode(payload["base64"])
                    with Image.open(io.BytesIO(raw)) as decoded:
                        assert decoded.mode == "RGB" and decoded.format == expected
                        if kind == "rgba":
                            assert decoded.getpixel((0, 0)) == (255, 255, 255)
                    streamed = await api.get("/image", params={"url": url, "format": "stream"})
                    assert streamed.status_code == 200 and streamed.content == raw
                    assert streamed.headers["content-type"] == "image/" + expected.lower()
                    assert streamed.headers["cache-control"] == "public, max-age=3600"
                for url in ("s3://image-probe/" + own, "data:image/png;base64," + base64.b64encode(rgb).decode()):
                    payload = (await api.get("/image", params={"url": url})).json()
                    assert payload["success"] and base64.b64decode(payload["base64"]) == rgb
                for url in ("s3://image-probe/" + foreign, f"http://127.0.0.1:{port}/invalid", "/private/data-process/a.png"):
                    response = await api.get("/image", params={"url": url})
                    assert response.status_code == 200
                    assert response.json() == {"success": False, "error": "Failed to fetch image"}
        assert queries[:4] == [{"first": "one", "second": "two"}] * 4
        assert queries[4:] == [{}]
        assert len(network) == 5
        assert all(urlsplit(url).path in {"/rgb", "/rgba", "/invalid"} for url in network)
        return {"http_formats": True, "query_preserved": True, "s3_and_inline": True,
                "foreign_denied": True, "invalid_denied": True,
                "no_data_process": all(not urlsplit(url).path.startswith("/tasks/") for url in network)}
    finally:
        await runner.cleanup()
        result = await manager.shutdown(timeout=3)
        clear_default_thread_manager(manager)
        assert not result.stuck_execution_ids


def main(run_id):
    assert len(run_id) == 32 and all(c in "0123456789abcdef" for c in run_id)
    name = "nexent-image-proof-" + run_id
    try:
        docker("image", "inspect", "quay.io/minio/minio:RELEASE.2023-12-20T01-00-02Z")
        docker("run", "--rm", "-d", "--name", name, "--label", "nexent.test_run=" + run_id,
               "-e", "MINIO_ROOT_USER=fixture-user", "-e", "MINIO_ROOT_PASSWORD=fixture-password",
               "-p", "127.0.0.1::9000", "quay.io/minio/minio:RELEASE.2023-12-20T01-00-02Z", "server", "/data")
        mapping = json.loads(docker("inspect", name))[0]["NetworkSettings"]["Ports"]["9000/tcp"][0]["HostPort"]
        endpoint = "http://127.0.0.1:" + mapping
        deadline = time.monotonic() + 25
        with httpx.Client(trust_env=False, timeout=1) as health:
            while True:
                try:
                    if health.get(endpoint + "/minio/health/ready").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                assert time.monotonic() < deadline, "Owned MinIO startup exceeded deadline"
                time.sleep(0.1)
        evidence = asyncio.run(scenario(endpoint))
    finally:
        matches = docker("ps", "-aq", "--filter", "label=nexent.test_run=" + run_id)
        for container in matches.splitlines():
            docker("rm", "-f", "-v", container)
        assert not docker("ps", "-aq", "--filter", "label=nexent.test_run=" + run_id)
    evidence["owned_cleanup"] = True
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1])
