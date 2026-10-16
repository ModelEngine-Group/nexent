# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Strict selected authored schemas pinned to models.dev e69e184.

No provider request binding or capability defaults are inferred here.
"""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from nexent.core.model_service.profiles._models_dev.reader import SourceDocument, SourceReadError


@dataclass(frozen=True)
class ObjectSchema:
    fields: Mapping[str, object]
    required: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArraySchema:
    item: object


def _error(document: SourceDocument, path: str, category: str = "SOURCE_VALUE_INVALID") -> SourceReadError:
    error = SourceReadError(category, document.file_path, document.kind)
    error.source_path = path
    error.rule_id = "models_dev_authored_v1"
    return error


def _date(value: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", value):
        return False
    parts = [int(part) for part in value.split("-")]
    year, month = parts[:2]
    if not 1 <= month <= 12:
        return False
    if len(parts) == 2:
        return True
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days = (31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    return 1 <= parts[2] <= days[month - 1]


def _validate(value: object, schema: object, document: SourceDocument, path: str, partial: bool = False) -> None:
    if isinstance(schema, ObjectSchema):
        if not isinstance(value, Mapping):
            raise _error(document, path)
        for key, item in value.items():
            field_path = f"{path}.{key}" if path else key
            if key not in schema.fields:
                raise _error(document, field_path, "SOURCE_FIELD_UNHANDLED")
            _validate(item, schema.fields[key], document, field_path, partial)
        if not partial:
            for key in schema.required:
                if key not in value:
                    raise _error(document, f"{path}.{key}" if path else key, "SOURCE_FIELD_REQUIRED")
        return
    if isinstance(schema, ArraySchema):
        if not isinstance(value, (list, tuple)):
            raise _error(document, path)
        for index, item in enumerate(value):
            _validate(item, schema.item, document, f"{path}[{index}]", partial)
        return
    valid = False
    if isinstance(schema, frozenset):
        valid = isinstance(value, str) and value in schema
    elif schema == "boolean":
        valid = type(value) is bool
    elif schema == "string":
        valid = isinstance(value, str)
    elif schema == "nonempty":
        valid = isinstance(value, str) and len(value) > 0
    elif schema == "date":
        valid = isinstance(value, str) and _date(value)
    elif schema == "url":
        if isinstance(value, str):
            try:
                parsed = urlsplit(value)
                valid = bool(
                    parsed.scheme and (parsed.netloc if parsed.scheme in ("http", "https", "ftp") else parsed.path)
                )
                valid = valid and not any(character.isspace() for character in value)
            except ValueError:
                valid = False
    elif schema in ("number", "nonnegative", "budget_min", "tokens"):
        valid = type(value) is int or (type(value) is float and math.isfinite(value))
        if valid and schema != "number":
            valid = value >= (-1 if schema == "budget_min" else 0)
        if valid and schema in ("tokens", "budget_min"):
            valid = type(value) is int
    elif schema == "score":
        valid = (type(value) is int or (type(value) is float and math.isfinite(value))) or (
            isinstance(value, str) and bool(value)
        )
    elif schema == "interleaved":
        if value is True:
            return
        _validate(
            value,
            ObjectSchema({"field": frozenset({"reasoning_content", "reasoning_details"})}, ("field",)),
            document,
            path,
            partial,
        )
        return
    elif schema == "reasoning_option":
        if not isinstance(value, Mapping) or value.get("type") not in ("toggle", "effort", "budget_tokens"):
            raise _error(document, f"{path}.type")
        mode = value["type"]
        fields = {"type": frozenset({mode})}
        required = ("type",)
        if mode == "effort":
            fields["values"] = ArraySchema(
                frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max", "default", "null"})
            )
            required += ("values",)
        if mode == "budget_tokens":
            fields.update(min="budget_min", max="tokens")
        _validate(value, ObjectSchema(fields, required), document, path, partial)
        if mode == "budget_tokens" and "min" in value and "max" in value and value["min"] > value["max"]:
            raise _error(document, f"{path}.min", "SOURCE_CONSTRAINT_INVALID")
        return
    if not valid:
        raise _error(document, path)


_MODALITIES = ObjectSchema(
    {
        "input": ArraySchema(frozenset({"text", "audio", "image", "video", "pdf"})),
        "output": ArraySchema(frozenset({"text", "audio", "image", "video", "pdf"})),
    },
    ("input", "output"),
)
_LIMIT = ObjectSchema({"context": "tokens", "input": "tokens", "output": "tokens"}, ("context",))
_LINK = ObjectSchema(
    {
        "url": "url",
        "label": "nonempty",
        "type": frozenset({"announcement", "blog", "docs", "license", "model_card", "paper", "weights", "other"}),
    },
    ("url",),
)
_WEIGHT = ObjectSchema({"url": "url", "label": "nonempty", "format": "nonempty", "quantization": "nonempty"}, ("url",))
_BENCHMARK = ObjectSchema(
    {
        "name": "nonempty",
        "score": "score",
        "metric": "nonempty",
        "harness": "nonempty",
        "variant": "nonempty",
        "dataset": "nonempty",
        "version": "nonempty",
        "source": "url",
        "date": "date",
    },
    ("name", "score"),
)
_COST_FIELDS = dict.fromkeys(
    ("input", "output", "reasoning", "cache_read", "cache_write", "input_audio", "output_audio"), "nonnegative"
)
_COST_TIER = ObjectSchema(
    {**_COST_FIELDS, "tier": ObjectSchema({"type": frozenset({"context"}), "size": "tokens"}, ("size",))},
    ("input", "output", "tier"),
)
_COST = ObjectSchema({**_COST_FIELDS, "tiers": ArraySchema(_COST_TIER)}, ("input", "output"))
_FAMILIES = frozenset(
    (
        "trinity",
        "trinity-mini",
        "gpt",
        "gpt-codex",
        "gpt-codex-spark",
        "gpt-codex-mini",
        "gpt-pro",
        "gpt-mini",
        "gpt-nano",
        "gpt-sol",
        "gpt-terra",
        "gpt-luna",
        "gpt-astra",
        "gpt-oss",
        "gpt-image",
        "o",
        "o-mini",
        "o-pro",
        "claude",
        "claude-haiku",
        "claude-sonnet",
        "claude-opus",
        "claude-fable",
        "claude-mythos",
        "gemini",
        "gemini-pro",
        "gemini-flash",
        "gemini-flash-lite",
        "gemini-embedding",
        "glm",
        "glmv",
        "glm-air",
        "glm-flash",
        "glm-free",
        "glm-z",
        "llama",
        "muse",
        "muse-free",
        "qwen",
        "qwen3.5",
        "qwen3.6",
        "qwen3.7-plus",
        "qwen3.7-max",
        "qwen3.8-max",
        "qwen-free",
        "ornith",
        "deepseek",
        "deepseek-thinking",
        "deepseek-flash",
        "deepseek-flash-free",
        "deepseek-flash-think",
        "phi",
        "kimi",
        "kimi-k2",
        "kimi-k3",
        "kimi-free",
        "kimi-thinking",
        "motif",
        "laguna",
        "laguna-s",
        "mistral",
        "mistral-large",
        "mistral-medium",
        "mistral-small",
        "mistral-nemo",
        "ministral",
        "codestral",
        "devstral",
        "leanstral",
        "pixtral",
        "mixtral",
        "grok",
        "grok-build",
        "grok-vision",
        "grok-beta",
        "gemma",
        "nova",
        "nova-pro",
        "nova-lite",
        "nova-micro",
        "command",
        "command-r",
        "command-a",
        "command-light",
        "north",
        "north-free",
        "jamba",
        "nemotron",
        "nemotron-free",
        "titan",
        "titan-embed",
        "minimax",
        "minimax-m2.5",
        "minimax-m2.7",
        "minimax-m3",
        "minimax-m3-free",
        "minimax-free",
        "hunyuan",
        "Hy",
        "yi",
        "granite",
        "reka",
        "sonar",
        "sonar-pro",
        "sonar-reasoning",
        "sonar-deep-research",
        "solar",
        "solar-mini",
        "solar-pro",
        "step",
        "text-embedding",
        "cohere-embed",
        "voyage",
        "mistral-embed",
        "bge",
        "plamo",
        "codestral-embed",
        "dall-e",
        "flux",
        "imagen",
        "recraft",
        "stable-diffusion",
        "ideogram",
        "dreamshaper",
        "sora",
        "veo",
        "runway",
        "dream-machine",
        "whisper",
        "elevenlabs",
        "lyria",
        "melotts",
        "ernie",
        "hermes",
        "zephyr",
        "openchat",
        "starling",
        "qvq",
        "sherlock",
        "pony",
        "mercury",
        "cogito",
        "mimo",
        "mimo-pro",
        "mimo-omni",
        "mimo-v2-pro",
        "mimo-v2-omni",
        "mimo-v2.5-pro",
        "mimo-v2.5",
        "mimo-v2.5-free",
        "mimo-pro-free",
        "mimo-omni-free",
        "mimo-flash-free",
        "mm-poly",
        "longcat",
        "magistral",
        "magistral-small",
        "magistral-medium",
        "phoenix",
        "lucid",
        "agi",
        "intellect",
        "aura",
        "jais",
        "sarvam",
        "falcon",
        "baichuan",
        "skywork",
        "bart",
        "distilbert",
        "resnet",
        "m2m",
        "indictrans",
        "llava",
        "seed",
        "ray",
        "tstars",
        "rnj",
        "hy3",
        "hy3-free",
        "ling",
        "ling-flash-free",
        "ring",
        "ring-1t-free",
        "kat-coder",
        "sqlcoder",
        "discolm",
        "osmosis",
        "parakeet",
        "nemoretriever",
        "nano-banana",
        "una-cybertron",
        "morph",
        "voxtral",
        "venice",
        "auto",
        "model-router",
        "fugu",
        "sakana-namazu",
        "v0",
        "tako",
        "mai",
        "rednote",
        "smart-turn",
        "qwerky",
        "big-pickle",
        "chutesai",
        "opengvlab",
        "tngtech",
        "topazlabs",
        "unsloth",
        "nousresearch",
        "alpha",
        "oswe",
        "neural-chat",
        "pangu",
        "liquid",
        "sourceful",
        "allenai",
        "palmyra",
        "allam",
        "canopylabs",
        "groq",
        "elephant",
    )
)
_COMMON = {
    "name": "nonempty",
    "description": "nonempty",
    "family": _FAMILIES,
    **dict.fromkeys(
        ("attachment", "reasoning", "tool_call", "structured_output", "temperature", "open_weights"), "boolean"
    ),
    **dict.fromkeys(("knowledge", "release_date", "last_updated"), "date"),
    "modalities": _MODALITIES,
    "limit": _LIMIT,
}
_MODEL = ObjectSchema(
    {
        **_COMMON,
        "license": "nonempty",
        "links": ArraySchema(_LINK),
        "weights": ArraySchema(_WEIGHT),
        "benchmarks": ArraySchema(_BENCHMARK),
    },
    ("name", "description"),
)
_PROVIDER_MODEL = ObjectSchema(
    {
        **_COMMON,
        "limit": ObjectSchema(_LIMIT.fields, ("context", "output")),
        "reasoning_options": ArraySchema("reasoning_option"),
        "interleaved": "interleaved",
        "cost": _COST,
        "status": frozenset({"alpha", "beta", "deprecated"}),
    },
    (
        "name",
        "description",
        "attachment",
        "reasoning",
        "tool_call",
        "release_date",
        "last_updated",
        "modalities",
        "open_weights",
        "limit",
    ),
)
_PROVIDER = ObjectSchema(
    {"name": "nonempty", "env": ArraySchema("string"), "npm": "nonempty", "api": "string", "doc": "nonempty"},
    ("name", "env", "npm", "doc"),
)


def validate_source_document(document: SourceDocument, *, effective: bool = False) -> None:
    """Validate authored overrides separately from complete inherited results.

    Valid upstream fields outside the selected subset fail explicitly until their
    source dispositions are registered. They are never silently ignored.
    """
    schema = {"model": _MODEL, "provider": _PROVIDER, "provider_model": _PROVIDER_MODEL}.get(document.kind)
    if schema is None:
        raise _error(document, "", "SOURCE_MODEL_KIND_INVALID")
    partial = document.kind == "provider_model" and "base_model" in document.data and not effective
    if partial:
        schema = ObjectSchema(
            {**schema.fields, "base_model": "nonempty", "base_model_omit": ArraySchema("nonempty")}, ("base_model",)
        )
    _validate(document.data, schema, document, "", partial)
    if document.kind == "provider":
        if not document.data["env"]:
            raise _error(document, "env", "SOURCE_CONSTRAINT_INVALID")
        npm = document.data["npm"]
        api = "api" in document.data
        required = {"@ai-sdk/openai-compatible", "@openrouter/ai-sdk-provider", "merge-gateway-ai-sdk-provider"}
        optional = {"@ai-sdk/openai", "@ai-sdk/anthropic", "kiro-acp-ai-provider"}
        if (npm in required and not api) or (npm not in required | optional and api):
            raise _error(document, "api", "SOURCE_CONSTRAINT_INVALID")
    if document.kind == "provider_model" and not partial:
        reasoning = document.data["reasoning"]
        options = "reasoning_options" in document.data
        if (reasoning and not options) or (not reasoning and options):
            raise _error(document, "reasoning_options", "SOURCE_CONSTRAINT_INVALID")
        cost = document.data.get("cost", {})
        if not reasoning and "reasoning" in cost:
            raise _error(document, "cost.reasoning", "SOURCE_CONSTRAINT_INVALID")
        sizes = [tier["tier"]["size"] for tier in cost.get("tiers", ())]
        if len(set(sizes)) != len(sizes):
            raise _error(document, "cost.tiers", "SOURCE_CONSTRAINT_INVALID")
