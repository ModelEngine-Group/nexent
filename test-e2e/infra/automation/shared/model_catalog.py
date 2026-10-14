"""Tenant-scoped model discovery for test asset preparation, not ACL assertions."""
from shared.asset_registry import AssetDependencyError
from shared.auth import sign_in
from shared.config import load_yaml
from shared.http import assert_status, client


async def catalog_reader(identity):
    users = load_yaml("users.yaml").get("users") or []
    candidates = [row for row in users
                  if row.get("tenant") == identity.configured_tenant
                  and str(row.get("role") or "").lower() in {"admin", "speed"}]
    if len(candidates) != 1:
        raise AssetDependencyError("identities", "model_catalog_reader",
                                   detail="Exactly one configured same-tenant model administrator is required")
    reader = await sign_in(str(candidates[0]["id"]))
    if reader.tenant_id != identity.tenant_id or reader.role not in {"ADMIN", "SPEED"}:
        raise AssetDependencyError("identities", "model_catalog_reader",
                                   detail="Configured administrator does not match the runtime test tenant/role")
    return reader


async def load_model_catalog(identity):
    """Only discovery/health uses the reader; runtime calls keep their own user."""
    async with client("config", token=identity.access_token) as api:
        response = await api.get("/model/list")
    reader = identity
    if response.status_code == 403 and identity.role in {"USER", "DEV", "DEVELOPER"}:
        reader = await catalog_reader(identity)
        async with client("config", token=reader.access_token) as api:
            response = await api.get("/model/list")
    assert_status(response, 200)
    async with client("config", token=reader.access_token) as api:
        selected_response = await api.get("/config/load_config")
    body = response.json()
    rows = body if isinstance(body, list) else body.get("data") or body.get("models") or []
    selected = selected_response.json() if selected_response.status_code == 200 else {}
    return rows, selected, reader

