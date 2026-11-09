# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


def canonical_path(path: str) -> str:
    return path[4:] if path.startswith("/api/") else path
