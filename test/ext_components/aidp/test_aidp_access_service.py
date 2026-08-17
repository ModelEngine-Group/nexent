import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

from ext_components.aidp.services import aidp_access_service as service


@pytest.fixture(autouse=True)
def clear_catalog_cache():
    service.invalidate_aidp_catalog_cache()
    service.invalidate_aidp_kb_detail_cache()
    service.invalidate_aidp_doc_count_cache()
    yield
    service.invalidate_aidp_catalog_cache()
    service.invalidate_aidp_kb_detail_cache()
    service.invalidate_aidp_doc_count_cache()


def test_snapshot_intersects_remote_catalog_and_builds_name_map():
    remote_items = [
        {"kds_id": "1", "kds_name": "Remote One"},
        {"kds_id": "2", "kds_name": "Remote Two"},
    ]
    accessible_rows = [
        {"kb_id": "2", "kds_id": "2", "kds_name": "Remote Two"},
    ]
    with patch.object(
        service,
        "fetch_all_aidp_knowledge_bases_impl",
        return_value={"value": remote_items},
    ), patch.object(
        service.aidp_permission_service,
        "intersect_accessible_kbs",
        return_value=accessible_rows,
    ):
        snapshot = service.resolve_current_aidp_access(
            "https://aidp.example", "key", "user", "tenant"
        )

    assert snapshot.remote_ids == {"1", "2"}
    assert snapshot.accessible_ids == ["2"]
    assert snapshot.accessible_id_set == {"2"}
    assert snapshot.name_to_id == {"Remote Two": "2"}


def test_remote_catalog_is_cached_but_user_permissions_are_recomputed():
    with patch.object(
        service,
        "fetch_all_aidp_knowledge_bases_impl",
        return_value={"value": [{"kds_id": "1"}]},
    ) as mock_fetch, patch.object(
        service.aidp_permission_service,
        "intersect_accessible_kbs",
        return_value=[],
    ) as mock_intersect:
        service.resolve_current_aidp_access("https://aidp.example", "key", "u1", "tenant")
        service.resolve_current_aidp_access("https://aidp.example", "key", "u2", "tenant")

    assert mock_fetch.call_count == 1
    assert mock_intersect.call_count == 2


def test_catalog_cache_key_scopes_by_url_and_tenant_not_api_key():
    """Credentials are process-constant, so the cache key tracks only the
    remote catalog identity (server_url + aidp_tenant_id). A different
    api_key against the same endpoint reuses the cached catalog, while a
    different endpoint misses."""
    with patch.object(
        service,
        "fetch_all_aidp_knowledge_bases_impl",
        return_value={"value": []},
    ) as mock_fetch, patch.object(
        service.aidp_permission_service,
        "intersect_accessible_kbs",
        return_value=[],
    ):
        # Same endpoint + tenant, different api_key: cache hit.
        service.resolve_current_aidp_access("https://aidp.example", "key-1", "u", "tenant")
        service.resolve_current_aidp_access("https://aidp.example", "key-2", "u", "tenant")
        # Different endpoint: cache miss.
        service.resolve_current_aidp_access("https://other.example", "key-2", "u", "tenant")

    assert mock_fetch.call_count == 2


def test_failed_catalog_request_is_not_cached():
    with patch.object(
        service,
        "fetch_all_aidp_knowledge_bases_impl",
        side_effect=[TimeoutError("down"), {"value": []}],
    ) as mock_fetch, patch.object(
        service.aidp_permission_service,
        "intersect_accessible_kbs",
        return_value=[],
    ):
        with pytest.raises(TimeoutError):
            service.resolve_current_aidp_access("https://aidp.example", "key", "u", "tenant")
        service.resolve_current_aidp_access("https://aidp.example", "key", "u", "tenant")

    assert mock_fetch.call_count == 2


