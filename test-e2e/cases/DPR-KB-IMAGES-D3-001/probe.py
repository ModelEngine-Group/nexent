# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real SDK KB image projection against owned HTTP and MinIO resources."""

import asyncio
import base64
import io
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

root = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(root), str(root / "backend"), str(root / "sdk")]

import boto3
import httpx
from aiohttp import web
from botocore.config import Config
from contracts.constants import environment
from nexent.core.agents.agent_model import ToolConfig
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager
from nexent.core.concurrency.cancellation import RunCancellationScope
from nexent.core.utils.observer import ProcessType
from PIL import Image
from runtime import knowledge_images
from runtime.images import WebImageFilter


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, stderr=subprocess.PIPE, timeout=20).strip()


def png(size):
    with Image.new("RGBA", (size, 200)) as image, io.BytesIO() as output:
        image.save(output, format="PNG")
        return output.getvalue()


def object_client(endpoint):
    return boto3.client("s3", endpoint_url=endpoint, aws_access_key_id="fixture-user",
                        aws_secret_access_key="fixture-password", region_name="us-east-1",
                        config=Config(retries={"total_max_attempts": 1}, proxies={"http": None, "https": None}))


async def scenario(endpoint):
    environment.MINIO_ENDPOINT = endpoint
    environment.MINIO_ACCESS_KEY = "fixture-user"
    environment.MINIO_SECRET_KEY = "fixture-password"
    environment.MINIO_DEFAULT_BUCKET = "kb-images"
    environment.MINIO_REGION = "us-east-1"
    large, small = png(200), png(199)
    own, foreign = "attachments/owner/a.png", "attachments/foreign/a.png"
    client = object_client(endpoint)
    try:
        client.create_bucket(Bucket="kb-images")
        client.put_bucket_versioning(Bucket="kb-images", VersioningConfiguration={"Status": "Enabled"})
        for key in (own, foreign):
            client.put_object(Bucket="kb-images", Key=key, Body=large, ContentType="image/png")
    finally:
        client.close()

    requests = Counter()

    async def image(request):
        name = request.match_info["name"]
        requests[name] += 1
        return web.Response(body={"large": large, "small": small}.get(name, b"not-image"))

    source = web.Application()
    source.router.add_get("/{name}", image)
    runner = web.AppRunner(source)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    base = "http://127.0.0.1:" + str(site._server.sockets[0].getsockname()[1])
    inline = "data:image/png;base64," + base64.b64encode(large).decode()
    urls = [base + "/large", base + "/small", "s3://kb-images/" + own,
            "s3://kb-images/" + foreign, inline, base + "/invalid", base + "/document-denied"]
    hits = [{"index": "kb", "score": 1, "document": {
        "title": "image-" + str(i), "filename": "sample.pdf", "source_type": "minio",
        "content": json.dumps({"image_url": url}), "process_source": "UniversalImageExtractor",
        "path_or_url": "approved" if i < 6 else "denied",
    }} for i, url in enumerate(urls)]
    searches, events, object_reads = [], [], []

    class Vectors:
        def accurate_search(self, **kwargs):
            searches.append(kwargs)
            return hits

    class Observer:
        def add_message(self, agent_name, process_type, content):
            events.append((process_type, content))

    actor = SimpleNamespace(user_id="owner", tenant_id="tenant")
    scope = RunCancellationScope()
    service = knowledge_images.KnowledgeImageFilter(actor, selector=WebImageFilter(enabled=False, model_path=None))
    config = ToolConfig(class_name="KnowledgeBaseSearchTool", name="knowledge_base_search", source="local",
                        params={"index_names": ["kb", "denied"], "search_mode": "accurate", "top_k": 10, "rerank": False},
                        metadata={"vdb_core": Vectors(), "allowed_index_names": ["kb"], "document_paths": ["approved"],
                                  "display_name_to_index_map": {"KB": "kb", "Denied": "denied"}, "image_filterer": service})
    owner = SimpleNamespace(observer=Observer(), cancellation_scope=scope)
    manager = ThreadManager(service_name="kb-image-proof", lane_policies={
        name: LanePolicy(name=name, max_workers=2, max_queue_size=4, queue_timeout_seconds=0,
                         cancel_grace_seconds=1, shutdown_grace_seconds=3)
        for name in ("model-tool-io", "control-io")
    })
    manager.start()
    original_read = knowledge_images.read_object_image

    def observed_object(url, **kwargs):
        object_reads.append((url, kwargs["role"]))
        return original_read(url, **kwargs)

    def exercise():
        tool = NexentAgent.create_local_tool(owner, config)
        result = json.loads(tool.forward("images", index_names=["KB", "Denied"]))
        assert not hasattr(tool, "data_process_service") and not hasattr(tool, "_filter_images")
        assert len(result["results"]) == 6
        assert [row["index"] for row in result["results"]] == [tool.tool_sign + str(i) for i in range(1, 7)]
        assert all(row["reference_mark"] == "[[" + row["index"] + "]]" for row in result["results"])
        assert "no read permission" in result["notice"] and "Denied" in result["notice"]
        assert tool.record_ops == 7

    try:
        with patch.object(knowledge_images, "read_object_image", observed_object):
            await manager.run("model-tool-io", ManagedTaskSpec(task_name="kb-images", owner="proof"), exercise)
        assert searches == [{"index_names": ["kb"], "query_text": "images", "top_k": 10}]
        pictures = [json.loads(content) for kind, content in events if kind == ProcessType.PICTURE_WEB]
        assert pictures == [{"images_url": [urls[0], urls[2], urls[4]]}]
        contents = [json.loads(content) for kind, content in events if kind == ProcessType.SEARCH_CONTENT]
        assert len(contents) == 1 and len(contents[0]) == 6
        assert [row["cite_index"] for row in contents[0]] == list(range(1, 7))
        assert all(row["url"] == "approved" and row["source_type"] == "file" for row in contents[0])
        assert requests == {"large": 1, "small": 1, "invalid": 1}
        assert object_reads == [(urls[2], "runtime")]
        assert not scope._closers
    finally:
        await runner.cleanup()
        drained = await manager.shutdown(timeout=3)
        assert not drained.stuck_execution_ids
    client = object_client(endpoint)
    try:
        assert {item["Key"] for item in client.list_objects_v2(Bucket="kb-images")["Contents"]} == {own, foreign}
        for key in (own, foreign):
            response = client.get_object(Bucket="kb-images", Key=key)
            with response["Body"] as stream:
                assert stream.read() == large
    finally:
        client.close()
    return {"sdk_projection": True, "owner_scope": True, "http_once": True,
            "source_preserved": True, "workers_reclaimed": True}


def main(run_id):
    assert len(run_id) == 32 and all(c in "0123456789abcdef" for c in run_id)
    name = "nexent-kb-images-" + run_id
    try:
        docker("image", "inspect", "quay.io/minio/minio:RELEASE.2023-12-20T01-00-02Z")
        docker("run", "--rm", "-d", "--name", name, "--label", "nexent.test_run=" + run_id,
               "-e", "MINIO_ROOT_USER=fixture-user", "-e", "MINIO_ROOT_PASSWORD=fixture-password",
               "-p", "127.0.0.1::9000", "quay.io/minio/minio:RELEASE.2023-12-20T01-00-02Z", "server", "/data")
        port = json.loads(docker("inspect", name))[0]["NetworkSettings"]["Ports"]["9000/tcp"][0]["HostPort"]
        endpoint = "http://127.0.0.1:" + port
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
        for container in docker("ps", "-aq", "--filter", "label=nexent.test_run=" + run_id).splitlines():
            docker("rm", "-f", "-v", container)
        assert not docker("ps", "-aq", "--filter", "label=nexent.test_run=" + run_id)
    evidence["owned_cleanup"] = True
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1])
