"""Read-only profile discovery for LLM onboarding from the pinned local catalog."""

from functools import lru_cache

from consts.exceptions import ModelOutletConflictError, ModelOutletValidationError
from nexent.core.model_service.profiles.resolver import load_profile_catalog
from nexent.core.model_service.registry import model_service_references


@lru_cache(maxsize=1)
def get_model_profile_catalog():
    """Load one immutable catalog per process; deployment updates invalidate it by restart."""
    return load_profile_catalog()


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
        candidates = [key for key, atom in entries.items()
                      if request.request_model_id == key or request.request_model_id == key.split("/", 1)[-1]
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
    from nexent.core.model_service.profiles.parameter_schema import (
        ParameterValidationError,
    )
    from nexent.core.model_service.profiles.protocol_parameters import (
        openai_chat_parameter_rules,
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
        _ = endpoint.port
        provider_key, providers = _select_profile(catalog, request, "provider")
        model_key, models = _select_profile(catalog, request, "model")
        refs = model_service_references()
        bindings = {key: values[0].model_dump() for key, values in refs.items() if key != "parameter_transform"}
        bindings["auth"] = next(ref.model_dump() for ref in refs["auth"] if ref.ref == request.authentication_scheme)
        if bindings["protocol"]["ref"] != request.protocol_id:
            raise ModelOutletValidationError()
        credential_kind = "none" if request.authentication_scheme == "no_auth_v1" else "model_record"
        policy = compose_provider_model_policy(
            catalog, provider_key=provider_key, model_profile_key=model_key,
            request_model_id=request.request_model_id, base_bindings=bindings,
            base_instruction=VersionedReference(ref="system_only_v1", version=1),
            registered_references=refs, submitted_values=request.parameter_values,
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
            from nexent.core.model_service.profiles.resolved_profile import (
                ResolvedModelProfile,
            )

            data = profile.model_dump(mode="json")
            if request.context_limits is not None:
                data["capabilities"]["context"].update(request.context_limits.model_dump(exclude_unset=True))
            if request.context_configuration is not None:
                data["context_configuration"].update(request.context_configuration.model_dump(exclude_unset=True))
            profile = ResolvedModelProfile.model_validate(data)
        return profile, {"models": models, "providers": providers}
    except ModelOutletConflictError:
        raise
    except (ProfileCompositionError, ParameterValidationError) as error:
        raise ModelOutletValidationError(error.category, error.path) from None
    except OutletResolutionError as error:
        raise ModelOutletValidationError(error.category) from None
    except (ValidationError, ValueError, StopIteration):
        raise ModelOutletValidationError() from None