def test_concurrent_catalog_requests_share_one_remote_fetch():
    started = threading.Event()
    release = threading.Event()

    def fetch_catalog(*_args, **_kwargs):
        started.set()
        assert release.wait(timeout=2)
        return {"value": [{"kds_id": "1"}]}

    with patch.object(
        service,
        "fetch_all_aidp_knowledge_bases_impl",
        side_effect=fetch_catalog,
    ) as mock_fetch, patch.object(
        service.aidp_permission_service,
        "intersect_accessible_kbs",
        return_value=[],
    ):
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(
                service.resolve_current_aidp_access,
                "https://aidp.example",
                "key",
                "u1",
                "tenant",
            )
            assert started.wait(timeout=1)
            second = executor.submit(
                service.resolve_current_aidp_access,
                "https://aidp.example",
                "key",
                "u2",
                "tenant",
            )
            time.sleep(0.05)
            release.set()
            first.result(timeout=2)
            second.result(timeout=2)

    assert mock_fetch.call_count == 1


def test_kb_detail_cache_hit_and_targeted_invalidation():
    loader = MagicMock(return_value={"kds_id": "1", "description": "cached"})

    first = service.get_cached_aidp_kb_detail(
        "https://aidp.example", "key", "1", loader
    )
    second = service.get_cached_aidp_kb_detail(
        "https://aidp.example", "key", "1", loader
    )
    service.invalidate_aidp_kb_detail_cache("https://aidp.example", "key", "1")
    third = service.get_cached_aidp_kb_detail(
        "https://aidp.example", "key", "1", loader
    )

    assert first == second == third
    assert loader.call_count == 2


def test_doc_count_cache_hit_and_targeted_invalidation():
    loader = MagicMock(return_value=7)

    assert service.get_cached_aidp_doc_count(
        "https://aidp.example", "key", "1", loader
    ) == 7
    assert service.get_cached_aidp_doc_count(
        "https://aidp.example", "key", "1", loader
    ) == 7
    service.invalidate_aidp_doc_count_cache("https://aidp.example", "key", "1")
    assert service.get_cached_aidp_doc_count(
        "https://aidp.example", "key", "1", loader
    ) == 7

    assert loader.call_count == 2


def test_remote_catalog_non_list_value_yields_empty_snapshot():
    """A remote catalog response whose ``value`` is not a list is skipped."""
    with patch.object(
        service,
        "fetch_all_aidp_knowledge_bases_impl",
        return_value={"value": "not-a-list"},
    ), patch.object(
        service.aidp_permission_service,
        "intersect_accessible_kbs",
        return_value=[],
    ):
        snapshot = service.resolve_current_aidp_access(
            "https://aidp.example", "key", "u", "tenant"
        )

    assert snapshot.remote_ids == set()
    assert snapshot.accessible_ids == []


def test_force_refresh_reloads_cached_catalog():
    """force_refresh=True bypasses a live cache entry."""
    with patch.object(
        service,
        "fetch_all_aidp_knowledge_bases_impl",
        return_value={"value": [{"kds_id": "1"}]},
    ) as mock_fetch, patch.object(
        service.aidp_permission_service,
        "intersect_accessible_kbs",
        return_value=[],
    ):
        service.resolve_current_aidp_access("https://aidp.example", "key", "u", "tenant")
        service.resolve_current_aidp_access(
            "https://aidp.example", "key", "u", "tenant", force_refresh=True
        )

    assert mock_fetch.call_count == 2


def test_expired_catalog_entry_is_dropped_and_reloaded():
    """A stale cache entry (past TTL) is evicted before reloading."""
    stale_key = service._cache_key("https://aidp.example", "aidp")
    service._catalog_cache[stale_key] = (
        time.monotonic() - 1,
        [{"kds_id": "stale"}],
    )
    with patch.object(
        service,
        "fetch_all_aidp_knowledge_bases_impl",
        return_value={"value": [{"kds_id": "fresh"}]},
    ) as mock_fetch, patch.object(
        service.aidp_permission_service,
        "intersect_accessible_kbs",
        return_value=[],
    ):
        snapshot = service.resolve_current_aidp_access(
            "https://aidp.example", "key", "u", "tenant"
        )

    assert mock_fetch.call_count == 1
    assert snapshot.remote_ids == {"fresh"}


def test_catalog_cache_evicts_lru_entry():
    """Overflowing the bounded catalog cache evicts the least-recently-used key."""
    with patch.object(service, "_CATALOG_CACHE_MAX_ENTRIES", 1), patch.object(
        service,
        "fetch_all_aidp_knowledge_bases_impl",
        return_value={"value": []},
    ) as mock_fetch, patch.object(
        service.aidp_permission_service,
        "intersect_accessible_kbs",
        return_value=[],
    ):
        service.resolve_current_aidp_access("https://one.example", "key", "u", "tenant")
        service.resolve_current_aidp_access("https://two.example", "key", "u", "tenant")

    assert mock_fetch.call_count == 2


