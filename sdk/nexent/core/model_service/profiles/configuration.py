# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compose immutable outlet policy without application services or persistence."""

import re
from functools import lru_cache
from nexent.core.model_service.profiles.parameter_schema import _json_copy

from nexent.core.model_service.profiles.configuration_errors import ModelOutletConflictError, ModelOutletValidationError
from nexent.core.model_service.profiles.resolver import load_profile_catalog
from nexent.core.model_service.registry import model_service_references

@lru_cache(maxsize=1)
def get_model_profile_catalog():
    return load_profile_catalog()

def _validate_credential_input(value):
    """Reject UI masking sentinels before persistence or model transport."""
    if value and (set(value.strip()) == {"*"} or "********" in value):
        raise ModelOutletValidationError()

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

def _clear_sampling_parameters(profile, cleared):
    """Treat explicit empty sampling inputs as omission, not provider JSON null."""
    if not cleared:
        return profile
    from nexent.core.model_service.profiles.parameter_rules import compile_parameter_rules, validate_saved_parameter_values
    from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
    from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile

    data = profile.model_dump(mode="json")
    rules = {rule["key"]: rule for rule in profile.parameter_rules}
    for key in cleared:
        rule = rules.get(key)
        if rule is None:
            raise ParameterValidationError("PARAMETER_UNKNOWN", "/" + key)
        if "fixed_value" in rule or not rule["editable"] or "outlet" not in rule["allowed_scopes"]:
            raise ParameterValidationError("FIXED_PARAMETER", "/" + key)
        data["parameter_values"].pop(key, None)
    validate_saved_parameter_values(compile_parameter_rules(profile.parameter_rules), data["parameter_values"])
    return ResolvedModelProfile.model_validate(data)

def _patch_context_limits(data, patch):
    """Bound inherited hidden limits when the user reduces the effective window."""
    context = data["capabilities"]["context"]
    context.update(patch)
    window = patch.get("combined_window")
    if type(window) is int:
        for key in ("input_limit", "output_limit"):
            if key not in patch and type(context.get(key)) is int:
                context[key] = min(context[key], window)

