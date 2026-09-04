from __future__ import annotations

import re
from typing import List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field


MATCHER_VERSION = "1.0.0"

_TOKEN_PATTERN = re.compile(
    r"[a-z]+(?:\d+(?:\.\d+)?)?|\d+(?:\.\d+)*(?:[a-z]+)?"
)
_SIZE_PATTERN = re.compile(r"^\d+(?:\.\d+)?[bmk]$")
_CONTEXT_EXTENSION_PATTERN = re.compile(r"^\d+(?:\.\d+)?(?:k|m)$")
_DATE_PATTERN = re.compile(r"^(?:20)?\d{4}(?:\d{2})?$")

_FAMILY_PREFIXES = (
    "deepseek",
    "hunyuan",
    "mistral",
    "moonshot",
    "qwen",
    "llama",
    "gemma",
    "kimi",
    "glm",
    "phi",
    "yi",
)
_MODALITY_TOKENS = {"vl", "vision", "omni", "audio", "image", "video"}
_TUNE_TOKENS = {"base", "chat", "instruct", "it", "coder", "captioner"}
_REASONING_TOKENS = {"thinking", "reasoner", "reasoning", "r1"}
_QUANTIZATION_TOKENS = {"awq", "gptq", "gguf", "fp8", "int4", "int8", "bnb"}


def _tokens(value: str) -> Tuple[str, ...]:
    parsed = _TOKEN_PATTERN.findall(value.strip().lower())
    expanded: list[str] = []
    for token in parsed:
        split = next(
            (
                (prefix, token[len(prefix):])
                for prefix in _FAMILY_PREFIXES
                if token.startswith(prefix)
                and token != prefix
                and token[len(prefix):]
                and token[len(prefix)].isdigit()
            ),
            None,
        )
        if split:
            expanded.extend(split)
        else:
            expanded.append(token)
    return tuple(expanded)


def _first_matching(tokens: Tuple[str, ...], candidates: set[str]) -> Optional[str]:
    return next((token for token in tokens if token in candidates), None)


class CanonicalModelIdentity(BaseModel):
    """Versioned, separator-aware identity used by independent profile matchers."""

    model_config = ConfigDict(frozen=True)

    raw_model_id: str
    provider: Optional[str] = None
    canonical_id: str
    family: Optional[str] = None
    version: Optional[str] = None
    size: Optional[str] = None
    modality: Optional[str] = None
    tune: Optional[str] = None
    reasoning: Optional[str] = None
    distillation: Optional[str] = None
    quantization: Optional[str] = None
    date: Optional[str] = None
    context_extension: Optional[str] = None
    namespace: Tuple[str, ...] = ()
    tokens: Tuple[str, ...] = ()
    resolved: bool = False
    ambiguous: bool = False
    confidence: str = "low"
    candidates: Tuple[str, ...] = ()
    matcher_version: str = MATCHER_VERSION
    evidence: List[str] = Field(default_factory=list)

    @property
    def variant_signature(self) -> Tuple[Optional[str], ...]:
        return (
            self.family,
            self.version,
            self.size,
            self.modality,
            self.tune,
            self.reasoning,
            self.distillation,
            self.context_extension,
        )


def parse_model_identity(model_id: str, provider: Optional[str] = None) -> CanonicalModelIdentity:
    """Parse a provider model ID without collapsing meaningful token boundaries."""
    raw = model_id.strip()
    if not raw:
        raise ValueError("model_id is required")

    normalized_provider = provider.strip().lower() if provider and provider.strip() else None
    path_parts = [part for part in re.split(r"/+", raw) if part]
    namespace = tuple(part.strip().lower() for part in path_parts[:-1])
    leaf_tokens = _tokens(path_parts[-1])
    all_tokens = tuple(token for part in path_parts for token in _tokens(part))

    family = next(
        (
            prefix
            for token in all_tokens
            for prefix in _FAMILY_PREFIXES
            if token == prefix or token.startswith(prefix)
        ),
        None,
    )
    version = None
    if family:
        family_index = next(
            (index for index, token in enumerate(all_tokens) if token == family or token.startswith(family)),
            -1,
        )
        family_token = all_tokens[family_index] if family_index >= 0 else ""
        suffix = family_token[len(family):]
        if suffix and suffix[0].isdigit():
            version = suffix
        elif family_index >= 0:
            version = next(
                (
                    token[1:] if token.startswith("v") else token
                    for token in all_tokens[family_index + 1:]
                    if (
                        token[0].isdigit()
                        or (token.startswith("v") and token[1:].replace(".", "").isdigit())
                    )
                    and not _SIZE_PATTERN.match(token)
                    and token not in _REASONING_TOKENS
                ),
                None,
            )

    size = next((token for token in all_tokens if _SIZE_PATTERN.match(token)), None)
    context_extension = next(
        (
            token
            for token in all_tokens
            if _CONTEXT_EXTENSION_PATTERN.match(token) and token != size
        ),
        None,
    )
    modality = _first_matching(all_tokens, _MODALITY_TOKENS)
    tune = _first_matching(all_tokens, _TUNE_TOKENS)
    reasoning = _first_matching(all_tokens, _REASONING_TOKENS)
    quantization = _first_matching(all_tokens, _QUANTIZATION_TOKENS)
    date = next((token for token in reversed(all_tokens) if _DATE_PATTERN.match(token)), None)

    distillation = None
    if "distill" in all_tokens:
        index = all_tokens.index("distill")
        lineage = all_tokens[index + 1:]
        distillation = "-".join(lineage) if lineage else "distill"

    canonical_path = "/".join("-".join(_tokens(part)) for part in path_parts)
    canonical_id = f"{normalized_provider}:{canonical_path}" if normalized_provider else canonical_path
    evidence = ["separator_aware_tokens"]
    for field_name, value in (
        ("family", family),
        ("version", version),
        ("size", size),
        ("modality", modality),
        ("tune", tune),
        ("reasoning", reasoning),
        ("distillation", distillation),
        ("quantization", quantization),
        ("date", date),
        ("context_extension", context_extension),
    ):
        if value:
            evidence.append(f"{field_name}:{value}")

    return CanonicalModelIdentity(
        raw_model_id=raw,
        provider=normalized_provider,
        canonical_id=canonical_id,
        family=family,
        version=version,
        size=size,
        modality=modality,
        tune=tune,
        reasoning=reasoning,
        distillation=distillation,
        quantization=quantization,
        date=date,
        context_extension=context_extension,
        namespace=namespace,
        tokens=leaf_tokens,
        resolved=family is not None,
        confidence="high" if family and version else "medium" if family else "low",
        evidence=evidence,
    )


def identities_are_safe_aliases(
    requested: CanonicalModelIdentity,
    candidate: CanonicalModelIdentity,
) -> bool:
    """Return true only when leaf tokens and every capacity-relevant variant agree."""
    if requested.tokens != candidate.tokens:
        return False
    for field_name in (
        "family",
        "version",
        "size",
        "modality",
        "tune",
        "reasoning",
        "distillation",
        "context_extension",
    ):
        requested_value = getattr(requested, field_name)
        candidate_value = getattr(candidate, field_name)
        if requested_value and candidate_value and requested_value != candidate_value:
            return False
    return True
