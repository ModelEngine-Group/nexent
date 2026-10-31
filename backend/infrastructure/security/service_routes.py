# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Private Runtime execution routes eligible for scoped service credentials."""

import re

from gateway.protocol.routes import canonical_path


def is_runtime_service_request(method: str, path: str) -> bool:
    path = canonical_path(path)
    return method == "POST" and bool(
        path in {"/agent/internal/northbound/run", "/agent-evaluations/internal/run",
                 "/agent-evaluations/internal/trial-run"}
        or re.fullmatch(r"/agent/internal/northbound/stop/[^/]+", path)
    )
