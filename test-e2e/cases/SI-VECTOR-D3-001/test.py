# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real vector protocol with owned Elasticsearch and no inference services."""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.mark.stage("D3")
@pytest.mark.case_id("SI-VECTOR-D3-001")
def test_scoped_vectors(record_property):
    root = Path(__file__).resolve().parents[3]
    sys.path[:0] = [
        str(root),
        str(root / "backend"),
        str(root / "sdk"),
        str(Path(__file__).parent),
    ]
    from elasticsearch import Elasticsearch
    from ingestion_probe import probe_ingestion
    from nexent.storage.errors import Conflict, PartialFailure, ScopeDenied
    from nexent.storage.models import (
        Comparison,
        OperationContext,
        Revision,
        SearchQuery,
        StorageScope,
        VectorKey,
        VectorRecord,
        WriteOutcome,
    )

    from infrastructure.storage.catalog import FieldDefinition
    from infrastructure.vdb.vector_store import ElasticsearchVectorStore, VectorBinding

    def docker(*args):
        return subprocess.check_output(
            ["docker", *args], text=True, stderr=subprocess.PIPE, timeout=30
        ).strip()

    def context():
        return OperationContext("vector-" + uuid4().hex, time.monotonic() + 30)

    name = "si-vector-" + uuid4().hex
    image = "docker.elastic.co/elasticsearch/elasticsearch:8.17.2"
    container = None
    ports = []
    try:
        image_id = docker("image", "inspect", "--format", "{{.Id}}", image)
        container = docker(
            "run",
            "--rm",
            "-d",
            "--name",
            name,
            "--memory",
            "1g",
            "--cpus",
            "2",
            "-e",
            "discovery.type=single-node",
            "-e",
            "xpack.security.enabled=false",
            "-e",
            "ingest.geoip.downloader.enabled=false",
            "-e",
            "xpack.ml.enabled=false",
            "-e",
            "ES_JAVA_OPTS=-Xms256m -Xmx256m",
            "-p",
            "127.0.0.1::9200",
            image,
        )
        config = json.loads(docker("inspect", container))[0]
        port = config["NetworkSettings"]["Ports"]["9200/tcp"][0]["HostPort"]
        endpoint = "http://127.0.0.1:" + port

        def client_factory(remaining):
            return Elasticsearch(
                endpoint,
                request_timeout=min(5, remaining),
                max_retries=0,
                retry_on_timeout=False,
            )

        deadline = time.monotonic() + 60
        while True:
            with client_factory(1) as client:
                if client.ping():
                    break
            assert time.monotonic() < deadline, (
                "Owned Elasticsearch startup exceeded deadline"
            )
            time.sleep(0.2)
        fields = (
            FieldDefinition("content", "string"),
            FieldDefinition("file_id", "string"),
            FieldDefinition("location", "object", nullable=True),
        )

        def store(
            tenant="tenant-a", collection="kb", dimensions=2, factory=client_factory
        ):
            result = ElasticsearchVectorStore(
                StorageScope("runtime", tenant, "vector-proof", {collection}),
                (
                    VectorBinding(
                        collection, "vector-proof", dimensions, fields, writable=True
                    ),
                ),
                factory,
            )
            ports.append(result)
            return result

        def row(
            key,
            values=(1.0, 0.0),
            file_id="base",
            content="hello",
            generation="v1",
            collection="kb",
        ):
            return VectorRecord(
                VectorKey(collection, key),
                values,
                {"content": content, "file_id": file_id, "location": {"page": 1}},
                Revision(generation),
            )

        primary, foreign, other = store(), store("tenant-b"), store(collection="other")
        assert primary.ensure_collection("kb", context=context()).dimensions == 2
        with pytest.raises(Conflict):
            store(dimensions=3).ensure_collection("kb", context=context())
        assert primary.describe_collection("kb", context=context()).dimensions == 2
        primary.upsert(
            (row("one"), row("two", (0.0, 1.0), content="goodbye")), context=context()
        )
        foreign.upsert((row("one", content="private tenant"),), context=context())
        other.upsert(
            (row("one", content="private collection", collection="other"),),
            context=context(),
        )
        assert primary.count("kb", None, context=context()) == 2
        assert foreign.count("kb", None, context=context()) == 1
        assert other.count("other", None, context=context()) == 1
        assert primary.get(VectorKey("kb", "one"), context=context()) == row("one")
        dense = primary.search(
            "kb", SearchQuery(vector=(1.0, 0.0), limit=1), context=context()
        )
        assert (
            dense[0].key.key == "one" and dense[0].score_kind == "elasticsearch.cosine"
        )
        text = primary.search(
            "kb", SearchQuery(text="hello", mode="text"), context=context()
        )
        assert [hit.key.key for hit in text] == ["one"] and text[
            0
        ].score_kind == "elasticsearch.bm25"
        bulk = tuple(row("bulk-" + str(index), file_id="bulk") for index in range(1005))
        primary.upsert(bulk[:1000], context=context())
        primary.upsert(bulk[1000:], context=context())
        receipts = primary.delete(
            "kb", Comparison("file_id", "eq", "bulk"), context=context()
        )
        assert len(receipts) == 1005 and all(item.deleted for item in receipts)
        assert len({item.operation_id for item in receipts}) == 1005
        assert primary.count("kb", None, context=context()) == 2
        assert foreign.count("kb", None, context=context()) == 1
        primary.upsert((row("race", file_id="race"),), context=context())
        replaced = [False]

        class RacingClient:
            def __init__(self, client):
                self.client = client

            def __getattr__(self, name):
                return getattr(self.client, name)

            def options(self, **kwargs):
                return RacingClient(self.client.options(**kwargs))

            def bulk(self, **kwargs):
                if not replaced[0]:
                    replaced[0] = True
                    primary.upsert(
                        (row("race", file_id="race", generation="v2"),),
                        context=context(),
                    )
                return self.client.bulk(**kwargs)

        racing = store(
            factory=lambda remaining: RacingClient(client_factory(remaining))
        )
        with pytest.raises(PartialFailure) as failure:
            racing.delete("kb", Comparison("file_id", "eq", "race"), context=context())
        assert replaced[0] and failure.value.results[0].outcome == WriteOutcome.FAILED
        assert primary.get(
            VectorKey("kb", "race"), context=context()
        ).generation == Revision("v2")
        assert primary.delete(
            "kb", Comparison("file_id", "eq", "race"), context=context()
        )[0].deleted
        ingestion = probe_ingestion(client_factory, ports, context)
        primary.close()
        with pytest.raises(ScopeDenied):
            primary.count("kb", None, context=context())
        record_property(
            "vector_probe",
            json.dumps(
                {
                    "collection_compatibility": True,
                    "dependency_image_id": image_id,
                    "tenant_and_collection_isolation": True,
                    "dense_and_text": True,
                    "snapshot_pages_and_cas": True,
                    "runtime_ingestion": ingestion,
                    "source_hashes": {
                        path: hashlib.sha256((root / path).read_bytes()).hexdigest()
                        for path in (
                            "infrastructure/vdb/vector_store.py",
                            "infrastructure/vdb/vector_delete.py",
                            "infrastructure/vdb/vector_schema.py",
                            "backend/runtime/knowledge_base/ingestion.py",
                        )
                    },
                }
            ),
        )
    finally:
        for port in ports:
            port.close()
        remaining = docker("ps", "-aq", "--filter", "name=^/" + name + "$")
        if container is None and remaining:
            container = remaining
        if container is not None:
            docker("rm", "-f", "-v", container)
        assert not docker("ps", "-aq", "--filter", "name=^/" + name + "$")
