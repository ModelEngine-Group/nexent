# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Read-only profile discovery for LLM onboarding from the pinned local catalog."""

from functools import lru_cache
import hmac
import json
import re
import secrets
import time

from contracts.errors.exceptions import DuplicateError, ModelOutletConflictError, ModelOutletValidationError

from nexent.core.model_service.profiles.parameter_schema import _json_copy
from nexent.core.model_service.profiles.resolver import load_profile_catalog
from nexent.core.model_service.registry import model_service_references


# Standalone development may have no shared auth secret. Such receipts are
# intentionally invalid after process restart or across unconfigured workers.
_PROCESS_RECEIPT_KEY = secrets.token_hex(32)


def _receipt_signature(body):
    from contracts.constants.environment import SUPABASE_JWT_SECRET
    from infrastructure.security.signatures import calculate_hmac_signature

    return calculate_hmac_signature(SUPABASE_JWT_SECRET or _PROCESS_RECEIPT_KEY,
        "model-connectivity-v1", "", body)


def _receipt_binding(profile, key, headers):
    from nexent.core.model_service.profiles.protocol_parameters import connectivity_request
    from nexent.core.model_service.connection_headers import connection_headers

    material = [profile.identity.tenant_id, profile.outlet_id,
        profile.config_revision if profile.outlet_id is not None else None,
        connectivity_request(profile), key or "",
        connection_headers(headers or {}, api_key=key)]
    return _receipt_signature(json.dumps(_json_copy(material), sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def _issue_check_receipt(profile, key, headers, ok):
    body = json.dumps([int(time.time()) + 3600, "available" if ok else "unavailable",
        _receipt_binding(profile, key, headers)], separators=(",", ":"))
    return body + "." + _receipt_signature(body)


def _checked_status(receipt, profile, key, headers):
    """Ignore stale/forged proof without preventing a valid configuration save."""
    if not receipt:
        return None
    try:
        body, signature = receipt.rsplit(".", 1)
        if not hmac.compare_digest(_receipt_signature(body), signature):
            return None
        expires, status, binding = json.loads(body)
        if expires <= time.time() or status not in ("available", "unavailable"):
            return None
        if hmac.compare_digest(binding, _receipt_binding(profile, key, headers)):
            return status
    except (ValueError, TypeError):
        return None
    return None


def _patch_credentials(request, key, headers):
    """Resolve write-only credential edits equally for preview checks and save."""
    from nexent.core.model_service.connection_headers import connection_headers

    key = request.api_key if "api_key" in request.model_fields_set else key
    supplied = (request.http_headers or {}) if "http_headers" in request.model_fields_set else headers
    existing = {name.lower(): value for name, value in headers.items()}
    try:
        merged = {name: existing[name.lower()] if value is None else value for name, value in supplied.items()}
        return key, connection_headers(merged, api_key=key)
    except (ValueError, KeyError):
        raise ModelOutletValidationError("MODEL_HTTP_HEADERS_INVALID", "/http_headers") from None


def _validate_credential_input(value):
    """Reject UI masking sentinels before persistence or model transport."""
    if value and (set(value.strip()) == {"*"} or "********" in value):
        raise ModelOutletValidationError()


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


def _select_profile(catalog, request, kind):
    """Use explicit versioned selections or an unambiguous exact automatic suggestion."""
    from urllib.parse import urlsplit

    entries = catalog.models if kind == "model" else catalog.providers
    explicit = request.model_profile if kind == "model" else request.provider_profile
    if explicit is not None:
        atom = entries.get(explicit.key)
        if atom is None:
            raise ModelOutletValidationError()
        if atom.revision != explicit.revision:
            raise ModelOutletConflictError()
        return explicit.key, [explicit.key]
    if request.selection_mode == "manual":
        return None, []
    if kind == "model":
        def identity(value):
            return re.sub(r"[^a-z0-9]", "", re.sub(r"(glm)[\s/_-]*v(?=\d)", r"\1", value.casefold()))

        requested = {identity(request.request_model_id), identity(request.request_model_id.rsplit("/", 1)[-1])}
        candidates = [key for key, atom in entries.items()
                      if requested.intersection((identity(key), identity(key.split("/", 1)[-1])))
                      or request.request_model_id in atom.aliases]
    else:
        endpoint = urlsplit(request.provider_info.base_url)
        candidates = []
        for key, atom in entries.items():
            if request.provider_info.provider_id == key:
                candidates.append(key)
                continue
            hints = list(atom.endpoint_hints)
            suggested = atom.source.connection_suggestions.get("base_url")
            if suggested:
                hints.append(suggested)
            if any((endpoint.scheme, endpoint.netloc, endpoint.path.rstrip("/")) ==
                   (urlsplit(hint).scheme, urlsplit(hint).netloc, urlsplit(hint).path.rstrip("/")) for hint in hints):
                candidates.append(key)
    return (candidates[0] if len(candidates) == 1 else None), sorted(candidates)


def _validate_request_output_limit(profile):
    from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError

    output = profile.parameter_values.get("max_output_tokens")
    limits = [value for value in (profile.capabilities.context.combined_window,
                                 profile.capabilities.context.output_limit) if value is not None]
    if type(output) is int and limits and output > min(limits):
        raise ParameterValidationError("PARAMETER_LIMIT_EXCEEDED", "/max_output_tokens")
    return profile


def _patch_context_limits(data, patch):
    """Bound inherited hidden limits when the user reduces the effective window."""
    context = data["capabilities"]["context"]
    context.update(patch)
    window = patch.get("combined_window")
    if type(window) is int:
        for key in ("input_limit", "output_limit"):
            if key not in patch and type(context.get(key)) is int:
                context[key] = min(context[key], window)


def build_outlet_draft(request, tenant_id, *, require_revision=False):
    """Recompose trusted policy at preview/save; never accept a client effective profile."""
    from urllib.parse import urlsplit

    from nexent.core.model_service.profiles.composition import (
        ProfileCompositionError,
        compose_provider_model_policy,
    )
    from nexent.core.model_service.profiles.contracts import VersionedReference
    from nexent.core.model_service.profiles.outlet_resolution import (
        OutletResolutionError,
        construct_resolved_model_profile,
    )
    from nexent.core.model_service.profiles.protocol_parameters import openai_chat_parameter_rules
    from nexent.core.model_service.profiles.parameter_schema import (
        ParameterValidationError,
    )
    from nexent.core.model_service.profiles.request_parameters import (
        apply_extra_api_parameters,
    )
    from nexent.core.model_service.profiles.resolved_profile import (
        ConnectionRules,
        ContextConfiguration,
        OutletConnection,
    )
    from pydantic import ValidationError

    if hasattr(request, "api_key"):
        _validate_credential_input(request.api_key)
    from nexent.core.model_service.connection_headers import connection_headers

    try:
        connection_headers(getattr(request, "http_headers", {}), api_key=getattr(request, "api_key", None))
    except ValueError as error:
        category = "MODEL_HTTP_AUTH_CONFLICT" if str(error) == "MODEL_HTTP_AUTH_CONFLICT" else "MODEL_HTTP_HEADERS_INVALID"
        raise ModelOutletValidationError(category, "/http_headers") from None
    catalog = get_model_profile_catalog()
    if require_revision and request.catalog_revision is None:
        raise ModelOutletValidationError()
    if request.catalog_revision is not None and request.catalog_revision != catalog.revision:
        raise ModelOutletConflictError()
    try:
        endpoint = urlsplit(request.provider_info.base_url)
        if (endpoint.scheme not in ("http", "https") or not endpoint.hostname
                or endpoint.username is not None or endpoint.password is not None or endpoint.fragment):
            raise ModelOutletValidationError()
        endpoint.port
        provider_key, providers = _select_profile(catalog, request, "provider")
        model_key, models = _select_profile(catalog, request, "model")
        refs = model_service_references()
        bindings = {key: values[0].model_dump() for key, values in refs.items() if key != "parameter_transform"}
        scheme = request.authentication_scheme
        if hasattr(request, "api_key"):
            scheme = "bearer_token_v1" if request.api_key and request.api_key.strip() else "no_auth_v1"
        bindings["auth"] = next(ref.model_dump() for ref in refs["auth"] if ref.ref == scheme)
        if bindings["protocol"]["ref"] != request.protocol_id:
            raise ModelOutletValidationError()
        credential_kind = "none" if scheme == "no_auth_v1" else "model_record"
        policy = compose_provider_model_policy(
            catalog, provider_key=provider_key, model_profile_key=model_key,
            request_model_id=request.request_model_id, base_bindings=bindings,
            base_instruction=VersionedReference(ref="system_only_v1", version=1),
            registered_references=refs, submitted_values={key: value for key, value in request.parameter_values.items()
                if not ((request.thinking_control not in (None, "profile_default") and key == "enable_thinking")
                    or (request.thinking_mode not in (None, "default") and key in {"reasoning_effort", "reasoning_budget_tokens"}))},
            protocol_parameter_rules=openai_chat_parameter_rules(),
        )
        apply_extra_api_parameters({}, request.extra_api_parameters,
            parameter_paths=[item["api_binding"]["path"] for item in policy.parameter_rules.declarations
                             if item.get("api_binding")],
            protected_paths=("/api_key", "/authorization", "/headers", "/credentials", "/base_url"))
        profile = construct_resolved_model_profile(
            policy, catalog, tenant_id=tenant_id, display_name=request.display_name or request.request_model_id,
            model_type="llm", provider_id=request.provider_info.provider_id or provider_key or "custom",
            connection=OutletConnection(
                **request.provider_info.model_dump(exclude={"provider_id"}),
                credential_ref={"kind": credential_kind, "model_id": None},
            ),
            connection_rules=ConnectionRules(credential_kind=credential_kind, relative_path="chat/completions",
                                             method="POST", headers={}),
            context_configuration=ContextConfiguration(output_reserve_tokens=None, tokenizer_family=None,
                                                       capacity_source="profile", capability_profile_version=None),
            registered_references=refs, extra_api_parameters=request.extra_api_parameters,
        )
        if request.context_limits is not None or request.context_configuration is not None:
            from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile

            data = profile.model_dump(mode="json")
            if request.context_limits is not None:
                _patch_context_limits(data, request.context_limits.model_dump(exclude_unset=True))
            if request.context_configuration is not None:
                data["context_configuration"].update(request.context_configuration.model_dump(exclude_unset=True))
            profile = ResolvedModelProfile.model_validate(data)
        from nexent.core.model_service.profiles.thinking_configuration import configure_thinking, configure_thinking_degree

        profile = configure_thinking_degree(configure_thinking(profile, request.thinking_control), request.thinking_mode)
        configured = {key: value for key, value in request.parameter_values.items()
                      if (key == "enable_thinking" and request.thinking_control not in (None, "profile_default"))
                      or (key in {"reasoning_effort", "reasoning_budget_tokens"}
                          and request.thinking_mode not in (None, "default"))}
        if configured:
            from nexent.core.model_service.compatibility.invocation_options import LegacyInvocationOptions

            profile = LegacyInvocationOptions(configured).resolve(profile)
        _validate_request_output_limit(profile)
        return profile, {"models": models, "providers": providers}
    except ModelOutletConflictError:
        raise
    except (ProfileCompositionError, ParameterValidationError) as error:
        raise ModelOutletValidationError(error.category, error.path) from None
    except OutletResolutionError as error:
        raise ModelOutletValidationError(error.category) from None
    except (ValidationError, ValueError, StopIteration):
        raise ModelOutletValidationError() from None


def preview_model_profile(request, tenant_id):
    profile, candidates = build_outlet_draft(request, tenant_id)
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
        connect_status=_checked_status(request.check_receipt, profile, request.api_key, request.http_headers) or "not_detected")
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
    from nexent.core.model_service.profiles.protocol_parameters import ensure_outlet_sampling_rules

    profile = ensure_outlet_sampling_rules(profile)
    from management.db.model.repository import get_model_by_model_id

    row = get_model_by_model_id(model_id, tenant_id) or {}
    return {"model_id": model_id, "config_revision": profile.config_revision,
            "profile": profile.model_dump(mode="json"), "field_specs": profile.parameter_rules,
            "http_header_names": sorted(row.get("http_headers") or {}),
            "has_credential": has_model_outlet_credential(model_id, tenant_id)}


def apply_outlet_patch(profile, request):
    """Validate partial updates against the saved rules without applying new defaults."""
    from nexent.core.model_service.profiles.parameter_rules import compile_parameter_rules, validate_saved_parameter_values
    from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError, json_values_equal
    from nexent.core.model_service.profiles.request_parameters import apply_extra_api_parameters
    from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
    from pydantic import ValidationError
    from urllib.parse import urlsplit

    _validate_credential_input(request.api_key)
    try:
        from nexent.core.model_service.profiles.thinking_configuration import configure_outlet_policy

        from nexent.core.model_service.profiles.protocol_parameters import ensure_outlet_sampling_rules

        profile = ensure_outlet_sampling_rules(profile)
        previous_rules = {rule["key"]: rule for rule in profile.parameter_rules}
        profile = configure_outlet_policy(profile, thinking_control=request.thinking_control,
            thinking_mode=request.thinking_mode,
            has_credential=bool(request.api_key and request.api_key.strip()) if "api_key" in request.model_fields_set else None)
        removed = request.delete_parameters
        if len(set(removed)) != len(removed) or set(removed) & request.parameter_values.keys():
            raise ParameterValidationError("PARAMETER_UPDATE_CONFLICT")
        compiled = compile_parameter_rules(profile.parameter_rules)
        rules = {rule["key"]: rule for rule in compiled.declarations}
        values = dict(profile.parameter_values)
        for key in set(removed) | request.parameter_values.keys():
            if key not in rules:
                old = previous_rules.get(key)
                if key in removed and old and old["editable"] and "outlet" in old["allowed_scopes"]:
                    continue
                raise ParameterValidationError("PARAMETER_UNKNOWN", "/" + key)
            same = key not in removed and key in values and json_values_equal(values[key], request.parameter_values[key])
            if not same and (not rules[key]["editable"] or "outlet" not in rules[key]["allowed_scopes"]):
                raise ParameterValidationError("FIXED_PARAMETER", "/" + key)
        for key in removed:
            values.pop(key, None)
        values.update(request.parameter_values)
        data = profile.model_dump(mode="json")
        data["parameter_values"] = validate_saved_parameter_values(compiled, values)
        if request.context_limits is not None:
            _patch_context_limits(data, request.context_limits.model_dump(exclude_unset=True))
        if request.context_configuration is not None:
            data["context_configuration"].update(request.context_configuration.model_dump(exclude_unset=True))
        if "display_name" in request.model_fields_set:
            data["identity"]["display_name"] = request.display_name
        if "connection" in request.model_fields_set and request.connection is None:
            raise ModelOutletValidationError()
        if request.connection is not None:
            data["connection"].update(request.connection.model_dump(exclude_unset=True))
        endpoint = urlsplit(data["connection"]["base_url"])
        if endpoint.scheme not in ("http", "https") or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.fragment:
            raise ModelOutletValidationError()
        endpoint.port
        if "extra_api_parameters" in request.model_fields_set:
            data["extra_api_parameters"] = request.extra_api_parameters
        apply_extra_api_parameters({}, data["extra_api_parameters"],
            parameter_paths=[rule["api_binding"]["path"] for rule in profile.parameter_rules if rule.get("api_binding")],
            protected_paths=("/api_key", "/authorization", "/headers", "/credentials", "/base_url"))
        return _validate_request_output_limit(ResolvedModelProfile.model_validate(data))
    except ParameterValidationError as error:
        raise ModelOutletValidationError(error.category, error.path) from None
    except (ValidationError, ValueError):
        raise ModelOutletValidationError() from None


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
    status = _checked_status(request.check_receipt, proposed, key, headers)
    if status is not None:
        credentials["connect_status"] = status
    revision = update_resolved_model_record(proposed, request.expected_revision, user_id, tenant_id,
                                           registered_references=refs, **credentials)
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
        return profile, row.get("api_key"), row.get("http_headers") or {}
    except ProfileStorageError:
        raise ModelOutletValidationError("PROFILE_STORAGE_INVALID") from None


async def validate_model_outlet(request, tenant_id, *, is_disconnected=None):
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
    result = await probe_model_profile(profile, key, http_headers=headers)
    if is_disconnected is not None and await is_disconnected():
        import asyncio
        raise asyncio.CancelledError()
    ok, error = result["ok"], result["error"]
    if request.outlet_id is not None and request.patch is None:
        from management.db.model.outlets import update_model_outlet_connectivity

        await run_blocking("outlet-validation-status", update_model_outlet_connectivity,
            request.outlet_id, tenant_id, profile.config_revision, "available" if ok else "unavailable")
    return {"ok": ok, "error": error, "check_scope": "connection_only",
            "check_receipt": _issue_check_receipt(profile, key, headers, ok),
            "model_id": profile.outlet_id, "config_revision": profile.config_revision}


async def probe_model_profile(profile, key, *, http_headers=None):
    """Probe through the production streamed sender without mutating configuration."""
    from uuid import uuid4

    from nexent.core.model_service.contracts import ModelMessage, ModelRequest
    from nexent.core.model_service.registry import AuthenticationRegistry
    from nexent.core.model_service.service import ModelService, ModelServiceError
    from nexent.core.models.retry import DEFAULT_MODEL_RETRY

    auth = AuthenticationRegistry()
    service = ModelService(lambda captured: auth.sender_for(captured, lambda _tenant, _reference: key, http_headers=http_headers),
                           retry_policy=DEFAULT_MODEL_RETRY)
    call = ModelRequest(request_id=uuid4().hex, outlet_id=profile.outlet_id,
        config_revision=profile.config_revision, stream=True, purpose="connection_validation",
        messages=[ModelMessage(semantic_role="user", content_parts=[{"type": "text", "text": "Hello"}])])
    error = None
    ok = False
    try:
        async with service.astream(call, profile) as events:
            async for event in events:
                if event.type == "error":
                    error = _probe_diagnostic(event.error)
                elif event.type == "message_completed":
                    ok = bool(event.message.content_parts or event.message.tool_calls)
        if not ok and error is None:
            error = {"category": "MODEL_EMPTY_RESPONSE", "scope": "model"}
    except ModelServiceError as failure:
        ok = False
        error = _probe_diagnostic(failure.error)
    return {"ok": ok, "error": error}


def _probe_diagnostic(error):
    """Classify by known provider semantics, not arbitrary upstream error text."""
    per_model = error.category in {"MODEL_REQUEST_INVALID", "MODEL_CONTEXT_EXCEEDED", "MODEL_PROTOCOL_ERROR"}
    per_model = per_model or error.provider_code == "model_not_found"
    from nexent.core.model_service.errors import model_error_message

    return {"category": error.category, "message": model_error_message(error),
            "diagnostic_code": error.diagnostic_code, "message_source": error.message_source,
            "messages": {lang: model_error_message(error, lang) for lang in ("en", "zh")},
            "scope": "model" if per_model else "connection", "request_id": error.request_id,
            **({"http_status": error.http_status} if getattr(error, "http_status", None) is not None else {}),
            **({"parameter": error.parameter_name} if getattr(error, "parameter_name", None) else {})}


def confirm_outlet_migration(model_id, request, user_id, tenant_id):
    """Confirm saved migration metadata under the authenticated tenant."""
    from management.db.model.outlets import confirm_model_outlet_migration

    return confirm_model_outlet_migration(model_id, tenant_id, user_id, request.expected_revision,
        registered_references=model_service_references())
