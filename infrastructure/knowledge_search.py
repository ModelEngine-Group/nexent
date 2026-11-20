# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Stable configuration and revisions for prepared knowledge search."""

import hashlib
import json


def knowledge_search_revision(record: dict) -> str:
    fields = ("knowledge_id", "index_name", "knowledge_name", "tenant_id", "embedding_model_id",
              "created_by", "group_ids", "ingroup_permission", "knowledge_sources")
    encoded = json.dumps([record.get(field) for field in fields], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _build_model_config(model: dict) -> dict:
    config = {
        "model_repo": model.get("model_repo", ""),
        "model_name": model["model_name"],
        "api_key": model.get("api_key", ""),
        "base_url": model.get("base_url", ""),
        "model_type": model.get("model_type", "embedding"),
        "max_tokens": model.get("max_tokens", 1024),
        "ssl_verify": model.get("ssl_verify", True),
    }
    # Carry the vendor through so multi_embedding/embedding adapters dispatch
    # to the right provider instead of silently falling back to the default.
    if model.get("model_factory"):
        config["model_factory"] = model["model_factory"]
    return config


def embedding_adapter_spec(model: dict) -> tuple[dict, str, str]:
    model_config = _build_model_config(model)
    model_type = model_config.get("model_type", "embedding")

    if model_type == "multi_embedding":
        modality, slot = "multi_embedding", "multiEmbedding"
    elif model_type == "embedding":
        modality, slot = "embedding", "embedding"
    else:
        raise ValueError(
            f"Invalid model_type '{model_type}' for model '{model_config.get('model_name')}'. "
            f"Expected 'embedding' or 'multi_embedding', got '{model_type}'. "
            f"Please check the model configuration in the model management page."
        )

    return model_config, modality, slot
