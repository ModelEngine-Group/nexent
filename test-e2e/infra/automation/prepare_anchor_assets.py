"""Prepare and verify long-lived, non-secret test anchor assets.

The script uses supported Nexent APIs for tenant/user/group/model creation. It
never writes passwords or API keys to anchor-assets.yaml. Existing assets are
reconciled idempotently and then verified through the same public read/login
interfaces used by later stages.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any
from uuid import uuid4

import yaml

from shared.auth import configured_user, sign_in
from shared.config import load_secret_env, load_yaml, test_root
from shared.http import assert_status, client


ROLE_MAP = {"admin": "ADMIN", "developer": "DEV", "dev": "DEV", "user": "USER"}
INVITE_MAP = {"ADMIN": "ADMIN_INVITE", "DEV": "DEV_INVITE", "USER": "USER_INVITE"}


def _data(response) -> Any:
    payload = response.json()
    return payload.get("data") if isinstance(payload, dict) and "data" in payload else payload


def _entry(value: Any, *, source: str = "anchor") -> dict[str, Any]:
    return {
        "value": value,
        "state": "READY",
        "source": source,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def _write_anchor(payload: dict[str, Any]) -> None:
    path = test_root() / "config" / "anchor-assets.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="anchor-assets.", suffix=".yaml", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


async def _ensure_tenant(api, name: str, actions: list[dict[str, str]]) -> str:
    listed = await api.post("/tenants/tenant-list", json={"page": 1, "page_size": 100})
    assert_status(listed, 200)
    rows = _data(listed) or []
    matches = [row for row in rows if str(row.get("tenant_name") or row.get("name") or "") == name]
    if len(matches) > 1:
        raise AssertionError(f"multiple anchor tenants named {name!r}")
    if matches:
        tenant_id = str(matches[0].get("tenant_id") or matches[0].get("id") or "")
        actions.append({"asset": f"tenant:{name}", "action": "UNCHANGED"})
        return tenant_id
    created = await api.post("/tenants", json={"tenant_name": name, "locale": "zh"})
    assert_status(created, 201)
    row = _data(created) or {}
    tenant_id = str(row.get("tenant_id") or row.get("id") or "")
    if not tenant_id:
        raise AssertionError(f"tenant creation returned no id for {name!r}")
    actions.append({"asset": f"tenant:{name}", "action": "CREATED"})
    return tenant_id


async def _ensure_group(api, tenant_id: str, label: str, actions: list[dict[str, str]]) -> int:
    listed = await api.post("/groups/list", json={"tenant_id": tenant_id, "search": label})
    assert_status(listed, 200)
    rows = _data(listed) or []
    matches = [row for row in rows if str(row.get("group_name") or row.get("name") or "") == label]
    if len(matches) > 1:
        raise AssertionError(f"multiple anchor groups named {label!r} in tenant {tenant_id}")
    if matches:
        group_id = int(matches[0].get("group_id") or matches[0].get("id"))
        actions.append({"asset": f"group:{label}", "action": "UNCHANGED"})
    else:
        created = await api.post("/groups", json={
            "tenant_id": tenant_id,
            "group_name": label,
            "group_description": "Nexent automated test anchor group",
        })
        assert_status(created, 201)
        row = _data(created) or {}
        group_id = int(row.get("group_id") or row.get("id"))
        actions.append({"asset": f"group:{label}", "action": "CREATED"})
    selected = await api.put(f"/groups/tenants/{tenant_id}/default", json={"default_group_id": group_id})
    assert_status(selected, 200)
    return group_id


async def _signup_missing_user(
    api,
    record: dict[str, Any],
    password: str,
    tenant_id: str,
    group_id: int,
) -> None:
    role = ROLE_MAP.get(str(record.get("role") or "").lower())
    if role not in INVITE_MAP:
        raise AssertionError(f"unsupported anchor role for {record['id']}: {record.get('role')}")
    invitation_code = f"NX{role[:3]}{uuid4().hex[:16]}".upper()
    created = await api.post("/invitations", json={
        "tenant_id": tenant_id,
        "code_type": INVITE_MAP[role],
        "invitation_code": invitation_code,
        "group_ids": [group_id],
        "capacity": 1,
    })
    assert_status(created, 201)
    async with client("config") as anonymous:
        signup = await anonymous.post("/user/signup", json={
            "email": record["username"],
            "password": password,
            "invite_code": invitation_code,
            "auto_login": False,
        })
    assert_status(signup, 200)


async def _ensure_users(
    api,
    tenant_ids: dict[str, str],
    group_ids: dict[str, int],
    actions: list[dict[str, str]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    asset_owner_enabled = bool((load_yaml("environment.yaml").get("features") or {}).get("asset_owner"))
    for record in load_yaml("users.yaml").get("users") or []:
        identity_id = str(record["id"])
        if identity_id == "super_admin":
            identity = await sign_in(identity_id)
            result[identity_id] = identity
            actions.append({"asset": f"user:{identity_id}", "action": "VERIFIED"})
            continue
        if str(record.get("role") or "").lower() == "asset_owner":
            if not asset_owner_enabled:
                actions.append({"asset": f"user:{identity_id}", "action": "SKIPPED_BY_POLICY"})
                continue
            identity = await sign_in(identity_id)
            if identity.tenant_id != "asset_owner_tenant_id" or identity.role.upper() != "ASSET_OWNER":
                raise AssertionError(f"anchor user {identity_id} is not an ASSET_OWNER identity")
            result[identity_id] = identity
            actions.append({"asset": f"user:{identity_id}", "action": "VERIFIED"})
            continue
        configured_tenant = str(record.get("tenant") or "")
        tenant_id = tenant_ids[configured_tenant]
        try:
            identity = await sign_in(identity_id)
            action = "UNCHANGED"
        except AssertionError:
            _, password = configured_user(identity_id)
            await _signup_missing_user(api, record, password, tenant_id, group_ids[configured_tenant])
            identity = await sign_in(identity_id)
            action = "CREATED"
        expected_role = ROLE_MAP[str(record.get("role") or "").lower()]
        if identity.tenant_id != tenant_id:
            raise AssertionError(
                f"anchor user {identity_id} belongs to tenant {identity.tenant_id}, expected {tenant_id}"
            )
        if identity.role.upper() != expected_role:
            raise AssertionError(
                f"anchor user {identity_id} has role {identity.role}, expected {expected_role}"
            )
        result[identity_id] = identity
        actions.append({"asset": f"user:{identity_id}", "action": action})
    return result


def _model_targets() -> list[dict[str, Any]]:
    secrets = load_secret_env()
    models = load_yaml("models.yaml").get("models") or []
    targets: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for configured in models:
        capability = str(configured.get("capability") or configured.get("model_type") or "").lower()
        if capability not in {"llm", "vlm", "embedding"}:
            continue
        names = [part.strip() for part in str(configured.get("model") or "").split(",") if part.strip()]
        if capability == "embedding":
            preferred = str(configured.get("preferred_model") or "").strip()
            names = [preferred or names[0]]
        model_type = "llm" if capability == "vlm" else capability
        for index, name in enumerate(names):
            key = (model_type, name)
            if key in seen:
                continue
            seen.add(key)
            secret_key = str(configured.get("secret_env_key") or "")
            api_key = secrets.get(secret_key, "")
            if not api_key:
                raise AssertionError(f"missing secret {secret_key} for anchor model {name}")
            targets.append({
                "capability": capability,
                "model_factory": "OpenAI-API-Compatible",
                "model_name": name,
                "model_type": model_type,
                "api_key": api_key,
                "base_url": str(configured.get("base_url") or ""),
                "display_name": name,
                # The product stores embedding vector dimension in max_tokens.
                "max_tokens": int((configured.get("dimension") if model_type == "embedding" else configured.get("max_tokens")) or (4096 if model_type == "llm" else 0)),
                "expected_chunk_size": configured.get("dimension") if model_type == "embedding" else None,
                "anchor_key": (
                    ("primary_" if index == 0 else "secondary_") + capability + "_id"
                ),
            })
    return targets


async def _ensure_models(identity, actions: list[dict[str, str]]) -> dict[str, int]:
    resolved: dict[str, int] = {}
    async with client("config", token=identity.access_token, timeout=300) as api:
        for target in _model_targets():
            listed = await api.get("/model/list")
            assert_status(listed, 200)
            rows = _data(listed) or []
            matches = [row for row in rows if
                str(row.get("display_name") or "") == target["display_name"]
                and str(row.get("model_type") or "").lower() == target["model_type"]]
            if len(matches) > 1:
                raise AssertionError(f"multiple anchor model records for {target['display_name']!r}")
            request = {key: value for key, value in target.items() if key not in {"capability", "anchor_key"}}
            # Registration is not connectivity. Only the model actually
            # consumed by an asset factory is probed by shared.model_health.
            # Dedicated connectivity test cases still call the real endpoint.
            if matches:
                # The create endpoint normalizes a repo-qualified name such as
                # ``BAAI/bge-m3`` into model_repo/model_name, while the update
                # endpoint accepts an untyped dict and does not perform that
                # normalization.  Reconstruct the persisted representation so
                # repeated reconciliation cannot turn it into
                # ``BAAI/BAAI/bge-m3``.
                model_repo, separator, normalized_name = target["model_name"].partition("/")
                if not separator:
                    model_repo, normalized_name = "", model_repo
                update_request = {
                    **request,
                    "model_repo": model_repo,
                    "model_name": normalized_name,
                }
                updated = await api.post(
                    "/model/update",
                    params={"display_name": target["display_name"]},
                    json=update_request,
                )
                assert_status(updated, 200)
                action = "UPDATED"
            else:
                created = await api.post("/model/create", json=request)
                assert_status(created, 200)
                action = "CREATED"
            listed = await api.get("/model/list")
            assert_status(listed, 200)
            rows = _data(listed) or []
            row = next(row for row in rows if
                str(row.get("display_name") or "") == target["display_name"]
                and str(row.get("model_type") or "").lower() == target["model_type"])
            resolved[target["anchor_key"]] = int(row.get("model_id") or row.get("id"))
            actions.append({"asset": f"model:{target['display_name']}", "action": action})
    return resolved


async def main() -> None:
    actions: list[dict[str, str]] = []
    super_admin = await sign_in("super_admin")
    async with client("config", token=super_admin.access_token) as api:
        tenant_ids = {
            name: await _ensure_tenant(api, name, actions)
            for name in ("tenant_a", "tenant_b")
        }
        group_ids = {
            name: await _ensure_group(api, tenant_id, f"{name}-automation-default", actions)
            for name, tenant_id in tenant_ids.items()
        }
        identities = await _ensure_users(api, tenant_ids, group_ids, actions)

    models = await _ensure_models(identities["tenant_a_admin"], actions)
    existing = load_yaml("anchor-assets.yaml")
    existing["schema_version"] = 2
    existing["identity"] = {
        "tenant_a_id": _entry(tenant_ids["tenant_a"]),
        "tenant_b_id": _entry(tenant_ids["tenant_b"]),
        **{f"{name}_user_id": _entry(identity.user_id) for name, identity in identities.items()},
    }
    existing["groups"] = {
        "tenant_a_default_group_id": _entry(group_ids["tenant_a"]),
        "tenant_b_default_group_id": _entry(group_ids["tenant_b"]),
    }
    existing["models"] = {key: _entry(value) for key, value in models.items()}
    existing["last_verified_at"] = datetime.now(timezone.utc).isoformat()
    _write_anchor(existing)

    report = {
        "status": "PASS",
        "verified_at": existing["last_verified_at"],
        "actions": actions,
        "tenants": sorted(tenant_ids),
        "users": sorted(identities),
        "model_anchor_keys": sorted(models),
        "model_verification": "registration_only; health checked on actual model consumption",
    }
    result_dir = os.environ.get("RESULT_DIR", "").strip()
    if result_dir:
        output = Path(result_dir) / "d0" / "anchor-assets.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
