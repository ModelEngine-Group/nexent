# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Read-only profile discovery for LLM onboarding from the pinned local catalog."""

from functools import lru_cache
import re

from contracts.errors.exceptions import DuplicateError, ModelOutletConflictError, ModelOutletValidationError

from nexent.core.model_service.profiles.parameter_schema import _json_copy
from nexent.core.model_service.profiles.resolver import load_profile_catalog
from nexent.core.model_service.registry import model_service_references


from nexent.core.model_service.profiles.configuration import _patch_credentials as _patch_credentials


from nexent.core.model_service.profiles.configuration import _validate_credential_input as _validate_credential_input


@lru_cache(maxsize=1)
def get_model_profile_catalog():
    """Load one immutable catalog per process; deployment updates invalidate it by restart."""
    return load_profile_catalog()


def list_atomic_profiles(kind, *, query="", family=None, page=1, page_size=20):
    """Return reference summaries, never imply that copied entries are qualified outlets."""
    if (kind not in ("model", "provider") or type(page) is not int or page < 1
            or type(page_size) is not int or not 1 <= page_size <= 100
            or not isinstance(query, str) or len(query) > 200
            or (family is not None and (not isinstance(family, str) or len(family) > 100))):
        raise ModelOutletValidationError()
    catalog = get_model_profile_catalog()
    entries = catalog.models if kind == "model" else catalog.providers
    needle = query.strip().casefold()
    selected = []
    for key, atom in sorted(entries.items()):
        identity = atom.source.identity
        name = identity.get("name", key)
        model_family = identity.get("family")
        if family and (model_family or "").casefold() != family.casefold():
            continue
        if needle and needle not in (key + " " + name).casefold():
            continue
        item = {"key": key, "name": name, "revision": atom.revision, "catalog_kind": kind,
                "qualification": "reference_only"}
        if kind == "model":
            item["family"] = model_family
            parameters = _json_copy(atom.parameters)
            item["configuration"] = {
                "capabilities": _json_copy(atom.capabilities),
                "field_specs": parameters,
                "parameter_values": {
                    rule["key"]: rule["fixed_value"] if "fixed_value" in rule else rule["default_value"]
                    for rule in parameters if "fixed_value" in rule or "default_value" in rule
                },
            }
        else:
            item["endpoint_hints"] = list(atom.endpoint_hints)
            suggested = atom.source.connection_suggestions.get("base_url")
            if suggested:
                item["suggested_base_url"] = suggested
        selected.append(item)
    offset = (page - 1) * page_size
    return {"catalog_revision": catalog.revision, "items": selected[offset:offset + page_size],
            "total": len(selected), "page": page, "page_size": page_size}


def list_profile_protocols():
    """Expose only executable protocol references; unknown API families are not choices."""
    references = model_service_references()
    return {"items": [{"ref": reference.ref, "version": reference.version}
                      for reference in references["protocol"]],
            "authentication_schemes": [{"ref": reference.ref, "version": reference.version}
                                       for reference in references["auth"]]}


from nexent.core.model_service.profiles.configuration import _select_profile as _select_profile


from nexent.core.model_service.profiles.configuration import _validate_request_output_limit as _validate_request_output_limit


from nexent.core.model_service.profiles.configuration import _clear_sampling_parameters as _clear_sampling_parameters


from nexent.core.model_service.profiles.configuration import _patch_context_limits as _patch_context_limits


def build_outlet_draft(request, tenant_id, *, require_revision=False):
    from nexent.core.model_service.profiles.configuration import build_outlet_draft as compile_draft

    return compile_draft(request, tenant_id, require_revision=require_revision, catalog=get_model_profile_catalog())


def preview_model_profile(request, tenant_id):
    from contracts.model import ModelProfilePreviewRequest

    data = request.model_dump(exclude_unset=True)
    data["display_name"] = data.get("display_name") or None
    connection = data.setdefault("provider_info", {})
    connection["base_url"] = connection.get("base_url") or "https://profile-preview.invalid"
    data["request_model_id"] = data.get("request_model_id") or (
        request.model_profile.key.rsplit("/", 1)[-1] if request.model_profile else "profile-preview")
    profile, candidates = build_outlet_draft(ModelProfilePreviewRequest.model_validate(data), tenant_id)
    return {"catalog_revision": get_model_profile_catalog().revision, "candidates": candidates,
            "matched_profile": bool(profile.model_profile_key or
                f"{profile.provider_key}/{profile.identity.request_model_id}" in get_model_profile_catalog().provider_models),
            "selected": {"model": profile.model_profile_key, "provider": profile.provider_key},
            "field_specs": profile.parameter_rules, "parameter_values": profile.parameter_values,
            "capabilities": profile.capabilities.model_dump(mode="json"),
            "instruction_mapping": profile.instruction_mapping.model_dump(mode="json"),
            "conflicts": []}


def _backfill_new_outlet(model_id, user_id, tenant_id):
    from management.services.model.management import _backfill_default_model_slots

    return _backfill_default_model_slots(user_id, tenant_id, new_model_ids=[model_id])


