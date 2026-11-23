"""Check configured voice models through the current model-management APIs."""

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from d3.assets import model_request
from shared.asset_registry import mark_asset_state, register_asset
from shared.case_evidence import write_case_evidence
from shared.http import MODEL_TIMEOUT, client


async def request(identity, method, path, *, label, secrets=(), **kwargs):
    """Record sanitized receipts before asserting; never log request credentials."""
    async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        response = await api.request(method, path, **kwargs)
    try:
        body = response.json()
    except ValueError:
        body = {"non_json_response": True}
    write_case_evidence(label, {
        "endpoint": path, "http_status": response.status_code, "body": body,
    }, secrets=secrets)
    assert not any(value and value in response.text for value in secrets), (
        f"{label}: response exposed a model credential"
    )
    return response


async def catalog(identity, kind):
    response = await request(identity, "GET", "/model/list", label=f"API-054-{kind}-catalog")
    assert response.status_code == 200, "Model catalog read failed"
    rows = response.json().get("data")
    assert isinstance(rows, list), "Model catalog must return an array"
    return rows


async def defaults(identity, kind):
    response = await request(identity, "GET", "/config/load_config", label=f"API-054-{kind}-defaults")
    assert response.status_code == 200, "Default model configuration read failed"
    config = response.json().get("config")
    assert isinstance(config, dict), "Default configuration read omitted config"
    return config.get("models") or {}


def assert_probe(response, *, connected, model_name):
    assert response.status_code == 200, f"Model connectivity API returned HTTP {response.status_code}"
    data = response.json().get("data")
    assert isinstance(data, dict), "Model connectivity response omitted data"
    assert data.get("model_name") == model_name, "Health check targeted a different model"
    assert data.get("connectivity") is connected, f"Expected connectivity={connected}"
    if not connected:
        assert isinstance(data.get("error"), str) and data["error"].strip(), (
            "Failed connectivity must include a nonempty diagnostic error"
        )


@asynccontextmanager
async def owned_model(identity, payload):
    """Journal a unique resource before creating it so interruption is recoverable."""
    name = payload["display_name"]
    register_asset("owned_models", name, name, owner_case_id="API-054", cleanup={
        "service": "config", "identity": identity.id, "method": "POST",
        "path": "/model/delete", "params": {"display_name": name}, "allowed_statuses": [200, 404],
    })
    primary_error = None
    secrets = tuple(value for value in (payload.get("api_key"), payload.get("access_token")) if value)
    kind = payload["model_type"]
    try:
        response = await request(identity, "POST", "/model/create", label=f"API-054-{kind}-create",
                                 secrets=secrets, json={**payload, "skip_default_backfill": True})
        assert response.status_code == 200, f"Owned voice model creation returned HTTP {response.status_code}"
        yield name
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        try:
            deleted = await request(identity, "POST", "/model/delete", label=f"API-054-{kind}-delete",
                                    secrets=secrets, params={"display_name": name})
            assert deleted.status_code in {200, 404}, "Owned model cleanup failed"
            assert not any(row.get("display_name") == name for row in await catalog(identity, kind)), (
                "Owned voice model remains after cleanup"
            )
            mark_asset_state("owned_models", name, "DELETED")
        except Exception as cleanup_error:
            mark_asset_state("owned_models", name, "ORPHANED", detail="API-054 model cleanup failed")
            if primary_error is None:
                raise
            primary_error.add_note(f"Owned model cleanup also failed: {type(cleanup_error).__name__}")


async def exercise_voice_model(identity, kind):
    payload = model_request(kind, display_name=f"api-054-{kind}-{uuid4().hex}")
    secrets = tuple(value for value in (payload.get("api_key"), payload.get("access_token")) if value)
    assert secrets, "Voice model configuration must provide a credential"
    before = await catalog(identity, kind)
    selected = await defaults(identity, kind)

    # Probes do not persist configuration; a valid credential cannot rescue
    # a negative probe through the edit-dialog stored-key fallback.
    good = await request(identity, "POST", "/model/temporary_healthcheck",
                         label=f"API-054-{kind}-temporary-valid", secrets=secrets, json=payload)
    assert_probe(good, connected=True, model_name=payload["model_name"])
    invalid_credential = "invalid-" + uuid4().hex
    negative = {**payload, "api_key": invalid_credential, "access_token": invalid_credential}
    bad = await request(identity, "POST", "/model/temporary_healthcheck",
                        label=f"API-054-{kind}-temporary-invalid", secrets=(*secrets, invalid_credential),
                        json=negative)
    assert_probe(bad, connected=False, model_name=payload["model_name"])
    # Validation errors can echo the rejected input. Send no real credential
    # when intentionally exercising a malformed request.
    malformed = {key: payload[key] for key in ("model_name", "model_factory", "base_url", "display_name")}
    invalid = await request(identity, "POST", "/model/temporary_healthcheck",
                            label=f"API-054-{kind}-validation", secrets=secrets, json=malformed)
    assert invalid.status_code == 422, "Missing model_type must be rejected by request validation"
    assert await catalog(identity, kind) == before, "Temporary probes changed the model catalog"
    assert await defaults(identity, kind) == selected, "Temporary probes changed default models"

    async with owned_model(identity, payload) as name:
        rows = await catalog(identity, kind)
        matching = [row for row in rows if row.get("display_name") == name]
        assert len(matching) == 1, "Owned voice model was not uniquely persisted"
        row = matching[0]
        assert row.get("model_type") == kind and row.get("model_name") == payload["model_name"], (
            "Saved voice model does not match machine-local configuration"
        )
        assert row.get("base_url") == payload["base_url"], "Saved voice endpoint does not match configuration"
        assert row.get("model_factory") == payload["model_factory"], "Saved voice provider changed"
        assert "api_key" not in row and not row.get("access_token"), "Catalog must not return stored credentials"
        # Deliberately send no credentials: this proves the service reads the
        # credentials belonging to this exact saved tenant-local model.
        health = await request(identity, "POST", "/model/healthcheck",
                               label=f"API-054-{kind}-saved-health", secrets=secrets,
                               params={"display_name": name, "model_type": kind})
        assert_probe(health, connected=True, model_name=payload["model_name"])
        refreshed = [item for item in await catalog(identity, kind) if item.get("display_name") == name]
        assert len(refreshed) == 1 and refreshed[0].get("connect_status") == "available", (
            "Saved-model connectivity did not persist available status"
        )
        assert await defaults(identity, kind) == selected, "Owned voice model changed tenant defaults"
    assert await defaults(identity, kind) == selected, "Cleanup changed tenant defaults"


@pytest.mark.case_id("API-054")
@pytest.mark.stage("D3")
@pytest.mark.asyncio
async def test_configured_voice_model_connectivity(tenant_a_admin):
    failures = []
    for kind in ("stt", "tts"):
        try:
            await exercise_voice_model(tenant_a_admin, kind)
        except AssertionError as exc:
            failures.append(f"{kind}: {exc}")
    assert not failures, "; ".join(failures)
