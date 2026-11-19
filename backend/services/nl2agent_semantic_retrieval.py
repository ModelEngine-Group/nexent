# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Optional tenant-scoped semantic retrieval; coverage remains model verified."""
import asyncio
import hashlib
import json
import logging
import math
import re
import time
from threading import Event

from nexent.core.concurrency import ThreadQueueTimedOut, run_blocking

from contracts.constants.environment import NL2AGENT_EMBEDDING_MIN_SIMILARITY
from contracts.nl2agent_resources import (
    MAX_CANDIDATES_PER_RECALL_ROUTE, RESOURCE_PREPARATION_TIMEOUT, RESOURCE_SEARCH_TIMEOUT,
)
from management.services.conversation.nl2agent_resource_index import (
    FILTER_BATCH_SIZE, AsyncResourceSearch, ResourceIndex, digest, map_search_jobs, projection,
)
from management.services.configuration.tenant.settings import tenant_config_manager
from management.services.model.resolver import create_embedding_model

BATCH_SIZE = 8
PREPARATION_TIMEOUT = RESOURCE_PREPARATION_TIMEOUT
RETRIEVAL_TIMEOUT = RESOURCE_SEARCH_TIMEOUT
PROJECTION_VERSION = 3
MODEL_VECTOR_FIELDS = (
    "model_id", "model_repo", "model_name", "model_type", "model_factory", "base_url",
    "embedding_dim", "dimension", "dimensions", "embedding_version", "model_version", "max_tokens",
)
logger = logging.getLogger(__name__)


class SemanticRetrievalTimeout(TimeoutError):
    """Identify the bounded phase that caused authorized text fallback."""

    def __init__(self, phase, threshold_seconds):
        super().__init__(f"Semantic {phase} budget exhausted")
        self.phase = phase
        self.threshold_seconds = threshold_seconds


class _PhaseBudget:
    def __init__(self, timeout, stopped):
        self.deadline = time.monotonic() + timeout
        self.stopped = stopped

    def remaining(self):
        seconds = self.deadline - time.monotonic()
        if self.stopped.is_set() or seconds <= 0:
            raise TimeoutError("Semantic phase budget exhausted")
        return seconds


def candidate_budget(size: int) -> int:
    return min(size, MAX_CANDIDATES_PER_RECALL_ROUTE)


def validate_vectors(values, count: int, dimension: int | None = None) -> list[list[float]]:
    if not isinstance(values, list) or len(values) != count:
        raise ValueError("Embedding result count mismatch")
    result = []
    for vector in values:
        if not isinstance(vector, list) or not vector or (dimension and len(vector) != dimension):
            raise ValueError("Embedding dimension mismatch")
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in vector):
            raise ValueError("Invalid embedding values")
        norm = math.sqrt(sum(value * value for value in vector))
        if not math.isfinite(norm) or norm == 0:
            raise ValueError("Invalid embedding norm")
        dimension = len(vector)
        result.append([value / norm for value in vector])
    return result


def _resolve(tenant_id):
    config = tenant_config_manager.get_model_config(key="EMBEDDING_ID", tenant_id=tenant_id)
    if not isinstance(config, dict) or not config.get("model_id"):
        return None
    if config.get("model_type") not in ("embedding", "multi_embedding"):
        raise ValueError("Configured embedding model unavailable")
    config = dict(config)
    adapter = create_embedding_model(config)
    identity = {key: config[key] for key in MODEL_VECTOR_FIELDS if key in config}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()
    dimension = config.get("embedding_dim")
    return adapter, fingerprint, dimension if type(dimension) is int and dimension > 0 else None


async def resolve_model(tenant_id):
    return await run_blocking("nl2agent-embedding-model", _resolve, tenant_id,
                              lane="control-io", owner=__name__)


def _text(resource):
    parts = [resource["name"], resource.get("description", ""),
             *resource.get("descriptions", []), *resource.get("labels", []), *resource.get("names", [])]
    normalized = [re.sub(r"\s+", " ", str(part)).strip() for part in parts if part]
    text = "\n".join(dict.fromkeys(part for part in normalized if part))
    return re.sub(r"https?://\S+", "[address]", text, flags=re.IGNORECASE)[:4000]


def _query_routes(value: str | dict[str, str]) -> list[str]:
    """Reuse equivalent expressions across requirements and language routes."""
    return list(dict.fromkeys([value] if isinstance(value, str) else value.values()))


def resource_revision(resource):
    return digest([resource["candidate_ref"], PROJECTION_VERSION, digest(_text(resource))])