def create_model_outlet(request, user_id, tenant_id):
    """Persist the server-composed snapshot and keep credentials out of the response."""
    from management.db.model.repository import get_models_by_display_name
    from management.db.model.outlets import create_resolved_model_record
    from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile

    profile, _ = build_outlet_draft(request, tenant_id, require_revision=True)
    if get_models_by_display_name(profile.identity.display_name, tenant_id):
        raise DuplicateError()
    model_id = create_resolved_model_record(profile, user_id, tenant_id,
        registered_references=model_service_references(), api_key=request.api_key, http_headers=request.http_headers,
        connect_status=request.connect_status or "not_detected")
    data = profile.model_dump(mode="json")
    data["outlet_id"] = model_id
    data["connection"]["credential_ref"]["model_id"] = model_id
    saved = ResolvedModelProfile.model_validate(data)
    defaults = []  # A newly saved outlet has not passed connectivity yet.
    return {"auto_configured_defaults": defaults, "model_id": model_id, "config_revision": saved.config_revision, "profile": saved.model_dump(mode="json"),
            "has_credential": bool(request.api_key and request.api_key.strip()),
            "http_header_names": sorted(request.http_headers)}


def get_model_outlet(model_id, tenant_id):
    """Read the saved snapshot without consulting the current TOML catalog."""
    from management.db.model.outlets import get_resolved_model_record, has_model_outlet_credential

    profile = get_resolved_model_record(model_id, tenant_id, registered_references=model_service_references())
    if profile is None:
        return None
    if profile.identity.model_type != "llm":
        raise ModelOutletValidationError()
    from nexent.core.model_service.profiles.outlet_controls import ensure_outlet_parameter_rules

    profile = ensure_outlet_parameter_rules(profile)
    from management.db.model.repository import get_model_by_model_id

    row = get_model_by_model_id(model_id, tenant_id) or {}
    return {"model_id": model_id, "config_revision": profile.config_revision,
            "profile": profile.model_dump(mode="json"), "field_specs": profile.parameter_rules,
            "http_header_names": sorted(row.get("http_headers") or {}),
            "has_credential": has_model_outlet_credential(model_id, tenant_id)}


def reselect_outlet_profile(profile, request):
    from nexent.core.model_service.profiles.configuration import reselect_outlet_profile as transform

    return transform(profile, request, compose=build_outlet_draft)


def preview_outlet_patch(model_id, request, tenant_id):
    """Preview exactly the same saved-snapshot update used by checks and persistence."""
    current, _, _ = _load_validation_outlet(model_id, tenant_id)
    if current.config_revision != request.expected_revision:
        raise ModelOutletConflictError()
    profile = apply_outlet_patch(current, request)
    reference = profile.provenance.atomic_refs.model or profile.provenance.atomic_refs.provider
    return {"catalog_revision": request.profile_selection.catalog_revision if request.profile_selection else
                (reference.catalog_revision if reference else "saved"),
            "selected": {"model": profile.model_profile_key, "provider": profile.provider_key},
            "candidates": {"models": [], "providers": []}, "field_specs": profile.parameter_rules,
            "parameter_values": profile.parameter_values, "capabilities": profile.capabilities.model_dump(mode="json"),
            "instruction_mapping": profile.instruction_mapping.model_dump(mode="json"), "conflicts": []}


def apply_outlet_patch(profile, request):
    from nexent.core.model_service.profiles.configuration import apply_outlet_patch as transform

    return transform(profile, request, compose=build_outlet_draft)


def update_model_outlet(model_id, request, user_id, tenant_id):
    """Update a frozen outlet with CAS; preserve omitted credentials and fields."""
    from management.db.model.repository import get_models_by_display_name, get_model_by_model_id
    from management.db.model.outlets import get_resolved_model_record, update_resolved_model_record, has_model_outlet_credential

    refs = model_service_references()
    current = get_resolved_model_record(model_id, tenant_id, registered_references=refs)
    if current is None:
        raise LookupError("MODEL_OUTLET_NOT_FOUND")
    if current.identity.model_type != "llm":
        raise ModelOutletValidationError()
    if current.config_revision != request.expected_revision:
        raise ModelOutletConflictError()
    proposed = apply_outlet_patch(current, request)
    if proposed.identity.display_name != current.identity.display_name:
        if any(row["model_id"] != model_id for row in get_models_by_display_name(proposed.identity.display_name, tenant_id)):
            raise ModelOutletConflictError()
    credentials = {"api_key": request.api_key} if "api_key" in request.model_fields_set else {}
    row = get_model_by_model_id(model_id, tenant_id) or {}
    key, headers = _patch_credentials(request, row.get("api_key"), row.get("http_headers") or {})
    if "http_headers" in request.model_fields_set or "api_key" in request.model_fields_set:
        credentials["http_headers"] = headers
    status = request.connect_status
    if status is not None:
        credentials["connect_status"] = status
    revision = update_resolved_model_record(proposed, request.expected_revision, user_id, tenant_id,
                                           registered_references=refs, replacement_base=reselect_outlet_profile(current, request)
                                           if request.profile_selection is not None else None, **credentials)
    data = proposed.model_dump(mode="json")
    data["config_revision"] = revision
    return {"model_id": model_id, "config_revision": revision, "profile": data,
            "has_credential": has_model_outlet_credential(model_id, tenant_id),
            "http_header_names": sorted(credentials.get("http_headers", (get_model_by_model_id(model_id, tenant_id) or {}).get("http_headers") or {}))}


