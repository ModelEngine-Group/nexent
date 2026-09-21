"""Assembly-level tests: control plane, AIDP root mount, fault-injection scoping.

These exercise the unified service itself (no product adapter imports).
"""
import time

AIDP_KB_LIST = "/KnowledgeBase/Tenants/aidp/KnowledgeBases"
AIDP_AUTH = {"Authorization": "Bearer mock-aidp-key"}
DIFY_AUTH = {"Authorization": "Bearer any-key"}


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
    assert http_client.get("/dify/v1/datasets", headers=DIFY_AUTH).status_code == 503
    # ...others keep working...
    assert (
        http_client.post("/datamate/api/knowledge-base/list", json={"page": 1, "size": 20}).status_code
        == 200
    )
    # ...including AIDP, which owns its own scoped failure middleware.
    assert http_client.get(AIDP_KB_LIST, headers=AIDP_AUTH).status_code == 200
    # The counter is exhausted after one hit.
    assert http_client.get("/dify/v1/datasets", headers=DIFY_AUTH).status_code == 200


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
    assert http_client.get("/dify/v1/datasets", headers=DIFY_AUTH).status_code == 200
    assert time.perf_counter() - started >= 0.18


def test_wire_log_records_traffic(http_client):
    http_client.post("/datamate/api/knowledge-base/list", json={"page": 1, "size": 5})
    records = http_client.get("/_wire-log", params={"service": "datamate"}).json()["records"]
    assert any(record["path"] == "/datamate/api/knowledge-base/list" for record in records)


def test_reset_rejects_unknown_service(http_client):
    assert http_client.post("/_reset", json={"services": ["nope"]}).status_code == 400


def test_unknown_paths_return_404(http_client):
    assert http_client.get("/dify/nope").status_code == 404
    # Unprefixed unknown paths fall through to the AIDP sub-app's 404.
    assert http_client.get("/definitely-not-a-route").status_code == 404