def _prepare(tenant_id, model, queries, installed, installable, progress, budget, stopped):
    started = time.monotonic()
    adapter, fingerprint, dimension = model
    catalog = list({row["candidate_ref"]: row for row in [*installed, *installable]}.values())
    if not catalog:
        return None

    remaining = budget.remaining

    def emit(stage, completed=None, total=None):
        if progress and not stopped.is_set() and time.monotonic() < budget.deadline:
            progress(stage, completed, total)

    # The query determines the actual dimension even for legacy model records.
    queries_by_text = {}
    unique_queries = list(dict.fromkeys(query for value in queries.values() for query in _query_routes(value)))
    for start in range(0, len(unique_queries), BATCH_SIZE):
        inputs = unique_queries[start:start + BATCH_SIZE]
        vectors = validate_vectors(adapter.get_embeddings(
            inputs, timeout=remaining(), retries=0), len(inputs), dimension)
        dimension = len(vectors[0])
        queries_by_text.update(zip(inputs, vectors))
    if not queries_by_text:
        return None
    documents = {row["candidate_ref"]: projection(
        tenant_id, row, _text(row), fingerprint, PROJECTION_VERSION) for row in catalog}
    with ResourceIndex(fingerprint, dimension, PROJECTION_VERSION, remaining) as index:
        snapshots = index.snapshots(tenant_id, catalog)
        pending = [row for row in catalog if snapshots[row["candidate_ref"]].get(
            "_source", {}).get("resource_revision") != documents[row["candidate_ref"]]["resource_revision"]]
        completed = len(catalog) - len(pending)
        emit("preparing_embeddings", completed, len(catalog))
        if not pending:
            # A previous writer may have stopped after indexing, before refresh.
            index.refresh()
        for start in range(0, len(pending), BATCH_SIZE):
            batch = pending[start:start + BATCH_SIZE]
            vectors = validate_vectors(adapter.get_embeddings(
                [_text(row) for row in batch], timeout=remaining(), retries=0), len(batch), dimension)
            remaining()
            for row, vector in zip(batch, vectors):
                ref = row["candidate_ref"]
                index.put(documents[ref], vector, snapshots[ref], refresh=False)
            index.refresh()
            for row in batch:
                completed += 1
                emit("preparing_embeddings", completed, len(catalog))
        remaining()
    # Build independent language/source scopes without name-based admission exceptions.
    groups = {}
    for query in queries_by_text:
        for label, group in (("installed", installed), ("installable", installable)):
            remaining()
            unique = {row["candidate_ref"]: row for row in group}
            groups[query, label] = (unique, candidate_budget(len(unique)))
    remaining()
    return dimension, documents, queries_by_text, groups, remaining, emit, started, len(pending)


async def _search(tenant_id, fingerprint, prepared, queries):
    dimension, documents, vectors, groups, remaining, emit, started, pending = prepared

    def jobs():
        for (query, label), (unique, size) in groups.items():
            refs = list(unique)
            for start in range(0, len(refs), FILTER_BATCH_SIZE):
                yield ((query, label), [documents[ref] for ref in refs[start:start + FILTER_BATCH_SIZE]], size)

    # Progress publishing uses synchronous Redis and stays on managed control I/O.
    total = len(groups)
    await run_blocking("nl2agent-search-progress", emit, "computing_similarity", 0, total,
                       lane="control-io", owner=__name__)
    ranked_groups = {}
    async with AsyncResourceSearch(fingerprint, dimension, PROJECTION_VERSION, remaining) as index:
        async def search(job):
            (query, _), chunk, limit = job
            return await index.search_chunk(tenant_id, chunk, vectors[query], limit)

        for (key, _, limit), rows in await map_search_jobs(jobs(), search, remaining):
            ranked_groups[key] = sorted(ranked_groups.get(key, []) + rows,
                                        key=lambda row: (-row[0], row[1]))[:limit]
    remaining()
    await run_blocking("nl2agent-search-progress", emit, "computing_similarity", total, total,
                       lane="control-io", owner=__name__)
    result = {}
    for key, value in queries.items():
        result[key] = {}
        for label in ("installed", "installable"):
            selected = {}
            for query in _query_routes(value):
                unique, _ = groups[query, label]
                for score, ref in ranked_groups.get((query, label), []):
                    if score >= NL2AGENT_EMBEDDING_MIN_SIMILARITY:
                        if ref not in selected or score > selected[ref][0]:
                            selected[ref] = (score, unique[ref])
            result[key][label] = sorted(selected.values(), key=lambda row: (-row[0], row[1]["candidate_ref"]))
    logger.info("NL2Agent ES retrieval resources=%s prepared=%s queries=%s elapsed=%.3f",
                len(documents), pending, len(vectors), time.monotonic() - started)
    return result


async def retrieve(tenant_id, model, queries, installed, installable, progress):
    stopped = Event()
    budget = _PhaseBudget(PREPARATION_TIMEOUT, stopped)
    phase, threshold = "preparation", PREPARATION_TIMEOUT
    try:
        async with asyncio.timeout(PREPARATION_TIMEOUT):
            prepared = await run_blocking(
                "nl2agent-prepare-index", _prepare, tenant_id, model, queries,
                installed, installable, progress, budget, stopped, owner=__name__)
            if prepared is None:
                return {key: {"installed": [], "installable": []} for key in queries}
        logger.info("event=nl2agent_preparation_complete resources=%s prepared=%s elapsed=%.3f",
                    len(prepared[1]), prepared[-1], time.monotonic() - prepared[-2])
        phase, threshold = "search", RETRIEVAL_TIMEOUT
        # Preparation has finished; its closures now share a fresh search budget.
        budget.deadline = time.monotonic() + RETRIEVAL_TIMEOUT
        async with asyncio.timeout(RETRIEVAL_TIMEOUT):
            return await _search(tenant_id, model[1], prepared, queries)
    except ThreadQueueTimedOut:
        raise
    except TimeoutError as exc:
        raise SemanticRetrievalTimeout(phase, threshold) from exc
    finally:
        stopped.set()
