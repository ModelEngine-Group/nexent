# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real KB image projection over signed content grants and owned MinIO objects."""

import asyncio
import hashlib
import io
import json
import socket
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
import uvicorn
from botocore.config import Config
from contracts.agentos_knowledge import (
    KnowledgeContentGrant,
    KnowledgeContentRequest,
    ObjectReference,
)
from contracts.constants import environment
from fastapi import FastAPI
from management.api.knowledge_base.agentos_authorization import (
    create_knowledge_authorization_router,
)
from nexent.core.agents.agent_model import ToolConfig
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager
from nexent.core.concurrency.cancellation import RunCancellationScope
from nexent.core.utils.observer import ProcessType
from nexent.storage.errors import ScopeDenied
from PIL import Image
from runtime.images import WebImageFilter
from runtime.knowledge_base import content
from runtime.knowledge_images import KnowledgeImageFilter

from infrastructure.agentos_client import AgentOSClient
from infrastructure.agentos_identity import ServicePrincipal


def docker(*args):
    return subprocess.check_output(
        ["docker", *args], text=True, stderr=subprocess.PIPE, timeout=20
    ).strip()


def png(size):
    with Image.new("RGBA", (size, 200)) as image, io.BytesIO() as output:
        image.save(output, format="PNG")
        return output.getvalue()


def object_client(endpoint):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id="fixture-user",
        aws_secret_access_key="fixture-password",
        region_name="us-east-1",
        config=Config(
            retries={"total_max_attempts": 1}, proxies={"http": None, "https": None}
        ),
    )


