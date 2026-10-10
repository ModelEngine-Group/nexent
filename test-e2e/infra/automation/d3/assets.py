"""Shared D3 asset helpers with explicit skip reasons and cleanup support."""

from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path
import re
from typing import AsyncIterator
from uuid import uuid4

import pytest

from shared.config import load_secret_env, load_yaml, model_by_type, test_root
from shared.http import assert_status, client
from shared.asset_registry import register_asset, register_asset_failure, resolve_asset


_ASSET_PRODUCERS = {
    ("agents", "basic_id"): "API-055",
    ("agents", "basic_name"): "API-055",
    ("agents", "tool_id"): "API-060",
    ("agents", "plan_id"): "API-060",
    ("agents", "skill_id"): "API-062",
    ("agents", "nested_id"): "API-064",
    ("agents", "parallel_id"): "API-064",
    ("agents", "mcp_id"): "CTR-028",
    ("agents", "mcp_outage_id"): "CTR-028",
    ("agents", "local_a2a_id"): "API-055",
    ("agents", "metadata_id"): "API-055",
    ("agents", "attachment_id"): "API-055",
    ("agents", "knowledge_id"): "API-097",
    ("evaluation", "completed_run_id"): "AGT-059",
    ("automation", "seeded_task_id"): "AGT-054",
    ("reliability", "scheduler_task_id"): "AGT-054",
    ("security", "prompt_injection_agent_id"): "API-055",
    ("sharing", "share_token"): "API-116",
    ("a2a", "local_endpoint_id"): "API-055",
    ("mcp", "service_id"): "CTR-028",
    ("mcp", "service_name"): "CTR-028",
}


def _current_case_id() -> str:
    current = os.environ.get("PYTEST_CURRENT_TEST", "")
    match = re.search(r"\[([^\]]+)\]", current)
    return match.group(1) if match else ""


def configured_model(model_type: str) -> dict:
    try:
        model = model_by_type(model_type)
    except (FileNotFoundError, KeyError, RuntimeError) as exc:
        pytest.skip(f"models.yaml lacks required {model_type} asset: {exc}")
    if not model.get("id") and not model.get("model_id"):
        pytest.skip(f"{model_type} model asset has no id/model_id")
    return model


async def model_id(model_type: str, identity) -> int:
    """Use only the configured model name/type within the authenticated tenant."""
    from shared.model_selection import select_configured_model
    from shared.model_catalog import load_model_catalog
    model = configured_model(model_type)
    rows, selected_config, reader = await load_model_catalog(identity)
    selected_id = None
    if selected_config:
        selected = ((selected_config.get('config') or {}).get('models') or {}).get(
            {'multi_embedding':'multiEmbedding'}.get(model_type,model_type)) or {}
        selected_id = selected.get('id') or selected.get('model_id')
    numeric = select_configured_model(model, model_type, rows, selected_id=selected_id)
    from shared.model_health import ensure_model_health
    row = next(row for row in rows if int(row.get('model_id') or row.get('id') or 0) == numeric)
    await ensure_model_health(reader, model, row)
    return numeric


def _single_model_name(model: dict) -> str | None:
    """Resolve one concrete model name from the asset entry.

    ``model`` may list several comma-separated candidates; prefer
    ``preferred_model`` and otherwise fall back to the first candidate so the
    create request never carries a multi-name string the backend cannot
    resolve against the provider.
    """
    preferred = str(model.get("preferred_model") or "").strip()
    if preferred:
        return preferred
    configured = model.get("model") or model.get("model_name")
    if isinstance(configured, list):
        return next((str(name).strip() for name in configured if str(name).strip()), None)
    raw = str(configured or "").strip()
    if not raw:
        return None
    return raw.split(",")[0].strip()


def model_request(model_type: str, *, display_name: str | None = None) -> dict:
    """Translate the external asset schema into the config-service ModelRequest."""
    model = configured_model(model_type)
    secret_key = model.get("secret_env_key")
    secrets = load_secret_env()
    api_key = secrets.get(str(secret_key), "") if secret_key else str(model.get("api_key") or "")
    if secret_key and not api_key:
        pytest.skip(f"secrets.env lacks {secret_key} for {model_type}")
    configured_name = _single_model_name(model)
    if not configured_name:
        raise ValueError(f"no configured model name for {model_type}")
    return {
        "model_factory": model.get("provider") or model.get("model_factory") or "OpenAI-API-Compatible",
        "model_name": configured_name,
        "model_type": model_type,
        "api_key": api_key,
        "base_url": model.get("base_url") or "",
        "display_name": display_name or model.get("display_name") or model.get("id") or f"daily-{model_type}",
        # Zero is not a usable generation budget. Preserve explicit limits and
        # leave non-generative model semantics (e.g. embedding dimension) alone.
        "max_tokens": model.get("max_tokens") or (4096 if model_type in {"llm", "vlm"} else 0),
        "expected_chunk_size": model.get("dimension") if model_type in {"embedding", "multi_embedding"} else None,
        "model_appid": model.get("model_appid"),
        "access_token": secrets.get(str(model.get("access_token_env_key")), "") if model.get("access_token_env_key") else model.get("access_token"),
    }


def get_test_asset(section: str, key: str, *, required: bool = True):
    return resolve_asset(
        section,
        key,
        required=required,
        consumer_case_id=_current_case_id(),
        dependency_case_id=_ASSET_PRODUCERS.get((section, key), ""),
    )


