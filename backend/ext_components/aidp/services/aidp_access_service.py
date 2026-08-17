"""Resolve the current AIDP catalog and Nexent user permissions consistently."""

from __future__ import annotations

import copy
import hashlib
import logging
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from ext_components.aidp.services import aidp_permission_service
from ext_components.aidp.services.aidp_service import fetch_all_aidp_knowledge_bases_impl

logger = logging.getLogger("aidp_access_service")

_CATALOG_CACHE_TTL_SECONDS = 30.0
_CATALOG_CACHE_MAX_ENTRIES = 32
_DETAIL_CACHE_TTL_SECONDS = 60.0
_DETAIL_CACHE_MAX_ENTRIES = 256
_DOC_COUNT_CACHE_TTL_SECONDS = 30.0
_DOC_COUNT_CACHE_MAX_ENTRIES = 256
_catalog_cache: OrderedDict[tuple[str, str, str], tuple[float, list[dict]]] = OrderedDict()
_detail_cache: OrderedDict[tuple[str, str, str, str], tuple[float, dict]] = OrderedDict()
_doc_count_cache: OrderedDict[tuple[str, str, str, str], tuple[float, int]] = OrderedDict()
_catalog_inflight: dict[tuple[str, str, str], Future[Any]] = {}
_detail_inflight: dict[tuple[str, str, str, str], Future[Any]] = {}
_doc_count_inflight: dict[tuple[str, str, str, str], Future[Any]] = {}
_catalog_versions: dict[tuple[str, str, str], int] = {}
_detail_versions: dict[tuple[str, str, str, str], int] = {}
_doc_count_versions: dict[tuple[str, str, str, str], int] = {}
_cache_lock = threading.RLock()

_T = TypeVar("_T")


@dataclass(frozen=True)
class AidpAccessSnapshot:
    """Current remote catalog intersected with one Nexent user's permissions."""

    remote_items: list[dict]
    remote_ids: set[str]
    accessible_rows: list[dict]
    accessible_ids: list[str]
    accessible_id_set: set[str]
    name_to_id: dict[str, str]


def _normalize_server_url(server_url: str) -> str:
    return str(server_url or "").strip().rstrip("/").lower()


def _cache_key(server_url: str, api_key: str, aidp_tenant_id: str) -> tuple[str, str, str]:
    api_key_digest = hashlib.sha256(str(api_key or "").encode("utf-8")).hexdigest()
    return (
        _normalize_server_url(server_url),
        str(aidp_tenant_id or "aidp").strip().lower(),
        api_key_digest,
    )


def _extract_remote_items(result: Any) -> list[dict]:
    raw_items = result.get("value", []) if isinstance(result, dict) else []
    if not isinstance(raw_items, list):
        return []
    return [copy.deepcopy(item) for item in raw_items if isinstance(item, dict)]


def _get_or_load_cached(
    *,
    cache: OrderedDict,
    inflight: dict,
    versions: dict,
    key: tuple,
    ttl_seconds: float,
    max_entries: int,
    loader: Callable[[], _T],
    force_refresh: bool,
) -> _T:
    """Return a cached value while coalescing concurrent loads for the same key."""
    now = time.monotonic()
    with _cache_lock:
        if not force_refresh:
            cached = cache.get(key)
            if cached and cached[0] > now:
                cache.move_to_end(key)
                return copy.deepcopy(cached[1])
            if cached:
                cache.pop(key, None)

        future = inflight.get(key)
        if future is None:
            future = Future()
            inflight[key] = future
            load_version = versions.get(key, 0)
            is_loader = True
        else:
            load_version = 0
            is_loader = False

    if not is_loader:
        return copy.deepcopy(future.result())

    try:
        value = loader()
        stored_value = copy.deepcopy(value)
        with _cache_lock:
            if versions.get(key, 0) == load_version:
                cache[key] = (time.monotonic() + ttl_seconds, stored_value)
                cache.move_to_end(key)
                while len(cache) > max_entries:
                    cache.popitem(last=False)
        future.set_result(copy.deepcopy(value))
        return value
    except BaseException as exc:
        future.set_exception(exc)
        raise
    finally:
        with _cache_lock:
            if inflight.get(key) is future:
                inflight.pop(key, None)


def _get_remote_catalog(
    server_url: str,
    api_key: str,
    aidp_tenant_id: str,
    force_refresh: bool,
) -> list[dict]:
    key = _cache_key(server_url, api_key, aidp_tenant_id)
    return _get_or_load_cached(
        cache=_catalog_cache,
        inflight=_catalog_inflight,
        versions=_catalog_versions,
        key=key,
        ttl_seconds=_CATALOG_CACHE_TTL_SECONDS,
        max_entries=_CATALOG_CACHE_MAX_ENTRIES,
        loader=lambda: _extract_remote_items(
            fetch_all_aidp_knowledge_bases_impl(server_url, api_key)
        ),
        force_refresh=force_refresh,
    )


def get_cached_aidp_kb_detail(
    server_url: str,
    api_key: str,
    kds_id: str,
    loader: Callable[[], dict],
    aidp_tenant_id: str = "aidp",
    force_refresh: bool = False,
) -> dict:
    """Return one credential-scoped KB detail with short-lived caching."""
    key = (*_cache_key(server_url, api_key, aidp_tenant_id), str(kds_id))
    return _get_or_load_cached(
        cache=_detail_cache,
        inflight=_detail_inflight,
        versions=_detail_versions,
        key=key,
        ttl_seconds=_DETAIL_CACHE_TTL_SECONDS,
        max_entries=_DETAIL_CACHE_MAX_ENTRIES,
        loader=loader,
        force_refresh=force_refresh,
    )


