# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Check the controlled provider without standing up a product stack."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
from threading import Thread
from time import monotonic, sleep
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "test-e2e/infra/automation"))

from shared.runtime_scaling_model import MODEL_NAME, INPUT_NAME, OUTPUT_NAME, fixture_server
from shared.runtime_scaling_k8s import (
    MODEL_FIXTURE, NAMESPACE, RUNTIME, RUN_LABEL, IsolationError, RuntimeScalingCluster, stage_deployment,
)
from shared.runtime_scaling_owner_loss import model_receipt


@pytest.fixture
def provider(request):
    token = uuid4().hex
    with fixture_server(token, host="127.0.0.1", port=0, mode=getattr(request, "param", "storage")) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        try:
            yield origin, token
        finally:
            call(origin, "/release", {})
            server.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive()


def call(origin, path, request=None):
    data = None if request is None else json.dumps(request).encode()
    with urlopen(Request(origin + path, data=data, headers={"Content-Type": "application/json"}), timeout=10) as response:
        return response.read().decode()


def model_request(token, **changes):
    return {"model": MODEL_NAME, "stream": True,
            "messages": [{"role": "user", "content": f"runtime-storage-run:{token}"}], **changes}


@pytest.mark.parametrize("provider", ["storage-pair"], indirect=True)
def test_storage_pair_releases_only_the_selected_agent_and_tracks_both_tool_rounds(provider):
    origin, token = provider

    def turn(role):
        return call(origin, "/v1/chat/completions", model_request(token, messages=[
            {"role": "user", "content": f"runtime-storage-pair:{token}:{role}"},
            {"role": "tool", "content": "previous result"},
        ]))

    for role in ("a-extra", "b-", "other"):
        with pytest.raises(HTTPError, match="400"):
            turn(role)
    with pytest.raises(HTTPError, match="409"):
        call(origin, "/release/a", {})

    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = {role: executor.submit(turn, role) for role in ("a", "b")}
        try:
            deadline = monotonic() + 4
            while json.loads(call(origin, "/probe"))["calls_by_tag"] != {"a": 1, "b": 1}:
                assert monotonic() < deadline, "Both tool rounds did not reach the provider"
                sleep(0.01)
            assert all(not execution.done() for execution in pending.values())
            for role in ("a", "b"):
                assert json.loads(call(origin, f"/release/{role}", {})) == {"released": True}
                result = pending[role].result(timeout=4)
                assert "upload_to_s3" in result and INPUT_NAME in result and OUTPUT_NAME in result
                assert f"runtime-storage-completed:{token}:{role}" in turn(role)
                if role == "a":
                    assert not pending["b"].done()
                    assert json.loads(call(origin, "/probe"))["released_tags"] == ["a"]
            assert json.loads(call(origin, "/probe")) == {
                "stream_calls": 4, "unexpected_calls": 3, "calls_by_tag": {"a": 2, "b": 2},
                "released_tags": ["a", "b"], "entered": True, "released": False,
            }
            with pytest.raises(HTTPError, match="409"):
                turn("a")
        finally:
            call(origin, "/release", {})


