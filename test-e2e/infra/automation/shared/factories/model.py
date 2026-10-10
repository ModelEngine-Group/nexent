"""Case-owned configured models for tenants without preinstalled anchors."""
from contextlib import asynccontextmanager
from uuid import uuid4

from d3.assets import configured_model, model_request
from shared.asset_registry import AssetDependencyError, mark_asset_state, register_asset
from shared.http import assert_status, client
from shared.model_health import ensure_model_health


@asynccontextmanager
async def owned_configured_model(identity, case_id, model_type="llm"):
    """Copy configuration, not an ID, into this tenant; never change defaults."""
    display = f"case-{case_id.lower()}-{uuid4().hex}"
    payload = {**model_request(model_type, display_name=display),
               "skip_default_backfill": True}
    primary = None
    created = False
    try:
        async with client("config", token=identity.access_token) as api:
            response = await api.post("/model/create", json=payload)
            if response.status_code == 409 and model_type in {"embedding", "multi_embedding"}:
                message = response.json().get("message", "")
                if isinstance(message, str) and message.startswith("Failed to get embedding dimension for model"):
                    raise AssetDependencyError("models", model_type,
                        detail="configured vector Provider dimension probe failed; no model was created")
            assert_status(response, 200)
            created = True
            register_asset("owned_models", display, display, owner_case_id=case_id,
                cleanup={"service": "config", "identity": identity.id, "method": "POST",
                         "path": "/model/delete", "params": {"display_name": display},
                         "allowed_statuses": [200, 404]})
            listing = await api.get("/model/list")
            assert_status(listing, 200)
            matches = [row for row in listing.json().get("data", [])
                       if row.get("display_name") == display and row.get("model_type") == model_type]
            assert len(matches) == 1, "Owned model must be uniquely visible in its tenant"
            row = matches[0]
            await ensure_model_health(identity, configured_model(model_type), row)
        yield int(row.get("model_id") or row["id"])
    except BaseException as exc:
        primary = exc
        raise
    finally:
        if created:
            try:
                async with client("config", token=identity.access_token) as api:
                    deleted = await api.post("/model/delete", params={"display_name": display})
                assert_status(deleted, (200, 404))
                mark_asset_state("owned_models", display, "DELETED")
            except Exception as exc:
                mark_asset_state("owned_models", display, "ORPHANED", detail=type(exc).__name__)
                if primary is None:
                    raise
                primary.add_note("Owned model cleanup also failed; inspect the asset journal")
