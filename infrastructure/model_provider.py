# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Optional

# Substring patterns matched against the lower-cased base_url. Order matters:
# `in` returns the first hit, so place more-specific patterns before broader
# ones (e.g. `dashscope` before `aliyuncs`). Patterns mirror frontend
# PROVIDER_HINTS in `frontend/const/modelConfig.ts` so backend provider-by-URL
# detection stays consistent with the icon the user sees in the UI.
HOST_PROVIDER_PATTERNS = (
    ("open/router", "modelengine"),
    ("dashscope", "dashscope"),
    ("aliyuncs", "dashscope"),
    ("siliconflow", "silicon"),
    ("silicon", "silicon"),
    ("modelengine", "modelengine"),
    ("openai", "openai"),
    ("deepseek", "deepseek"),
    ("jina", "jina"),
    ("tokenpony", "tokenpony"),
    ("bytedance", "volcengine"),
)

def pick_provider_from_base_url(base_url: Optional[str]) -> Optional[str]:
    # Match the entire lower-cased base_url, mirroring the frontend
    # detectProviderFromUrl helper. Substring `in` check, first hit wins.
    if not base_url:
        return None

    lowered = base_url.lower()
    for pattern, provider in HOST_PROVIDER_PATTERNS:
        if pattern in lowered:
            return provider
    return None
