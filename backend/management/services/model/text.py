# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


import re

def remove_think_blocks(text: str) -> str:
    """Remove <think>...</think> blocks including inner content."""
    if not text:
        return text
    return re.sub(r"(?:<think>)?.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