async def scenario(endpoint):
    for key, value in {
        "MINIO_ENDPOINT": endpoint,
        "MINIO_ACCESS_KEY": "fixture-user",
        "MINIO_SECRET_KEY": "fixture-password",
        "MINIO_DEFAULT_BUCKET": "kb-images",
        "MINIO_REGION": "us-east-1",
        "JWT_SECRET": "synthetic-image-grant",
    }.items():
        setattr(environment, key, value)
    actor = ServicePrincipal("owner", "tenant")
    inputs = [png(200), png(199), b"not-image", png(200)]
    references = [
        KnowledgeContentRequest(
            knowledge_id=1 if i < 3 else 2,
            file_id=char * 32,
            file_version=0,
            image_ref=ObjectReference(
                space="files",
                key=f"images/{char * 64}/{hashlib.sha256(raw).hexdigest()}.png",
                version="pending",
                sha256=hashlib.sha256(raw).hexdigest(),
            ),
        )
        for i, (char, raw) in enumerate(zip("abcd", inputs, strict=True))
    ]
    client = object_client(endpoint)
    try:
        client.create_bucket(Bucket="kb-images")
        client.put_bucket_versioning(
            Bucket="kb-images", VersioningConfiguration={"Status": "Enabled"}
        )
        for reference, raw in zip(references, inputs, strict=True):
            response = client.put_object(
                Bucket="kb-images",
                Key="tenant/" + reference.image_ref.key,
                Body=raw,
                ContentType="image/png",
            )
            reference.image_ref.version = "version:" + response["VersionId"]
    finally:
        client.close()
    calls, reads, events, searches = Counter(), [], [], []

    def authorize(request, principal, *, context):
        assert principal == actor
        context.remaining()
        calls[request.file_id] += 1
        if request not in references[:3]:
            raise ScopeDenied()
        return KnowledgeContentGrant(
            **request.model_dump(), object_ref=request.image_ref, filename="sample.pdf"
        )

    app = FastAPI(root_path="/api")
    app.include_router(create_knowledge_authorization_router(content_service=authorize))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)
    rpc = AgentOSClient(
        "http://127.0.0.1:" + str(listener.getsockname()[1]),
        lambda **kwargs: httpx.AsyncClient(trust_env=False, **kwargs),
    )
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    manager = ThreadManager(
        service_name="kb-image-proof",
        lane_policies={
            name: LanePolicy(
                name=name,
                max_workers=2,
                max_queue_size=8,
                queue_timeout_seconds=0,
                cancel_grace_seconds=1,
                shutdown_grace_seconds=3,
            )
            for name in ("model-tool-io", "control-io")
        },
    )
    manager.start()
    scope = RunCancellationScope()
    original = content.read_knowledge_content

    def observed(actor, grant, **kwargs):
        reads.append(grant.file_id)
        return original(actor, grant, **kwargs)

    def search(**kwargs):
        searches.append(kwargs)
        return {
            "results": [
                {
                    "filename": "sample.pdf",
                    "source_type": "file",
                    "content": "image",
                    "path_or_url": "",
                    "score": 1,
                    "file_ref": ref.model_dump(exclude={"image_ref"}),
                    "image_ref": ref.image_ref.model_dump(),
                }
                for ref in references
            ],
            "total": len(references),
        }

    observer = SimpleNamespace(
        add_message=lambda _, kind, value: events.append((kind, value))
    )
    service = KnowledgeImageFilter(
        actor, rpc, selector=WebImageFilter(enabled=False, model_path=None)
    )
    config = ToolConfig(
        class_name="KnowledgeBaseSearchTool",
        name="knowledge_base_search",
        source="local",
        params={
            "index_names": ["kb", "denied"],
            "search_mode": "accurate",
            "top_k": 10,
        },
        metadata={
            "knowledge_searcher": search,
            "allowed_index_names": ["kb"],
            "display_name_to_index_map": {"KB": "kb", "Denied": "denied"},
            "image_filterer": service,
        },
    )

    def exercise():
        tool = NexentAgent.create_local_tool(
            SimpleNamespace(observer=observer, cancellation_scope=scope), config
        )
        result = json.loads(tool.forward("images", index_names=["KB", "Denied"]))
        assert len(result["results"]) == 4 and tool.record_ops == 5
        assert [row["index"] for row in result["results"]] == [
            tool.tool_sign + str(i) for i in range(1, 5)
        ]
        assert all(
            row["reference_mark"] == "[[" + row["index"] + "]]"
            for row in result["results"]
        )
        assert "no read permission" in result["notice"] and "Denied" in result["notice"]
        assert not hasattr(tool, "vdb_core") and not hasattr(tool, "_extract_image_url")

    try:
        async with asyncio.timeout(5):
            while not server.started:
                await asyncio.sleep(0.01)
        with patch.object(content, "read_knowledge_content", observed):
            await manager.run(
                "model-tool-io",
                ManagedTaskSpec(task_name="kb-images", owner="proof"),
                exercise,
            )
        assert len(searches) == 1 and searches[0]["index_names"] == ["kb"]
        (picture,) = [
            json.loads(value)
            for kind, value in events
            if kind == ProcessType.PICTURE_WEB
        ]
        assert picture == {
            "images_url": [],
            "images_ref": [
                {
                    "file_ref": references[0].model_dump(exclude={"image_ref"}),
                    "image_ref": references[0].image_ref.model_dump(),
                    "cite_index": 1,
                    "tool_sign": "a",
                }
            ],
        }
        (projected,) = [
            json.loads(value)
            for kind, value in events
            if kind == ProcessType.SEARCH_CONTENT
        ]
        assert [row["cite_index"] for row in projected] == [1, 2, 3, 4]
        assert all(
            row["url"] == "" and row["file_ref"]["file_version"] == 0
            for row in projected
        )
        assert Counter(reads) == Counter({char * 32: 1 for char in "abc"})
        assert calls == Counter({char * 32: 2 for char in "abc"}) + Counter(
            {"d" * 32: 1}
        )
        assert not scope._closers
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(serving, timeout=5)
        finally:
            listener.close()
            drained = await manager.shutdown(timeout=3)
            assert not drained.stuck_execution_ids
    client = object_client(endpoint)
    try:
        assert {
            item["Key"]
            for item in client.list_objects_v2(Bucket="kb-images")["Contents"]
        } == {"tenant/" + ref.image_ref.key for ref in references}
        for reference, raw in zip(references, inputs, strict=True):
            response = client.get_object(
                Bucket="kb-images", Key="tenant/" + reference.image_ref.key
            )
            with response["Body"] as stream:
                assert stream.read() == raw
    finally:
        client.close()
    return {
        "sdk_projection": True,
        "owner_scope": True,
        "bounded_grants": True,
        "source_preserved": True,
        "workers_reclaimed": True,
    }


def main(run_id):
    assert len(run_id) == 32 and all(c in "0123456789abcdef" for c in run_id)
    name = "nexent-kb-images-" + run_id
    try:
        docker(
            "run",
            "--rm",
            "-d",
            "--name",
            name,
            "--label",
            "nexent.test_run=" + run_id,
            "-e",
            "MINIO_ROOT_USER=fixture-user",
            "-e",
            "MINIO_ROOT_PASSWORD=fixture-password",
            "-p",
            "127.0.0.1::9000",
            "quay.io/minio/minio:RELEASE.2023-12-20T01-00-02Z",
            "server",
            "/data",
        )
        port = json.loads(docker("inspect", name))[0]["NetworkSettings"]["Ports"][
            "9000/tcp"
        ][0]["HostPort"]
        endpoint = "http://127.0.0.1:" + port
        deadline = time.monotonic() + 25
        with httpx.Client(trust_env=False, timeout=1) as health:
            while True:
                try:
                    if health.get(endpoint + "/minio/health/ready").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                assert time.monotonic() < deadline, (
                    "Owned MinIO startup exceeded deadline"
                )
                time.sleep(0.1)
        evidence = asyncio.run(scenario(endpoint))
    finally:
        for container in docker(
            "ps", "-aq", "--filter", "label=nexent.test_run=" + run_id
        ).splitlines():
            docker("rm", "-f", "-v", container)
        assert not docker("ps", "-aq", "--filter", "label=nexent.test_run=" + run_id)
    evidence["owned_cleanup"] = True
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1])