@pytest.mark.parametrize("provider", ["stream"], indirect=True)
def test_stream_provider_flushes_unicode_prefix_and_releases_turns_independently(provider):
    origin, token = provider

    def open_turn(tag):
        payload = model_request(token, messages=[{"role": "user", "content": f"runtime-stream:{token}:{tag}"}])
        request = Request(origin + "/v1/chat/completions", data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"})
        return urlopen(request, timeout=10)

    with open_turn("first") as first, open_turn("second") as second, ThreadPoolExecutor(max_workers=2) as executor:
        for tag, stream in (("first", first), ("second", second)):
            prefix = json.loads(stream.readline().decode().removeprefix("data: "))
            assert prefix["choices"][0]["delta"]["reasoning_content"] == f"stream-prefix:{tag}:界🌊"
        pending = [executor.submit(stream.read) for stream in (first, second)]
        try:
            assert json.loads(call(origin, "/probe"))["calls_by_tag"] == {"first": 1, "second": 1}
            with pytest.raises(HTTPError, match="409"):
                call(origin, "/release/not-entered", {})
            assert json.loads(call(origin, "/release/first", {}))["released"] is True
            assert b"stream-tail:first:" in pending[0].result(timeout=5)
            assert not pending[1].done()
        finally:
            call(origin, "/release/second", {})
        assert b"stream-tail:second:" in pending[1].result(timeout=5)
    with pytest.raises(HTTPError, match="409"):
        open_turn("first")
    with pytest.raises(AssertionError, match="calls_by_tag"):
        model_receipt(lambda action: json.loads(call(origin, f"/{action}")), "first", "second")


@pytest.mark.parametrize("provider", ["stream"], indirect=True)
def test_owner_model_receipt_rejects_an_unexpected_nonstream_call(provider):
    origin, token = provider

    def control(action):
        return json.loads(call(origin, f"/{action}"))

    assert model_receipt(control)["auxiliary_calls"] == 0
    call(origin, "/v1/chat/completions", model_request(token, stream=False))
    with pytest.raises(AssertionError, match="auxiliary_calls"):
        model_receipt(control)
    assert model_receipt(control, allow_auxiliary=True)["auxiliary_calls"] == 1


@pytest.mark.parametrize("provider", ["maintenance"], indirect=True)
def test_maintenance_provider_counts_tool_round_and_blocks_only_followup(provider):
    origin, token = provider
    route = "/v1/chat/completions"
    user = {"role": "user", "content": f"runtime-stream:{token}:retry-owner"}
    payload = model_request(token, messages=[user])
    first = call(origin, route, payload)
    deltas = [json.loads(line[6:])["choices"][0]["delta"] for line in first.splitlines() if line.startswith("data: {")]
    assert deltas[0]["content"] == (
        f'<code>\nprint(upload_to_s3("inputs/000_{INPUT_NAME}", "runtime-maintenance-retry-owner.txt"))\n</code>'
    )
    with pytest.raises(HTTPError, match="409"):
        call(origin, "/release/retry-owner", {})

    payload["messages"].append({"role": "user", "content": "Observation: tool step finished"})
    request = Request(origin + route, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=10) as response:
        prefix = json.loads(response.readline().decode().removeprefix("data: "))
        assert prefix["choices"][0]["delta"]["reasoning_content"] == "stream-prefix:retry-owner:界🌊"
        receipt = model_receipt(lambda action: json.loads(call(origin, f"/{action}")), "retry-owner", rounds=2)
        assert receipt["stream_calls"] == 2
        assert json.loads(call(origin, "/release/retry-owner", {}))["released"] is True
        assert b"stream-tail:retry-owner:" in response.read()
    with pytest.raises(HTTPError, match="409"):
        call(origin, route, payload)
    assert json.loads(call(origin, "/probe"))["calls_by_tag"] == {"retry-owner": 3}


@pytest.mark.parametrize("provider", ["scheduler"], indirect=True)
def test_scheduler_provider_counts_repeated_occurrences_of_the_same_task(provider):
    origin, token = provider
    request = model_request(token, messages=[{"role": "user", "content": f"runtime-stream:{token}:auto"}])
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(call, origin, "/v1/chat/completions", request)
        deadline = monotonic() + 5
        try:
            while not json.loads(call(origin, "/probe"))["entered"] and monotonic() < deadline:
                sleep(0.02)
            assert json.loads(call(origin, "/probe"))["calls_by_tag"] == {"auto": 1}
            assert not first.done()
        finally:
            call(origin, "/release/auto", {})
        assert "stream-tail:auto:" in first.result(timeout=5)

    assert "stream-tail:auto:" in call(origin, "/v1/chat/completions", request)
    with pytest.raises(HTTPError, match="409"):
        call(origin, "/v1/chat/completions", request)
    assert json.loads(call(origin, "/probe"))["calls_by_tag"] == {"auto": 3}


def test_provider_blocks_then_emits_fixed_upload_and_final_answer(provider):
    origin, token = provider
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(call, origin, "/v1/chat/completions", model_request(token))
        try:
            deadline = monotonic() + 5
            while not json.loads(call(origin, "/probe"))["entered"] and monotonic() < deadline:
                sleep(0.02)
            assert not pending.done()
            assert json.loads(call(origin, "/probe")) == {
                "entered": True, "released": False, "stream_calls": 1, "unexpected_calls": 0,
            }
        finally:
            assert json.loads(call(origin, "/release", {})) == {"released": True}
        first = pending.result(timeout=5)
    second = call(origin, "/v1/chat/completions", model_request(token))
    deltas = [json.loads(line[6:])["choices"][0]["delta"] for line in first.splitlines() if line.startswith("data: {")]
    assert deltas[0]["content"] == f'<code>\nprint(upload_to_s3("inputs/000_{INPUT_NAME}", "{OUTPUT_NAME}"))\n</code>'
    assert f"runtime-storage-completed:{token}" in second and second.endswith("data: [DONE]\n\n")
    with pytest.raises(HTTPError, match="409"):
        call(origin, "/v1/chat/completions", model_request(token))


def test_provider_rejects_unrelated_requests_without_entering_barrier(provider):
    origin, token = provider
    with pytest.raises(HTTPError, match="400"):
        call(origin, "/v1/chat/completions", model_request(token, model="other-model"))
    with pytest.raises(HTTPError, match="400"):
        call(origin, "/v1/chat/completions", model_request(uuid4().hex))
    title = json.loads(call(origin, "/v1/chat/completions", model_request(token, stream=False)))
    assert title["choices"][0]["message"]["content"] == "Runtime storage fixture"
    assert json.loads(call(origin, "/probe")) == {
        "entered": False, "released": False, "stream_calls": 0, "unexpected_calls": 2,
    }


@pytest.mark.parametrize("provider", ["admission"], indirect=True)
def test_admission_provider_counts_distinct_waiters_and_auxiliary_calls(provider):
    origin, token = provider
    route = "/v1/chat/completions"

    def request(tag):
        return model_request(token, messages=[{"role": "user", "content": f"runtime-admission:{token}:{tag}"}])

    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = {tag: executor.submit(call, origin, route, request(tag)) for tag in ("race-a", "second-slot")}
        try:
            deadline = monotonic() + 5
            while True:
                snapshot = json.loads(call(origin, "/probe"))
                if snapshot["stream_calls"] == 2:
                    break
                assert monotonic() < deadline
                sleep(0.02)
            assert snapshot["calls_by_tag"] == {"race-a": 1, "second-slot": 1}
            assert not any(future.done() for future in pending.values())
            with pytest.raises(HTTPError, match="409"):
                call(origin, route, request("race-a"))
        finally:
            call(origin, "/release", {})
        for tag, response in pending.items():
            assert f"runtime-admitted:{tag}" in response.result(timeout=5)
    call(origin, route, {**request("race-a"), "stream": False})
    completed = json.loads(call(origin, "/probe"))
    assert completed["calls_by_tag"] == {"race-a": 2, "second-slot": 1}
    assert completed["auxiliary_calls"] == 1 and completed["auxiliary_tags"] == ["race-a"]
    assert completed["released"] is True


def test_only_staged_environment_receives_test_agent_quota(tmp_path):
    repository = Path(__file__).resolve().parents[4]
    template = repository / "deploy/env/.env.example"
    before = template.read_bytes()
    root = tmp_path / "stage"
    stage_deployment(repository, root, agent_limit=2)
    staged = (root / "deploy/env/.env.example").read_text(encoding="utf-8").splitlines()
    assert [line for line in staged if line.startswith("RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS=")] == [
        "RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS=2",
    ]
    assert template.read_bytes() == before and not (root / "deploy/env/.env").exists()


def test_scheduler_settings_are_only_written_to_the_scheduler_release(tmp_path):
    repository = Path(__file__).resolve().parents[4]
    relative_template = Path("deploy/env/.env.example")
    before = (repository / relative_template).read_bytes()
    baseline, scheduler = tmp_path / "baseline", tmp_path / "scheduler"
    stage_deployment(repository, baseline)
    stage_deployment(repository, scheduler, scheduler_case=True)
    settings = (scheduler / relative_template).read_text(encoding="utf-8").splitlines()
    for key, value in {"AGENT_AUTOMATION_ENABLED": "false", "AGENT_AUTOMATION_MAX_CONCURRENT_RUNS": "1",
                       "AGENT_AUTOMATION_POLL_INTERVAL_SECONDS": "1", "AGENT_AUTOMATION_LEASE_SECONDS": "30"}.items():
        assert [line for line in settings if line.startswith(f"{key}=")] == [f"{key}={value}"]
    assert (baseline / relative_template).read_bytes() == (repository / relative_template).read_bytes() == before


@pytest.fixture
def boundary(tmp_path, monkeypatch):
    cluster = RuntimeScalingCluster(SimpleNamespace(wait_seconds=30), tmp_path)
    requests = []

    def kubectl(*args, stdin=None, **kwargs):
        requests.append((args, json.loads(stdin) if stdin else None))
        return stdin or ""

    monkeypatch.setattr(cluster, "_kubectl", kubectl)
    monkeypatch.setattr(cluster, "require_owned_namespace", lambda: None)
    return cluster, requests


def test_fixture_model_uses_release_image_and_internal_service(boundary):
    cluster, requests = boundary
    pod = {"metadata": {"namespace": NAMESPACE, "labels": {"app": RUNTIME}}, "spec": {"containers": [
        {"name": RUNTIME, "image": "fixture/nexent:tested", "imagePullPolicy": "Never", "envFrom": ["not copied"]},
    ]}}
    cluster.create_runtime_model(pod)
    (_, model), (_, service), (wait, _) = requests
    assert model["kind"] == "Pod" and model["metadata"]["namespace"] == NAMESPACE
    assert model["spec"]["automountServiceAccountToken"] is False and "volumes" not in model["spec"]
    container, = model["spec"]["containers"]
    assert (container["image"], container["imagePullPolicy"]) == ("fixture/nexent:tested", "Never")
    assert "envFrom" not in container and "env" not in container
    assert container["command"][-1] == cluster.run_id
    assert service["kind"] == "Service" and service["metadata"]["namespace"] == NAMESPACE
    assert service["spec"] == {"selector": {"app": MODEL_FIXTURE, RUN_LABEL: cluster.run_id},
                               "ports": [{"port": 8090, "targetPort": 8090}]}
    assert wait[:5] == ("wait", "-n", NAMESPACE, "--for=condition=Ready", f"pod/{MODEL_FIXTURE}")


@pytest.mark.parametrize("override", [{"type": "NodePort"}, {"externalIPs": ["192.0.2.8"]},
                                     {"selector": {"app": MODEL_FIXTURE}}, {"ports": [{"port": 80, "nodePort": 31000}]}])
def test_model_service_rejects_exposure_outside_the_case(boundary, override):
    cluster, requests = boundary
    spec = {"selector": {RUN_LABEL: cluster.run_id}, "ports": [{"port": 8090}], **override}
    with pytest.raises(IsolationError, match="cluster-internal"):
        cluster.create_namespaced_fixture({"kind": "Service", "metadata": {"name": MODEL_FIXTURE}, "spec": spec})
    assert not requests
