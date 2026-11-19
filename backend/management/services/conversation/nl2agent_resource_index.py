# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Dedicated, rebuildable ES resource projections; callers own authorization."""

import asyncio
import hashlib
import json
import math
from datetime import datetime, timezone
from threading import BoundedSemaphore

from elasticsearch import AsyncElasticsearch, BadRequestError, ConflictError, Elasticsearch, NotFoundError

from contracts.constants.environment import (
    ES_API_KEY, ES_HOST, NL2AGENT_ES_PROCESS_SEARCH_CONCURRENCY, NL2AGENT_ES_SEARCH_CONCURRENCY,
)

INDEX_PREFIX = "nl2agent-resources"
FILTER_BATCH_SIZE = 512
# Thread-safe admission is shared even when MCP requests use different event loops.
_PROCESS_SEARCH_GATE = BoundedSemaphore(NL2AGENT_ES_PROCESS_SEARCH_CONCURRENCY)


async def map_search_jobs(jobs, operation, remaining):
    """Run a lazy job iterator with bounded tasks and cross-loop process admission."""
    jobs = iter(jobs)
    results = []
    gate = _PROCESS_SEARCH_GATE

    async def worker():
        while True:
            remaining()
            try:
                job = next(jobs)
            except StopIteration:
                return
            # Never block an event loop or allocate a thread to wait for a slot.
            while not gate.acquire(blocking=False):
                await asyncio.sleep(min(.01, remaining()))
            try:
                remaining()
                value = await operation(job)
                remaining()
                results.append((job, value))
            finally:
                gate.release()

    async with asyncio.timeout(remaining()):
        tasks = [asyncio.create_task(worker()) for _ in range(NL2AGENT_ES_SEARCH_CONCURRENCY)]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    return results


def digest(value):
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode()).hexdigest()


def document_id(tenant_id, ref):
    return digest([tenant_id, ref])


def projection(tenant_id, resource, text, fingerprint, version):
    """Only explicitly allowed fields may enter the search document."""
    content_hash = digest(text)
    return {
        "tenant_id": tenant_id, "candidate_ref": resource["candidate_ref"],
        "resource_type": resource["resource_type"], "source": resource["source"],
        "name": text.split("\n", 1)[0], "description": text,
        "projection_version": version, "model_fingerprint": fingerprint,
        "content_hash": content_hash,
        "resource_revision": digest([resource["candidate_ref"], version, content_hash]),
    }


def create_client():
    if not ES_HOST:
        raise ValueError("Resource search is not configured")
    return Elasticsearch(ES_HOST, api_key=ES_API_KEY or None, verify_certs=False,
                         ssl_show_warn=False, max_retries=0, retry_on_timeout=False)


def create_async_client():
    if not ES_HOST:
        raise ValueError("Resource search is not configured")
    return AsyncElasticsearch(
        ES_HOST, api_key=ES_API_KEY or None, verify_certs=False, ssl_show_warn=False,
        max_retries=0, retry_on_timeout=False,
        connections_per_node=NL2AGENT_ES_PROCESS_SEARCH_CONCURRENCY,
    )


