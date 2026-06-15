"""Day-one capability profile catalog for ModelCapacityResolver.

Source of truth: W1 ADR at
`doc/working/context-management-workstreams/W1_ADR_Capability_Catalog_Storage_and_Fingerprint.md`.

This module owns the approved catalog data. The SDK resolver
(`sdk/nexent/core/models/capacity_resolver.py`) takes the catalog as a parameter;
it does not import this module directly. Backend services read CATALOG here and
pass it through to the resolver.

Changes to entries: bump the per-entry `capability_profile_version` integer
suffix AND `CATALOG_REVISION` in one PR. Numerical values must be re-verified
against provider documentation at PR merge time.
"""
from __future__ import annotations

import logging
from typing import Dict

from nexent.core.models.capacity_resolver import CapabilityProfile, ProfileKey

logger = logging.getLogger(__name__)


CATALOG_REVISION = "2026-06-15.1"


CATALOG: Dict[ProfileKey, CapabilityProfile] = {
    ("openai", "gpt-4o"): CapabilityProfile(
        provider="openai",
        model_name="gpt-4o",
        capability_profile_version="openai/gpt-4o@1",
        window_shape="combined",
        context_window_tokens=128_000,
        max_output_tokens=16_384,
        default_output_reserve_tokens=4_096,
        tokenizer_family="o200k_base",
    ),
    ("openai", "gpt-4.1"): CapabilityProfile(
        provider="openai",
        model_name="gpt-4.1",
        capability_profile_version="openai/gpt-4.1@1",
        window_shape="combined",
        context_window_tokens=1_000_000,
        max_output_tokens=32_768,
        default_output_reserve_tokens=8_192,
        tokenizer_family="o200k_base",
    ),
    ("dashscope", "qwen-plus"): CapabilityProfile(
        provider="dashscope",
        model_name="qwen-plus",
        capability_profile_version="dashscope/qwen-plus@1",
        window_shape="combined",
        context_window_tokens=131_072,
        max_output_tokens=16_384,
        default_output_reserve_tokens=4_096,
        tokenizer_family="qwen",
    ),
    ("dashscope", "qwen-turbo"): CapabilityProfile(
        provider="dashscope",
        model_name="qwen-turbo",
        capability_profile_version="dashscope/qwen-turbo@1",
        window_shape="combined",
        context_window_tokens=1_000_000,
        max_output_tokens=16_384,
        default_output_reserve_tokens=4_096,
        tokenizer_family="qwen",
    ),
    ("dashscope", "glm-5.1"): CapabilityProfile(
        provider="dashscope",
        model_name="glm-5.1",
        capability_profile_version="dashscope/glm-5.1@1",
        window_shape="combined",
        context_window_tokens=200_000,
        max_output_tokens=131_072,
        default_output_reserve_tokens=8_192,
        tokenizer_family="chatglm",
    ),
    ("silicon", "deepseek-ai/DeepSeek-V4-Flash"): CapabilityProfile(
        provider="silicon",
        model_name="deepseek-ai/DeepSeek-V4-Flash",
        capability_profile_version="silicon/deepseek-v4-flash@1",
        window_shape="combined",
        context_window_tokens=1_000_000,
        max_output_tokens=384_000,
        default_output_reserve_tokens=8_192,
        tokenizer_family="deepseek",
    ),
    ("silicon", "Qwen/Qwen3.6-27B"): CapabilityProfile(
        provider="silicon",
        model_name="Qwen/Qwen3.6-27B",
        capability_profile_version="silicon/qwen3.6-27b@1",
        window_shape="combined",
        context_window_tokens=262_144,
        max_output_tokens=65_536,
        default_output_reserve_tokens=8_192,
        tokenizer_family="qwen",
    ),
    ("silicon", "Pro/moonshotai/Kimi-K2.6"): CapabilityProfile(
        provider="silicon",
        model_name="Pro/moonshotai/Kimi-K2.6",
        capability_profile_version="silicon/kimi-k2.6@1",
        window_shape="combined",
        context_window_tokens=262_144,
        max_output_tokens=131_072,
        default_output_reserve_tokens=8_192,
        tokenizer_family="moonshot",
    ),
}
