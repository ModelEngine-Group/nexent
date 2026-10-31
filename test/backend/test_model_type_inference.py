# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Discovery fallback must distinguish GLM version and visual markers (AC-FIX-01)."""

import pytest

from contracts.model import ProviderModelRequest, _infer_model_type_from_name


@pytest.mark.parametrize("model_name", [
    "GLM-V5.2", "glm-v5.2", "zai-org/GLM-V5.2", "Pro/zai-org/GLM-V5.2",
    "glm-5.2", "glm-5.3", "glm-v5.2-flash", "glm-4.6verbose",
])
def test_version_prefix_does_not_imply_visual_capability(model_name):
    assert _infer_model_type_from_name(model_name) == "llm"


@pytest.mark.parametrize("model_name, expected", [
    ("GLM-4V", "vlm"), ("glm-4.6v", "vlm"), ("glm-4.6v-flash", "vlm"),
    ("zai-org/GLM-4.6V", "vlm"), ("glm_4_6v_flash", "vlm"),
    ("glm-vision", "vlm"), ("Qwen/Qwen3-VL-32B-Instruct", "vlm"),
    ("vendor/vision-ocr", "vlm"), ("vendor/video-chat", "vlm3"),
    ("vendor/image-generator", "vlm2"), ("BAAI/bge-m3", "embedding"),
    ("BAAI/bge-reranker-v2-m3", "rerank"), ("", "llm"),
])
def test_actual_visual_and_other_families_keep_their_discovery_type(model_name, expected):
    assert _infer_model_type_from_name(model_name) == expected


@pytest.mark.parametrize("model_type", [None, "llm", "vlm"])
def test_discovery_request_preserves_explicit_type(model_type):
    request = ProviderModelRequest(provider="custom", model_type=model_type)
    assert request.model_type == model_type
