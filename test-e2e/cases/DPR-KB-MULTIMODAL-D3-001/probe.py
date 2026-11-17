# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real Runtime/SDK embedding protocol with owned scoped MinIO and ES."""

import asyncio
import base64
import hashlib
import io
import json
import subprocess
import sys
import time
from functools import partial
from pathlib import Path
from types import SimpleNamespace

root = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(root), str(root / "backend"), str(root / "sdk")]

import boto3
import httpx
from aiohttp import web
from botocore.config import Config
from contracts.agentos_knowledge import (
    CleanseArtifact,
    KnowledgeFileGrant,
    KnowledgeFileUpload,
    ObjectReference,
)
from contracts.constants import environment
from management.services.file.cleanse import cleanse_object
from nexent.core.concurrency import (
    LanePolicy,
    ManagedTaskSpec,
    ThreadManager,
    clear_default_thread_manager,
    set_default_thread_manager,
)
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import ObjectRef, OperationContext, Revision, SearchQuery
from nexent.storage.objects import read_verified_object
from PIL import Image
from runtime.knowledge_base.ingestion import KnowledgeIngestor
from runtime.knowledge_base.search import KnowledgeSearchService
from runtime.model.service import ModelService

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.file_processing.objects import bind_cleanse_objects
from infrastructure.knowledge_objects import bind_knowledge_image_objects
from infrastructure.knowledge_runtime import knowledge_execution_ports
from infrastructure.model_adapter import build_adapter_fresh
from infrastructure.object_storage.composition import bind_source_objects


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, stderr=subprocess.PIPE, timeout=25).strip()


def context():
    return OperationContext("multimodal-proof", time.monotonic() + 30)


def stage(actor, png):
    raw = b"Owned mixed source"
    objects = bind_source_objects(actor.tenant_id, actor.user_id, "source", "mm-files")
    try:
        uploaded = objects.put(ObjectRef("files", "source"), io.BytesIO(raw), size=len(raw), content_type="application/pdf", context=context())
    finally:
        objects.close()
    source = ObjectReference(space="files", key="source", version=uploaded.ref.version.value, sha256=uploaded.sha256)
    outputs = bind_cleanse_objects(actor.tenant_id, actor.user_id, source, context=context())
    try:
        parser = SimpleNamespace(file_structure=lambda **kwargs: ([{"content": "Multimodal source text"}], [
            {"image_bytes": png, "image_format": "png", "position": {"page_number": 2}}]))
        artifact = cleanse_object(source, "source.pdf", "fixture-v1", parser=parser, objects=outputs, context=context())
    finally:
        outputs.close()
    return source, artifact


async def scenario():
    actor = ServicePrincipal("owner", "tenant")
    with io.BytesIO() as buffer, Image.new("RGB", (200, 200), "blue") as image:
        image.save(buffer, format="PNG")
        png = buffer.getvalue()
    calls, adapters = [], []

    async def embed(request):
        body = await request.json()
        values = body["input"]
        image_input = isinstance(values[0], dict)
        if image_input:
            assert base64.b64decode(values[0]["image"].partition(",")[2]) == png
        else:
            assert values == ["Multimodal source text"]
        calls.append("image" if image_input else "text")
        return web.json_response({"data": [{"embedding": [0.5, 1.0] if image_input else [1.0, 0.5]} for _ in values]})

    provider = web.Application()
    provider.router.add_post("/embedding", embed)
    runner = web.AppRunner(provider)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    endpoint = "http://127.0.0.1:" + str(site._server.sockets[0].getsockname()[1]) + "/embedding"
    manager = ThreadManager(service_name="mm-proof", lane_policies={
        name: LanePolicy(name=name, max_workers=2, max_queue_size=4, queue_timeout_seconds=0, cancel_grace_seconds=2, shutdown_grace_seconds=3)
        for name in ("control-io", "model-embedding")
    })
    manager.start()
    set_default_thread_manager(manager)

    async def blocking(fn, *args, **kwargs):
        return await manager.run("control-io", ManagedTaskSpec(task_name="mm-proof", owner="proof"), fn, *args, **kwargs)

    def load(model_id, tenant_id):
        assert model_id == 7 and tenant_id == actor.tenant_id
        return {"tenant_id": tenant_id, "delete_flag": "N", "model_type": "multi_embedding", "update_time": "v1",
                "model_name": "fixture-multimodal", "model_factory": "siliconflow", "api_key": "synthetic",
                "base_url": endpoint, "max_tokens": 2, "timeout_seconds": 2}

    def build(*args, **kwargs):
        adapter = build_adapter_fresh(*args, **kwargs)
        adapters.append(adapter)
        return adapter

    models = ModelService(load, build)
    try:
        source, artifact = await blocking(stage, actor, png)
        request = KnowledgeFileUpload(knowledge_id=1, file_id="a" * 32, file_version=0, artifact=artifact,
                                      parser_version="fixture-v1", idempotency_key="mixed", chunking_strategy="none",
                                      embedding_model={"model_id": 7, "revision": "v1"})
        grant = KnowledgeFileGrant(**request.model_dump(include={"knowledge_id", "file_id", "file_version", "artifact", "parser_version"}),
                                   action="execute", source=source, filename="source.pdf", collection="mm-kb", embedding_model_id=7)
        with knowledge_execution_ports(actor, grant, 2, context=context()) as (objects, vectors):
            await blocking(vectors.ensure_collection, grant.collection, context=context())
            ingestor = KnowledgeIngestor(objects, vectors, models, max_artifact_bytes=100000, max_source_bytes=100000,
                                         image_objects=partial(bind_knowledge_image_objects, actor, grant))
            result = await ingestor.execute(request, actor=actor, source=source, filename="source.pdf", collection="mm-kb",
                                            generation=Revision("generation-1"), context=context())
            assert result.chunk_keys == (f"1/{request.file_id}/0/0", f"1/{request.file_id}/0/1")
            assert calls == ["text", "image"]
            hits = await blocking(vectors.search, "mm-kb", SearchQuery(vector=(0.5, 1.0), limit=10), context=context())
            assert len(hits) == 2
            image_hits = [KnowledgeSearchService._dto(hit) for hit in hits if hit.payload["location"].get("kind") == "image"]
            assert len(image_hits) == 1 and image_hits[0].location["page_number"] == 2
            assert image_hits[0].image_ref.sha256 == hashlib.sha256(png).hexdigest()
            assert all(hit.generation == Revision("generation-1") for hit in hits)
            assert base64.b64encode(png).decode() not in json.dumps([hit.payload for hit in hits])
            manifest = CleanseArtifact.model_validate_json(await blocking(read_verified_object, objects,
                ObjectRef("files", artifact.key, Revision(artifact.version)), sha256=artifact.sha256, limit=100000, context=context()))
            assert image_hits[0].image_ref == manifest.blocks[-1].object_ref
            bad_image = manifest.blocks[-1].object_ref.model_copy(update={"key": "images/foreign/" + manifest.blocks[-1].sha256 + ".png"})
            bad = manifest.model_copy(update={"blocks": [*manifest.blocks[:-1], manifest.blocks[-1].model_copy(update={"object_ref": bad_image})]})
            # Reuse the real verified-source ports; only the corrupt manifest is controlled here.
            denied = KnowledgeIngestor(objects, vectors, models, max_artifact_bytes=100000, max_source_bytes=100000,
                                       image_objects=partial(bind_knowledge_image_objects, actor, grant))
            denied._artifact = lambda *args, **kwargs: bad
            try:
                await denied.execute(request, actor=actor, source=source, filename="source.pdf", collection="mm-kb",
                                     generation=Revision("denied"), context=context())
                raise AssertionError("Unauthorized manifest image was accepted")
            except ScopeDenied:
                pass
            assert calls == ["text", "image"]
            assert await blocking(vectors.count, "mm-kb", None, context=context()) == 2
    finally:
        await runner.cleanup()
        for adapter in adapters:
            await adapter.close()
            # The current SDK HTTP mixin close is a no-op; the fixture owns
            # the persistent requests session created by its embedding adapter.
            adapter._session.close()
        drained = await manager.shutdown(timeout=3)
        clear_default_thread_manager(manager)
        assert not drained.stuck_execution_ids
    return {"provider_types": calls, "physical_vectors": 2, "typed_image_ref": True, "denied_no_side_effects": True}