def asset_path(section: str, key: str) -> Path:
    """Resolve an asset path relative to NEXENT_TEST_HOME and require a real file."""
    configured = Path(str(get_test_asset(section, key)))
    path = configured if configured.is_absolute() else test_root() / configured
    if not path.is_file():
        from shared.asset_registry import AssetDependencyError
        raise AssetDependencyError(
            section, key, _current_case_id(), _ASSET_PRODUCERS.get((section, key), ""),
            detail=f"configured path is not a file: {path}",
        )
    return path


@asynccontextmanager
async def temporary_knowledge_base(
    identity,
    *,
    prefix: str = "d3-kb",
    preserve_source_file: bool = True,
    quota_limit_bytes: int | None = None,
    embedding_model_id: int | None = None,
) -> AsyncIterator[dict]:
    """Create an isolated real KB and remove its ES, DB and MinIO state afterward."""
    display_name = f"{prefix}-{uuid4().hex[:10]}"
    payload = {
        "embedding_model_id": embedding_model_id if embedding_model_id is not None else await model_id("embedding", identity),
        "ingroup_permission": "PRIVATE",
        "group_ids": [],
        "preserve_source_file": preserve_source_file,
    }
    if quota_limit_bytes is not None:
        payload["quota_limit_bytes"] = quota_limit_bytes
    async with client("config", token=identity.access_token) as api:
        response = await api.post(f"/indices/{display_name}", json=payload)
    if response.status_code != 200:
        from shared.factories.knowledge import register_partial_knowledge
        register_partial_knowledge(identity,display_name,owner='TEMPORARY-KB',role=display_name)
    assert_status(response, 200)
    created = response.json()
    internal_name = str(created.get("id") or "")
    if not internal_name:
        raise AssertionError(f"KB creation omitted internal id: {created}")
    created["display_name"] = display_name
    created["index_name"] = internal_name
    registered = bool(os.getenv('RESULT_DIR'))
    if registered:
        register_asset('owned_knowledge', internal_name, internal_name, owner_case_id='TEMPORARY-KB',
            cleanup={'service':'config','identity':identity.id,'method':'DELETE',
                     'path':f'/indices/{internal_name}','allowed_statuses':[200,404]})
    primary_error = None
    try:
        yield created
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        from shared.asset_registry import mark_asset_state
        from shared.factories.knowledge import cleanup_registered_knowledge_files
        try:
            await cleanup_registered_knowledge_files(identity, internal_name)
            async with client("config", token=identity.access_token) as api:
                cleanup = await api.delete(f"/indices/{internal_name}")
            assert_status(cleanup, (200, 404))
            if registered: mark_asset_state('owned_knowledge',internal_name,'DELETED')
        except Exception:
            if registered: mark_asset_state('owned_knowledge',internal_name,'ORPHANED',detail='temporary KB cleanup failed')
            if primary_error is None: raise
            primary_error.add_note('Temporary KB cleanup also failed; inspect owned_knowledge registry.')


@asynccontextmanager
async def temporary_conversation(identity, title: str = "D3 integration") -> AsyncIterator[int]:
    from shared.factories.conversation import owned_conversation
    async with owned_conversation(identity, title) as conversation_id:
        yield conversation_id


async def create_registered_knowledge_base(
    identity,
    *,
    owner_case_id: str,
    role: str = "basic",
    prefix: str = "d3-shared-kb",
    quota_limit_bytes: int | None = None,
    embedding_model_id: int | None = None,
) -> dict:
    """Create a real KB that remains available until batch cleanup."""
    display_name = f"{prefix}-{uuid4().hex[:10]}"
    try:
        payload = {
            "embedding_model_id": embedding_model_id or await model_id("embedding", identity),
            "ingroup_permission": "PRIVATE",
            "group_ids": [],
            "preserve_source_file": True,
        }
        if quota_limit_bytes is not None:
            payload["quota_limit_bytes"] = quota_limit_bytes
        async with client("config", token=identity.access_token) as api:
            response = await api.post(f"/indices/{display_name}", json=payload)
        assert_status(response, 200)
        created = response.json()
        internal_name = str(created.get("id") or "")
        if not internal_name:
            raise AssertionError(f"KB creation omitted internal id: {created}")
        created.update({"display_name": display_name, "index_name": internal_name})
        cleanup = {
            "service": "config", "identity": identity.id, "method": "DELETE",
            "path": f"/indices/{internal_name}", "allowed_statuses": [200, 404],
        }
        register_asset(
            "knowledge", f"{role}_index", internal_name,
            owner_case_id=owner_case_id, cleanup=cleanup,
        )
        register_asset(
            "knowledge", f"{role}_display_name", display_name, owner_case_id=owner_case_id,
        )
        knowledge_id = created.get("knowledge_id")
        if knowledge_id not in (None, ""):
            register_asset("knowledge", f"{role}_id", knowledge_id, owner_case_id=owner_case_id)
        return created
    except Exception as exc:
        from shared.factories.knowledge import register_partial_knowledge
        try:
            register_partial_knowledge(identity,display_name,owner=owner_case_id,role=role)
        except Exception as reconciliation_error:
            # Preserve both faults; never report cleanup PASS on an unknown
            # partial create. The journal retains this unresolved obligation.
            register_asset_failure('knowledge',role+'_reconciliation',owner_case_id=owner_case_id,
                                   reason=str(reconciliation_error))
            raise RuntimeError('KB preparation and partial-resource reconciliation both failed') from exc
        if resolve_asset("knowledge", f"{role}_index", required=False) is None:
            register_asset_failure(
                "knowledge", f"{role}_index", owner_case_id=owner_case_id, reason=str(exc),
            )
        raise
