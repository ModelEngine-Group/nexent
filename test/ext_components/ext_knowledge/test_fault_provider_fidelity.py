"""Fault-provider fidelity: the minimal controlled OpenAI-compatible gateway.

Every test here mirrors a concrete suite case (see fault_provider_mock.py's
docstring for the case mapping); the deliberately-absent pieces (/models,
unused markers, usage stats) are pinned by tests too, so nobody re-adds them
"just in case" without a case needing them.
"""
RECOVERY_CONTENT = "CONTROLLED_PROVIDER_RECOVERED_AFTER_RATE_LIMIT"


def _completion(content: str):
    return {"messages": [{"role": "user", "content": content}]}


def test_plain_completion_returns_recovery_content(http_client):
    response = http_client.post(
        "/fault/v1/chat/completions",
        json=_completion("an ordinary prompt"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == "controlled-fault-model"
    assert body["choices"][0]["message"]["content"] == RECOVERY_CONTENT
    assert body["choices"][0]["finish_reason"] == "stop"


def test_regenerate_name_marker_returns_503(http_client):
    response = http_client.post(
        "/fault/v1/chat/completions",
        json=_completion("please force-regenerate-name-failure now"),
    )
    assert response.status_code == 503
    assert response.json()["error"]["message"] == (
        "controlled name-regeneration provider failure"
    )


def test_rate_limit_marker_fails_twice_then_recovers(http_client):
    payload = _completion("Provider 429/5xx/timeout recovery probe")

    first = http_client.post("/fault/v1/chat/completions", json=payload)
    second = http_client.post("/fault/v1/chat/completions", json=payload)
    third = http_client.post("/fault/v1/chat/completions", json=payload)

    assert first.status_code == 429
    assert first.json()["error"]["message"] == "controlled upstream rate limit"
    assert second.status_code == 429
    assert third.status_code == 200
    assert third.json()["choices"][0]["message"]["content"] == RECOVERY_CONTENT


def test_control_plane_reset_rearms_rate_limit_marker(http_client):
    payload = _completion("another provider 429 probe")
    for _ in range(3):  # exhaust the two failures and recover
        http_client.post("/fault/v1/chat/completions", json=payload)
    assert http_client.post("/fault/v1/chat/completions", json=payload).status_code == 200

    reset = http_client.post("/_reset", json={"services": ["fault"]})
    assert reset.status_code == 200
    assert "fault" in reset.json()["reset"]
    assert http_client.post("/fault/v1/chat/completions", json=payload).status_code == 429


def test_stream_completion_is_sse(http_client):
    response = http_client.post(
        "/fault/v1/chat/completions",
        json={**_completion("an ordinary prompt"), "stream": True},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    text = response.text
    assert "chat.completion.chunk" in text
    assert RECOVERY_CONTENT in text
    assert text.strip().endswith("data: [DONE]")


def test_models_endpoint_intentionally_absent(http_client):
    # No suite case calls it: LLM model creation performs no connectivity
    # probe (only embedding models are verified). Keep it absent until a
    # case needs it.
    assert http_client.get("/fault/v1/models").status_code == 404


def test_fail_next_scopes_to_fault_route_set(http_client):
    plan = http_client.post("/_mock/fail-next", json={"service": "fault", "count": 1, "status": 503})
    assert plan.status_code == 200

    # The scheduled failure hits the fault route set...
    assert (
        http_client.post("/fault/v1/chat/completions", json=_completion("an ordinary prompt")).status_code
        == 503
    )
    # ...is exhausted after one hit, and other route sets are unaffected
    # (the dify auth check is reached, not failed).
    assert http_client.get("/dify/v1/datasets").status_code == 401
    assert (
        http_client.post("/fault/v1/chat/completions", json=_completion("an ordinary prompt")).status_code
        == 200
    )