def build_outlet_draft(request, tenant_id, *, require_revision=False, catalog=None):
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
    catalog = catalog if catalog is not None else get_model_profile_catalog()
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
        from nexent.core.model_service.profiles.outlet_controls import (
            custom_thinking_allowed, custom_thinking_rule, has_manual_thinking_parameter,
        )

        protocol_rules = openai_chat_parameter_rules()
        model_atom = catalog.models.get(model_key)
        if (provider_key is None and model_atom and custom_thinking_allowed(model_atom.capabilities["reasoning"])
                and not has_manual_thinking_parameter(request.extra_api_parameters)):
            protocol_rules.append(custom_thinking_rule())
        policy = compose_provider_model_policy(
            catalog, provider_key=provider_key, model_profile_key=model_key,
            request_model_id=request.request_model_id, base_bindings=bindings,
            base_instruction=VersionedReference(ref="system_only_v1", version=1),
            registered_references=refs, submitted_values={key: value for key, value in request.parameter_values.items()
                if not (key in {"temperature", "top_p"} and value is None)
                if not ((request.thinking_control not in (None, "profile_default") and key == "enable_thinking")
                    or (request.thinking_mode not in (None, "default") and key in {"reasoning_effort", "reasoning_budget_tokens"}))},
            protocol_parameter_rules=protocol_rules,
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
        from nexent.core.model_service.profiles.outlet_controls import ensure_outlet_parameter_rules

        profile = _clear_sampling_parameters(ensure_outlet_parameter_rules(profile), {
            key for key in ("temperature", "top_p")
            if key in request.parameter_values and request.parameter_values[key] is None
        })
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


def reselect_outlet_profile(profile, request, *, compose=None):
    """Recompose only explicitly selected catalog references, retaining outlet identity."""
    if request.profile_selection is None and request.request_model_id is None:
        return profile
    if request.profile_selection is None:
        raise ModelOutletValidationError("PROFILE_SELECTION_REQUIRED", "/profile_selection")
    from nexent.core.model_service.profiles.configuration_inputs import ModelProfilePreviewRequest
    from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile

    selection = request.profile_selection
    connection = profile.connection.model_dump(mode="json", exclude={"credential_ref"})
    connection.update(request.connection.model_dump(exclude_unset=True) if request.connection else {})
    values = {} if request.reset_parameters else {key: value for key, value in profile.parameter_values.items() if key not in request.delete_parameters}
    values.update(request.parameter_values)
    draft = ModelProfilePreviewRequest(
        selection_mode="manual", catalog_revision=selection.catalog_revision,
        model_profile=selection.model_profile, provider_profile=selection.provider_profile,
        request_model_id=request.request_model_id or profile.identity.request_model_id,
        display_name=request.display_name or profile.identity.display_name,
        provider_info={**connection, "provider_id": selection.provider_profile.key if selection.provider_profile else "custom"},
        authentication_scheme=profile.bindings.auth.ref, parameter_values=values,
        thinking_control=request.thinking_control, thinking_mode=request.thinking_mode,
        extra_api_parameters=request.extra_api_parameters if request.extra_api_parameters is not None else profile.extra_api_parameters,
    )
    # A custom provider can retain registered manual controls from the saved outlet.
    # Inspect the new trusted declarations before validating inherited user values.
    native, _ = build_outlet_draft(draft.model_copy(update={"parameter_values": {},
        "thinking_control": None, "thinking_mode": None}), profile.identity.tenant_id, require_revision=True)
    native_keys = {rule["key"] for rule in native.parameter_rules}
    native_toggle = next((rule for rule in native.parameter_rules if rule["key"] == "enable_thinking"), None)
    saved_toggle = next((rule for rule in profile.parameter_rules if rule["key"] == "enable_thinking"), None)
    compatible_default = (native_toggle is not None
        and native_toggle.get("source", {}).get("ref") == "custom_provider_thinking_v1"
        and saved_toggle is not None
        and saved_toggle.get("source", {}).get("ref") != "custom_provider_thinking_v1")
    if ("enable_thinking" in values and ("enable_thinking" not in native_keys or compatible_default)
            and draft.thinking_control in (None, "profile_default")):
        from nexent.core.model_service.profiles.thinking_configuration import THINKING_FORMATS

        binding = next((rule.get("api_binding") for rule in profile.parameter_rules if rule["key"] == "enable_thinking"), None)
        preset = next((key for key, (path, transform) in THINKING_FORMATS.items()
            if binding and binding.get("path") == path and binding.get("transform_ref") == transform), None)
        if preset:
            draft = draft.model_copy(update={"thinking_control": preset})
    degrees = {"reasoning_effort": "effort", "reasoning_budget_tokens": "budget_tokens"}
    if not native_keys.intersection(degrees) and draft.thinking_mode in (None, "default"):
        paths = {"reasoning_effort": "/reasoning_effort", "reasoning_budget_tokens": "/thinking_budget"}
        mode = next((mode for key, mode in degrees.items() if key in values and any(
            rule["key"] == key and rule.get("api_binding", {}).get("path") == paths[key]
            and rule.get("api_binding", {}).get("transform_ref") == "identity_v1"
            for rule in profile.parameter_rules)), None)
        if mode:
            draft = draft.model_copy(update={"thinking_mode": mode})
    rebuilt, _ = (compose if compose is not None else build_outlet_draft)(draft, profile.identity.tenant_id, require_revision=True)
    data = rebuilt.model_dump(mode="json")
    data.update(outlet_id=profile.outlet_id, config_revision=profile.config_revision)
    data["connection"]["credential_ref"] = profile.connection.credential_ref.model_dump(mode="json")
    data["capabilities"]["context"] = profile.capabilities.context.model_dump(mode="json")
    data["context_configuration"] = profile.context_configuration.model_dump(mode="json")
    migration = profile.provenance.provider_metadata.get("migration")
    if isinstance(migration, dict):
        data["provenance"]["provider_metadata"]["migration"] = _json_copy(migration)
    return ResolvedModelProfile.model_validate(data)


def apply_outlet_patch(profile, request, *, compose=None):
    """Validate partial updates against the saved rules without applying new defaults."""
    from nexent.core.model_service.profiles.parameter_rules import apply_parameter_values, compile_parameter_rules, validate_saved_parameter_values
    from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError, json_values_equal
    from nexent.core.model_service.profiles.request_parameters import apply_extra_api_parameters
    from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
    from pydantic import ValidationError
    from urllib.parse import urlsplit

    _validate_credential_input(request.api_key)
    previous_rules = {rule["key"]: rule for rule in profile.parameter_rules}
    cleared = {key for key in ("temperature", "top_p")
               if key in request.parameter_values and request.parameter_values[key] is None}
    submitted = {key: value for key, value in request.parameter_values.items() if key not in cleared}
    profile = reselect_outlet_profile(profile, request.model_copy(update={"parameter_values": submitted}), compose=compose)
    try:
        from nexent.core.model_service.profiles.thinking_configuration import configure_outlet_policy

        from nexent.core.model_service.profiles.outlet_controls import ensure_outlet_parameter_rules

        profile = ensure_outlet_parameter_rules(profile)
        metadata = profile.provenance.provider_metadata if request.profile_selection is not None else {}
        control = request.thinking_control
        mode = request.thinking_mode
        if control in (None, "profile_default"):
            control = metadata.get("operator_thinking", {}).get("preset", control)
        if mode in (None, "default"):
            mode = metadata.get("operator_thinking_degree", {}).get("mode", mode)
        inherited_values = dict(profile.parameter_values)
        profile = configure_outlet_policy(profile, thinking_control=control,
            thinking_mode=mode,
            has_credential=bool(request.api_key and request.api_key.strip()) if "api_key" in request.model_fields_set else None)
        removed = request.delete_parameters
        if (request.reset_parameters and removed) or len(set(removed)) != len(removed) or set(removed) & request.parameter_values.keys():
            raise ParameterValidationError("PARAMETER_UPDATE_CONFLICT")
        compiled = compile_parameter_rules(profile.parameter_rules)
        rules = {rule["key"]: rule for rule in compiled.declarations}
        values = dict(profile.parameter_values)
        selected_degree = {"effort": "reasoning_effort", "budget_tokens": "reasoning_budget_tokens"}.get(mode)
        if selected_degree in inherited_values and selected_degree in rules:
            values.setdefault(selected_degree, inherited_values[selected_degree])
        for key in set(removed) | request.parameter_values.keys():
            if key not in rules:
                old = previous_rules.get(key)
                if key in removed and old and old["editable"] and "outlet" in old["allowed_scopes"]:
                    continue
                raise ParameterValidationError("PARAMETER_UNKNOWN", "/" + key)
            same = key not in removed and key in values and json_values_equal(values[key], request.parameter_values[key])
            if not same and (not rules[key]["editable"] or "outlet" not in rules[key]["allowed_scopes"]):
                raise ParameterValidationError("FIXED_PARAMETER", "/" + key)
        for key in set(removed) | cleared:
            values.pop(key, None)
        values.update(submitted)
        if request.reset_parameters:
            values = apply_parameter_values(compiled, submitted, scope="outlet", saved_values={})
            for key in cleared:
                values.pop(key, None)
        data = profile.model_dump(mode="json")
        data["parameter_values"] = validate_saved_parameter_values(compiled, values)
        if profile.capabilities.reasoning.can_disable is False and values.get("enable_thinking") is False:
            raise ParameterValidationError("FIXED_PARAMETER", "/enable_thinking")
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
