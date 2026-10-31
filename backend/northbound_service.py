# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compatibility launcher for the proxy-only Gateway on port 5013."""

import uvicorn

from gateway.application import northbound_app


if __name__ == "__main__":
    uvicorn.run(northbound_app, host="0.0.0.0", port=5013, proxy_headers=False)
