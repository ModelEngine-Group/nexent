# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Explicit versioned adapter registration, independent of persisted import strings."""

from types import MappingProxyType

from nexent.core.model_service.adapters.openai_chat import ModelAdapterError, OpenAIChatAdapter
from nexent.core.model_service.http_contracts import ModelTransportError, validate_headers
from nexent.core.model_service.http_sender import HttpRequestSender
from nexent.core.model_service.parameter_transforms import parameter_transform_references
from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.resource_conversion import ResourceConverterRegistry


class AdapterRegistry:
    """A detached immutable directory of trusted, already-constructed implementations."""

    def __init__(self, adapters=None):
        instances = (OpenAIChatAdapter(),) if adapters is None else tuple(adapters)
        entries = {}
        for adapter in instances:
            reference = getattr(adapter, "reference", None)
            if not isinstance(reference, VersionedReference):
                raise ModelAdapterError("MODEL_ADAPTER_REGISTRATION_INVALID")
            if not isinstance(getattr(adapter, "protocol_reference", None), VersionedReference):
                raise ModelAdapterError("MODEL_ADAPTER_REGISTRATION_INVALID")
            key = (reference.ref, reference.version)
            if key in entries:
                raise ModelAdapterError("MODEL_ADAPTER_REGISTRATION_DUPLICATE")
            methods = ("prepare_http_request", "decode_response", "decode_stream", "adecode_stream", "normalize_error")
            if any(not callable(getattr(adapter, method, None)) for method in methods):
                raise ModelAdapterError("MODEL_ADAPTER_REGISTRATION_INVALID")
            entries[key] = adapter
        self._entries = MappingProxyType(entries)

    def resolve(self, reference: VersionedReference):
        if not isinstance(reference, VersionedReference):
            raise ModelAdapterError("MODEL_ADAPTER_UNREGISTERED")
        adapter = self._entries.get((reference.ref, reference.version))
        if adapter is None:
            raise ModelAdapterError("MODEL_ADAPTER_UNREGISTERED")
        return adapter

    @property
    def references(self) -> tuple[VersionedReference, ...]:
        return tuple(VersionedReference(ref=key, version=version) for key, version in self._entries)

    @property
    def protocol_references(self) -> tuple[VersionedReference, ...]:
        keys = sorted({(adapter.protocol_reference.ref, adapter.protocol_reference.version)
                       for adapter in self._entries.values()})
        return tuple(VersionedReference(ref=key, version=version) for key, version in keys)


def _bearer_headers(lookup, tenant_id, reference):
    if reference.kind != "model_record":
        raise ModelTransportError("CREDENTIAL_SCHEME_MISMATCH")
    value = lookup(tenant_id, reference)
    if not isinstance(value, str) or not value.strip():
        raise ModelTransportError("CREDENTIAL_RESOLUTION_FAILED")
    return validate_headers({"authorization": "Bearer " + value}, credentials=True)


def _no_auth_headers(lookup, tenant_id, reference):
    if reference.kind != "none":
        raise ModelTransportError("CREDENTIAL_SCHEME_MISMATCH")
    return {}


class AuthenticationRegistry:
    """Trusted auth functions; credential lookup remains tenant-scoped and injected."""

    def __init__(self):
        self._entries = MappingProxyType({
            ("bearer_token_v1", 1): _bearer_headers,
            ("no_auth_v1", 1): _no_auth_headers,
        })

    @property
    def references(self) -> tuple[VersionedReference, ...]:
        return tuple(VersionedReference(ref=key, version=version) for key, version in self._entries)

    def sender_for(self, profile, lookup, *, http_headers=None) -> HttpRequestSender:
        reference = profile.bindings.auth
        scheme = self._entries.get((reference.ref, reference.version))
        if scheme is None:
            raise ModelAdapterError("MODEL_AUTH_UNREGISTERED")
        credential = profile.connection.credential_ref
        tenant_id = profile.identity.tenant_id

        def resolve(submitted_reference):
            if submitted_reference != credential:
                raise ModelTransportError("CREDENTIAL_REFERENCE_MISMATCH")
            try:
                from nexent.core.model_service.connection_headers import connection_headers

                headers = connection_headers(http_headers or {})
                generated = scheme(lookup, tenant_id, credential)
                if headers.keys() & generated.keys():
                    raise ModelTransportError("CREDENTIAL_HEADER_CONFLICT")
                return {**headers, **generated}
            except Exception:
                raise ModelTransportError("CREDENTIAL_RESOLUTION_FAILED") from None

        return HttpRequestSender(resolve)


def model_service_references():
    """Report executable local registrations for composing and restoring outlets."""
    adapters, authentication, converters = AdapterRegistry(), AuthenticationRegistry(), ResourceConverterRegistry()
    return MappingProxyType({
        "protocol": adapters.protocol_references,
        "adapter": adapters.references,
        "auth": authentication.references,
        "code_converter": converters.references("code_converter"),
        "native_converter": converters.references("native_converter"),
        "parameter_transform": parameter_transform_references(),
    })
