# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Assembly-level tests: control plane, AIDP root mount, fault-injection scoping.

These exercise the unified service itself (no product adapter imports).

The first block below is the original fidelity set (10 tests). The
``--- new regressions ---`` block covers the unified-control-plane additions
(identity endpoint, full-AIDP reset semantics, ModelService fail-budget
scoping, wire-log truncation accounting) and is counted separately from the
original 57 fidelity assertions.
"""
import sys
import time
from pathlib import Path

AIDP_KB_LIST = "/KnowledgeBase/Tenants/aidp/KnowledgeBases"
AIDP_AUTH = {"Authorization": "Bearer mock-aidp-key"}
DIFY_AUTH = {"Authorization": "Bearer any-key"}
FAQ_HISTORY = "/KnowledgeBase/Tenants/aidp/KnowledgeBases/aidp-kb-faq/KnowledgeFiles/History"


def test_health_reports_every_route_set(http_client):
    body = http_client.get("/health").json()
    assert body["status"] == "ok"
    for service in ("dify", "datamate", "idata", "ragflow", "haotian", "assets", "aidp"):
        assert body["services"][service] == "ok"


def test_aidp_protocol_is_mounted_at_root(http_client):
    response = http_client.get(AIDP_KB_LIST, headers=AIDP_AUTH)
    assert response.status_code == 200
    body = response.json()
    # Untouched AIDP mock: 25 seed KBs, default page_size 20 -> one page.
    assert len(body["value"]) == 20
    assert body["next_link"] is not None


def test_aidp_auth_is_enforced_by_the_sub_app(http_client):
    assert http_client.get(AIDP_KB_LIST).status_code == 401


def test_control_reset_restores_aidp_seed_state(http_client):
    created = http_client.put(AIDP_KB_LIST, headers=AIDP_AUTH, json={"name": "temporary-kb"})
    assert created.status_code == 200

    reset = http_client.post("/_reset")
    assert reset.status_code == 200
    assert "aidp" in reset.json()["reset"]

    listing = http_client.get(
        AIDP_KB_LIST, headers=AIDP_AUTH, params={"page": 1, "page_size": 100}
    )
    names = [kb["kds_name"] for kb in listing.json()["value"]]
    assert "temporary-kb" not in names
    assert len(names) == 25


def test_fail_next_is_scoped_to_one_route_set(http_client):
    plan = http_client.post("/_mock/fail-next", json={"service": "dify", "count": 1, "status": 503})
    assert plan.status_code == 200

    # The scheduled route set fails...
    assert http_client.get("/v1/datasets", headers=DIFY_AUTH).status_code == 503
    # ...others keep working...
    assert (
        http_client.post("/api/knowledge-base/list", json={"page": 1, "size": 20}).status_code
        == 200
    )
    # ...including AIDP, which owns its own scoped failure middleware.
    assert http_client.get(AIDP_KB_LIST, headers=AIDP_AUTH).status_code == 200
    # The counter is exhausted after one hit.
    assert http_client.get("/v1/datasets", headers=DIFY_AUTH).status_code == 200


def test_aidp_fail_next_proxies_to_the_sub_app(http_client):
    plan = http_client.post("/_mock/fail-next", json={"service": "aidp", "count": 1, "status": 503})
    assert plan.status_code == 200
    assert http_client.get(AIDP_KB_LIST, headers=AIDP_AUTH).status_code == 503
    assert http_client.get(AIDP_KB_LIST, headers=AIDP_AUTH).status_code == 200


def test_latency_injection_adds_delay(http_client):
    assert (
        http_client.post("/_mock/latency", json={"service": "dify", "delay_ms": 200}).status_code
        == 200
    )
    started = time.perf_counter()
    assert http_client.get("/v1/datasets", headers=DIFY_AUTH).status_code == 200
    assert time.perf_counter() - started >= 0.18


def test_wire_log_records_traffic(http_client):
    http_client.post("/api/knowledge-base/list", json={"page": 1, "size": 5})
    records = http_client.get("/_wire-log", params={"service": "datamate"}).json()["records"]
    assert any(record["path"] == "/api/knowledge-base/list" for record in records)


def test_reset_rejects_unknown_service(http_client):
    assert http_client.post("/_reset", json={"services": ["nope"]}).status_code == 400


def test_unknown_paths_return_404(http_client):
    assert http_client.get("/v1/unknown-endpoint").status_code == 404
    # Unprefixed unknown paths fall through to the AIDP sub-app's 404.
    assert http_client.get("/definitely-not-a-route").status_code == 404


# ---------------------------------------------------------------------------
# --- new regressions (unified control plane additions) — counted separately --
# ---------------------------------------------------------------------------


def test_identity_reports_session_metadata(http_client, expected_identity):
    body = http_client.get("/_mock/identity").json()
    assert body["service"] == "ext-knowledge"
    assert body["run_id"] == expected_identity["run_id"]
    assert body["source_revision"] == expected_identity["source_revision"]
    assert body["build_manifest_sha256"] == expected_identity["build_manifest_sha256"]
    # Identity never carries credential material.
    assert set(body) == {"service", "run_id", "source_revision", "build_manifest_sha256"}


def test_mock_state_exposes_fault_plan_and_identity(http_client, expected_identity):
    plan = http_client.post("/_mock/fail-next", json={"service": "ragflow", "count": 2, "status": 429})
    assert plan.status_code == 200

    state = http_client.get("/_mock/state").json()
    assert state["faults"]["fail_remaining"] == {"ragflow": 2}
    assert state["faults"]["fail_status"] == {"ragflow": 429}
    assert state["identity"]["run_id"] == expected_identity["run_id"]


def test_modelservice_calls_do_not_consume_aidp_fail_budget(http_client):
    # The AIDP sub-app's failure middleware only intercepts /KnowledgeBase;
    # /ModelService traffic must pass through without spending the budget.
    plan = http_client.post("/_mock/fail-next", json={"service": "aidp", "count": 1, "status": 503})
    assert plan.status_code == 200

    models = http_client.get("/ModelService/Tenants/aidp/Service", headers=AIDP_AUTH)
    assert models.status_code == 200

    assert http_client.get(AIDP_KB_LIST, headers=AIDP_AUTH).status_code == 503
    assert http_client.get(AIDP_KB_LIST, headers=AIDP_AUTH).status_code == 200


def test_aidp_unified_reset_restores_knobs_and_failures(http_client):
    """The unified reset must undo failure plans AND runtime knobs.

    The AIDP sub-app's own /_reset only clears KB/document data; without the
    unified sequence a case that tuned knobs (or armed failures) would leak
    them into the next case. Everything below is driven through the PUBLIC
    control endpoints and verified by observable behavior.
    """
    # Arm a failure and verify it bites.
    plan = http_client.post("/_mock/fail-next", json={"service": "aidp", "count": 1, "status": 503})
    assert plan.status_code == 200
    assert http_client.get(AIDP_KB_LIST, headers=AIDP_AUTH).status_code == 503

    # Processing knob: an upload stays hidden from the completed listing.
    api_files_path = "/KnowledgeBase/Tenants/aidp/KnowledgeBases/aidp-kb-api/KnowledgeFiles"
    knob = http_client.post("/_mock/processing-seconds", params={"seconds": 30})
    assert knob.status_code == 200 and knob.json()["processing_seconds"] == 30
    upload = http_client.post(
        "/KnowledgeBase/Tenants/aidp/KnowledgeBases/aidp-kb-api/KnowledgeFiles/Upload",
        headers=AIDP_AUTH,
        files={"files": ("processing-probe.txt", b"probe", "text/plain")},
    )
    assert upload.status_code == 200
    listing = http_client.get(api_files_path, headers=AIDP_AUTH)
    assert listing.status_code == 200
    # With processing=30 the new document is not COMPLETED yet, so the
    # completed listing for that KB stays empty.
    assert listing.json()["value"] == []

    # File-query fault (global knob): the completed-files listing must fail.
    files_path = "/KnowledgeBase/Tenants/aidp/KnowledgeBases/aidp-kb-faq/KnowledgeFiles"
    faults = http_client.post("/_mock/file-faults", params={"query_fail": "true"})
    assert faults.status_code == 200 and faults.json()["query_fail"] is True
    assert http_client.get(files_path, headers=AIDP_AUTH).status_code == 503

    # History page-size knob: one entry per page while set to 1.
    history_knob = http_client.post("/_mock/history-page-size", params={"size": 1})
    assert history_knob.status_code == 200
    history = http_client.post(
        FAQ_HISTORY, headers=AIDP_AUTH,
        json={"dir_path": "/aidp/knowledge/aidp-kb-faq", "page": 1},
    )
    assert history.status_code == 200
    assert len(history.json()["value"]) == 1
    assert history.json()["next_link"] is not None

    # --- the unified reset must restore all of it in one call ---
    reset = http_client.post("/_reset", json={"services": ["aidp"]})
    assert reset.status_code == 200
    assert reset.json()["reset"] == ["aidp"]

    # Failure plan cleared: the KB listing answers 200 again.
    assert http_client.get(AIDP_KB_LIST, headers=AIDP_AUTH).status_code == 200
    # File-query fault cleared: the completed listing is served again.
    assert http_client.get(files_path, headers=AIDP_AUTH).status_code == 200
    # Processing knob restored to 0: a fresh upload is immediately visible.
    upload = http_client.post(
        "/KnowledgeBase/Tenants/aidp/KnowledgeBases/aidp-kb-api/KnowledgeFiles/Upload",
        headers=AIDP_AUTH,
        files={"files": ("completed-probe.txt", b"probe", "text/plain")},
    )
    assert upload.status_code == 200
    listing = http_client.get(api_files_path, headers=AIDP_AUTH)
    assert listing.status_code == 200
    assert [doc["file_name"] for doc in listing.json()["value"]] == ["completed-probe.txt"]
    # History page size restored to 10: both FAQ documents fit one page.
    history = http_client.post(
        FAQ_HISTORY, headers=AIDP_AUTH,
        json={"dir_path": "/aidp/knowledge/aidp-kb-faq", "page": 1},
    )
    assert history.status_code == 200
    assert len(history.json()["value"]) == 4
    assert history.json()["next_link"] is None


def test_wire_log_reports_truncation_accounting(http_client):
    assert http_client.post("/_wire-log/clear").status_code == 200
    for _ in range(3):
        assert http_client.get("/health").status_code == 200
    body = http_client.get("/_wire-log", params={"limit": 2}).json()
    # The clear request itself is recorded after its handler empties the log
    # (the wire middleware logs on the way out), so retained counts it plus
    # the three health probes. The exporter can still tell "asked for fewer"
    # (records) from "ring full" (dropped): a limited response with dropped=0
    # is a complete log.
    assert len(body["records"]) == 2
    assert body["retained"] == 4
    assert body["dropped"] == 0
    assert all(record["path"] == "/health" for record in body["records"])


def test_wire_log_drop_counter_is_accounted_in_memory():
    """Pure in-memory check of the ring-buffer eviction accounting."""
    module_dir = Path(__file__).resolve().parents[2] / "test-e2e" / "infra" / "mock-services" / "ext-knowledge-mock"
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))
    from mock_common import WireLog

    log = WireLog(maxlen=3)
    for index in range(5):
        log.record("control", "GET", f"/p{index}", 200, 1.0)
    assert log.stats() == {"retained": 3, "dropped": 2}
    assert [record["path"] for record in log.query(limit=10)] == ["/p2", "/p3", "/p4"]
    log.clear()
    assert log.stats() == {"retained": 0, "dropped": 0}
