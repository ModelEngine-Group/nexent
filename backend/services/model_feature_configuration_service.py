"""Resolve and validate tenant-model feature capability configuration."""

from __future__ import annotations

from typing import Any, Mapping, Optional
from urllib.parse import urlparse

from consts.model_feature_capabilities import (
    CATALOG_REVISION,
    EXACT_CATALOG,
    FAMILY_RULES,
)
from nexent.core.models.feature_capability import (
    normalize_feature_capability_override,
    normalize_feature_profile,
    resolve_feature_capabilities,
    resolve_model_feature_configuration,
)
from utils.model_name_utils import add_repo_to_name


_GENERIC_OPENAI_FACTORIES = {
    "openaiapicompatible", "openaicompatible", "openaiapi",
}
_PROVIDER_HOSTS = (
    ("dashscope", ("dashscope.aliyuncs.com",)),
    ("silicon", ("api.siliconflow.cn", "siliconflow.cn")),
    ("deepseek", ("api.deepseek.com",)),
    ("openai", ("api.openai.com",)),
    ("tokenpony", ("api.tokenpony.cn",)),
)


class ModelFeatureConfigurationError(ValueError):
    """Raised when a tenant-model feature override is structurally invalid."""


def _endpoint_host(base_url: Any) -> str:
    raw = str(base_url or "").strip()
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    return (parsed.hostname or "").lower().rstrip(".")


def effective_feature_factory(record: Mapping[str, Any]) -> str:
    factory = str(record.get("model_factory") or "").strip().lower()
    normalized = "".join(character for character in factory if character.isalnum())
    if normalized not in _GENERIC_OPENAI_FACTORIES:
        return factory
    host = _endpoint_host(record.get("base_url"))
    for provider, hosts in _PROVIDER_HOSTS:
        if host in hosts:
            return provider
    return factory


def model_feature_identity(record: Mapping[str, Any]) -> dict[str, str]:
    model_name = str(record.get("model_name") or "")
    model_repo = str(record.get("model_repo") or "")
    full_name = (
        model_name
        if "/" in model_name or not model_repo
        else add_repo_to_name(model_repo, model_name)
    )
    return {
        "model_factory": effective_feature_factory(record),
        "model": full_name,
        "endpoint_host": _endpoint_host(record.get("base_url")),
    }


def current_feature_baseline(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return a provider baseline or the latest code-catalog resolution."""
    persisted = normalize_feature_profile(record.get("feature_capability_metadata"))
    if persisted and persisted.get("source") == "provider_extension":
        return persisted
    identity = model_feature_identity(record)
    return resolve_feature_capabilities(
        identity["model_factory"],
        identity["model"],
        exact_catalog=EXACT_CATALOG,
        family_rules=FAMILY_RULES,
        catalog_revision=CATALOG_REVISION,
    )


def prepare_feature_override(
    raw_override: Optional[Mapping[str, Any]],
    record: Mapping[str, Any],
) -> Optional[dict[str, Any]]:
    """Normalize an explicit admin update and bind it to current identity."""
    try:
        normalized = normalize_feature_capability_override(raw_override)
        if normalized is None:
            return None
        normalized["authored_identity"] = model_feature_identity(record)
        baseline = current_feature_baseline(record)
        resolve_model_feature_configuration(
            baseline,
            normalized,
            current_identity=normalized["authored_identity"],
        )
        return normalized
    except ValueError as exc:
        raise ModelFeatureConfigurationError(str(exc)) from exc


def resolve_record_feature_configuration(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    baseline = current_feature_baseline(record)
    try:
        configuration = resolve_model_feature_configuration(
            baseline,
            record.get("feature_capability_override"),
            current_identity=model_feature_identity(record),
        )
    except ValueError:
        configuration = resolve_model_feature_configuration(
            baseline, None, current_identity=model_feature_identity(record)
        )
        configuration["warnings"] = ["invalid_feature_capability_override"]
        configuration["effective_policy"]["warnings"] = list(
            configuration["warnings"]
        )
    configuration["baseline_changed"] = (
        normalize_feature_profile(record.get("feature_capability_metadata"))
        != baseline
    )
    return configuration


def enrich_feature_configuration(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return a sanitized API/runtime view without mutating the input record."""
    output = dict(record)
    configuration = resolve_record_feature_configuration(output)
    output["feature_capability_metadata"] = configuration["baseline"]
    output["feature_capability_override"] = configuration["override"]
    output["effective_feature_capabilities"] = configuration[
        "effective_capabilities"
    ]
    output["effective_feature_policy"] = configuration["effective_policy"]
    output["feature_capability_warnings"] = configuration["warnings"]
    output["feature_capability_baseline_changed"] = configuration[
        "baseline_changed"
    ]
    return output