def test_version_bump_during_load_skips_cache_write():
    """An invalidation while loading skips persisting the just-loaded entry."""

    def bump_then_return():
        service.invalidate_aidp_catalog_cache("https://aidp.example", "key")
        return {"value": [{"kds_id": "1"}]}

    # MagicMock side_effect lists never invoke stored callables, so dispatch
    # explicitly: the first remote fetch bumps the cache version.
    responses = [bump_then_return, {"value": []}]

    def dispatch(*_args, **_kwargs):
        item = responses.pop(0)
        return item() if callable(item) else item

    with patch.object(
        service,
        "fetch_all_aidp_knowledge_bases_impl",
        side_effect=dispatch,
    ) as mock_fetch, patch.object(
        service.aidp_permission_service,
        "intersect_accessible_kbs",
        return_value=[],
    ):
        first = service.resolve_current_aidp_access("https://aidp.example", "key", "u", "tenant")
        second = service.resolve_current_aidp_access("https://aidp.example", "key", "u", "tenant")

    assert first.remote_ids == {"1"}
    assert second.remote_ids == set()
    assert mock_fetch.call_count == 2


def test_finally_keeps_replaced_inflight_future():
    """The finally block does not pop an inflight entry replaced mid-load."""
    actual_key = service._cache_key("https://aidp.example", "aidp")

    def loader(*_args, **_kwargs):
        with service._cache_lock:
            service._catalog_inflight[actual_key] = Future()
        return {"value": []}

    try:
        with patch.object(
            service,
            "fetch_all_aidp_knowledge_bases_impl",
            side_effect=loader,
        ), patch.object(
            service.aidp_permission_service,
            "intersect_accessible_kbs",
            return_value=[],
        ):
            snapshot = service.resolve_current_aidp_access(
                "https://aidp.example", "key", "u", "tenant"
            )
        assert snapshot.remote_ids == set()
    finally:
        service._catalog_inflight.pop(actual_key, None)


def test_invalidate_detail_and_doc_count_by_prefix_without_kds_id():
    """Invalidation without a kds_id clears every entry under the prefix."""
    detail_loader = MagicMock(return_value={"kds_id": "1"})
    count_loader = MagicMock(return_value=7)

    service.get_cached_aidp_kb_detail("https://aidp.example", "key", "1", detail_loader)
    service.get_cached_aidp_doc_count("https://aidp.example", "key", "1", count_loader)
    service.invalidate_aidp_kb_detail_cache("https://aidp.example", "key")
    service.invalidate_aidp_doc_count_cache("https://aidp.example", "key")
    service.get_cached_aidp_kb_detail("https://aidp.example", "key", "1", detail_loader)
    service.get_cached_aidp_doc_count("https://aidp.example", "key", "1", count_loader)

    assert detail_loader.call_count == 2
    assert count_loader.call_count == 2


def test_remote_item_missing_id_is_skipped():
    """Catalog items without kds_id/id never enter the remote id set."""
    with patch.object(
        service,
        "fetch_all_aidp_knowledge_bases_impl",
        return_value={"value": [{"kds_name": "no-id"}]},
    ), patch.object(
        service.aidp_permission_service,
        "intersect_accessible_kbs",
        return_value=[],
    ):
        snapshot = service.resolve_current_aidp_access(
            "https://aidp.example", "key", "u", "tenant"
        )

    assert snapshot.remote_ids == set()


def test_accessible_row_missing_kb_id_is_skipped():
    """Permission rows without kb_id never contribute to accessible maps."""
    with patch.object(
        service,
        "fetch_all_aidp_knowledge_bases_impl",
        return_value={"value": [{"kds_id": "1"}]},
    ), patch.object(
        service.aidp_permission_service,
        "intersect_accessible_kbs",
        return_value=[{"kds_name": "orphan"}],
    ):
        snapshot = service.resolve_current_aidp_access(
            "https://aidp.example", "key", "u", "tenant"
        )

    assert snapshot.accessible_ids == []
    assert snapshot.name_to_id == {}