def get_cached_aidp_doc_count(
    server_url: str,
    api_key: str,
    kds_id: str,
    loader: Callable[[], int],
    aidp_tenant_id: str = "aidp",
    force_refresh: bool = False,
) -> int:
    """Return one credential-scoped document count with short-lived caching."""
    key = (*_cache_key(server_url, api_key, aidp_tenant_id), str(kds_id))
    return _get_or_load_cached(
        cache=_doc_count_cache,
        inflight=_doc_count_inflight,
        versions=_doc_count_versions,
        key=key,
        ttl_seconds=_DOC_COUNT_CACHE_TTL_SECONDS,
        max_entries=_DOC_COUNT_CACHE_MAX_ENTRIES,
        loader=loader,
        force_refresh=force_refresh,
    )


def resolve_current_aidp_access(
    server_url: str,
    api_key: str,
    user_id: str,
    tenant_id: str,
    aidp_tenant_id: str = "aidp",
    force_refresh: bool = False,
) -> AidpAccessSnapshot:
    """Return the current AIDP catalog intersected with local user access."""
    started_at = time.perf_counter()
    remote_started_at = time.perf_counter()
    remote_items = _get_remote_catalog(
        server_url=server_url,
        api_key=api_key,
        aidp_tenant_id=aidp_tenant_id,
        force_refresh=force_refresh,
    )
    remote_ms = (time.perf_counter() - remote_started_at) * 1000
    permission_started_at = time.perf_counter()
    accessible_rows = aidp_permission_service.intersect_accessible_kbs(
        remote_items=remote_items,
        user_id=user_id,
        tenant_id=tenant_id,
    )
    permission_ms = (time.perf_counter() - permission_started_at) * 1000

    remote_ids: set[str] = set()
    for item in remote_items:
        raw_id = item.get("kds_id") or item.get("id")
        if raw_id is not None:
            remote_ids.add(str(raw_id))

    accessible_ids = [str(row["kb_id"]) for row in accessible_rows if row.get("kb_id") is not None]
    accessible_id_set = set(accessible_ids)
    name_to_id: dict[str, str] = {}
    for row in accessible_rows:
        raw_id = row.get("kb_id") or row.get("kds_id")
        if raw_id is None:
            continue
        kds_id = str(raw_id)
        name = row.get("kds_name") or row.get("name") or kds_id
        name_to_id[str(name)] = kds_id

    snapshot = AidpAccessSnapshot(
        remote_items=remote_items,
        remote_ids=remote_ids,
        accessible_rows=accessible_rows,
        accessible_ids=accessible_ids,
        accessible_id_set=accessible_id_set,
        name_to_id=name_to_id,
    )
    logger.info(
        "AIDP access snapshot timing: total_ms=%.1f remote_ms=%.1f permission_ms=%.1f "
        "remote_count=%d accessible_count=%d",
        (time.perf_counter() - started_at) * 1000,
        remote_ms,
        permission_ms,
        len(remote_items),
        len(accessible_rows),
    )
    return snapshot


def invalidate_aidp_catalog_cache(
    server_url: str | None = None,
    api_key: str | None = None,
    aidp_tenant_id: str = "aidp",
) -> None:
    """Invalidate one credential-scoped catalog, or every catalog when omitted."""
    with _cache_lock:
        if server_url is None or api_key is None:
            _catalog_cache.clear()
            for key in set(_catalog_versions) | set(_catalog_inflight):
                _catalog_versions[key] = _catalog_versions.get(key, 0) + 1
            return
        key = _cache_key(server_url, api_key, aidp_tenant_id)
        _catalog_cache.pop(key, None)
        _catalog_versions[key] = _catalog_versions.get(key, 0) + 1


def invalidate_aidp_kb_detail_cache(
    server_url: str | None = None,
    api_key: str | None = None,
    kds_id: str | None = None,
    aidp_tenant_id: str = "aidp",
) -> None:
    """Invalidate cached KB details for one resource or all resources."""
    with _cache_lock:
        if server_url is None or api_key is None:
            keys = set(_detail_cache) | set(_detail_versions) | set(_detail_inflight)
        else:
            prefix = _cache_key(server_url, api_key, aidp_tenant_id)
            keys = {
                key
                for key in set(_detail_cache) | set(_detail_versions) | set(_detail_inflight)
                if key[:3] == prefix and (kds_id is None or key[3] == str(kds_id))
            }
            if kds_id is not None:
                keys.add((*prefix, str(kds_id)))
        for key in keys:
            _detail_cache.pop(key, None)
            _detail_versions[key] = _detail_versions.get(key, 0) + 1


def invalidate_aidp_doc_count_cache(
    server_url: str | None = None,
    api_key: str | None = None,
    kds_id: str | None = None,
    aidp_tenant_id: str = "aidp",
) -> None:
    """Invalidate cached document counts for one resource or all resources."""
    with _cache_lock:
        if server_url is None or api_key is None:
            keys = set(_doc_count_cache) | set(_doc_count_versions) | set(_doc_count_inflight)
        else:
            prefix = _cache_key(server_url, api_key, aidp_tenant_id)
            keys = {
                key
                for key in set(_doc_count_cache) | set(_doc_count_versions) | set(_doc_count_inflight)
                if key[:3] == prefix and (kds_id is None or key[3] == str(kds_id))
            }
            if kds_id is not None:
                keys.add((*prefix, str(kds_id)))
        for key in keys:
            _doc_count_cache.pop(key, None)
            _doc_count_versions[key] = _doc_count_versions.get(key, 0) + 1


__all__ = [
    "AidpAccessSnapshot",
    "get_cached_aidp_doc_count",
    "get_cached_aidp_kb_detail",
    "invalidate_aidp_catalog_cache",
    "invalidate_aidp_doc_count_cache",
    "invalidate_aidp_kb_detail_cache",
    "resolve_current_aidp_access",
]
