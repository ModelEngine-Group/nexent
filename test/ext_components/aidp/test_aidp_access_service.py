import threading
import time
from concurrent.futures import ThreadPoolExecutor
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


def test_api_key_change_misses_catalog_cache():
    with patch.object(
        service,
        "fetch_all_aidp_knowledge_bases_impl",
        return_value={"value": []},
    ) as mock_fetch, patch.object(
        service.aidp_permission_service,
        "intersect_accessible_kbs",
        return_value=[],
    ):
        service.resolve_current_aidp_access("https://aidp.example", "key-1", "u", "tenant")
        service.resolve_current_aidp_access("https://aidp.example", "key-2", "u", "tenant")

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