def _load_validation_outlet(model_id, tenant_id):
    from management.db.model.repository import get_model_by_model_id
    from nexent.core.model_service.profiles.outlet_storage import decode_resolved_model_profile, ProfileStorageError

    row = get_model_by_model_id(model_id, tenant_id=tenant_id)
    if row is None:
        raise LookupError("MODEL_OUTLET_NOT_FOUND")
    try:
        profile = decode_resolved_model_profile(row, registered_references=model_service_references())
        if profile.identity.tenant_id != tenant_id or profile.identity.model_type != "llm" or profile.outlet_id != model_id:
            raise ModelOutletValidationError()
        from nexent.core.model_service.profiles.outlet_controls import ensure_outlet_parameter_rules

        return ensure_outlet_parameter_rules(profile), row.get("api_key"), row.get("http_headers") or {}
    except ProfileStorageError:
        raise ModelOutletValidationError("PROFILE_STORAGE_INVALID") from None


async def validate_model_outlet(request, tenant_id, *, is_disconnected=None, persist_status=True, user_id=None):
    """Probe one captured endpoint/model with the common sender; no tool qualification."""
    from nexent.core.concurrency import run_blocking

    if request.outlet_id is not None:
        profile, key, headers = await run_blocking("outlet-validation-load", _load_validation_outlet, request.outlet_id, tenant_id)
        if request.expected_revision is not None and profile.config_revision != request.expected_revision:
            raise ModelOutletConflictError()
        if request.patch is not None:
            if request.patch.expected_revision != profile.config_revision:
                raise ModelOutletConflictError()
            profile = apply_outlet_patch(profile, request.patch)
            key, headers = _patch_credentials(request.patch, key, headers)
    else:
        profile, _ = await run_blocking("outlet-validation-draft", build_outlet_draft, request.draft, tenant_id)
        key = request.draft.api_key
        headers = getattr(request.draft, "http_headers", {})
    if is_disconnected is not None and await is_disconnected():
        import asyncio
        raise asyncio.CancelledError()
    result = await _probe_with_disconnect(profile, key, headers, is_disconnected, user_id=user_id)
    if is_disconnected is not None and await is_disconnected():
        import asyncio
        raise asyncio.CancelledError()
    ok, error = result["ok"], result["error"]
    if persist_status and request.outlet_id is not None and request.patch is None:
        from management.db.model.outlets import update_model_outlet_connectivity

        await run_blocking("outlet-validation-status", update_model_outlet_connectivity,
            request.outlet_id, tenant_id, profile.config_revision, "available" if ok else "unavailable")
    return {"ok": ok, "error": error, "check_scope": "connection_only",
            "model_id": profile.outlet_id, "config_revision": profile.config_revision}


async def _probe_with_disconnect(profile, key, headers, is_disconnected, *, user_id=None):
    """Own and reap the in-flight HTTP probe when its request disappears."""
    import asyncio

    actor = {"user_id": user_id} if user_id is not None else {}
    if is_disconnected is None:
        return await probe_model_profile(profile, key, http_headers=headers, **actor)
    task = asyncio.create_task(
        probe_model_profile(profile, key, http_headers=headers, **actor), name="model-outlet-connectivity",
    )
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=0.05)
            if not task.done() and await is_disconnected():
                raise asyncio.CancelledError()
        return await task
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


async def probe_model_profile(profile, key, *, http_headers=None, user_id=None):
    """Send the captured policy to the authenticated Runtime probe boundary."""
    from backend.http.client import create_httpx_client
    from contracts.agentos import ModelAdministrationOperation
    from contracts.constants.environment import RUNTIME_SERVICE_URL
    from contracts.model_administration import ModelProfileProbe
    from gateway.identity.context import trusted_identity
    from management.clients.agentos import AgentOSClient

    tenant_id = profile.identity.tenant_id
    if user_id is None:
        identity = trusted_identity()
        if identity is not None and identity.get("tenant_id") == tenant_id:
            user_id = identity.get("user_id")
    if not user_id:
        raise ValueError("Authenticated actor is required for model connectivity validation")
    payload = ModelProfileProbe(profile=profile.model_dump(mode="json"), api_key=key,
                                http_headers=http_headers or {})
    return await AgentOSClient(RUNTIME_SERVICE_URL, create_httpx_client).model_command(
        ModelAdministrationOperation.PROFILE_PROBE, payload, user_id, tenant_id,
    )


from nexent.core.model_service.profiles.probe_diagnostics import _probe_diagnostic as _probe_diagnostic


def confirm_outlet_migration(model_id, request, user_id, tenant_id):
    """Confirm saved migration metadata under the authenticated tenant."""
    from management.db.model.outlets import confirm_model_outlet_migration

    return confirm_model_outlet_migration(model_id, tenant_id, user_id, request.expected_revision,
        registered_references=model_service_references())