def main(run_id):
    assert len(run_id) == 32 and all(c in "0123456789abcdef" for c in run_id)
    images = {"minio": "quay.io/minio/minio:RELEASE.2023-12-20T01-00-02Z", "es": "docker.elastic.co/elasticsearch/elasticsearch:8.17.2"}
    try:
        endpoints = {}
        for role, image in images.items():
            docker("image", "inspect", image)
            args = (["-e", "MINIO_ROOT_USER=fixture-user", "-e", "MINIO_ROOT_PASSWORD=fixture-password", "-p", "127.0.0.1::9000"] if role == "minio" else
                    ["--memory", "1g", "--cpus", "2", "-e", "discovery.type=single-node", "-e", "xpack.security.enabled=false",
                     "-e", "ingest.geoip.downloader.enabled=false", "-e", "xpack.ml.enabled=false", "-e", "ES_JAVA_OPTS=-Xms256m -Xmx256m", "-p", "127.0.0.1::9200"])
            container = docker("run", "--rm", "-d", "--label", "nexent.test_run=" + run_id, *args, image, *(["server", "/data"] if role == "minio" else []))
            mapping = json.loads(docker("inspect", container))[0]["NetworkSettings"]["Ports"]
            endpoints[role] = "http://127.0.0.1:" + next(iter(mapping.values()))[0]["HostPort"]
        deadline = time.monotonic() + 70
        with httpx.Client(trust_env=False, timeout=1) as client:
            while True:
                try:
                    if client.get(endpoints["minio"] + "/minio/health/ready").status_code == 200 and client.get(endpoints["es"]).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                assert time.monotonic() < deadline, "Owned storage startup exceeded deadline"
                time.sleep(0.1)
        environment.MINIO_ENDPOINT = endpoints["minio"]
        environment.MINIO_ACCESS_KEY = "fixture-user"
        environment.MINIO_SECRET_KEY = "fixture-password"
        environment.MINIO_DEFAULT_BUCKET = "mm-files"
        environment.MINIO_REGION = "us-east-1"
        environment.ES_HOST = endpoints["es"]
        environment.ES_API_KEY = ""
        client = boto3.client("s3", endpoint_url=endpoints["minio"], aws_access_key_id="fixture-user", aws_secret_access_key="fixture-password",
                               region_name="us-east-1", config=Config(retries={"total_max_attempts": 1}, proxies={"http": None, "https": None}))
        try:
            client.create_bucket(Bucket="mm-files")
            client.put_bucket_versioning(Bucket="mm-files", VersioningConfiguration={"Status": "Enabled"})
        finally:
            client.close()
        evidence = asyncio.run(scenario())
    finally:
        for container in docker("ps", "-aq", "--filter", "label=nexent.test_run=" + run_id).splitlines():
            docker("rm", "-f", "-v", container)
        assert not docker("ps", "-aq", "--filter", "label=nexent.test_run=" + run_id)
    evidence["owned_cleanup"] = True
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1])