class ResourceIndex:
    """One client per bounded retrieval, closed by the owning worker."""

    def __init__(self, fingerprint, dimension, version, remaining, client=None):
        self.client = client if client is not None else create_client()
        self.remaining = remaining
        self.dimension = dimension
        self.name = f"{INDEX_PREFIX}-p{version}-m{fingerprint}-d{dimension}-v1"

    def __enter__(self):
        try:
            try:
                self._api().indices.create(index=self.name, mappings={
                    "dynamic": "strict", "properties": {
                        **{key: {"type": "keyword"} for key in (
                            "tenant_id", "candidate_ref", "resource_type", "source", "name",
                            "model_fingerprint", "content_hash", "resource_revision",
                        )},
                        "description": {"type": "text", "index": False},
                        "projection_version": {"type": "integer"},
                        "updated_at": {"type": "date"},
                        "embedding": {"type": "dense_vector", "dims": self.dimension, "index": False},
                    },
                })
            except BadRequestError as exc:
                if exc.error != "resource_already_exists_exception":
                    raise
            # Another creator can expose metadata before its primary shard is ready.
            health = self._api().cluster.health(index=self.name, wait_for_status="yellow",
                wait_for_active_shards="1", wait_for_no_initializing_shards=True,
                timeout=f"{max(1, int(self.remaining() * 1000))}ms")
            if (health.get("timed_out") or health.get("status") not in {"yellow", "green"}
                    or health.get("active_primary_shards", 0) < 1
                    or health.get("unassigned_primary_shards", 0)):
                raise TimeoutError("Resource index primary shard is not ready")
        except BaseException:
            self.client.close()
            raise
        return self

    def __exit__(self, *_):
        self.client.close()

    def _api(self):
        return self.client.options(request_timeout=self.remaining(), max_retries=0,
                                   retry_on_timeout=False)

    def snapshots(self, tenant_id, resources):
        """Read versions and optimistic-concurrency tokens, never resource vectors."""
        snapshots = {}
        for start in range(0, len(resources), FILTER_BATCH_SIZE):
            refs = [row["candidate_ref"] for row in resources[start:start + FILTER_BATCH_SIZE]]
            response = self._api().mget(index=self.name,
                ids=[document_id(tenant_id, ref) for ref in refs],
                source_includes=["tenant_id", "candidate_ref", "resource_revision", "model_fingerprint"])
            docs = response["docs"]
            if len(docs) != len(refs) or any("error" in doc for doc in docs):
                raise ValueError("Incomplete resource index snapshot")
            snapshots.update(zip(refs, docs))
        return snapshots

    def put(self, document, vector, snapshot, *, refresh="wait_for"):
        body = {**document, "embedding": vector,
                "updated_at": datetime.now(timezone.utc).isoformat()}
        options = ({"if_seq_no": snapshot["_seq_no"], "if_primary_term": snapshot["_primary_term"]}
                   if snapshot.get("found") else {"op_type": "create"})
        try:
            self._api().index(index=self.name,
                id=document_id(document["tenant_id"], document["candidate_ref"]),
                document=body, refresh=refresh, **options)
        except ConflictError:
            # A newer write wins. Never retry a stale document unconditionally.
            current = self.snapshots(document["tenant_id"], [document])[document["candidate_ref"]]
            if current.get("_source", {}).get("resource_revision") != document["resource_revision"]:
                raise ValueError("Resource changed during index preparation") from None

    def refresh(self):
        response = self._api().indices.refresh(index=self.name)
        if response.get("_shards", {}).get("failed", 0):
            raise ValueError("Resource index refresh failed")

    def delete(self, tenant_id, ref):
        """Delete an explicitly identified resource, never an entire tenant scope."""
        try:
            self._api().delete(index=self.name, id=document_id(tenant_id, ref), refresh="wait_for")
        except NotFoundError:
            pass

    def search_arguments(self, tenant_id, chunk, query_vector, size):
        """Use identical authorization and scoring for sync maintenance and async retrieval."""
        filters = [
            {"term": {"tenant_id": tenant_id}},
            {"term": {"model_fingerprint": chunk[0]["model_fingerprint"]}},
            {"term": {"projection_version": chunk[0]["projection_version"]}},
            {"terms": {"candidate_ref": [row["candidate_ref"] for row in chunk]}},
            {"terms": {"resource_revision": [row["resource_revision"] for row in chunk]}},
            {"exists": {"field": "embedding"}},
        ]
        return dict(index=self.name, size=min(size, len(chunk)),
                allow_partial_search_results=False, track_total_hits=True,
                timeout=f"{max(1, int(self.remaining() * 1000))}ms",
                source_includes=["candidate_ref", "resource_revision", "tenant_id"],
                sort=[{"_score": "desc"}, {"candidate_ref": "asc"}],
                query={"script_score": {
                    "query": {"bool": {"filter": filters}},
                    "script": {"source": "cosineSimilarity(params.query_vector, 'embedding') + 1.0",
                               "params": {"query_vector": query_vector}},
                }})

    @staticmethod
    def read_search_response(tenant_id, chunk, response):
        if response.get("timed_out") or response.get("_shards", {}).get("failed", 0):
            raise TimeoutError("Incomplete resource search")
        if response["hits"]["total"]["value"] != len(chunk):
            raise ValueError("Resource index is incomplete or has changed")
        authorized = {row["candidate_ref"]: row for row in chunk}
        rows = []
        for hit in response["hits"]["hits"]:
            source = hit["_source"]
            ref = source["candidate_ref"]
            expected = authorized.get(ref)
            if (expected is None or source.get("tenant_id") != tenant_id
                    or source.get("resource_revision") != expected["resource_revision"]):
                raise ValueError("Resource search returned an unauthorized revision")
            score = float(hit["_score"]) - 1.0
            if not math.isfinite(score):
                raise ValueError("Invalid resource similarity score")
            rows.append((score, ref))
        return rows

    def search(self, tenant_id, documents, query_vector, size):
        if not documents or not size:
            return []
        rows = []
        for start in range(0, len(documents), FILTER_BATCH_SIZE):
            chunk = documents[start:start + FILTER_BATCH_SIZE]
            response = self._api().search(**self.search_arguments(tenant_id, chunk, query_vector, size))
            rows.extend(self.read_search_response(tenant_id, chunk, response))
        return sorted(rows, key=lambda row: (-row[0], row[1]))[:size]


class AsyncResourceSearch(ResourceIndex):
    """Request-owned async transport; mapping and refresh are prepared by managed I/O."""

    def __init__(self, fingerprint, dimension, version, remaining, client=None):
        super().__init__(fingerprint, dimension, version, remaining,
                         client=client if client is not None else create_async_client())

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        close = asyncio.create_task(self.client.close())
        try:
            await asyncio.shield(close)
        except asyncio.CancelledError:
            await close
            raise

    async def search_chunk(self, tenant_id, documents, query_vector, size):
        response = await self._api().search(**self.search_arguments(tenant_id, documents, query_vector, size))
        return self.read_search_response(tenant_id, documents, response)
